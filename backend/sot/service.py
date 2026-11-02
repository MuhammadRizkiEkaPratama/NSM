"""Source of Truth logic: read/save intent, render, and audit trail.

The only place allowed to write `intent_nilai`, `intent_interface`, `intent_vlan` and
`intent_rute`. Web pages and `main.py` call the functions here and never write SQLAlchemy
directly (same pattern as `report_service.py`).

Touches NO device: functions only read/write NSM's own database and call the pure `sot/render.py`.
"""
import json
from datetime import datetime

from sqlalchemy import select

from models import (Device, IntentNilai, IntentInterface, IntentVlan,
                    IntentRute, IntentRiwayat)
from sot import katalog, render as _render


def _muat_nilai(db, device_id):
    """dict {key: canonical_value} for one device, from intent_nilai."""
    line = db.execute(
        select(IntentNilai).where(IntentNilai.device_id == device_id)
    ).scalars().all()
    return {b.kunci: json.loads(b.nilai_json) for b in line}


def _muat_interface(db, device_id):
    line = db.execute(
        select(IntentInterface).where(IntentInterface.device_id == device_id)
    ).scalars().all()
    return sorted(
        [{"nama": b.nama, "deskripsi": b.deskripsi, "ip": b.ip_address,
          "mask": b.subnet_mask, "vlan": b.vlan_id,
          "shutdown": bool(b.shutdown)} for b in line],
        key=lambda i: i["nama"])


def _muat_vlan(db, device_id):
    line = db.execute(
        select(IntentVlan).where(IntentVlan.device_id == device_id)
    ).scalars().all()
    return sorted([{"vlan_id": b.vlan_id, "nama": b.nama} for b in line],
                 key=lambda v: v["vlan_id"])


def _muat_rute(db, device_id):
    line = db.execute(
        select(IntentRute).where(IntentRute.device_id == device_id)
    ).scalars().all()
    return [{"tujuan": b.tujuan, "mask": b.subnet_mask,
            "next_hop": b.next_hop, "catatan": b.catatan} for b in line]


def _catat(db, device_id, kategori, kunci, aksi, lama, baru, oleh):
    db.add(IntentRiwayat(
        device_id=device_id, kategori=kategori, kunci=kunci, aksi=aksi,
        lama_json=json.dumps(lama, ensure_ascii=False) if lama is not None else None,
        baru_json=json.dumps(baru, ensure_ascii=False) if baru is not None else None,
        oleh=oleh, waktu=datetime.now()))


def _device_atau_tolak(db, device_id):
    d = db.get(Device, device_id)
    if d is None:
        raise katalog.Ditolak("device id=%s tidak ditemukan." % device_id)
    if not d.platform or d.platform not in katalog.platform_didukung():
        raise katalog.Ditolak(
            "device '%s' berplatform '%s', dan platform itu belum punya "
            "katalog Sumber Kebenaran. Yang didukung: %s"
            % (d.name, d.platform, ", ".join(katalog.platform_didukung())))
    return d


def ambil(db, device_id):
    """A device's whole intent, plus the applicable key catalog and what is missing.

    Used by the web page to build the form and to show "complete / still missing X" without trying a render.
    """
    d = _device_atau_tolak(db, device_id)
    nilai = _muat_nilai(db, device_id)
    kurang = katalog.kekurangan(d.platform, nilai)
    return {
        "device_id": d.id,
        "device": d.name,
        "platform": d.platform,
        "katalog": katalog.untuk_platform(d.platform),
        "nilai": nilai,
        "interface": _muat_interface(db, device_id),
        "vlan": _muat_vlan(db, device_id),
        "rute": _muat_rute(db, device_id),
        "lengkap": not kurang,
        "kurang": [{"kunci": k["kunci"], "judul": k["judul"]} for k in kurang],
    }


def simpan_nilai(db, device_id, form_nilai, oleh=None):
    """Save the single-key intent values for one device.

    `form_nilai` may be PARTIAL, so the admin can fill the form in stages. Every SUBMITTED key is
    still fully validated (`katalog.periksa`); keys that do not apply to this device's platform are
    rejected rather than silently ignored.
    """
    d = _device_atau_tolak(db, device_id)
    rapi = katalog.periksa_parsial(d.platform, form_nilai)

    exists = {b.kunci: b for b in db.execute(
        select(IntentNilai).where(IntentNilai.device_id == device_id)
    ).scalars().all()}

    diubah = 0
    for kunci, value_new in rapi.items():
        line_json = json.dumps(value_new, ensure_ascii=False)
        lama = exists.get(kunci)
        if lama is None:
            db.add(IntentNilai(device_id=device_id, kunci=kunci,
                               nilai_json=line_json, diubah_oleh=oleh,
                               diubah_waktu=datetime.now()))
            _catat(db, device_id, "nilai", kunci, "tambah", None, value_new, oleh)
            diubah += 1
        elif json.loads(lama.nilai_json) != value_new:
            value_old = json.loads(lama.nilai_json)
            lama.nilai_json = line_json
            lama.diubah_oleh = oleh
            lama.diubah_waktu = datetime.now()
            _catat(db, device_id, "nilai", kunci, "ubah", value_old,
                  value_new, oleh)
            diubah += 1
    db.commit()
    return {"disimpan": len(rapi), "berubah": diubah}


def _nilai_kolom(sumber, kolom):
    """Read one column from a dict (form row) OR an ORM object (stored row)."""
    if isinstance(sumber, dict):
        return sumber.get(kolom)
    return getattr(sumber, kolom)


def _kunci_baris(sumber, kolom_kunci):
    """Composite key from `kolom_kunci` (tuple of column names), for dicts and ORM objects alike.

    Column names must match the SQLAlchemy model attribute names exactly, so one function works
    for both source shapes.
    """
    vals = tuple(_nilai_kolom(sumber, k) for k in kolom_kunci)
    return vals[0] if len(vals) == 1 else vals


def _selaraskan(db, model, device_id, kategori, baris_baru, kolom_kunci,
               oleh):
    """Replace all repeated-intent rows (interface/vlan/route) of one device.

    Uses a SYNC pattern, not manual add/remove: the web page always sends the WHOLE list and this
    function works out which rows to add, change and delete by comparing with what is stored.
    An old row that is no longer sent was deleted on purpose and is logged as 'hapus' in history.

    `kolom_kunci` is a tuple of column names (e.g. `("nama",)` for interfaces,
    `("tujuan", "subnet_mask", "next_hop")` for routes), not a lambda, so the key is computed the
    same way for dicts and ORM objects via `_kunci_baris`.
    """
    exists = {_kunci_baris(b, kolom_kunci): b for b in db.execute(
        select(model).where(model.device_id == device_id)
    ).scalars().all()}
    used = set()
    diubah = 0

    for baru in baris_baru:
        k = _kunci_baris(baru, kolom_kunci)
        used.add(k)
        lama_obj = exists.get(k)
        if lama_obj is None:
            kolom = dict(baru)
            kolom["device_id"] = device_id
            kolom["diubah_oleh"] = oleh
            kolom["diubah_waktu"] = datetime.now()
            db.add(model(**kolom))
            _catat(db, device_id, kategori, str(k), "tambah", None, baru, oleh)
            diubah += 1
        else:
            snapshot_old = {c.key: getattr(lama_obj, c.key)
                             for c in model.__table__.columns
                             if c.key not in ("id", "device_id", "diubah_oleh",
                                              "diubah_waktu")}
            berubah = False
            for kolom, nilai in baru.items():
                if getattr(lama_obj, kolom, None) != nilai:
                    setattr(lama_obj, kolom, nilai)
                    berubah = True
            if berubah:
                lama_obj.diubah_oleh = oleh
                lama_obj.diubah_waktu = datetime.now()
                _catat(db, device_id, kategori, str(k), "ubah",
                      snapshot_old, baru, oleh)
                diubah += 1

    for k, obj in exists.items():
        if k not in used:
            snapshot_old = {c.key: getattr(obj, c.key)
                             for c in model.__table__.columns
                             if c.key not in ("id", "device_id", "diubah_oleh",
                                              "diubah_waktu")}
            db.delete(obj)
            _catat(db, device_id, kategori, str(k), "hapus",
                  snapshot_old, None, oleh)
            diubah += 1

    return diubah


def simpan_interface(db, device_id, daftar, oleh=None):
    """Sync all intended interfaces of one device from a raw list of dicts."""
    _device_atau_tolak(db, device_id)
    rapi = [katalog.periksa_interface(b) for b in daftar]
    # Composite key is the unique name: two interfaces with the same name in one list mean the form was submitted wrongly.
    nama_terpakai = set()
    for b in rapi:
        if b["nama"] in nama_terpakai:
            raise katalog.Ditolak(
                "interface '%s' muncul dua kali dalam satu pengiriman."
                % b["nama"])
        nama_terpakai.add(b["nama"])
    line_model = [
        {"nama": b["nama"], "deskripsi": b["deskripsi"],
         "ip_address": b["ip"], "subnet_mask": b["mask"],
         "vlan_id": b["vlan"], "shutdown": b["shutdown"]}
        for b in rapi
    ]
    diubah = _selaraskan(db, IntentInterface, device_id, "interface",
                         line_model, ("nama",), oleh)
    db.commit()
    return {"disimpan": len(rapi), "berubah": diubah}


def simpan_vlan(db, device_id, daftar, oleh=None):
    """Sync all intended VLANs of one device."""
    _device_atau_tolak(db, device_id)
    rapi = [katalog.periksa_vlan(b) for b in daftar]
    terpakai = set()
    for b in rapi:
        if b["vlan_id"] in terpakai:
            raise katalog.Ditolak(
                "VLAN %d muncul dua kali dalam satu pengiriman." % b["vlan_id"])
        terpakai.add(b["vlan_id"])
    diubah = _selaraskan(db, IntentVlan, device_id, "vlan", rapi,
                         ("vlan_id",), oleh)
    db.commit()
    return {"disimpan": len(rapi), "berubah": diubah}


def simpan_rute(db, device_id, daftar, oleh=None):
    """Reconcile all intended static routes of one device."""
    _device_atau_tolak(db, device_id)
    rapi = [katalog.periksa_rute(b) for b in daftar]
    line_model = [
        {"tujuan": b["tujuan"], "subnet_mask": b["mask"],
         "next_hop": b["next_hop"], "catatan": b["catatan"]}
        for b in rapi
    ]
    diubah = _selaraskan(db, IntentRute, device_id, "rute", line_model,
                         ("tujuan", "subnet_mask", "next_hop"), oleh)
    db.commit()
    return {"disimpan": len(rapi), "berubah": diubah}


def render_intent(db, device_id):
    """Render a device's stored intent into configuration text.

    Raises `katalog.Ditolak` (not a raw Jinja2 error) if the intent is incomplete; the message
    names the required keys still empty, so the web page need not show a Python traceback.
    """
    d = _device_atau_tolak(db, device_id)
    nilai = _muat_nilai(db, device_id)
    kurang = katalog.kekurangan(d.platform, nilai)
    if kurang:
        raise katalog.Ditolak(
            "intent %s belum lengkap, %d kunci wajib masih kosong: %s"
            % (d.name, len(kurang),
               ", ".join(k["judul"] for k in kurang)))

    hasil = _render.render(d.platform, nilai, _muat_interface(db, device_id),
                           _muat_vlan(db, device_id), _muat_rute(db, device_id))
    hasil["device_id"] = d.id
    hasil["device"] = d.name
    hasil["platform"] = d.platform
    return hasil


def riwayat(db, device_id, batas=100):
    """Intent change history of one device, newest first."""
    _device_atau_tolak(db, device_id)
    line = db.execute(
        select(IntentRiwayat)
        .where(IntentRiwayat.device_id == device_id)
        .order_by(IntentRiwayat.waktu.desc())
        .limit(batas)
    ).scalars().all()
    return [{
        "id": b.id, "kategori": b.kategori, "kunci": b.kunci, "aksi": b.aksi,
        "lama": json.loads(b.lama_json) if b.lama_json else None,
        "baru": json.loads(b.baru_json) if b.baru_json else None,
        "oleh": b.oleh, "waktu": b.waktu.isoformat() if b.waktu else None,
    } for b in line]


def ringkasan(db):
    """One row per device whose platform has a Source of Truth catalog.

    Used by the list page: which devices have complete intent and which are missing something.
    Devices with unsupported platforms are left out, since an empty row would suggest an error.
    """
    hasil = []
    platform_ok = set(katalog.platform_didukung())
    for d in db.execute(select(Device)).scalars().all():
        if d.platform not in platform_ok:
            continue
        nilai = _muat_nilai(db, d.id)
        kurang = katalog.kekurangan(d.platform, nilai)
        hasil.append({
            "device_id": d.id, "device": d.name, "platform": d.platform,
            "lengkap": not kurang, "kunci_terisi": len(nilai),
            "kunci_total": len(katalog.untuk_platform(d.platform)),
        })
    return hasil

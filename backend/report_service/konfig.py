"""`konfig` section of report_service."""
import re
from sqlalchemy import desc
from models import (Device)

from ._inti import (_pelaku_jendela, _perubahan_nsm_per_device)



def konfig_daftar(db, device_id=None, batas=50):
    """Configuration snapshot history, newest first.

    One row is one real change: the poller only stores a snapshot when its fingerprint changes.
    """
    from models import KonfigSnapshot

    peta = {d.id: d.name for d in db.query(Device).all()}
    q = db.query(KonfigSnapshot)
    if device_id:
        q = q.filter(KonfigSnapshot.device_id == device_id)
    baris = q.order_by(desc(KonfigSnapshot.waktu)).limit(batas).all()

    since_per_snapshot = {}
    for k in baris:
        if k.baris_tambah is None and k.baris_hapus is None:
            continue
        previous = (db.query(KonfigSnapshot)
                      .filter(KonfigSnapshot.device_id == k.device_id,
                              KonfigSnapshot.waktu < k.waktu)
                      .order_by(desc(KonfigSnapshot.waktu))
                      .first())
        since_per_snapshot[k.id] = previous.waktu if previous else None

    per_device = _perubahan_nsm_per_device(db, list({k.device_id for k in baris}))

    hasil = []
    for k in baris:
        ada_perubahan_baris = bool(k.baris_tambah or k.baris_hapus)
        # Window is computed per snapshot from its own predecessor's `sejak`; one device can have many snapshots in the list.
        pelaku = _pelaku_jendela(per_device.get(k.device_id),
                                 since_per_snapshot.get(k.id), k.waktu)
        if pelaku is None and ada_perubahan_baris and k.id in since_per_snapshot:
            # Rows changed but no NSM record explains them: changed directly on the device, outside NSM.
            # Not the same as "not applicable" (first snapshot, or only the saved status changed).
            pelaku = {"lewat_nsm": False}
        hasil.append({
            "id": k.id,
            "device_id": k.device_id,
            "device": peta.get(k.device_id) or f"device {k.device_id}",
            "waktu": k.waktu.isoformat() if k.waktu else None,
            "sidik": (k.sidik or "")[:12],
            "baris": len((k.teks or "").splitlines()),
            "byte": len((k.teks or "").encode("utf-8", "replace")),
            # None for a device's first snapshot (no baseline); it is not zero.
            "baris_tambah": k.baris_tambah,
            "baris_hapus": k.baris_hapus,
            "pertama": k.baris_tambah is None and k.baris_hapus is None,
            # None = the platform has no startup-config concept; this is not zero.
            "belum_disimpan": k.belum_disimpan,
            "punya_startup": k.sidik_startup is not None,
            # Who made this change, if known. None = not applicable. {"lewat_nsm": True, ...} matches
            # NSM block/unblock history; {"lewat_nsm": False} = changed directly on the device.
            "pelaku": pelaku,
        })

    from connectors import konfig as _konfig
    not_yet = [d.name for d in db.query(Device).all()
             if d.platform in _konfig.PERINTAH and d.aktif != 0
             and not db.query(KonfigSnapshot)
                       .filter(KonfigSnapshot.device_id == d.id).first()]

    return {
        "potret": hasil,
        "total": len(hasil),
        "belum_terpotret": not_yet,
        "catatan": ("Potret hanya disimpan saat isinya BERUBAH, jadi satu baris "
                    "di sini sama dengan satu perubahan yang benar-benar "
                    "terjadi. Nilai password, community SNMP, dan kunci "
                    "pra-berbagi sudah disamarkan sebelum disimpan; baris yang "
                    "berubah sendiri seperti `ntp clock-period` dibuang supaya "
                    "tidak terbaca sebagai perubahan."),
    }


def konfig_kepatuhan(db, device_id=None):
    """Compliance findings on the LATEST snapshot of each device.

    This page shows current state, not full history (history lives in `konfig_temuan`).
    No single compliance percentage is published: findings of different severity are
    not comparable, so the response carries counts per severity instead.
    """
    from models import KonfigSnapshot, KonfigTemuan
    from connectors import kepatuhan as _kp

    peta = {d.id: d for d in db.query(Device).all()}

    q = db.query(KonfigSnapshot)
    if device_id:
        q = q.filter(KonfigSnapshot.device_id == device_id)
    last = {}
    for k in q.order_by(KonfigSnapshot.waktu).all():
        last[k.device_id] = k

    perangkat = []
    for did, potret in last.items():
        temuan = (db.query(KonfigTemuan)
                  .filter(KonfigTemuan.snapshot_id == potret.id).all())
        # A snapshot not yet assessed is NOT reported as zero findings: zero means "checked, clean",
        # not assessed means "not checked".
        if not temuan:
            perangkat.append({
                "device_id": did,
                "device": peta[did].name if did in peta else f"device {did}",
                "device_type": peta[did].device_type if did in peta else None,
                "platform": peta[did].platform if did in peta else None,
                "snapshot_id": potret.id,
                "waktu": potret.waktu.isoformat() if potret.waktu else None,
                "dinilai": False,
                "temuan": [], "patuh": [], "tidak_berlaku": [],
                "cacah": None,
            })
            continue

        detail = {"temuan": [], "patuh": [], "tidak_berlaku": []}
        cacah = {_kp.TINGGI: 0, _kp.SEDANG: 0, _kp.RENDAH: 0}
        for t in temuan:
            rule = _kp.PETA_KATALOG.get(t.aturan_id)
            butir = {
                "aturan_id": t.aturan_id,
                "judul": rule["judul"] if rule else t.aturan_id,
                "keparahan": t.keparahan,
                "kenapa": rule["kenapa"] if rule else None,
                "perbaikan": rule["perbaikan"] if rule else None,
                "baris_bukti": t.baris_bukti,
                "nomor_baris": t.nomor_baris,
            }
            if t.hasil == _kp.TEMUAN:
                detail["temuan"].append(butir)
                cacah[t.keparahan] = cacah.get(t.keparahan, 0) + 1
            elif t.hasil == _kp.PATUH:
                detail["patuh"].append(butir)
            else:
                detail["tidak_berlaku"].append(butir)

        detail["temuan"].sort(
            key=lambda b: _kp.URUTAN_KEPARAHAN.get(b["keparahan"], 9))
        perangkat.append({
            "device_id": did,
            "device": peta[did].name if did in peta else f"device {did}",
            "device_type": peta[did].device_type if did in peta else None,
            "platform": peta[did].platform if did in peta else None,
            "snapshot_id": potret.id,
            "waktu": potret.waktu.isoformat() if potret.waktu else None,
            "dinilai": True,
            "cacah": cacah,
            **detail,
        })

    perangkat.sort(key=lambda p: -(
        (p["cacah"] or {}).get(_kp.TINGGI, 0) * 100
        + (p["cacah"] or {}).get(_kp.SEDANG, 0) * 10
        + (p["cacah"] or {}).get(_kp.RENDAH, 0)))

    return {
        "perangkat": perangkat,
        "jumlah_aturan": len(_kp.KATALOG),
        "katalog": [{
            "id": a["id"], "judul": a["judul"], "platform": a["platform"],
            "keparahan": a["keparahan"], "kenapa": a["kenapa"],
            "perbaikan": a["perbaikan"],
        } for a in _kp.KATALOG],
        "catatan": ("Penilaian dilakukan atas potret konfigurasi yang SUDAH "
                    "tersimpan, tanpa menyentuh perangkat sama sekali. Nilai "
                    "rahasia sudah disamarkan sebelum potretnya disimpan, jadi "
                    "aturan yang menuntut nilai aslinya sengaja tidak ada. "
                    "Jumlah temuan dilaporkan per tingkat keparahan, bukan "
                    "sebagai satu persentase: telnet terbuka dan banner yang "
                    "hilang tidak sebanding untuk dijumlahkan."),
    }


def konfig_isi(db, snapshot_id):
    """Contents of one snapshot, as stored."""
    from models import KonfigSnapshot

    k = db.query(KonfigSnapshot).filter(KonfigSnapshot.id == snapshot_id).first()
    if not k:
        return {"error": "Potret tidak ditemukan"}
    d = db.query(Device).filter(Device.id == k.device_id).first()
    return {
        "id": k.id,
        "device": d.name if d else f"device {k.device_id}",
        "waktu": k.waktu.isoformat() if k.waktu else None,
        "sidik": k.sidik,
        "teks": k.teks or "",
    }


def konfig_beda(db, snapshot_id):
    """Compare a snapshot with the PREVIOUS snapshot of the same device."""
    from models import KonfigSnapshot
    from connectors import konfig as _konfig

    k = db.query(KonfigSnapshot).filter(KonfigSnapshot.id == snapshot_id).first()
    if not k:
        return {"error": "Potret tidak ditemukan"}

    d = db.query(Device).filter(Device.id == k.device_id).first()
    before = (db.query(KonfigSnapshot)
               .filter(KonfigSnapshot.device_id == k.device_id,
                       KonfigSnapshot.waktu < k.waktu)
               .order_by(desc(KonfigSnapshot.waktu))
               .first())

    if before is None:
        return {
            "id": k.id,
            "device": d.name if d else f"device {k.device_id}",
            "waktu": k.waktu.isoformat() if k.waktu else None,
            "ada_pembanding": False,
            "alasan": ("Ini potret pertama untuk perangkat itu, jadi belum ada "
                       "yang bisa dibandingkan. Perubahan berikutnya akan punya "
                       "pembanding."),
            "baris": [],
        }

    tambah, hapus, chunk = _konfig.beda_baris(before.teks, k.teks)

    # Diff is parsed into tagged lines so JavaScript does not guess meaning from "+" / "-" prefixes.
    baris = []
    for b in chunk.split("\n"):
        if not b:
            continue
        if b.startswith("+++") or b.startswith("---"):
            continue
        if b.startswith("@@"):
            jenis = "posisi"
            # Raw unified-diff hunk headers (`@@ -45,4 +45,5 @@`) are translated to plain sentences,
            # using line numbers of the NEW configuration.
            cocok = re.search(r"\+(\d+)", b)
            b = ("── sekitar baris %s dari konfigurasi ──" % cocok.group(1)
                 if cocok else "── bagian lain dari konfigurasi ──")
        elif b.startswith("+"):
            jenis = "tambah"
        elif b.startswith("-"):
            jenis = "hapus"
        else:
            jenis = "sama"
        baris.append({"jenis": jenis, "teks": b})

    per_device = _perubahan_nsm_per_device(db, [k.device_id])
    pelaku = _pelaku_jendela(per_device.get(k.device_id), before.waktu, k.waktu)
    if pelaku is None and (tambah or hapus):
        pelaku = {"lewat_nsm": False}

    return {
        "id": k.id,
        "device": d.name if d else f"device {k.device_id}",
        "waktu": k.waktu.isoformat() if k.waktu else None,
        "waktu_sebelum": before.waktu.isoformat() if before.waktu else None,
        "ada_pembanding": True,
        "baris_tambah": tambah,
        "baris_hapus": hapus,
        "baris": baris,
        "pelaku": pelaku,
    }


def konfig_belum_disimpan(db, snapshot_id):
    """Lines present in running-config but not yet in startup-config.

    That is, the changes that would be LOST if the device rebooted now. Direction is
    deliberate (startup first, running second) so a `+` line means "present now, gone after reboot".
    """
    from models import KonfigSnapshot
    from connectors import konfig as _konfig

    k = db.query(KonfigSnapshot).filter(KonfigSnapshot.id == snapshot_id).first()
    if not k:
        return {"error": "Potret tidak ditemukan"}

    d = db.query(Device).filter(Device.id == k.device_id).first()
    base = {
        "id": k.id,
        "device": d.name if d else f"device {k.device_id}",
        "waktu": k.waktu.isoformat() if k.waktu else None,
    }

    if k.sidik_startup is None:
        base.update({
            "punya_startup": False,
            "alasan": ("Perangkat ini tidak memisahkan konfigurasi yang berjalan "
                       "dari konfigurasi yang dipakai saat menyala, atau potret "
                       "ini diambil sebelum NSM mulai membacanya."),
            "baris": [],
        })
        return base

    tambah, hapus, chunk = _konfig.beda_baris(k.teks_startup or "", k.teks or "")

    baris = []
    for b in chunk.split("\n"):
        if not b or b.startswith("+++") or b.startswith("---"):
            continue
        if b.startswith("@@"):
            jenis = "posisi"
        elif b.startswith("+"):
            jenis = "tambah"
        elif b.startswith("-"):
            jenis = "hapus"
        else:
            jenis = "sama"
        baris.append({"jenis": jenis, "teks": b})

    base.update({
        "punya_startup": True,
        "belum_disimpan": k.belum_disimpan,
        "akan_hilang": tambah,
        "akan_kembali": hapus,
        "baris": baris,
        "catatan": ("Baris hijau ada di konfigurasi yang berjalan sekarang "
                    "tetapi TIDAK ada di konfigurasi simpanan: baris itu akan "
                    "hilang kalau perangkat dinyalakan ulang. Baris merah ada "
                    "di simpanan tetapi tidak berlaku sekarang: baris itu akan "
                    "kembali setelah reboot. Menyimpannya di perangkat Cisco "
                    "dilakukan dengan `write memory`."),
    })
    return base


def perintah_katalog(db, device_id):
    """Commands available for a device.

    The interface list is included so the page can offer real choices instead of a free-text field.
    """
    from models import KonfigSnapshot
    from connectors import perintah as _pr
    from connectors import konfig as _konfig

    d = db.query(Device).filter(Device.id == device_id).first()
    if not d:
        return {"error": "Device tidak ditemukan"}

    potret = (db.query(KonfigSnapshot)
              .filter(KonfigSnapshot.device_id == device_id)
              .order_by(desc(KonfigSnapshot.waktu)).first())
    interface = _konfig.daftar_interface(potret.teks) if potret else []

    return {
        "device_id": d.id,
        "device": d.name,
        "platform": d.platform,
        "perintah": [{
            "id": p["id"], "nama": p["nama"], "penjelasan": p["penjelasan"],
            "memutus": p["memutus"], "parameter": p["parameter"],
        } for p in _pr.daftar(d.platform)],
        "interface": interface,
        # Without a snapshot, interface-name validation falls back to a pattern check only.
        "punya_potret": potret is not None,
        "catatan": ("Bagian ini hanya menyusun dan memeriksa perintah. NSM "
                    "belum punya jalur untuk mengirimkannya ke perangkat, dan "
                    "penambahannya membutuhkan izin eksplisit untuk tiap "
                    "perubahan."),
    }


def perintah_pratinjau(db, device_id, perintah_id, nilai):
    """Build the commands and show them. Sends NOTHING.

    Interface names are validated against the device's latest configuration snapshot.
    """
    from models import KonfigSnapshot
    from connectors import perintah as _pr
    from connectors import konfig as _konfig

    d = db.query(Device).filter(Device.id == device_id).first()
    if not d:
        return {"ok": False, "galat": {"_": "Device tidak ditemukan"}}

    available = _pr.daftar(d.platform)
    if not any(p["id"] == perintah_id for p in available):
        return {"ok": False, "galat": {
            "_": f"Perintah ini tidak tersedia untuk platform '{d.platform}'"}}

    potret = (db.query(KonfigSnapshot)
              .filter(KonfigSnapshot.device_id == device_id)
              .order_by(desc(KonfigSnapshot.waktu)).first())
    interface = _konfig.daftar_interface(potret.teks) if potret else None

    hasil = _pr.pratinjau(perintah_id, nilai, interface)
    hasil["device"] = d.name
    hasil["device_id"] = d.id

    # Identity guard (docs/design/TRAFFIC-IDENTITY-FW.md).
    #
    # Asked here in the PREVIEW path so the verdict is visible while the user reads the
    # command, not as a surprise refusal after pressing send. This does NOT replace the
    # check on the send path, which must call `identitas.boleh_ditulisi()` again right
    # before sending: a verdict from preview time says nothing about the device minutes later.
    import identitas
    allowed, vonis, kenapa = identitas.boleh_ditulisi(db, device_id)
    hasil["identitas"] = {
        "boleh_ditulisi": allowed,
        "vonis": vonis,
        "alasan": kenapa,
        "penanda": identitas.penanda_tersimpan(db, device_id),
        "diperiksa": d.identitas_diperiksa.isoformat()
                     if d.identitas_diperiksa else None,
    }
    return hasil

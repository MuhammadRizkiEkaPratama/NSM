"""Compare the intent with the latest configuration snapshot (observed).

The only entry point `main.py` may call for drift detection, like
`sot/service.py`: one place knows the shape of the comparison, other callers
only need the shape of the result.

ZERO device contact. Reads only `intent_*` (via `sot.service`) and
`konfig_snapshots` from NSM's own database, then calls the pure `drift.ekstrak`.
"""
from sqlalchemy import select

from models import Device, KonfigSnapshot
from sot import katalog, service as sot_svc
from drift import ekstrak

COCOK = "cocok"
BEDA = "beda"
TIDAK_TERBACA = "tidak_terbaca"
HILANG = "hilang"


def _sama(a, b):
    """Value equality. Lists (ntp_server, dns_server, ...) are compared as SETS, not
    sequences: an operator who adds NTP servers in a different order than the intent
    is still compliant, and ordering alone is not a drift worth reporting.
    """
    if isinstance(a, list) or isinstance(b, list):
        return set(a or []) == set(b or [])
    return a == b


def _status_nilai(v_intended, v_observed):
    if v_observed is None:
        return TIDAK_TERBACA
    return COCOK if _sama(v_intended, v_observed) else BEDA


def _banding_nilai(platform, nilai_intended, nilai_observed):
    """One result row per key the intent STATES. Keys the intent does not state are
    skipped entirely: that is scope, not an oversight (see the package docstring).
    """
    hasil = []
    for spec in katalog.untuk_platform(platform):
        kunci = spec["kunci"]
        if kunci not in nilai_intended:
            continue
        v_i = nilai_intended[kunci]
        v_o = nilai_observed.get(kunci)
        level, alasan = katalog.risiko_kunci(kunci)
        hasil.append({
            "kategori": "nilai", "kunci": kunci, "judul": spec["judul"],
            "status": _status_nilai(v_i, v_o),
            "intended": v_i, "observed": v_o,
            "risiko": level, "kenapa_risiko": alasan,
        })
    return hasil


def _status_keseluruhan(medan):
    """Priority: a single `BEDA` field makes the row `BEDA`; otherwise any
    `TIDAK_TERBACA` field is what gets reported; if all fields are `COCOK` (or none
    were checked), `COCOK`.
    """
    if any(m["status"] == BEDA for m in medan):
        return BEDA
    if any(m["status"] == TIDAK_TERBACA for m in medan):
        return TIDAK_TERBACA
    return COCOK


def _banding_interface(intended_list, observed_list):
    observed_map = {i["nama"]: i for i in observed_list}
    level, alasan = katalog.risiko_kategori("interface")
    hasil = []
    for it in intended_list:
        nama = it["nama"]
        obs = observed_map.get(nama)
        if obs is None:
            hasil.append({
                "kategori": "interface", "kunci": nama, "judul": nama,
                "status": HILANG, "medan": [],
                "risiko": level, "kenapa_risiko": alasan,
                "catatan": "Interface ini dinyatakan di intent tapi TIDAK "
                          "ditemukan sama sekali di potret konfigurasi.",
            })
            continue
        medan = []
        for f, label in (("deskripsi", "Deskripsi"), ("ip", "Alamat IP"),
                        ("mask", "Subnet mask"), ("shutdown", "Status mati"),
                        ("vlan", "VLAN akses")):
            vi = it.get(f)
            if vi is None:
                continue  # intent does not state this field
            vo = obs.get(f)
            medan.append({"medan": f, "label": label, "intended": vi,
                          "observed": vo, "status": _status_nilai(vi, vo)})
        hasil.append({
            "kategori": "interface", "kunci": nama, "judul": nama,
            "status": _status_keseluruhan(medan), "medan": medan,
            "risiko": level, "kenapa_risiko": alasan,
        })
    return hasil


def _banding_vlan(intended_list, observed_list):
    observed_map = {v["vlan_id"]: v for v in observed_list}
    level, alasan = katalog.risiko_kategori("vlan")
    hasil = []
    for it in intended_list:
        vid = it["vlan_id"]
        obs = observed_map.get(vid)
        judul = "VLAN %d" % vid
        if obs is None:
            hasil.append({
                "kategori": "vlan", "kunci": str(vid), "judul": judul,
                "status": HILANG, "medan": [],
                "risiko": level, "kenapa_risiko": alasan,
                "catatan": "VLAN ini dinyatakan di intent tapi TIDAK "
                          "ditemukan di potret konfigurasi.",
            })
            continue
        medan = []
        if it.get("nama") is not None:
            medan.append({"medan": "nama", "label": "Nama VLAN",
                          "intended": it["nama"], "observed": obs.get("nama"),
                          "status": _status_nilai(it["nama"], obs.get("nama"))})
        hasil.append({
            "kategori": "vlan", "kunci": str(vid), "judul": judul,
            "status": _status_keseluruhan(medan), "medan": medan,
            "risiko": level, "kenapa_risiko": alasan,
        })
    return hasil


def _banding_rute(intended_list, observed_list):
    observed_set = {(r["tujuan"], r["mask"], r["next_hop"]) for r in observed_list}
    level, alasan = katalog.risiko_kategori("rute")
    hasil = []
    for it in intended_list:
        key_route = (it["tujuan"], it["mask"], it["next_hop"])
        judul = "%s/%s via %s" % key_route
        exists = key_route in observed_set
        hasil.append({
            "kategori": "rute", "kunci": "|".join(key_route), "judul": judul,
            "status": COCOK if exists else HILANG, "medan": [],
            "risiko": level, "kenapa_risiko": alasan,
            "catatan": None if exists else
                      "Rute ini dinyatakan di intent tapi TIDAK ditemukan "
                      "di potret konfigurasi.",
        })
    return hasil


def bandingkan(db, device_id):
    """Complete drift result for one device.

    Always returns a dict (never raises for expected states: unsupported platform,
    empty intent, no snapshot yet) so the web page can explain WHY there is no
    result instead of showing a generic error. Raises `katalog.Ditolak` only if the
    device_id itself does not exist.
    """
    d = db.get(Device, device_id)
    if d is None:
        raise katalog.Ditolak("device id=%s tidak ditemukan." % device_id)

    base = {"device_id": d.id, "device": d.name, "platform": d.platform}

    if not ekstrak.didukung(d.platform):
        return dict(base, didukung=False, alasan=(
            "Platform '%s' belum didukung deteksi penyimpangan. Yang "
            "didukung: %s. Potret Linux yang ada saat ini berisi POSTUR "
            "KEAMANAN (sshd_config, port dengar), bukan hostname/NTP/DNS "
            "yang dinyatakan katalog intent -- membandingkannya akan "
            "menghasilkan kesimpulan yang salah, bukan sekadar tidak "
            "lengkap." % (d.platform, ", ".join(sorted(ekstrak.EKSTRAKTOR)))))

    intent = sot_svc.ambil(db, device_id)
    if not (intent["nilai"] or intent["interface"] or intent["vlan"] or intent["rute"]):
        return dict(base, didukung=True, punya_intent=False, alasan=(
            "Belum ada satu pun kunci intent dinyatakan untuk perangkat "
            "ini. Isi dulu di /admin/konfig/sot/%d sebelum penyimpangan "
            "bisa dideteksi -- tidak ada yang bisa dibandingkan dengan "
            "kekosongan." % d.id))

    snap = db.execute(
        select(KonfigSnapshot).where(KonfigSnapshot.device_id == device_id)
        .order_by(KonfigSnapshot.waktu.desc())
    ).scalars().first()
    if snap is None:
        return dict(base, didukung=True, punya_intent=True, punya_potret=False,
                   alasan="Belum ada potret konfigurasi tersimpan untuk "
                         "perangkat ini -- poller belum sempat membacanya.")

    observed = ekstrak.ekstrak(d.platform, snap.teks)

    result_value = _banding_nilai(d.platform, intent["nilai"], observed["nilai"])
    result_interface = _banding_interface(intent["interface"], observed["interface"])
    result_vlan = _banding_vlan(intent["vlan"], observed["vlan"])
    result_route = _banding_rute(intent["rute"], observed["rute"])
    semua = result_value + result_interface + result_vlan + result_route

    menyimpang = [h for h in semua if h["status"] in (BEDA, HILANG)]
    tidak_terbaca = [h for h in semua if h["status"] == TIDAK_TERBACA]

    return dict(
        base, didukung=True, punya_intent=True, punya_potret=True,
        potret_waktu=snap.waktu.isoformat(),
        nilai=result_value, interface=result_interface, vlan=result_vlan, rute=result_route,
        jumlah_diperiksa=len(semua),
        jumlah_menyimpang=len(menyimpang),
        jumlah_tidak_terbaca=len(tidak_terbaca),
        jumlah_aman_otomatis=sum(1 for h in menyimpang if h["risiko"] == katalog.RISIKO_AMAN),
        jumlah_wajib_manusia=sum(1 for h in menyimpang if h["risiko"] == katalog.RISIKO_MANUSIA),
        selaras=not menyimpang,
    )


def ringkasan(db):
    """One row per device that has an intent catalog (like `sot.service.ringkasan()`),
    plus its drift status.
    """
    hasil = []
    for d in db.execute(select(Device)).scalars().all():
        if d.platform not in katalog.platform_didukung():
            continue
        r = bandingkan(db, d.id)
        hasil.append({
            "device_id": d.id, "device": d.name, "platform": d.platform,
            "didukung": r["didukung"],
            "punya_intent": r.get("punya_intent"),
            "punya_potret": r.get("punya_potret"),
            "selaras": r.get("selaras"),
            "jumlah_menyimpang": r.get("jumlah_menyimpang"),
            "jumlah_wajib_manusia": r.get("jumlah_wajib_manusia"),
            "alasan": r.get("alasan"),
        })
    return hasil

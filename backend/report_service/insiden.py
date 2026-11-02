"""Incident reports (root cause vs impact) for report_service; re-exported by `report_service/__init__.py`."""
from datetime import datetime
from sqlalchemy import func
from models import (Device, DeviceEvent, SumberDaya, Service, ServiceCheck)

from ._inti import (BATAS_PRAKIRAAN_HARI)



def diagnosis(db):
    """What is broken, what is only affected, and the first step to take.

    Intentionally ONE ordered list: `sebab` (cause) entries on top, each `akibat`
    (impact) right below its cause. Impacts are not hidden: a tool that hides
    alarms for tidiness hides the important one the day it guesses wrong, and the
    dependency list is written by hand.
    """
    import akar
    from connectors import layanan as _layanan

    # Down devices are judged from `device_events`, not from a single ping row.
    #
    # The latest `status_logs` row is not enough: one lost ping on the
    # high-latency (152 ms) Site B path would show a cause card for a healthy
    # device while its device card on the same screen says UP.
    #
    # `device_events` holds NSM's outage decisions: written only on status change,
    # after the poller's consecutive-failure rule. Using it gives this panel the
    # same definition of "down" as the rest of NSM.
    name_device = {}
    for d in db.query(Device).all():
        name_device[d.id] = d.name

    sub_e = (db.query(DeviceEvent.device_id.label("did"),
                      func.max(DeviceEvent.id).label("mid"))
             .group_by(DeviceEvent.device_id).subquery())
    device_fall = set()
    for e in db.query(DeviceEvent).join(sub_e, DeviceEvent.id == sub_e.c.mid).all():
        if e.event_type == "DOWN":
            device_fall.add(e.device_id)

    # Paused devices are not counted as down. A pause is a decision, not an outage;
    # otherwise planned maintenance would look like an incident.
    paused = {d.id for d in db.query(Device).filter(Device.aktif == 0).all()}
    device_fall -= paused

    # Services currently failing, from the latest check.
    sub_s = (db.query(ServiceCheck.service_id.label("sid"),
                      func.max(ServiceCheck.id).label("mid"))
             .group_by(ServiceCheck.service_id).subquery())
    check_last = {
        c.service_id: c
        for c in db.query(ServiceCheck).join(sub_s, ServiceCheck.id == sub_s.c.mid).all()
    }

    service_fall = {}
    info = {}
    for s in db.query(Service).filter(Service.aktif != 0).all():
        c = check_last.get(s.id)
        if c is None or c.ok:
            continue
        service_fall[s.id] = s.device_id
        info[s.id] = (s, c)

    vonis = akar.nilai(db, service_fall, device_fall)

    daftar = []
    for sid, v in vonis.items():
        s, c = info[sid]
        kategori = c.kategori
        daftar.append({
            "layanan_id": sid,
            "nama": s.nama,
            "device": name_device.get(s.device_id, "?"),
            "device_id": s.device_id,
            "vonis": v["vonis"],
            # Plain sentence first: what someone glancing at the screen reads; details below.
            "arti": _layanan.teks_sebab(kategori) if kategori else
                    "Pemeriksaan gagal tanpa kategori.",
            "karena": v["karena"],
            "karena_layanan": (info[v["karena_layanan"]][0].nama
                               if v["karena_layanan"] in info else None),
            "karena_device": (name_device.get(v["karena_device"])
                              if v["karena_device"] else None),
            # Steps are shown only for causes. Telling people to check a service that is
            # merely affected sends them to the wrong place.
            "langkah": (_layanan.langkah(kategori)
                        if v["vonis"] == "sebab" else []),
            "kalau_buntu": (_layanan.KALAU_BUNTU
                            if v["vonis"] == "sebab" else None),
            "kategori": kategori,
            "kode": c.kode,
            "waktu_ms": c.waktu_ms,
            "terakhir_cek": c.timestamp.isoformat() if c.timestamp else None,
            # Raw technical evidence for readers who skip straight to the details.
            "bukti": "%s %s:%s%s" % (s.jenis, name_device.get(s.device_id, "?"),
                                     s.port, s.path or ""),
        })

    # Down devices with no registered services must still appear; otherwise a dead
    # switch (no monitored services) would never show here.
    # A device that is down only because its path runs through another down device
    # is an impact, not a cause, just like a service on a dead host (e.g. with R1
    # down, R2 and SW-B behind it are impacts). The answer comes from
    # `ketergantungan.py`.
    #
    # `mati=device_turun` is passed so there is ONE definition of "down": this
    # panel's (device_events), not a second one from that module.
    import ketergantungan as _kg
    graf_kg = None
    try:
        graf_kg = _kg.graf(db)
    except Exception:
        graf_kg = None

    has_service = {d for d in service_fall.values()}
    for did in sorted(device_fall - has_service):
        upstream = None
        if graf_kg is not None:
            try:
                h = _kg.penyebab_hulu(db, did, g=graf_kg, mati=device_fall)
                if h["status"] == _kg.ADA_PENYEBAB and h["hulu_mati"]:
                    upstream = h
            except Exception:
                upstream = None

        # Name the MOST UPSTREAM down device, not the nearest neighbor: that is what
        # needs fixing. `jalur` is ordered outward from NSM, so the first element of
        # `hulu_mati` is closest to NSM, i.e. the real root.
        root_cause_dev = upstream["hulu_mati"][0] if upstream else None
        daftar.append({
            "layanan_id": None, "nama": name_device.get(did, "?"),
            "device": name_device.get(did, "?"), "device_id": did,
            "vonis": "akibat" if upstream else "sebab",
            "arti": "Perangkat tidak menjawab ping maupun port TCP mana pun.",
            "karena": (("jalan ke sana melewati %s, yang juga sedang mati -- "
                        "belum tentu perangkat ini sendiri bermasalah"
                        % root_cause_dev["nama"]) if upstream else None),
            "karena_layanan": None,
            # Name, not id: the service branch above fills this field with
            # `nama_device.get(...)` and the view prints it as-is. A number here would print
            # "5" mid-sentence on device cards: one field, two meanings.
            "karena_device": root_cause_dev["nama"] if upstream else None,
            # Steps only for causes, same as services above.
            "langkah": ([] if upstream else
                        ["ping <alamat> dari laptop",
                         "periksa apakah VM/perangkatnya menyala",
                         "kalau lintas lokasi: periksa router di jalurnya"]),
            "kalau_buntu": None if upstream else _layanan.KALAU_BUNTU,
            "kategori": "perangkat_mati", "kode": None, "waktu_ms": None,
            "terakhir_cek": None, "bukti": "icmp + tcp gagal",
        })

    # Saturation: not broken yet, but will be.
    #
    # Same panel, not a separate page: someone handling an outage will not open a
    # second page to check what is nearly full, and disks fill fastest during
    # outages (logs, diagnostic snapshots).
    #
    # Ranked below impacts since it has caused nothing yet, but unlike impacts it
    # carries steps: the fix for a nearly full disk is clear and cheaper now.
    from connectors import sumberdaya as _sd
    sub_sd = (db.query(SumberDaya.device_id.label("did"),
                       func.max(SumberDaya.id).label("mid"))
              .group_by(SumberDaya.device_id).subquery())
    for r in db.query(SumberDaya).join(sub_sd, SumberDaya.id == sub_sd.c.mid).all():
        if r.device_id in paused:
            continue
        ukur = {"disk": r.disk_persen, "mem": r.mem_persen,
                "load": r.load_per_inti}
        ukur = {k: v for k, v in ukur.items() if v is not None}
        for kunci, v in _sd.vonis(ukur).items():
            if v == "sehat":
                continue
            daftar.append({
                "layanan_id": None,
                "nama": "%s — %s" % (name_device.get(r.device_id, "?"),
                                     _sd.NAMA[kunci]),
                "device": name_device.get(r.device_id, "?"),
                "device_id": r.device_id,
                "vonis": "peringatan",
                "arti": _sd.ARTI[kunci],
                "karena": None, "karena_layanan": None, "karena_device": None,
                "langkah": _sd.LANGKAH[kunci],
                "kalau_buntu": None,
                "kategori": "saturasi_" + kunci,
                "kode": None, "waktu_ms": None,
                "terakhir_cek": r.waktu.isoformat() if r.waktu else None,
                # Value AND threshold, so "why is this lit" need not be guessed. A warning
                # without its threshold can only be trusted or ignored, not judged.
                "bukti": "%s %.1f%s (ambang %s / %s)" % (
                    kunci, ukur[kunci], _sd.SATUAN[kunci],
                    _sd.AMBANG[kunci][0], _sd.AMBANG[kunci][1]),
            })

    # Capacity forecast: warns BEFORE a threshold is crossed.
    #
    # The saturation block above fires only after a threshold is passed; it cannot
    # answer "is this heading there?". A disk at 59% triggers nothing today, but at
    # 1.39%/day it crosses within thirty days. Data comes from `sumber_daya`; see
    # `kapasitas.py` for the three honesty rules limiting forecasts.
    #
    # Only shown when the device is healthy NOW. If the threshold is already
    # crossed, saturation covers it; two warnings for one disk add nothing.
    try:
        import kapasitas as _kap
        for p in _kap.prakiraan_semua(db):
            if p["device_id"] in paused:
                continue
            hw = p.get("hari_menuju_waspada")
            if p["vonis"] not in (_kap.CUKUP, _kap.TIDAK_YAKIN):
                continue
            if hw is None or hw > BATAS_PRAKIRAAN_HARI:
                continue
            if (p.get("disk_persen") or 0) >= _kap.AMBANG_WASPADA:
                continue  # already handled by the saturation block above
            daftar.append({
                "layanan_id": None,
                "nama": "%s — Disk menuju penuh" % p["nama"],
                "device": p["nama"], "device_id": p["device_id"],
                "vonis": "peringatan",
                "arti": p["alasan"],
                "karena": None, "karena_layanan": None, "karena_device": None,
                "langkah": [
                    "periksa apa yang tumbuh: `du -h --max-depth=1 / | sort -h`",
                    "log dan potret diagnosa biasanya penyumbang terbesar",
                    "kalau pertumbuhannya wajar, siapkan penambahan disk "
                    "SEBELUM tanggal di atas — bukan sesudahnya",
                ],
                "kalau_buntu": None,
                "kategori": "kapasitas_disk",
                "kode": None, "waktu_ms": None, "terakhir_cek": None,
                # Evidence the reader can judge: rate, sample count, and how linear the trend is.
                "bukti": "disk %.0f%%, +%.2f%%/hari, %d sampel dalam %d hari, "
                         "R^2 %.2f" % (p.get("disk_persen") or 0,
                                       p.get("laju_per_hari") or 0,
                                       p.get("sampel") or 0,
                                       p.get("jendela_hari") or 0,
                                       p.get("r2") or 0),
            })
    except Exception as e:
        # The forecast is an add-on, not a requirement: its failure must not wipe out
        # the diagnosis panel (same pattern as blast radius in `kirim_perintah.py`).
        print("   [kapasitas] prakiraan dilewati: %s" % str(e)[:120])

    # Causes first, then impacts, then warnings. Sorted by name within each group
    # so the order stays stable across refreshes (every 10 s).
    order_verdict = {"sebab": 0, "akibat": 1, "peringatan": 2}
    daftar.sort(key=lambda x: (order_verdict.get(x["vonis"], 9), x["nama"]))

    # The summary is computed from the final `daftar`, not from `vonis`.
    #
    # `vonis` holds only SERVICES; down devices without registered services are
    # added afterwards. Counting from `vonis` would show "all monitored services
    # healthy" above a red cause card, and a header that contradicts the page
    # teaches readers to ignore it.
    n_cause = sum(1 for x in daftar if x["vonis"] == "sebab")
    n_akibat = sum(1 for x in daftar if x["vonis"] == "akibat")
    n_peringatan = sum(1 for x in daftar if x["vonis"] == "peringatan")

    section = []
    if n_cause:
        section.append("%d sebab" % n_cause)
    if n_akibat:
        section.append("%d ikut terdampak" % n_akibat)
    if n_peringatan:
        section.append("%d peringatan" % n_peringatan)

    if not daftar:
        ringkas = "Semua yang dipantau sehat."
    elif not n_cause and not n_akibat:
        ringkas = ("Tidak ada yang rusak. %d hal mendekati batas dan pantas "
                   "dikerjakan sebelum jadi gangguan." % n_peringatan)
    elif n_akibat:
        ringkas = (", ".join(section) + ". Perbaiki yang bertanda SEBAB lebih "
                   "dulu — yang lain kemungkinan pulih sendiri.")
    else:
        ringkas = ", ".join(section) + "."

    return {
        "waktu": datetime.now().isoformat(),
        "ringkas": ringkas,
        "jumlah_sebab": n_cause,
        "jumlah_akibat": n_akibat,
        "jumlah_peringatan": n_peringatan,
        "daftar": daftar,
    }

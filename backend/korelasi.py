r"""Correlate many symptoms into ONE incident.

PROBLEM SOLVED
--------------
If LDAP `.101` goes down, NSM produces separate rows: device DOWN, LDAP service
DOWN, E-Canteen login failure, SSH failure, replica unreachable. That is ONE event
reported as five, and someone has to merge them in their head every time. Fewer
alarms is not the real point: an alarm that is always on trains people to ignore
the page that must be trusted on the day something really breaks.

THREE THINGS THAT MERGE SYMPTOMS
--------------------------------
1. Time. Symptoms inside one window may be related.
2. Dependency. Symptoms with the SAME root according to the graph are merged. This
   is what makes the correlation more than a guess.
3. Same root = same incident. Because the root is computed from the graph, this is
   far more precise than grouping by time proximity alone.

WHY NOT GROUP BY TIME ALONE
---------------------------
Two unrelated faults can happen in the same minute. Merging them gives an
"incident" that tells two stories at once, which is more confusing than two
separate rows. So time is only a FILTER; the root is what MERGES.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It never touches devices or triggers any action: it reads recorded events and
organizes them. Every decision to act stays with `pagar_otomasi`.
"""
from datetime import datetime, timedelta

from sqlalchemy import func, select

import ketergantungan
import models

# Symptoms appearing within this span of an open incident are treated as possibly part
# of it. The poller runs every 5 s with a threshold of 3 consecutive failures, so
# genuinely related symptoms usually appear within tens of seconds; 10 minutes leaves
# slack for services that take several rounds to be noticed.
JENDELA_GABUNG_DETIK = 600

JEDA_TUTUP_DETIK = 300

KEPARAHAN_URUT = {"info": 0, "perhatian": 1, "bahaya": 2}


def _lebih_parah(a, b):
    return a if KEPARAHAN_URUT.get(a, 0) >= KEPARAHAN_URUT.get(b, 0) else b


def device_mati(db, sekarang=None):
    """Set of device_ids currently down according to `device_events`.

    Read from `device_events` (transitions that already passed the threshold), NOT from
    raw `status_logs`: a single missed ping is not an outage.
    """
    mati = set()
    sub = (select(models.DeviceEvent.device_id,
                  func.max(models.DeviceEvent.timestamp).label("t"))
           .group_by(models.DeviceEvent.device_id).subquery())
    line = db.execute(
        select(models.DeviceEvent)
        .join(sub, (models.DeviceEvent.device_id == sub.c.device_id)
              & (models.DeviceEvent.timestamp == sub.c.t))
    ).scalars().all()
    for e in line:
        if (e.event_type or "").upper() == "DOWN":
            mati.add(e.device_id)
    return mati


def akar_untuk(db, device_id, g, mati):
    """(root_device_id, certain) for one problem device.

    If an UPSTREAM device is also down, that device is the root and this one is only an
    effect; otherwise this device is its own root.
    """
    try:
        h = ketergantungan.penyebab_hulu(db, device_id, g=g, mati=mati)
    except Exception:
        return device_id, False
    upstream = h.get("hulu_mati") or []
    if upstream:
        return upstream[0]["id"], h.get("status") != "tidak_bisa_dipastikan"
    if h.get("status") == "tidak_bisa_dipastikan":
        return device_id, False
    return device_id, True


def _insiden_terbuka(db, akar_id, sekarang):
    """Open incident with the same root, still inside the merge window."""
    batas = sekarang - timedelta(seconds=JENDELA_GABUNG_DETIK)
    q = select(models.Insiden).where(
        models.Insiden.status == "terbuka",
        models.Insiden.mulai >= batas - timedelta(days=2))
    q = (q.where(models.Insiden.akar_device_id == akar_id)
         if akar_id is not None
         else q.where(models.Insiden.akar_device_id.is_(None)))
    return db.execute(q.order_by(models.Insiden.mulai.desc())
                      .limit(1)).scalars().first()


def record_symptom(db, jenis, sumber_id, device_id, waktu, detail,
                 keparahan="perhatian", akar_id=None, akar_pasti=None,
                 sekarang=None):
    """Put one symptom into the right incident, creating a new one if needed.

    Returns (incident, symptom, new). `baru` is True if the incident was just created;
    the caller uses it to decide whether to notify.
    """
    sekarang = sekarang or datetime.now()
    if akar_id is None:
        akar_id = device_id

    ins = _insiden_terbuka(db, akar_id, sekarang)
    baru = ins is None
    if baru:
        ins = models.Insiden(
            mulai=waktu, status="terbuka", akar_device_id=akar_id,
            akar_pasti=akar_pasti, keparahan=keparahan,
            jumlah_gejala=0, notif_terkirim=False)
        db.add(ins)
        db.flush()
    else:
        ins.keparahan = _lebih_parah(ins.keparahan or "info", keparahan)
        if akar_pasti is not None and ins.akar_pasti is None:
            ins.akar_pasti = akar_pasti

    g = db.execute(select(models.InsidenGejala).where(
        models.InsidenGejala.insiden_id == ins.id,
        models.InsidenGejala.jenis == jenis,
        models.InsidenGejala.device_id == device_id,
        models.InsidenGejala.detail == detail)).scalars().first()
    if g is None:
        g = models.InsidenGejala(
            insiden_id=ins.id, jenis=jenis, sumber_id=sumber_id,
            device_id=device_id, waktu=waktu, waktu_terakhir=waktu,
            jumlah=1, pulih=False, detail=detail)
        db.add(g)
        ins.jumlah_gejala = (ins.jumlah_gejala or 0) + 1
    else:
        g.jumlah = (g.jumlah or 1) + 1
        g.waktu_terakhir = waktu
        g.pulih = False
        # A symptom that RECURS forgets its recovery time. Otherwise a flapping device would
        # close its incident using the OLD recovery time, skipping the 300 s anti-flap delay
        # and closing the incident while the symptom is active again.
        g.pulih_pada = None

    ins.ringkas = _susun_ringkas(db, ins)
    db.commit()
    return ins, g, baru


def tandai_pulih(db, device_id, jenis=None, sekarang=None):
    """Mark this device's symptoms as recovered, and close the incident once all of its
    symptoms have recovered.
    """
    sekarang = sekarang or datetime.now()
    q = select(models.InsidenGejala).join(
        models.Insiden, models.Insiden.id == models.InsidenGejala.insiden_id
    ).where(models.Insiden.status == "terbuka",
            models.InsidenGejala.device_id == device_id,
            models.InsidenGejala.pulih == False)  # noqa: E712
    if jenis:
        q = q.where(models.InsidenGejala.jenis == jenis)
    for g in db.execute(q).scalars().all():
        g.pulih = True
        # Recovery time is RECORDED, not inferred from `waktu_terakhir`, which only says when
        # the symptom was last seen still broken. Using it as the end time would give
        # `mttr_detik = 0` to every incident that recovers before the next correlation round
        # (60 s).
        g.pulih_pada = sekarang
    db.commit()
    return tutup_yang_selesai(db, sekarang=sekarang)


def tutup_yang_selesai(db, sekarang=None):
    """Close incidents whose symptoms have all recovered.

    Waits `JEDA_TUTUP_DETIK` before closing: a flapping device (recovers, then fails
    again) should stay ONE incident, not three. Without the delay, correlation would
    multiply rows instead of reducing them.
    """
    sekarang = sekarang or datetime.now()
    ditutup = []
    for ins in db.execute(select(models.Insiden).where(
            models.Insiden.status == "terbuka")).scalars().all():
        gejala = db.execute(select(models.InsidenGejala).where(
            models.InsidenGejala.insiden_id == ins.id)).scalars().all()
        if not gejala or any(not g.pulih for g in gejala):
            continue
        # When the symptom last RECOVERED, not when it was last seen broken. Old rows created
        # before the `pulih_pada` column existed fall back to `waktu_terakhir`.
        pulih_pada = max((g.pulih_pada or g.waktu_terakhir or g.waktu)
                         for g in gejala)

        if (sekarang - pulih_pada).total_seconds() < JEDA_TUTUP_DETIK:
            continue
        ins.status = "pulih"
        ins.selesai = pulih_pada

        # MTTR is never negative: the system clock can step backwards (NTP correcting a
        # drifted clock), and a negative MTTR on the page is more confusing than zero.
        ins.mttr_detik = max(0, int((pulih_pada - ins.mulai).total_seconds()))
        ditutup.append(ins.id)
    if ditutup:
        db.commit()
    return ditutup


def _susun_ringkas(db, ins):
    akar = db.get(models.Device, ins.akar_device_id) if ins.akar_device_id else None
    gejala = db.execute(select(models.InsidenGejala).where(
        models.InsidenGejala.insiden_id == ins.id)).scalars().all()
    n_dev = len({g.device_id for g in gejala if g.device_id})

    if akar is None:
        pokok = "Gangguan yang akarnya belum bisa dipastikan"
    elif n_dev <= 1:
        pokok = "%s bermasalah" % akar.name
    else:
        pokok = ("%s bermasalah, dan %d perangkat lain ikut terdampak"
                 % (akar.name, n_dev - 1))

    if ins.akar_pasti is False:
        pokok += " (akar belum pasti -- graf ketergantungan tidak yakin)"
    return "%s. %d gejala tercatat." % (pokok, len(gejala))


def proses(db, sekarang=None):
    """One correlation round: read the current state, build incidents.

    Called by the poller. Idempotent: running it twice creates no duplicate incidents,
    because identical symptoms are recognized and deduplicated.

    RUNS PER TENANT once tenants are in use. This is for correctness, not tidiness: the
    dependency graph is rooted at the device with `platform='lokal'`, and with two
    tenants there are TWO vantage points. One combined graph makes upstream tracing fail
    for the second tenant, so each of its devices becomes its own root and correlation
    silently stops working for it.
    """
    sekarang = sekarang or datetime.now()

    import tenancy
    if tenancy.sekarang() is None:
        with tenancy.lintas_tenant():
            ids = db.execute(select(models.Tenant.id).where(
                models.Tenant.aktif == True)).scalars().all()   # noqa: E712
        if ids:
            merge = {"mati": 0, "insiden_baru": 0, "gejala_diperbarui": 0,
                      "ditutup": 0}
            for tid in ids:
                with tenancy.dengan_tenant(tid):
                    h = _proses_satu(db, sekarang)
                for k in merge:
                    merge[k] += h.get(k, 0)
            # Devices WITHOUT a tenant are still correlated, so enabling tenants does not silently
            # stop monitoring devices whose owner has not been assigned yet.
            h = _proses_satu(db, sekarang, hanya_tanpa_tenant=True)
            for k in merge:
                merge[k] += h.get(k, 0)
            return merge
    return _proses_satu(db, sekarang)


def _proses_satu(db, sekarang, hanya_tanpa_tenant=False):
    g = ketergantungan.graf(db)
    mati = device_mati(db, sekarang)

    created, diperbarui = 0, 0
    for did in sorted(mati):
        d = db.get(models.Device, did)
        if d is None:
            continue
        if hanya_tanpa_tenant and d.tenant_id is not None:
            continue
        akar_id, certain = akar_untuk(db, did, g, mati)
        detail = "Device %s tidak terjangkau" % d.name
        _, _, baru = record_symptom(
            db, "device", did, did, sekarang, detail,
            keparahan="bahaya", akar_id=akar_id, akar_pasti=certain,
            sekarang=sekarang)
        created += 1 if baru else 0
        diperbarui += 0 if baru else 1

    q_all = select(models.Device.id).where(
        models.Device.aktif == True)                   # noqa: E712
    if hanya_tanpa_tenant:
        q_all = q_all.where(models.Device.tenant_id.is_(None))
    semua = db.execute(q_all).scalars().all()
    for did in semua:
        if did not in mati:
            tandai_pulih(db, did, jenis="device", sekarang=sekarang)

    ditutup = tutup_yang_selesai(db, sekarang=sekarang)
    return {"mati": len(mati), "insiden_baru": created,
            "gejala_diperbarui": diperbarui, "ditutup": len(ditutup)}


def ringkas(db, jam=24):
    """For the page: open incidents plus recently recovered ones."""
    batas = datetime.now() - timedelta(hours=jam)
    terbuka = db.execute(select(models.Insiden).where(
        models.Insiden.status == "terbuka"
    ).order_by(models.Insiden.mulai.desc())).scalars().all()
    pulih = db.execute(select(models.Insiden).where(
        models.Insiden.status == "pulih",
        models.Insiden.selesai >= batas
    ).order_by(models.Insiden.selesai.desc()).limit(20)).scalars().all()

    def bentuk(i):
        akar = db.get(models.Device, i.akar_device_id) if i.akar_device_id else None
        return {"id": i.id, "mulai": i.mulai.isoformat() if i.mulai else None,
                "selesai": i.selesai.isoformat() if i.selesai else None,
                "status": i.status, "akar": akar.name if akar else None,
                "akar_pasti": i.akar_pasti, "keparahan": i.keparahan,
                "ringkas": i.ringkas, "jumlah_gejala": i.jumlah_gejala,
                "mttr_detik": i.mttr_detik}

    return {"terbuka": [bentuk(i) for i in terbuka],
            "pulih": [bentuk(i) for i in pulih],
            "jam": jam}

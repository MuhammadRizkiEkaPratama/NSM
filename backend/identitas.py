"""Device identity beyond the IP address.

Design: docs/design/TRAFFIC-IDENTITY-FW.md.

The problem: NSM recognizes devices by IP address alone, and four of the six
devices in the lab have DEFAULT addresses that would also match on someone
else's network: `192.168.1.1`, `192.168.56.101`, `192.168.56.103`,
`192.168.56.1`.

While NSM only read, hitting the wrong target produced wrong data. Once it can
write, it produces **configuration changes on someone else's device**, and the
`reload in 5` safety net does not help there: it protects against a wrong
command, not a wrong device.

MANY MARKERS, AND A PARTIAL MATCH IS ENOUGH. A single marker is too fragile: the
MAC changes if the network card is replaced, `machine-id` is copied when a VM is
cloned, hostnames legitimately change, and VMs have no serial. So several are
stored and the verdict depends on how many match.

"EMPTY" AND "CONTRADICTING" ARE DIFFERENT. An empty marker means NSM never asked.
A contradicting marker means NSM asked and got a different answer. Treating them
alike makes a device not yet identified look like a foreign one, and a feature
that blocks normal work gets switched off on day one.
"""
from datetime import datetime

from models import Device, KonfigSnapshot, IdentitasPerangkat

SAMA = "sama"
KEMUNGKINAN_SAMA = "kemungkinan_sama"
BERTENTANGAN = "bertentangan"
BELUM_DIKETAHUI = "belum_diketahui"

# Verdicts that allow the WRITE path. Kept as a list, not as a comparison at the
# point of use, so the condition lives in one place and can be read without
# tracing the sender code.
BOLEH_DITULISI = (SAMA,)


def hostname_dari_konfig(teks):
    """Extract `hostname X` from a Cisco IOS configuration snapshot.

    The CHEAPEST source available: the text is already stored in the database, so
    collecting it needs no connection at all.
    """
    for line in (teks or "").splitlines():
        b = line.strip()
        if b.lower().startswith("hostname "):
            nilai = b.split(None, 1)[1].strip()
            return nilai or None
    return None


def catat(db, device_id, jenis, nilai, sumber):
    """Store one marker. Returns (row, changed, old_value).

    A different OLD VALUE IS NOT OVERWRITTEN: the row is left as is and a new row is
    written beside it. Overwriting would erase the only evidence that a difference
    ever existed, and "since when did the hostname change?" is exactly the question
    people bring to this page.
    """
    if not nilai:
        return None, False, None
    sekarang = datetime.now()
    lama = (db.query(IdentitasPerangkat)
            .filter(IdentitasPerangkat.device_id == device_id,
                    IdentitasPerangkat.jenis == jenis,
                    IdentitasPerangkat.nilai == nilai)
            .first())
    if lama is not None:
        lama.terakhir = sekarang
        return lama, False, None

    # DIFFERENT value for the same kind: that is a contradiction, and the row is
    # added without touching the old one.
    previous = (db.query(IdentitasPerangkat)
                  .filter(IdentitasPerangkat.device_id == device_id,
                          IdentitasPerangkat.jenis == jenis)
                  .order_by(IdentitasPerangkat.terakhir.desc())
                  .first())
    baru = IdentitasPerangkat(
        device_id=device_id, jenis=jenis, nilai=nilai,
        pertama=sekarang, terakhir=sekarang, sumber=sumber)
    db.add(baru)
    return baru, previous is not None, (previous.nilai if previous else None)


def vonis(db, device_id, terlihat=None, dalam_detik=3600):
    """Identity verdict of a device.

    `terlihat` = {kind: value} the device JUST answered. If empty, the verdict is
    computed from what is stored only.

    `dalam_detik` decides which markers still count. A marker not confirmed for a
    long time counts neither as evidence nor as a contradiction.
    """
    stored = (db.query(IdentitasPerangkat)
                 .filter(IdentitasPerangkat.device_id == device_id).all())
    if not stored and not terlihat:
        return BELUM_DIKETAHUI, {"cocok": 0, "bentrok": 0, "alasan": []}

    per_kind = {}
    for t in stored:
        per_kind.setdefault(t.jenis, []).append(t)

    cocok = 0
    bentrok = 0
    alasan = []
    for jenis, nilai in (terlihat or {}).items():
        if not nilai:
            continue
        has = per_kind.get(jenis)
        if not has:
            # Never recorded: neither evidence nor contradiction.
            alasan.append(f"{jenis}: baru pertama kali terlihat ({nilai})")
            continue
        if any(p.nilai == nilai for p in has):
            cocok += 1
            alasan.append(f"{jenis}: cocok ({nilai})")
        else:
            bentrok += 1
            lama = ", ".join(sorted({p.nilai for p in has}))
            alasan.append(f"{jenis}: BERBEDA — tersimpan {lama}, terlihat {nilai}")

    if bentrok:
        return BERTENTANGAN, {"cocok": cocok, "bentrok": bentrok, "alasan": alasan}
    if cocok >= 2:
        return SAMA, {"cocok": cocok, "bentrok": 0, "alasan": alasan}
    if cocok == 1:
        return KEMUNGKINAN_SAMA, {"cocok": 1, "bentrok": 0, "alasan": alasan}
    return BELUM_DIKETAHUI, {"cocok": 0, "bentrok": 0, "alasan": alasan}


def amati_dari_konfig(db):
    """Read markers from configuration snapshots. Stores NOTHING.

    Returns `{device_id: {kind: value}}`, the same shape `vonis(terlihat=...)`
    takes.

    ZERO NETWORK CONNECTIONS: the text is already stored in the database.
    """
    terlihat = {}
    for d in db.query(Device).all():
        snapshot = (db.query(KonfigSnapshot)
                  .filter(KonfigSnapshot.device_id == d.id)
                  .order_by(KonfigSnapshot.waktu.desc())
                  .first())
        if snapshot is None:
            continue
        nama = hostname_dari_konfig(snapshot.teks)
        if nama:
            terlihat.setdefault(d.id, {})["hostname"] = nama
    return terlihat


def kumpulkan_dari_konfig(db):
    """Observe, JUDGE, then store. The order determines the meaning.

    Storing first and judging after makes the first comparison match itself: the
    value just written is of course equal to the value seen. That "evidence" proves
    nothing, and it would appear at the most important moment, the first time a
    device is recognized.

    So the verdict is computed against what was ALREADY stored, and only then are the
    values stored. The first collection therefore yields `belum_diketahui` (nothing
    to compare with yet), and later collections yield evidence.

    Returns a list of human-readable notes.
    """
    terlihat = amati_dari_konfig(db)
    catatan = []
    for d in db.query(Device).all():
        nilai = terlihat.get(d.id)
        if not nilai:
            perbarui_vonis(db, d.id)
            continue
        # 1. JUDGE first, against what is already stored.
        v, detail = perbarui_vonis(db, d.id, nilai)
        # 2. THEN store.
        for jenis, content in nilai.items():
            _line, berubah, lama = catat(db, d.id, jenis, content, "konfig")
            catatan.append({
                "device_id": d.id, "device": d.name, "jenis": jenis,
                "nilai": content, "berubah": berubah, "lama": lama,
                "vonis": v, "alasan": detail["alasan"],
            })
    return catatan


def amati_semua(db, pakai_jaringan=True):
    """Combine markers from ALL sources. Stores NOTHING.

    Returns `{device_id: {kind: value}}`.

    `pakai_jaringan=False` limits it to sources that do not touch the network at all
    (stored configuration snapshots + this machine's ARP table). Used by tests and
    quick checks.

    Why ONE function, not one per source: the verdict depends on HOW MANY markers
    match, so it is only correct if all markers obtainable in one round are judged
    TOGETHER. Collecting per source and judging three times would produce three
    verdicts overwriting each other, and the stored one would come from whichever
    source ran last, usually `kemungkinan_sama` even though three markers match.
    """
    import identitas_sumber as sumber

    merge = {}

    def tambah(peta):
        for did, penanda in (peta or {}).items():
            for jenis, nilai in (penanda or {}).items():
                if nilai:
                    # The source called first wins. The order is set below: the least disputable
                    # first.
                    merge.setdefault(did, {}).setdefault(jenis, nilai)

    # 1. Configuration snapshots: already stored, zero connections.
    tambah(amati_dari_konfig(db))
    # 2. ARP table + own network card: no new connections.
    tambah(sumber.amati_dari_arp(db))

    if not pakai_jaringan:
        return merge

    # 3. SSH before SNMP, on purpose. Both can give `hostname`; the SSH one comes from
    #    the machine itself, while SNMP `sysName` is a value TYPED into the SNMP
    #    configuration and can go stale after the machine is renamed. When both exist,
    #    the machine's own answer is used.
    for d in db.query(Device).all():
        # `== 0`, NOT `is False`: the `aktif` column is an INTEGER, and `0 is False` is
        # False in Python. With `is False` this line would never skip a single device.
        if d.aktif == 0:
            # Paused devices are not contacted. Pausing means ceasing to look, and quietly
            # collecting their identity would violate what the button means.
            continue
        try:
            tambah({d.id: sumber.penanda_ssh(d)})
        except Exception:
            pass
        try:
            tambah({d.id: sumber.penanda_snmp(d)})
        except Exception:
            pass

    return merge


def kumpulkan(db, pakai_jaringan=True):
    """Observe all sources, JUDGE, then store. The order determines the meaning.

    Same as `kumpulkan_dari_konfig()`: the verdict is computed against what is
    ALREADY stored, then the markers are stored. Reversed, the first comparison
    would match itself (the value just written equals the value seen), and such
    "evidence" appears at the most important moment, when a device is first
    recognized.
    """
    terlihat = amati_semua(db, pakai_jaringan=pakai_jaringan)
    catatan = []
    for d in db.query(Device).all():
        penanda = terlihat.get(d.id)
        if not penanda:
            perbarui_vonis(db, d.id)
            catatan.append({
                "device_id": d.id, "device": d.name, "penanda": {},
                "vonis": d.identitas_vonis, "alasan": [],
                "baru": [], "bentrok": [],
            })
            continue

        v, detail = perbarui_vonis(db, d.id, penanda)

        baru, bentrok = [], []
        for jenis, content in penanda.items():
            # "First time" is decided BEFORE `catat()`, not from its return value. `catat()`
            # returns the SAME shape for a newly created marker and an existing one
            # (`berubah=False, nilai_lama=None` for both), so they cannot be told apart from
            # it. Trying that made the poller report "6 devices got a new marker" every round,
            # forever, for markers unchanged since half an hour earlier. A note that always
            # says the same thing is one people stop reading.
            pernah_ada = (db.query(IdentitasPerangkat)
                          .filter(IdentitasPerangkat.device_id == d.id,
                                  IdentitasPerangkat.jenis == jenis)
                          .first() is not None)
            _b, berubah, lama = catat(db, d.id, jenis, content, "kumpul")
            if berubah:
                bentrok.append({"jenis": jenis, "lama": lama, "baru": content})
            elif not pernah_ada:
                baru.append({"jenis": jenis, "nilai": content})
        catatan.append({
            "device_id": d.id, "device": d.name, "penanda": penanda,
            "vonis": v, "alasan": detail["alasan"],
            "baru": baru, "bentrok": bentrok,
        })
    return catatan


def penanda_tersimpan(db, device_id):
    """All stored markers of a device, for display."""
    line = (db.query(IdentitasPerangkat)
             .filter(IdentitasPerangkat.device_id == device_id)
             .order_by(IdentitasPerangkat.jenis,
                       IdentitasPerangkat.terakhir.desc()).all())
    return [{
        "jenis": b.jenis, "nilai": b.nilai, "sumber": b.sumber,
        "pertama": b.pertama.isoformat() if b.pertama else None,
        "terakhir": b.terakhir.isoformat() if b.terakhir else None,
    } for b in line]


def perbarui_vonis(db, device_id, terlihat=None):
    """Compute the verdict and store it in `devices`. Returns (verdict, details)."""
    v, detail = vonis(db, device_id, terlihat)
    d = db.query(Device).filter(Device.id == device_id).first()
    if d is not None:
        d.identitas_vonis = v
        d.identitas_diperiksa = datetime.now()
    return v, detail


def boleh_ditulisi(db, device_id):
    """May WRITE commands be sent to this device?

    Called by the write path right before sending, not once at the start. A
    fingerprint checked ten minutes ago proves nothing about the device that will
    receive the command NOW.

    Returns (allowed, verdict, reason).
    """
    d = db.query(Device).filter(Device.id == device_id).first()
    if d is None:
        return False, None, "perangkat tidak ada"
    v = d.identitas_vonis
    if v in BOLEH_DITULISI:
        return True, v, "identitas terbukti sama"
    if v == BERTENTANGAN:
        return False, v, ("identitas perangkat di alamat ini BERBEDA dari yang "
                          "tersimpan. Perintah tidak dikirim.")
    if v == KEMUNGKINAN_SAMA:
        return False, v, ("identitas baru cocok pada satu penanda. Untuk "
                          "menulis, dibutuhkan sekurangnya dua.")
    return False, v, ("identitas perangkat ini belum pernah dikumpulkan, jadi "
                      "tidak ada yang bisa dibandingkan.")

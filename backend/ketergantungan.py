"""Device dependencies: "is it down by itself, or because its parent is?"

Of several devices that go down together, tells which is the CAUSE and which the
EFFECT, so one root fault does not trigger many redundant alerts and automatic
repair attempts (an "automation storm").

HOW IT WORKS: GRAPH TRAVERSAL, NOT A HAND-WRITTEN LIST
------------------------------------------------------
Uses the existing `device_link` table, filled from the lab's real cabling
(`isi_device_link.py`, copied from GNS3). Dependencies are derived from the
cables, so nothing needs updating when the topology changes.

`device_link` deliberately has no direction (a cable is two-way, see
`models.DeviceLink`). Direction comes from the vantage point: NSM observes from the
machine it runs on, so a device's "upstream" is every device on the path from NSM
to it. If one of them is down, the device at the end cannot be judged down on its
own; NSM has merely lost its route.

THREE ANSWERS, NOT TWO
----------------------
    `ada_penyebab`          an upstream device is down. An EFFECT: do not alert
                            on or repair it separately.
    `tidak_ada`             path intact, all upstream alive. A CAUSE.
    `tidak_bisa_dipastikan` the graph cannot answer (device or anchor missing
                            from `device_link`, or not connected). NOT `tidak_ada`.

An incomplete graph must never read as "no upstream cause": a device nobody
registered in `device_link` would silently look as if its path were proven healthy.
Callers that take DECISIONS (e.g. the recovery) must handle `tidak_bisa_dipastikan`
explicitly rather than equating it with either of the other two.
"""
from collections import deque

from sqlalchemy import desc, select

import dialek_perangkat
from models import Device, DeviceLink, StatusLog

ADA_PENYEBAB = "ada_penyebab"
TIDAK_ADA = "tidak_ada"
TIDAK_BISA_DIPASTIKAN = "tidak_bisa_dipastikan"


def graf(db):
    """{device_id: set of neighbor device_ids} from `device_link`.

    Two-way, because cables are. Rows pointing at deleted devices are skipped silently.
    """
    hasil = {}
    for l in db.execute(select(DeviceLink)).scalars().all():
        a, b = l.device_a_id, l.device_b_id
        if a is None or b is None:
            continue
        hasil.setdefault(a, set()).add(b)
        hasil.setdefault(b, set()).add(a)
    return hasil


def titik_pandang(db):
    """Device NSM itself runs on: the root of every traversal.

    Derived from `platform == 'lokal'` (the "this machine" marker already used by
    `connectors/lokal.py`), not from an IP address hardcoded in the code, which goes
    stale when NSM moves. None if no `lokal` device exists; then the whole module
    answers `tidak_bisa_dipastikan`, which is the honest answer.
    """
    return db.execute(
        select(Device).where(Device.platform.in_(
            dialek_perangkat.platform_dengan("lokal", True))).limit(1)
    ).scalars().first()


def jalur(db, dari_id, ke_id, g=None):
    """SHORTEST path (hop count) from `dari_id` to `ke_id` as a list of device_ids
    including both ends; None if not connected.

    BFS rather than weighted search: the lab graph is small, has no truly known
    weights, and hop count is the only honest measure.
    """
    g = g if g is not None else graf(db)
    if dari_id not in g or ke_id not in g:
        return None
    if dari_id == ke_id:
        return [dari_id]

    previous = {dari_id: None}
    antrean = deque([dari_id])
    while antrean:
        current = antrean.popleft()
        for tetangga in sorted(g.get(current, ())):   # sorted -> hasil stabil
            if tetangga in previous:
                continue
            previous[tetangga] = current
            if tetangga == ke_id:
                lintasan = [ke_id]
                while previous[lintasan[-1]] is not None:
                    lintasan.append(previous[lintasan[-1]])
                return list(reversed(lintasan))
            antrean.append(tetangga)
    return None


def hilir(db, device_id, g=None):
    """Devices whose path from NSM passes THROUGH `device_id`.

    This is a device's blast radius: who else goes dark if it fails. Traced from
    `device_link`, the same graph used for cause attribution. It closes a gap in
    pre-change verification in `kirim_perintah`, which only rejected commands on the
    interface NSM uses to reach the target itself (one hop): shutting `Fa1/0` on R1
    left R1 reachable via `Fa0/0` while R2, SW-B and LDAP behind it would all go dark.

    Returns a list of dicts {id, nama, jalur}. EMPTY means nothing depends on it, NOT
    that it is safe: with an incomplete graph the answer is incomplete too. Callers
    that must tell the two apart should check `graf_lengkap()`.
    """
    anchor = titik_pandang(db)
    if anchor is None or anchor.id == device_id:
        return []
    g = g if g is not None else graf(db)
    hasil = []
    for d in db.execute(
        select(Device).where(Device.aktif == 1)
    ).scalars().all():
        if d.id in (device_id, anchor.id):
            continue
        lintasan = jalur(db, anchor.id, d.id, g=g)
        # `[1:-1]`: only the devices in between (both ends excluded), as in `penyebab_hulu()`.
        if lintasan and device_id in lintasan[1:-1]:
            hasil.append({"id": d.id, "nama": d.name, "jalur": lintasan})
    return hasil


def graf_lengkap(db, g=None):
    """(complete, unreachable): whether ALL active devices have a path from the vantage
    point. Distinguishes "nothing depends on it" from "the graph does not know".
    """
    anchor = titik_pandang(db)
    if anchor is None:
        return False, []
    g = g if g is not None else graf(db)
    disconnect = []
    for d in db.execute(
        select(Device).where(Device.aktif == 1)
    ).scalars().all():
        if d.id == anchor.id:
            continue
        if jalur(db, anchor.id, d.id, g=g) is None:
            disconnect.append({"id": d.id, "nama": d.name})
    return (not disconnect), disconnect


def _sedang_mati(db, device_id):
    """True if the device's NEWEST `status_logs` row has `is_reachable=0`.

    Deliberately uses only the latest row instead of repeating the poller's
    `DOWN_THRESHOLD` logic: this module asks "does NSM see it answering NOW", and the
    only threshold logic in the project stays in the poller.
    """
    log = db.execute(
        select(StatusLog).where(StatusLog.device_id == device_id)
        .order_by(desc(StatusLog.timestamp)).limit(1)
    ).scalars().first()
    return log is not None and not log.is_reachable


def penyebab_hulu(db, device_id, g=None, mati=None):
    """Whether the outage of `device_id` can be explained by a device UPSTREAM of it.

    Returns a dict: `status` (one of the three constants above), `hulu_mati` (list of
    {id, nama}), `jalur` (list of ids, for display), `alasan` (human-readable sentence).

    `mati`: set of device_ids the caller considers DOWN; if given it replaces
    `_sedang_mati()`. The causality panel decides "down" from `device_events` (statuses
    that passed the poller's consecutive-failure threshold), while `_sedang_mati()` uses
    the latest `status_logs` row. Mixing both in ONE panel would show the same device
    alive in one row and down in the next.

    Only devices BETWEEN the vantage point and the target are checked: if NSM itself is
    down nothing runs this check, and the target is the one being asked about.
    """
    anchor = titik_pandang(db)
    if anchor is None:
        return {"status": TIDAK_BISA_DIPASTIKAN, "hulu_mati": [], "jalur": [],
                "alasan": "Tidak ada device ber-platform 'lokal' -- NSM tidak "
                         "tahu dari titik mana ia mengamati, jadi 'hulu' tidak "
                         "punya arti."}

    if anchor.id == device_id:
        return {"status": TIDAK_ADA, "hulu_mati": [], "jalur": [device_id],
                "alasan": "Ini device tempat NSM sendiri berjalan -- tidak ada "
                         "hulu di antara NSM dan dirinya sendiri."}

    g = g if g is not None else graf(db)
    lintasan = jalur(db, anchor.id, device_id, g=g)
    if lintasan is None:
        return {"status": TIDAK_BISA_DIPASTIKAN, "hulu_mati": [], "jalur": [],
                "alasan": "Tidak ada jalur yang tercatat di `device_link` dari "
                         "%s ke device ini. Grafnya belum lengkap -- ini BUKAN "
                         "berarti jalurnya sehat, melainkan NSM tidak tahu "
                         "jalurnya lewat mana." % anchor.name}

    between = lintasan[1:-1]
    def _mati(pid):
        return (pid in mati) if mati is not None else _sedang_mati(db, pid)

    hulu_mati = []
    for pid in between:
        if _mati(pid):
            d = db.get(Device, pid)
            hulu_mati.append({"id": pid,
                              "nama": d.name if d else "device #%s" % pid})

    if hulu_mati:
        nama = ", ".join(m["nama"] for m in hulu_mati)
        return {"status": ADA_PENYEBAB, "hulu_mati": hulu_mati, "jalur": lintasan,
                "alasan": "Perangkat di hulu sedang mati: %s. Matinya device "
                         "ini kemungkinan AKIBAT, bukan sebab -- NSM kehilangan "
                         "jalan ke sana, belum tentu perangkatnya sendiri "
                         "bermasalah." % nama}

    return {"status": TIDAK_ADA, "hulu_mati": [], "jalur": lintasan,
            "alasan": "Seluruh %d perangkat di jalur dari %s ke sini menjawab "
                     "normal -- jadi matinya device ini bukan akibat jalur "
                     "yang putus." % (len(between), anchor.name)}


def boleh_ditindak(db, device_id, izinkan_kalau_ragu=False, g=None):
    """(allowed, reason): decision wrapper for the recovery and notifications.

    `izinkan_kalau_ragu` sets how `tidak_bisa_dipastikan` is treated, and the right
    answer differs by caller:

      * RECOVERY (default False): when unsure, do NOT act; sending commands to a device
        whose path is unknown is a risky action on incomplete grounds.
      * NOTIFICATIONS (True): when unsure, notify anyway; a skipped alarm is far worse
        than an extra one.
    """
    hasil = penyebab_hulu(db, device_id, g=g)
    if hasil["status"] == ADA_PENYEBAB:
        return False, hasil["alasan"]
    if hasil["status"] == TIDAK_BISA_DIPASTIKAN:
        return izinkan_kalau_ragu, hasil["alasan"]
    return True, hasil["alasan"]


def filter_candidate(db, kandidat, ambil_device):
    """Filter recovery candidates: drop those whose outage is an EFFECT of an upstream failure.

    `ambil_device(item) -> Device` lets it serve all four recoverers, whose candidate
    shapes differ (`Device`, `(Device, nama_iface)`, `(Device, kunci, temuan)`).

    Returns `(diteruskan, ditahan)`. Held-back items are returned with reasons so the
    caller can log them instead of losing them silently.
    """
    g = graf(db)
    forwarded, withheld = [], []
    for item in kandidat:
        d = ambil_device(item)
        allowed, alasan = boleh_ditindak(db, d.id, g=g)
        (forwarded if allowed else withheld).append(
            item if allowed else {"item": item, "device": d, "alasan": alasan})
    return forwarded, withheld

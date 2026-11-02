r"""Log pattern mining with Drain3.

`syslog_terima.py` already computes `sidik_templat` with hand-written
normalization, which only handles shapes its author anticipated. Drain3 groups
similar messages and discovers the variable parts itself
(`%LINK-3-UPDOWN: Interface <*> changed state to <*>`), so it recognizes new
message shapes. Both are kept: the cheap fingerprint runs in the UDP receive
path for flood suppression, while mining runs later from the database and
answers "which patterns exist and which are NEW". A template seen for the first
time is the most valuable signal; patterns seen thousands of times fold into one row.

Drain3 is used without river: measured, drain3 adds about 7 MB while
river+drain3 adds about 103 MB (numpy + scipy), too much for an EWMA formula.

If Drain3 is not installed the feature reports that it cannot work. It does not
silently fall back to hand-written normalization, which would produce false
"new patterns" whenever the library is installed or removed.
"""
import json
import os
from datetime import datetime, timedelta

from sqlalchemy import func, select

import models
import syslog_terima

# Drain3 similarity threshold. The library default is 0.4; 0.5 is used because
# short Cisco messages share many words ("changed state to") and the default
# merged `%LINK-3-UPDOWN` with `%LINEPROTO-5-UPDOWN`.
AMBANG_MIRIP = 0.5

# Parse tree depth; 4 is the default and enough for Cisco syslog messages.
KEDALAMAN = 4

# Cluster limit. Without it, a device sending a unique id in every message (an
# unrecognized UUID, say) would grow the tree until memory runs out.
MAKS_GUGUS = 2000

BATAS_PER_PUTARAN = 3000

POSISI = "drain3"


class Drain3TidakAda(Exception):
    """Raised, not masked; see the module docstring."""


def tersedia():
    try:
        import drain3  # noqa: F401
        return True
    except ImportError:
        return False


def _buat_penambang():
    """TemplateMiner whose state lives only in this process's memory.

    Not persisted to a file on purpose: a binary state file would be a second source
    of truth outside the database that can go stale. The tree is rebuilt from the
    `log_templat` table at each start, which is cheap (tens of thousands of messages per second).
    """
    try:
        from drain3.template_miner import TemplateMiner
        from drain3.template_miner_config import TemplateMinerConfig
    except ImportError as e:
        raise Drain3TidakAda(
            "pustaka drain3 belum terpasang di lingkungan ini") from e

    cfg = TemplateMinerConfig()
    cfg.drain_sim_th = AMBANG_MIRIP
    cfg.drain_depth = KEDALAMAN
    cfg.drain_max_clusters = MAKS_GUGUS
    # Drain3's built-in masking is off: `syslog_terima.py` has its own normalization,
    # and two masking layers make templates unmatchable against original messages.
    cfg.masking_instructions = []
    return TemplateMiner(config=cfg)


def _posisi(db):
    p = db.execute(select(models.LogTemplatPosisi).where(
        models.LogTemplatPosisi.nama == POSISI)).scalars().first()
    if p is None:
        p = models.LogTemplatPosisi(nama=POSISI, posisi_id=0)
        db.add(p)
        db.flush()
    return p


def tambang(db, batas=BATAS_PER_PUTARAN, sekarang=None):
    """One mining round. Return a summary of counts.

    `pola_baru` lists templates that did not exist before this round, returned
    separately so callers need not recount.
    """
    sekarang = sekarang or datetime.now()
    if not tersedia():
        return {"jalan": False, "alasan": "drain3 belum terpasang",
                "dibaca": 0, "pola_baru": []}

    pos = _posisi(db)
    line = db.execute(
        select(models.SyslogPesan)
        .where(models.SyslogPesan.id > pos.posisi_id)
        .order_by(models.SyslogPesan.id).limit(batas)).scalars().all()
    if not line:
        return {"jalan": True, "dibaca": 0, "pola_baru": [],
                "templat": db.execute(select(func.count(models.LogTemplat.id))
                                      ).scalar() or 0}

    penambang = _buat_penambang()

    # Rebuild the tree from stored templates first; otherwise every poller restart
    # would report all patterns as new.
    map_cluster = _bangun_ulang(db, penambang)

    pola_baru = []
    touched = {}
    for r in line:
        # Cisco timestamps are stripped again here (same function the receiver uses):
        # rows stored before the `.` marker was recognized still carry them, and Drain3
        # would put stamped and unstamped copies of one message in different clusters.
        pesan = syslog_terima.buang_stempel_cisco((r.pesan or "").strip())
        if not pesan:
            continue
        hasil = penambang.add_log_message(pesan)
        if not hasil:
            continue
        templat = hasil.get("template_mined") or pesan
        gugus_id = hasil.get("cluster_id")

        # Keyed by cluster id, not template text. Drain3 first creates a cluster whose
        # template is the literal first message, then generalizes it (`Interface <*>`)
        # as similar messages arrive; keying by text produced two rows for one pattern,
        # each reported as new.
        t = map_cluster.get(gugus_id)
        if t is None:
            t = models.LogTemplat(
                gugus_id=gugus_id or 0, templat=templat, jumlah=0,
                pertama=r.waktu, terakhir=r.waktu,
                severity_min=r.severity, jumlah_device=0, ditinjau=False)
            db.add(t)
            db.flush()
            map_cluster[gugus_id] = t
            pola_baru.append({"id": t.id, "templat": templat,
                              "device_id": r.device_id,
                              "waktu": r.waktu.isoformat() if r.waktu else None,
                              "severity": r.severity})
        elif templat != t.templat:
            # Same cluster with a refined template: update the existing row rather than adding a second.
            t.templat = templat
            t.gugus_id = gugus_id or t.gugus_id

        t.jumlah = (t.jumlah or 0) + 1
        t.terakhir = r.waktu
        if t.pertama is None or (r.waktu and r.waktu < t.pertama):
            t.pertama = r.waktu
        # Keep the WORST severity, not the latest: one serious occurrence makes the
        # pattern worth a look, and a later routine one must not hide that.
        if r.severity is not None:
            t.severity_min = (r.severity if t.severity_min is None
                              else min(t.severity_min, r.severity))
        touched.setdefault(t.id, set()).add(r.device_id)

    # Device count per template is recomputed from the table, not added up
    # incrementally, which would count the same device twice across rounds.
    for t_id in touched:
        t = db.get(models.LogTemplat, t_id)
        if t is None:
            continue
        t.jumlah_device = _cacah_device(db, t)

    pos.posisi_id = line[-1].id
    pos.diperbarui = sekarang
    db.commit()
    return {"jalan": True, "dibaca": len(line), "pola_baru": pola_baru,
            "templat": db.execute(
                select(func.count(models.LogTemplat.id))).scalar() or 0,
            "digabung": len(map_cluster)}


def _bangun_ulang(db, penambang):
    """Fill the Drain3 tree from stored templates; return a cluster -> row map.

    Also heals duplicate rows from older versions: two stored templates that fall
    in the same cluster are the literal and generalized forms of one pattern; the
    generalized one is kept, counts are summed, the literal one is dropped. Only
    this derived table is touched, never `syslog_pesan`.
    """
    peta = {}
    line = db.execute(select(models.LogTemplat)
                       .order_by(models.LogTemplat.id)).scalars().all()
    dibuang = []
    for t in line:
        if not (t.templat or "").strip():
            continue
        hasil = penambang.add_log_message(
            syslog_terima.buang_stempel_cisco(t.templat))
        gid = hasil.get("cluster_id") if hasil else None
        if gid is None:
            continue
        old = peta.get(gid)
        if old is None:
            t.gugus_id = gid
            peta[gid] = t
            continue

        # Two rows, one cluster: keep the one whose template is generalized (contains
        # `<*>`); if both are alike, keep the one with the larger count.
        def berpola(x):
            return "<*>" in (x.templat or "")

        if berpola(t) and not berpola(old):
            simpan, discard = t, old
        elif berpola(old) and not berpola(t):
            simpan, discard = old, t
        else:
            simpan, discard = ((t, old) if (t.jumlah or 0) > (old.jumlah or 0)
                             else (old, t))

        simpan.jumlah = (simpan.jumlah or 0) + (discard.jumlah or 0)
        if discard.pertama and (simpan.pertama is None
                              or discard.pertama < simpan.pertama):
            simpan.pertama = discard.pertama
        if discard.terakhir and (simpan.terakhir is None
                               or discard.terakhir > simpan.terakhir):
            simpan.terakhir = discard.terakhir
        if discard.severity_min is not None:
            simpan.severity_min = (discard.severity_min
                                   if simpan.severity_min is None
                                   else min(simpan.severity_min,
                                            discard.severity_min))
        simpan.jumlah_device = max(simpan.jumlah_device or 0,
                                   discard.jumlah_device or 0)
        simpan.gugus_id = gid
        peta[gid] = simpan
        dibuang.append(discard)

    for b in dibuang:
        db.delete(b)
    if dibuang:
        db.flush()
    return peta


def _cacah_device(db, t):
    """How many distinct devices have ever emitted this pattern.

    Counted from `syslog_pesan` rows with the same template fingerprint, using tag
    prefix matching since the message-to-cluster mapping is not stored. Enough for
    "one device or many".
    """
    if not t.templat:
        return 0
    prefix = t.templat.split()[0][:60] if t.templat.split() else ""
    if not prefix:
        return 0
    line = db.execute(select(models.SyslogPesan.device_id).where(
        models.SyslogPesan.pesan.like(prefix + "%"))).scalars().all()
    return len({d for d in line if d is not None})


def ringkas(db, jam=24, batas=40):
    """For the page and the SOC agent.

    NEW patterns are kept separate from the most frequent ones: they answer opposite
    questions (rarest vs most common), which one sorted list cannot do.
    """
    sekarang = datetime.now()
    limit_time = sekarang - timedelta(hours=jam)
    semua = db.execute(select(models.LogTemplat)).scalars().all()

    # How old the syslog history itself is. "Never seen before" only means something
    # when there is history to compare against; if all of `syslog_pesan` is only
    # hours old, every pattern looks new, and calling a pattern seen hundreds of times
    # "new" teaches people to ignore the most valuable signal. So the situation is
    # stated explicitly rather than hidden or silently filtered.
    oldest = db.execute(select(func.min(models.SyslogPesan.waktu))).scalar()
    riwayat_jam = ((sekarang - oldest).total_seconds() / 3600.0
                   if oldest else 0.0)
    riwayat_muda = riwayat_jam < jam

    baru = [t for t in semua if t.pertama and t.pertama >= limit_time]

    # Rarest first, not newest: a pattern seen once deserves a human look more than
    # one seen hundreds of times, even if both were first seen today.
    baru.sort(key=lambda t: ((t.jumlah or 0),
                             -(t.pertama.timestamp() if t.pertama else 0)))

    sering = sorted(semua, key=lambda t: (t.jumlah or 0), reverse=True)

    def bentuk(t):
        return {"id": t.id, "templat": t.templat, "jumlah": t.jumlah,
                "pertama": t.pertama.isoformat() if t.pertama else None,
                "terakhir": t.terakhir.isoformat() if t.terakhir else None,
                "severity_min": t.severity_min,
                "jumlah_device": t.jumlah_device,
                "ditinjau": bool(t.ditinjau)}

    catatan = None
    if riwayat_muda and baru:
        catatan = (
            "NSM baru mendengar syslog selama %.1f jam, lebih pendek dari "
            "jendela %d jam di sini. Selama itu SETIAP pola terhitung 'baru' "
            "-- termasuk yang sudah muncul ratusan kali. Daftar ini akan mulai "
            "berarti sesudah riwayatnya lebih panjang dari jendelanya."
            % (riwayat_jam, jam))

    return {
        "jam": jam,
        "tersedia": tersedia(),
        # The page must read this before treating "new" as a signal; see the note above.
        "riwayat_jam": round(riwayat_jam, 1),
        "riwayat_muda": riwayat_muda,
        "catatan": catatan,
        "total_templat": len(semua),
        "baru": [bentuk(t) for t in baru[:batas]],
        "tersering": [bentuk(t) for t in sering[:batas]],
        # How many log rows no longer need reading one by one because they fold into patterns.
        "total_pesan": sum(t.jumlah or 0 for t in semua),
    }

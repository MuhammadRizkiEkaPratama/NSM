r"""Behavior baseline: "how much is NORMAL for THIS device at THIS hour".

The problem: `anomali.py` uses fixed thresholds. The LDAP directory (across the
GNS3 WAN) normally answers in hundreds of milliseconds, while the web server on
the same LAN answers in under one. A single "200 ms = bad" threshold makes the
first always alarm and the second never, even when it becomes a thousand times
slower than its habit. This module answers instead: "LDAP is usually 40 ms on
Saturday at 20:00; now 260 ms, 6.5 deviations from its habit".

Why EWMA + mean absolute deviation, and not River: River's footprint was
re-measured and it pulls in numpy and scipy (about +103 MB), while drain3 alone
is about 7 MB. nsm-app has limited memory, and the formula is about sixty
lines, so "EWMA + MAD" is written directly. River is used only as a judge:
`uji_baseline.py` compares this module's numbers with `river.stats.EWMean` on
the same series. River is installed where CI runs, not on nsm-app.

Constant 1.2533, not 1.4826: each slot stores the EWMA of |x - ewma|, the mean
absolute deviation, not the median absolute deviation. For a normal
distribution E|X - mu| = sigma * sqrt(2/pi) = 0.7979 * sigma, so
sigma = 1.2533 * E|X - mu|. The much-quoted 1.4826 is for the MEDIAN absolute
deviation; using it here would make every reported sigma score about 18% too
small and real anomalies look milder. This kind of error produces no
exception, only a confidently wrong number.

Three honesty rules (shared with `kapasitas.py`):
1. A slot with few samples is NOT scored: it answers "not enough yet" rather
   than computing sigma from five points.
2. A very stable device must not yield a huge sigma from measurement noise. A
   deviation floor exists; without it a device that is always 0.4 ms would
   report "50 deviations" when one sample reads 0.9 ms.
3. Scores are capped. "Sigma 4812" adds nothing over "more than 50"; it is
   only false precision.
"""
import math
from datetime import datetime, timedelta

from sqlalchemy import select

import models

# ---------------------------------------------------------------------------
# Tetapan
# ---------------------------------------------------------------------------

ALPHA = 0.05

KE_SIGMA = 1.2533

MIN_SAMPEL = 20

SIGMA_MAKS = 50.0

# Relative deviation floor: the divisor is never below 5% of the habitual
# value, so a very stable device does not report dozens of sigma for a
# meaningless difference. An absolute per-metric floor (below) covers values near
# zero, where the relative floor shrinks to nothing.
LANTAI_RELATIF = 0.05

LANTAI_MUTLAK = {
    "latency": 0.5,  # milliseconds; below this is measurement noise
    "bandwidth_rx": 1024.0,  # bita/detik
    "bandwidth_tx": 1024.0,
}
LANTAI_MUTLAK_BAWAAN = 0.5

BATAS_PER_PUTARAN = 5000

# How far back the baseline may learn.
#
# This is about correctness, not speed. Folding the whole history once produced
# "LDAP is usually 0.8 ms on Sunday at 15:00; now 196.5 ms, 50 deviations"
# while the 7-day LDAP average was 213.8 ms. The 0.8 ms came from an older
# topology (before LDAP moved across the GNS3 WAN); the position marker was
# 880,306 rows (72.9%) behind. Folding everything costs about 20 hours to catch
# up and publishes false 50-sigma alarms meanwhile.
#
# So the baseline learns only from the last 14 days, which is also the right
# concept: the question is what is normal NOW, not what was ever normal.
JENDELA_BELAJAR_HARI = 14

# If the position marker lags by MORE than this, the baseline is "catching up"
# and results are flagged as not yet trustworthy (stated, not hidden).
AMBANG_MENGEJAR_BARIS = 20000


def slot_dari(waktu):
    """Hour of the week. Monday 00:00 = 0, Sunday 23:00 = 167."""
    return waktu.weekday() * 24 + waktu.hour


NAMA_HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def sebut_slot(slot):
    """'Saturday 20:00' form used by the explanatory sentence."""
    return "%s pukul %02d.00" % (NAMA_HARI[slot // 24], slot % 24)



def lipat(ewma, ewmd, n, x, alpha=ALPHA):
    """Feed one sample; returns the new (ewma, ewmd, n).

    The FIRST sample becomes the initial value and its deviation is zero.
    Starting from zero and drifting toward the real value would make the early
    samples read as huge anomalies, exactly when people look at them most.
    """
    if n <= 0 or ewma is None:
        return float(x), 0.0, 1
    diff = abs(x - ewma)
    ewma_new = alpha * x + (1.0 - alpha) * ewma
    ewmd_baru = alpha * diff + (1.0 - alpha) * (ewmd or 0.0)
    return ewma_new, ewmd_baru, n + 1


def lantai_simpangan(metrik, ewma):
    mutlak = LANTAI_MUTLAK.get(metrik, LANTAI_MUTLAK_BAWAAN)
    return max(mutlak, abs(ewma or 0.0) * LANTAI_RELATIF)


def sigma(x, ewma, ewmd, n, metrik="latency"):
    """Deviation of `x` from habit; None if not yet scorable.

    None is deliberately distinct from 0.0: zero means "exactly as usual", None
    means "habit not known yet". Merging them would make a newly monitored device
    look perfectly normal when least is known about it.
    """
    if n is None or n < MIN_SAMPEL or ewma is None:
        return None
    simpangan = max(ewmd or 0.0, 0.0) * KE_SIGMA
    simpangan = max(simpangan, lantai_simpangan(metrik, ewma))
    if simpangan <= 0:
        return None
    return min(SIGMA_MAKS, abs(x - ewma) / simpangan)


def kalimat(nama_device, metrik, slot, x, ewma, s, satuan="ms"):
    if s is None:
        return ("%s: kebiasaan pada %s belum cukup terkumpul untuk dinilai."
                % (nama_device, sebut_slot(slot)))
    return ("%s biasanya %.1f %s pada %s. Sekarang %.1f %s -- %.1f simpangan "
            "dari kebiasaannya." % (nama_device, ewma, satuan,
                                    sebut_slot(slot), x, satuan, s))



def _ambil(db, device_id, metrik, slot, buat=True):
    b = db.execute(select(models.BaselinePerilaku).where(
        models.BaselinePerilaku.device_id == device_id,
        models.BaselinePerilaku.metrik == metrik,
        models.BaselinePerilaku.slot == slot)).scalars().first()
    if b is None and buat:
        b = models.BaselinePerilaku(device_id=device_id, metrik=metrik,
                                    slot=slot, n=0, ewma=None, ewmd=None)
        db.add(b)
        db.flush()
    return b


def _posisi(db, metrik):
    p = db.execute(select(models.BaselinePosisi).where(
        models.BaselinePosisi.metrik == metrik)).scalars().first()
    if p is None:
        p = models.BaselinePosisi(metrik=metrik, posisi_id=0)
        db.add(p)
        db.flush()
    return p


def perbarui_latency(db, batas=BATAS_PER_PUTARAN, sekarang=None):
    """Fold unread `status_logs` rows into the baseline.

    Only SUCCESSFUL samples are folded. A failed ping has an empty
    `response_time_ms`; counting it as zero would pull a device's habit down every
    time it has trouble, making a flapping device look faster.
    """
    metrik = "latency"
    sekarang = sekarang or datetime.now()
    pos = _posisi(db, metrik)

    # Skip history older than the learning window, ONCE at the start of each round
    # (not as a query filter): the position marker must actually advance, or the
    # next round would rescan the same old range forever.
    limit_time = sekarang - timedelta(days=JENDELA_BELAJAR_HARI)
    oldest = db.execute(
        select(models.StatusLog.id)
        .where(models.StatusLog.id > pos.posisi_id,
               models.StatusLog.timestamp >= limit_time)
        .order_by(models.StatusLog.id).limit(1)).scalars().first()
    if oldest is not None and oldest > pos.posisi_id + 1:
        dilompati = oldest - pos.posisi_id - 1
        pos.posisi_id = oldest - 1
        pos.diperbarui = sekarang
        db.commit()
        if dilompati > 1000:
            print("[baseline] %d baris lebih tua dari %d hari dilompati -- "
                  "kebiasaan dihitung dari perilaku SEKARANG, bukan dari "
                  "topologi lama" % (dilompati, JENDELA_BELAJAR_HARI))

    line = db.execute(
        select(models.StatusLog)
        .where(models.StatusLog.id > pos.posisi_id,
               models.StatusLog.is_reachable == True,          # noqa: E712
               models.StatusLog.response_time_ms.isnot(None))
        .order_by(models.StatusLog.id)
        .limit(batas)).scalars().all()

    if not line:
        tertinggi = db.execute(
            select(models.StatusLog.id).order_by(models.StatusLog.id.desc())
            .limit(1)).scalars().first()
        if tertinggi and tertinggi > pos.posisi_id:
            pos.posisi_id = tertinggi
            pos.diperbarui = sekarang
            db.commit()
        return {"dibaca": 0, "slot_disentuh": 0, "posisi": pos.posisi_id}

    touched = set()
    saved = {}
    for r in line:
        if r.device_id is None:
            continue
        slot = slot_dari(r.timestamp or datetime.now())
        kunci = (r.device_id, slot)
        b = saved.get(kunci)
        if b is None:
            b = _ambil(db, r.device_id, metrik, slot)
            saved[kunci] = b
        b.ewma, b.ewmd, b.n = lipat(b.ewma, b.ewmd, b.n, float(r.response_time_ms))
        b.diperbarui = r.timestamp
        touched.add(kunci)

    pos.posisi_id = line[-1].id
    pos.diperbarui = sekarang
    db.commit()
    return {"dibaca": len(line), "slot_disentuh": len(touched),
            "posisi": pos.posisi_id}


def nilai_sekarang(db, device_id, metrik="latency", nilai=None, waktu=None):
    """How unusual a device's LATEST value is compared to its habit.

    The result always includes `layak` (True/False) so callers need not guess what
    a None `sigma` means: "cannot be scored yet" is stated, not disguised as a number.
    """
    waktu = waktu or datetime.now()
    slot = slot_dari(waktu)
    d = db.get(models.Device, device_id)
    nama = d.name if d else "device %s" % device_id

    if nilai is None:
        r = db.execute(
            select(models.StatusLog)
            .where(models.StatusLog.device_id == device_id,
                   models.StatusLog.is_reachable == True,      # noqa: E712
                   models.StatusLog.response_time_ms.isnot(None))
            .order_by(models.StatusLog.id.desc()).limit(1)).scalars().first()
        if r is None:
            return {"layak": False, "alasan": "belum ada sampel",
                    "device": nama, "slot": slot, "sigma": None}
        nilai = float(r.response_time_ms)
        waktu = r.timestamp or waktu
        slot = slot_dari(waktu)

    b = _ambil(db, device_id, metrik, slot, buat=False)
    if b is None or (b.n or 0) < MIN_SAMPEL:
        return {"layak": False,
                "alasan": "kebiasaan pada %s belum cukup terkumpul (%d dari "
                          "%d sampel)" % (sebut_slot(slot),
                                          (b.n if b else 0), MIN_SAMPEL),
                "device": nama, "slot": slot, "nilai": nilai, "sigma": None,
                "kalimat": kalimat(nama, metrik, slot, nilai, b.ewma if b else 0,
                                   None)}

    s = sigma(nilai, b.ewma, b.ewmd, b.n, metrik=metrik)
    return {
        "layak": True, "device": nama, "device_id": device_id,
        "metrik": metrik, "slot": slot, "slot_teks": sebut_slot(slot),
        "nilai": nilai, "biasanya": b.ewma, "simpangan": b.ewmd, "n": b.n,
        "sigma": s, "aneh": s is not None and s >= 3.0,
        "kalimat": kalimat(nama, metrik, slot, nilai, b.ewma, s),
    }


def ringkas(db, ambang=3.0, metrik="latency"):
    """For the page: which devices deviate from their habit RIGHT NOW.

    Unreachable devices are skipped on purpose: a dead device already has its own
    alarm, and reporting it twice is noise.
    """
    hasil = []
    devs = db.execute(select(models.Device).where(
        models.Device.aktif == True)).scalars().all()          # noqa: E712
    for d in devs:
        h = nilai_sekarang(db, d.id, metrik=metrik)
        if h.get("layak") and h.get("sigma") is not None:
            hasil.append(h)
    hasil.sort(key=lambda x: x["sigma"], reverse=True)
    kejar = mengejar(db, metrik=metrik)
    return {
        "ambang": ambang,
        "mengejar": kejar["mengejar"],
        "tertinggal_baris": kejar["tertinggal"],
        "catatan": ("Baseline masih mengejar %d baris; angka simpangan di "
                    "bawah dihitung dari kebiasaan yang BELUM lengkap dan "
                    "belum bisa dipercaya." % kejar["tertinggal"]
                    if kejar["mengejar"] else None),
        "aneh": [h for h in hasil if h["sigma"] >= ambang],
        "semua": hasil,
        "belum_cukup": sum(1 for d in devs
                           if not nilai_sekarang(db, d.id, metrik=metrik)
                           .get("layak")),
    }


def mengejar(db, metrik="latency"):
    """Is the baseline still far behind the latest data?

    Stated, not hidden: while catching up, published sigma values come from an
    incomplete habit, and a page showing them without a caveat reads like real alarms.
    """
    pos = db.execute(select(models.BaselinePosisi).where(
        models.BaselinePosisi.metrik == metrik)).scalars().first()
    tertinggi = db.execute(
        select(models.StatusLog.id).order_by(models.StatusLog.id.desc())
        .limit(1)).scalars().first() or 0
    posisi = pos.posisi_id if pos else 0
    remaining = max(0, tertinggi - posisi)
    return {"posisi": posisi, "tertinggi": tertinggi, "tertinggal": remaining,
            "mengejar": remaining > AMBANG_MENGEJAR_BARIS,
            "ambang": AMBANG_MENGEJAR_BARIS}


def cakupan(db, metrik="latency"):
    line = db.execute(select(models.BaselinePerilaku).where(
        models.BaselinePerilaku.metrik == metrik)).scalars().all()
    layak = [b for b in line if (b.n or 0) >= MIN_SAMPEL]
    n_dev = len(db.execute(select(models.Device.id).where(
        models.Device.aktif == True)).scalars().all())         # noqa: E712
    kejar = mengejar(db, metrik=metrik)
    return {
        "mengejar": kejar["mengejar"],
        "tertinggal_baris": kejar["tertinggal"],
        "jendela_belajar_hari": JENDELA_BELAJAR_HARI,
        "slot_terisi": len(line),
        "slot_layak": len(layak),
        "slot_mungkin": n_dev * 168,
        "device": len({b.device_id for b in line}),
        "min_sampel": MIN_SAMPEL,
    }

"""Capacity forecast: "how many days until this disk is full?"

`sumber_daya` already stores disk, memory, and load per device, but was only used
to ask "is it over the threshold NOW". The trend answers a more useful question: a
disk growing about 1.2% per day triggers no alert today and every alert at once a
few weeks later. "Disk 59%, full in 33 days" is a decision; "disk 59%" is a number.

Three honesty rules:

1. **Too little or too short data is NOT forecast.** It answers "not enough data"
   instead of fitting a line through three points.
2. **Noisy trends are flagged.** If the points do not follow the line (low R^2),
   the figure is still given but with the verdict `tidak_yakin`.
3. **No long extrapolation.** Beyond 365 days the answer is "more than a year", not
   "1,482 days".

Falling or flat trends are reported as they are; a shrinking disk is useful
information (cleanup, or something deleted too much).
"""
from datetime import datetime, timedelta

from sqlalchemy import select

from models import Device, SumberDaya

# Minimums for a trend to count as a trend.
MIN_SAMPEL = 24  # about two hours at a 5-minute interval
MIN_RENTANG_JAM = 12.0  # below this, a daily trend means nothing

# Observation window. 7 days smooths daily swings (nightly backups, log rotation)
# while still following recent changes in usage.
JENDELA_HARI = 7

# "Full" threshold for alerting. 90%, not 100%: many file systems misbehave well
# before they are completely full, and what matters is when to act.
AMBANG_WASPADA = 90.0
AMBANG_PENUH = 100.0

# Horizon limit. Beyond this the number carries no information.
HORIZON_MAKS_HARI = 365

# R^2 below this means the points are too scattered to trust as a straight line.
# The figure is still computed but gets the verdict `tidak_yakin`.
R2_MIN_YAKIN = 0.5

CUKUP = "cukup"
TIDAK_CUKUP = "tidak_cukup_data"
STABIL = "stabil"
MENURUN = "menurun"
TIDAK_YAKIN = "tidak_yakin"


def _regresi(titik):
    """Least-squares slope and intercept, plus R^2.

    `titik` = [(x_days, y_percent), ...]. Hand-written instead of numpy: this module is
    called from the poller and the web pages, and ten lines of arithmetic do not
    justify a heavy dependency.
    """
    n = len(titik)
    if n < 2:
        return None, None, None
    sx = sum(p[0] for p in titik)
    sy = sum(p[1] for p in titik)
    sxx = sum(p[0] * p[0] for p in titik)
    sxy = sum(p[0] * p[1] for p in titik)
    penyebut = n * sxx - sx * sx
    if penyebut == 0:
        return None, None, None
    kemiringan = (n * sxy - sx * sy) / penyebut
    deviation = (sy - kemiringan * sx) / n

    average = sy / n
    ss_tot = sum((p[1] - average) ** 2 for p in titik)
    ss_res = sum((p[1] - (kemiringan * p[0] + deviation)) ** 2 for p in titik)
    r2 = 1.0 if ss_tot == 0 else max(0.0, 1.0 - ss_res / ss_tot)
    return kemiringan, deviation, r2


def _hari_menuju(sekarang_persen, laju_per_hari, target):
    """Days until reaching `target`, or None if it never will."""
    if laju_per_hari is None or laju_per_hari <= 0:
        return None
    if sekarang_persen >= target:
        return 0.0
    return (target - sekarang_persen) / laju_per_hari


def prakiraan_device(db, device_id, sekarang=None, jendela_hari=JENDELA_HARI):
    """Disk forecast for one device. Always returns a dict, never raises.

    Pages must decide how to display it from `vonis` only; `hari_menuju_penuh` may
    legitimately be None.
    """
    sekarang = sekarang or datetime.now()
    since = sekarang - timedelta(days=jendela_hari)

    line = db.execute(
        select(SumberDaya)
        .where(SumberDaya.device_id == device_id,
               SumberDaya.waktu >= since,
               SumberDaya.disk_persen.isnot(None))
        .order_by(SumberDaya.waktu.asc())
    ).scalars().all()

    d = db.get(Device, device_id)
    base = {"device_id": device_id, "nama": d.name if d else None,
             "sampel": len(line), "jendela_hari": jendela_hari}

    if len(line) < MIN_SAMPEL:
        base.update({"vonis": TIDAK_CUKUP, "disk_persen": None,
                      "laju_per_hari": None, "hari_menuju_penuh": None,
                      "alasan": "Baru %d sampel dalam %d hari terakhir; "
                                "butuh minimal %d sebelum trennya pantas "
                                "disebut tren." % (len(line), jendela_hari,
                                                   MIN_SAMPEL)})
        return base

    rentang_jam = (line[-1].waktu - line[0].waktu).total_seconds() / 3600.0
    if rentang_jam < MIN_RENTANG_JAM:
        base.update({"vonis": TIDAK_CUKUP,
                      "disk_persen": float(line[-1].disk_persen),
                      "laju_per_hari": None, "hari_menuju_penuh": None,
                      "alasan": "Datanya hanya membentang %.1f jam; tren "
                                "harian tidak punya arti di rentang sependek "
                                "itu." % rentang_jam})
        return base

    begin = line[0].waktu
    titik = [((b.waktu - begin).total_seconds() / 86400.0, float(b.disk_persen))
             for b in line]
    laju, _deviation, r2 = _regresi(titik)
    kini = float(line[-1].disk_persen)

    base.update({"disk_persen": kini,
                  "laju_per_hari": None if laju is None else round(laju, 3),
                  "r2": None if r2 is None else round(r2, 3),
                  "rentang_jam": round(rentang_jam, 1)})

    if laju is None:
        base.update({"vonis": TIDAK_CUKUP, "hari_menuju_penuh": None,
                      "alasan": "Tren tidak bisa dihitung dari data ini."})
        return base

    # Under 0.05% per day a one-percent change takes three weeks; calling that "rising"
    # would overstate it.
    if abs(laju) < 0.05:
        base.update({"vonis": STABIL, "hari_menuju_penuh": None,
                      "alasan": "Pemakaian disk praktis datar (%.3f%%/hari)."
                                % laju})
        return base

    if laju < 0:
        base.update({"vonis": MENURUN, "hari_menuju_penuh": None,
                      "alasan": "Pemakaian disk justru MENURUN %.2f%% per "
                                "hari. Itu fakta yang berguna: ada yang "
                                "membersihkan, atau ada yang menghapus lebih "
                                "banyak daripada yang ditulis." % abs(laju)})
        return base

    h_waspada = _hari_menuju(kini, laju, AMBANG_WASPADA)
    h_full = _hari_menuju(kini, laju, AMBANG_PENUH)

    def batasi(h):
        if h is None:
            return None
        return None if h > HORIZON_MAKS_HARI else round(h, 1)

    base.update({
        "vonis": CUKUP if (r2 or 0) >= R2_MIN_YAKIN else TIDAK_YAKIN,
        "hari_menuju_waspada": batasi(h_waspada),
        "hari_menuju_penuh": batasi(h_full),
        "lewat_horizon": (h_full is not None and h_full > HORIZON_MAKS_HARI),
    })
    base["alasan"] = _kalimat(base, laju, kini)
    return base


def _kalimat(hasil, laju, kini):
    """One ready-to-read sentence. Built here rather than in the Java template so the
    text explaining a number cannot drift from where the number is computed.
    """
    if hasil.get("lewat_horizon"):
        return ("Naik %.2f%% per hari, tetapi pada laju itu masih lebih dari "
                "setahun sebelum penuh. Tidak ada yang perlu dikerjakan "
                "sekarang." % laju)
    h = hasil.get("hari_menuju_penuh")
    hw = hasil.get("hari_menuju_waspada")
    core = "Terisi %.0f%% dan naik %.2f%% per hari" % (kini, laju)
    if hw is not None and hw > 0:
        core += "; menyentuh %.0f%% dalam %.0f hari" % (AMBANG_WASPADA, hw)
    if h is not None:
        core += "; penuh dalam %.0f hari" % h
    if hasil.get("vonis") == TIDAK_YAKIN:
        core += (". Titik datanya berserak (R^2 %.2f), jadi angka ini kasar "
                 "-- pakai sebagai isyarat, bukan tanggal." % (hasil.get("r2") or 0))
    else:
        core += "."
    return core


def prakiraan_semua(db, sekarang=None, jendela_hari=JENDELA_HARI):
    """Forecasts for all active devices that have disk data.

    Sorted by soonest to fill. Devices without enough data are still included at the
    end, so the page never looks like it checked everything when it did not.
    """
    sekarang = sekarang or datetime.now()
    hasil = []
    for d in db.execute(
        select(Device).where(Device.aktif == 1).order_by(Device.id)
    ).scalars().all():
        r = prakiraan_device(db, d.id, sekarang=sekarang,
                             jendela_hari=jendela_hari)
        if r["sampel"] == 0:
            continue  # devices whose disk is not monitored
        hasil.append(r)

    def kunci(r):
        h = r.get("hari_menuju_penuh")
        return (0, h) if h is not None else (1, 0)

    hasil.sort(key=kunci)
    return hasil

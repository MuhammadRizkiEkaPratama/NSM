"""SLO and error budget, following the Google SRE pattern.

A bare availability figure (is 99.2% good or bad? can the fix wait until Monday?) cannot
drive a decision. An SLO makes it answerable:

    TARGET          percentage promised (e.g. 99.5%)
    ERROR BUDGET    downtime still allowed = (100% - target) x observation window
    SPENT           downtime that has actually happened

Reading: plenty of budget left means risk is acceptable (deploys, fault injection, new
automation); thin budget means stop taking risks and fix reliability; exhausted budget means
an outage is a broken promise that needs a decision, not a chart.

The figures come from `report_service.hitung_device()` WITHOUT recomputing anything, because
it already excludes time when NSM was not monitoring (laptop closed, poller down). Computing
from the raw window would count a closed laptop overnight as 12 hours of SLO violation.
"""
from datetime import datetime

import config
import report_service


# Default target. Deliberately not 99.9%: this lab runs on a laptop that may be closed, on VMs
# sharing CPU, with GNS3 routers used for experiments, and a target that is always missed just
# gets ignored. 99.0% over a 30-day window allows about 7 h 12 min of downtime.
TARGET_BAWAAN = 99.0

# Below this remaining share the budget counts as THIN: still running, but stop taking new risks.
AMBANG_MENIPIS = 25.0


def target_untuk(nama_device=None):
    """SLO target (percent) for one device, or the general target.

    Read from `.env` so it can differ per environment without code changes:

        SLO_TARGET=99.5
        SLO_TARGET_ROUTER_LOKASI_A=99.9

    The device name is upper-cased and non-alphanumerics become underscores
    ("Router Lokasi A" -> SLO_TARGET_ROUTER_LOKASI_A).
    """
    env = config._baca()
    if nama_device:
        kunci = "SLO_TARGET_" + "".join(
            c if c.isalnum() else "_" for c in nama_device).upper()
        value = env.get(kunci)
        if value:
            try:
                return max(0.0, min(100.0, float(value)))
            except ValueError:
                pass
    try:
        return max(0.0, min(100.0, float(env.get("SLO_TARGET", TARGET_BAWAAN))))
    except ValueError:
        return TARGET_BAWAAN


def _teks_durasi(detik):
    """Human-readable duration. The minus sign is kept for an overspent budget ('-2 jam 5 menit' is more honest than '0')."""
    if detik is None:
        return "-"
    mark = "-" if detik < 0 else ""
    d = int(abs(detik))
    hour, remaining = divmod(d, 3600)
    minute, second_remaining = divmod(remaining, 60)
    if hour:
        return "%s%d jam %d menit" % (mark, hour, minute)
    if minute:
        return "%s%d menit" % (mark, minute)
    return "%s%d detik" % (mark, second_remaining)


def hitung(db, device, mulai, selesai, daftar_jeda=None):
    """Error budget of one device for one time window.

    Returns None when the observation is too short to publish a figure: an SLO computed from
    two hours of observation would jump between 100% and 0%. "Cannot be assessed yet" beats a
    confident wrong number.
    """
    h = report_service.hitung_device(db, device, mulai, selesai, daftar_jeda)
    if not h or not h.get("cukup_diamati"):
        return None

    window = h.get("durasi_diamati_detik")
    if not window or window <= 0:
        return None

    target = target_untuk(getattr(device, "name", None))
    # Budget = share of the window that MAY be down, computed from the window minus unmonitored
    # time (see `hitung_device`), not from calendar length.
    anggaran_detik = window * (100.0 - target) / 100.0
    terpakai_detik = h.get("total_down_detik") or 0
    sisa_detik = anggaran_detik - terpakai_detik

    if anggaran_detik <= 0:
        # Target 100% means no budget at all. Allowed, but the remaining percentage is undefined, so do not divide by it.
        sisa_persen = 0.0 if terpakai_detik else 100.0
    else:
        sisa_persen = round(sisa_detik / anggaran_detik * 100.0, 1)

    if sisa_detik < 0:
        vonis = "habis"
        arti = ("Anggaran galat HABIS terlampaui. Waktu mati sudah melewati "
                "yang dijanjikan target %.2f%%. Ini bukan lagi 'ada gangguan' "
                "-- ini janji yang dilanggar, dan menuntut keputusan: "
                "perbaiki keandalannya, atau turunkan targetnya dengan sadar."
                % target)
    elif sisa_persen <= AMBANG_MENIPIS:
        vonis = "menipis"
        arti = ("Sisa anggaran tinggal %.1f%%. Masih di dalam janji, tetapi "
                "ini saatnya BERHENTI mengambil risiko baru (deploy besar, "
                "injeksi gangguan, menyalakan otomasi baru) dan mengurus "
                "keandalan lebih dulu." % sisa_persen)
    else:
        vonis = "aman"
        arti = ("Sisa anggaran %.1f%%. Masih longgar -- ini justru keadaan "
                "yang tepat untuk mengambil risiko terkendali, karena "
                "anggaran yang tidak pernah dipakai sama saja dengan target "
                "yang terlalu rendah." % sisa_persen)

    return {
        "device": getattr(device, "name", None),
        "device_id": getattr(device, "id", None),
        "target_persen": target,
        "availability_persen": h.get("availability"),
        "jendela_detik": window,
        "jendela_teks": h.get("durasi_diamati_teks"),
        "anggaran_detik": anggaran_detik,
        "anggaran_teks": _teks_durasi(anggaran_detik),
        "terpakai_detik": terpakai_detik,
        "terpakai_teks": _teks_durasi(terpakai_detik),
        "sisa_detik": sisa_detik,
        "sisa_teks": _teks_durasi(sisa_detik),
        "sisa_persen": sisa_persen,
        "vonis": vonis,
        "arti": arti,
        "insiden": h.get("insiden"),
        "tak_terpantau_detik": h.get("tak_terpantau_detik"),
        "tak_terpantau_teks": h.get("tak_terpantau_teks"),
    }


def semua(db, period="30d"):
    """Error budget for all active devices, most critical first.

    The thinnest budget is deliberately at the TOP: an alphabetical list would hide the one
    row that matters among healthy ones.
    """
    import models

    mulai, selesai, _ = report_service.rentang(period)
    hasil, skipped = [], []
    for d in db.query(models.Device).filter(models.Device.aktif == True).all():  # noqa: E712
        # `daftar_jeda` is deliberately not passed: `hitung_device()` loads it itself via `jeda.cari_jeda()` when omitted.
        r = hitung(db, d, mulai, selesai, None)
        if r is None:
            skipped.append(getattr(d, "name", str(getattr(d, "id", "?"))))
        else:
            hasil.append(r)

    hasil.sort(key=lambda x: x["sisa_persen"])
    return {
        "period": period,
        "mulai": mulai.isoformat() if isinstance(mulai, datetime) else None,
        "selesai": selesai.isoformat() if isinstance(selesai, datetime) else None,
        "device": hasil,
        # Skipped devices are REPORTED, not silently dropped: a list that quietly omits entries reads as complete.
        "belum_cukup_diamati": skipped,
        "ambang_menipis_persen": AMBANG_MENIPIS,
    }

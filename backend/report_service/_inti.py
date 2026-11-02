"""Core part of report_service, split out of the former single-file module with
function bodies unchanged. `report_service/__init__.py` re-exports everything.
"""
import re
from datetime import datetime, timedelta

from sqlalchemy import desc, func, or_

import config
import jeda
import rollup
from models import (
    Device,
    DeviceEvent,
    OrangLdap,
    Service,
    ServiceCheck,
    ServiceEvent,
    StatusLog,
)

# Cache only for genuinely heavy queries.
#
# Cached: average latency, the only query that sweeps millions of status_logs
# rows (a 30-day period can be 1.5M rows per device).
#
# Not cached: incident/availability/history, computed from device_events (tens of
# rows). Caching them once made a card say "1 incident" while the history list
# showed 2; now every part of a page is computed from the same database state.
_cache = {}


CACHE_LATENCY_DETIK = 30


def _cache_ambil(kunci, umur_detik):
    content = _cache.get(kunci)
    if not content:
        return None
    waktu, nilai = content
    if (datetime.now() - waktu).total_seconds() > umur_detik:
        return None
    return nilai


def _cache_simpan(kunci, nilai):
    _cache[kunci] = (datetime.now(), nilai)
    return nilai


PERIODE = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


# Period names are written manually, not via format_durasi(): `24h` would read
# `1 hari` while the page button says `24 Jam`.
PERIODE_NAMA = {
    "1h": "1 jam",
    "24h": "24 jam",
    "7d": "7 hari",
    "30d": "30 hari",
}


# Observation this short must not be used to publish an availability number
# (a paused device once left 26 s of a 24 h window and produced "0.188%").
MIN_DIAMATI_DETIK = 300


def rentang(period):
    """Return (start, end, label). Defaults to 24 hours for unknown values."""
    delta = PERIODE.get(period, PERIODE["24h"])
    selesai = datetime.now()
    return selesai - delta, selesai, period if period in PERIODE else "24h"


def format_durasi(detik):
    """Turn seconds into readable Indonesian text (e.g. '2 jam 5 menit').

    Callers must pass an already `round`ed value: raw 164.7 is truncated to
    '2 menit 44 detik' while round(164.7) = 165 gives '2 menit 45 detik', which
    once made a card and a table differ by 1 second for the same outage.
    """
    if detik is None:
        return "-"
    detik = int(detik)
    if detik < 60:
        return f"{detik} detik"
    menit, remaining_second = divmod(detik, 60)
    if menit < 60:
        return f"{menit} menit {remaining_second} detik" if remaining_second else f"{menit} menit"
    jam, remaining_minute = divmod(menit, 60)
    if jam < 24:
        return f"{jam} jam {remaining_minute} menit" if remaining_minute else f"{jam} jam"
    hari, remaining_hour = divmod(jam, 24)
    return f"{hari} hari {remaining_hour} jam" if remaining_hour else f"{hari} hari"


TEKS_KATEGORI = {
    "dead": "Tidak ada respons sama sekali (kemungkinan mati/terputus)",
    "ping_blocked": "Ping diblokir, tapi device menjawab di port TCP (kemungkinan hidup)",
    "recovered": "Kembali normal",
    "baseline": "Awal pemantauan",
    "pulih": "Layanan kembali menjawab dengan benar",
}


def teks_kategori(kategori):
    """Translate a category code into a sentence. An empty category still gets
    readable text, not a leaked 'None'.

    SERVICE categories come from `connectors/layanan.py` and are not copied here:
    the cause sentence must have a single owner.
    """
    if not kategori:
        return "Tidak diketahui"
    if kategori in TEKS_KATEGORI:
        return TEKS_KATEGORI[kategori]
    from connectors.layanan import TEKS_SEBAB
    if kategori in TEKS_SEBAB:
        return TEKS_SEBAB[kategori]
    return kategori


def selang_down(db, device_id, mulai, selesai, daftar_jeda=None):
    """Return (down_intervals, monitored_since).

    down_intervals: list of dicts {mulai, selesai (None = ongoing), durasi_detik,
    durasi_mentah_detik, jeda_detik, kategori, detail, event_id}.
    monitored_since: when this device first had an event (None if never).

    `durasi_detik` is the outage length actually OBSERVED: the time between the two
    events minus time NSM was not monitoring the device (poller down or device
    paused). `durasi_mentah_detik` is the value before subtraction and `jeda_detik`
    the difference, so the UI can explain why they differ; see `jeda.py`.

    `event_id` is the id of the DeviceEvent row that OPENED the outage. Intervals
    are rebuilt, not database rows, so this gives the incident card on the Report
    page an anchor (`#insiden-{event_id}`) to link to.
    """
    event_first = (
        db.query(DeviceEvent)
        .filter(DeviceEvent.device_id == device_id)
        .order_by(DeviceEvent.timestamp, DeviceEvent.id)
        .first()
    )
    if event_first is None:
        return [], None

    dipantau_sejak = event_first.timestamp
    limit_start = max(mulai, dipantau_sejak)

    # Status at batas_mulai = last event BEFORE or AT that boundary
    before = (
        db.query(DeviceEvent)
        .filter(DeviceEvent.device_id == device_id,
                DeviceEvent.timestamp <= limit_start)
        .order_by(desc(DeviceEvent.timestamp), desc(DeviceEvent.id))
        .first()
    )
    origin = before if before else event_first
    status = origin.event_type
    kategori = origin.category
    detail = origin.detail
    ev_id = origin.id
    sejak = limit_start

    at_inner = (
        db.query(DeviceEvent)
        .filter(DeviceEvent.device_id == device_id,
                DeviceEvent.timestamp > limit_start,
                DeviceEvent.timestamp <= selesai)
        .order_by(DeviceEvent.timestamp, DeviceEvent.id)
        .all()
    )

    if daftar_jeda is None:
        daftar_jeda = jeda.find_gaps(db, device_id, limit_start, selesai)

    def catat(awal, akhir, sedang_berjalan):
        """Build one DOWN interval with unmonitored time already trimmed."""
        raw = (akhir - awal).total_seconds()
        tak_terpantau = jeda.detik_tak_terpantau(daftar_jeda, awal, akhir)
        hasil.append({
            "mulai": awal,
            "selesai": None if sedang_berjalan else akhir,
            "durasi_detik": max(0.0, raw - tak_terpantau),
            "durasi_mentah_detik": raw,
            "jeda_detik": tak_terpantau,
            "kategori": kategori,
            "detail": detail,
            "event_id": ev_id,
        })

    hasil = []
    for ev in at_inner:
        if ev.event_type == status:
            continue
        if status == "DOWN":
            catat(sejak, ev.timestamp, False)
        status = ev.event_type
        kategori = ev.category
        detail = ev.detail
        ev_id = ev.id
        sejak = ev.timestamp

    # Still DOWN now -> ongoing outage
    if status == "DOWN":
        catat(sejak, selesai, True)

    return hasil, dipantau_sejak


def hitung_device(db, d, mulai, selesai, daftar_jeda=None):
    """Summary of one device for a given period."""
    if daftar_jeda is None:
        daftar_jeda = jeda.find_gaps(db, d.id, mulai, selesai)
    down_list, dipantau_sejak = selang_down(db, d.id, mulai, selesai, daftar_jeda)

    if dipantau_sejak is None:
        # No events yet (new poller has not run). Fallback: compute from raw status_logs so numbers still appear.
        total = db.query(func.count(StatusLog.id)).filter(
            StatusLog.device_id == d.id,
            StatusLog.timestamp >= mulai).scalar() or 0
        rise = db.query(func.count(StatusLog.id)).filter(
            StatusLog.device_id == d.id,
            StatusLog.timestamp >= mulai,
            StatusLog.is_reachable == True).scalar() or 0  # noqa: E712
        avail = round(rise / total * 100, 3) if total else None
        return {
            "availability": avail,
            "insiden": 0,
            "insiden_selesai": 0,
            "total_down_detik": 0,
            "total_down_teks": "-",
            "total_down_selesai_detik": 0,
            "mttr_detik": None,
            "mttr_teks": "-",
            "sumber": "status_logs (belum ada catatan transisi)",
            "dipantau_sejak": None,
            "durasi_diamati_detik": None,
            "durasi_diamati_teks": "-",
            # This fallback computes from the proportion of samples, not time, so it has no
            # observation window; marked sufficient so the page does not conclude the number was withheld.
            "cukup_diamati": True,
            "min_diamati_detik": MIN_DIAMATI_DETIK,
            "tak_terpantau_detik": 0,
            "tak_terpantau_teks": None,
        }

    effective_start = max(mulai, dipantau_sejak)
    # Availability denominator: time NSM was not monitoring this device is excluded
    # (not counted healthy, not counted down). Otherwise a laptop closed overnight
    # would read as a 12-hour outage.
    tak_terpantau = jeda.detik_tak_terpantau(daftar_jeda, effective_start, selesai)
    window = (selesai - effective_start).total_seconds() - tak_terpantau

    # Round EACH incident's duration first, then sum, so the total matches the sum of
    # the rounded durations shown in the history list.
    durasi_bulat = [round(x["durasi_detik"]) for x in down_list]
    selesai_saja = [round(x["durasi_detik"])
                    for x in down_list if x["selesai"] is not None]
    total_down = sum(durasi_bulat)

    # MINIMUM OBSERVATION THRESHOLD. `jendela > 0` is not enough: a paused device
    # once left 26 s observed in a 24 h window and NSM published "0.188%". The number
    # was computed correctly but published wrongly, since it says something about 24
    # hours that were never measured. The honest answer is no number; the page
    # already shows an empty availability for never-monitored devices.
    #
    # The threshold is five minutes and deliberately absolute, not a percentage of
    # the period (a percentage would hide a device registered three hours ago on a
    # 30-day period, although three hours is meaningful when reported with "monitored 3 hours").
    avail = None
    cukup = window >= MIN_DIAMATI_DETIK
    if window > 0 and cukup:
        avail = round(max(0.0, (window - total_down)) / window * 100, 3)

    mttr = round(sum(selesai_saja) / len(selesai_saja)) if selesai_saja else None

    return {
        "availability": avail,
        "insiden": len(down_list),
        # Completed incidents only, used for combined MTTR in ringkasan(); an ongoing
        # outage has no final duration.
        "insiden_selesai": len(selesai_saja),
        "total_down_detik": total_down,
        "total_down_teks": format_durasi(total_down) if total_down else "-",
        "total_down_selesai_detik": sum(selesai_saja),
        "mttr_detik": mttr,
        "mttr_teks": format_durasi(mttr) if mttr is not None else "-",
        "sumber": "device_events",
        "dipantau_sejak": dipantau_sejak.isoformat(),
        # Time actually OBSERVED. Can be shorter than the requested period if the device
        # was added recently or NSM stopped watching (poller down / device paused).
        "durasi_diamati_detik": round(max(0.0, window)),
        "durasi_diamati_teks": format_durasi(round(max(0.0, window))),
        # Whether observation was long enough to publish availability. False means
        # `availability` is None on purpose, which differs from "never monitored"; the
        # page needs to tell them apart to pick the sentence.
        "cukup_diamati": bool(cukup),
        "min_diamati_detik": MIN_DIAMATI_DETIK,
        # How long NSM did not see this device in the period, so the page can state the
        # gap instead of hiding it behind one tidy percentage.
        "tak_terpantau_detik": round(tak_terpantau),
        "tak_terpantau_teks": (format_durasi(round(tak_terpantau))
                               if tak_terpantau >= 1 else None),
    }


def status_sekarang(db, device_id):
    """Fetch the device's latest ping result."""
    return (
        db.query(StatusLog)
        .filter(StatusLog.device_id == device_id)
        .order_by(desc(StatusLog.timestamp), desc(StatusLog.id))
        .first()
    )


def rata_latency(db, device_id, label, mulai):
    """Average latency from status_logs, the only heavy query in the report.

    Cached 30 s because a 30-day period can sweep millions of rows.
    `label` must be the sanitized period (from `rentang()`), not raw URL text,
    otherwise equivalent requests would use different cache keys.
    """
    kunci = f"lat:{device_id}:{label}"
    stored = _cache_ambil(kunci, CACHE_LATENCY_DETIK)
    if stored is not None:
        return stored["nilai"]

    # Read from the HOURLY rollup for the summarized part of the period and from raw
    # rows at both ends (68x faster on about 306k rows, and the gap grows with row
    # count). The result must equal computing everything from raw rows; `uji_rollup.py`
    # section 7b enforces this over seven window shapes.
    jumlah, tally, _small, _large = rollup.latency_periode(
        db, device_id, mulai, datetime.now())
    nilai = round(jumlah / tally, 2) if tally else None
    _cache_simpan(kunci, {"nilai": nilai})
    return nilai


# Link-quality verdict threshold, in percent packet loss. Not 0% because an
# occasional lost packet is normal on any network. Chosen from real data: devices
# not behind GNS3 measured 0.00-0.01% all day, those behind GNS3 5.7-40.7%. The
# threshold sits well below the GNS3 range so the report stays honest about path
# quality regardless of the current DOWN_THRESHOLD.
KEHILANGAN_BAGUS = 1.0


KEHILANGAN_CUKUP = 5.0


KEHILANGAN_BURUK = 15.0


def hitung_kualitas_sambungan(db, device_id, label, mulai):
    """Highest packet loss and latency of the period. Different from availability.

    Availability (hitung_device) answers "is the device up or down" from
    device_events filtered by DOWN_THRESHOLD. This answers "is the connection good
    or bad" from EVERY ping attempt (status_logs via rollup.sampel_periode),
    without a threshold. After DOWN_THRESHOLD was raised for GNS3 routers that delay
    ICMP replies, availability rose to 99%+ even though the path may still drop
    many packets; this column keeps that visible. Cached 30 s like rata_latency().
    """
    kunci = f"kualitas:{device_id}:{label}"
    stored = _cache_ambil(kunci, CACHE_LATENCY_DETIK)
    if stored is not None:
        return stored

    sekarang = datetime.now()
    sampel, sample_rise = rollup.sampel_periode(db, device_id, mulai, sekarang)
    if not sampel:
        hasil = {"kehilangan_persen": None, "vonis": None,
                 "latensi_maks_ms": None, "sampel": 0}
        return _cache_simpan(kunci, hasil)

    _jumlah, _tally, _small, latensi_maks = rollup.latency_periode(
        db, device_id, mulai, sekarang)
    percent = round(max(0, sampel - sample_rise) * 100.0 / sampel, 2)

    if percent < KEHILANGAN_BAGUS:
        vonis = "bagus"
    elif percent < KEHILANGAN_CUKUP:
        vonis = "cukup"
    elif percent < KEHILANGAN_BURUK:
        vonis = "buruk"
    else:
        vonis = "sangat_buruk"

    hasil = {
        "kehilangan_persen": percent,
        "vonis": vonis,
        "latensi_maks_ms": round(latensi_maks, 1) if latensi_maks is not None else None,
        "sampel": sampel,
    }
    return _cache_simpan(kunci, hasil)


# ---------------------------------------------------------------------------
# Endpoint-level
# ---------------------------------------------------------------------------
def hitung_kestabilan(db, device_id, sekarang=None):
    """Current stable/unstable status for one device, with hysteresis.

    Replaces the old per-report-period flapping count, which kept a device marked
    unstable until the next day and could not say how long it had been so. This
    runs the state machine through the device's WHOLE DOWN history to reach the
    state NOW, independent of the period on screen.

    Rules (config.get_stabil_*):
    - STABLE -> UNSTABLE: >= min_siklus DOWNs within the last jendela_menit minutes.
    - UNSTABLE -> STABLE: total silence (no DOWN) for pulih_menit minutes, longer
      than the entry window so a brief calm does not clear the status.

    DOWN rows with category 'baseline' (first-row marker, not a real outage) are
    excluded, as on the "Insiden Terakhir" card. Not cached on purpose: computing
    from device_events is cheap, and caching could make the card and table disagree.
    """
    if sekarang is None:
        sekarang = datetime.now()
    min_siklus = config.get_stabil_min_siklus()
    window = timedelta(minutes=config.get_stabil_jendela_menit())
    pulih = timedelta(minutes=config.get_stabil_pulih_menit())

    dipantau_sejak = (
        db.query(func.min(DeviceEvent.timestamp))
        .filter(DeviceEvent.device_id == device_id)
        .scalar()
    )

    down_events = [
        ts for (ts,) in (
            db.query(DeviceEvent.timestamp)
            .filter(DeviceEvent.device_id == device_id,
                    DeviceEvent.event_type == "DOWN",
                    or_(DeviceEvent.category.is_(None),
                        DeviceEvent.category != "baseline"))
            .order_by(DeviceEvent.timestamp)
            .all()
        )
    ]

    stabil = True
    sejak = dipantau_sejak
    window_active = []
    last = None

    for ts in down_events:
        if not stabil and last is not None and (ts - last) >= pulih:
            # Quiet long enough BEFORE this outage -> it recovered in between, so the next flapping pattern starts from zero.
            stabil = True
            sejak = last + pulih
            window_active = []

        window_active = [t for t in window_active if (ts - t) <= window]
        window_active.append(ts)

        if stabil and len(window_active) >= min_siklus:
            stabil = False
            sejak = ts

        last = ts

    # Recovered since the LAST outage, but no new outage has triggered the check above to record it.
    if not stabil and last is not None and (sekarang - last) >= pulih:
        stabil = True
        sejak = last + pulih

    lama_detik = None
    if sejak is not None:
        lama_detik = max(0.0, (sekarang - sejak).total_seconds())

    return {
        "stabil": stabil,
        "sejak": sejak.isoformat() if sejak else None,
        "lama_detik": round(lama_detik) if lama_detik is not None else None,
        "lama_teks": (format_durasi(round(lama_detik))
                      if lama_detik is not None else None),
        # How many DOWNs still count in the active window; only meaningful when `stabil`
        # is False, sent for explanation text ("3 outages in the last 15 minutes").
        "siklus_jendela": len(window_active) if not stabil else 0,
    }


def availability_semua(db, period):
    """Per-device list plus aggregate numbers, used by the report table and cards."""
    mulai, selesai, label = rentang(period)
    # One "now" for the whole list, read once per report, so the card and table never
    # tell different seconds for the same request.
    sekarang = datetime.now()
    daftar = []
    for d in db.query(Device).all():
        summarize = hitung_device(db, d, mulai, selesai)
        log = status_sekarang(db, d.id)
        stability = hitung_kestabilan(db, d.id, sekarang)
        kualitas = hitung_kualitas_sambungan(db, d.id, label, mulai)
        daftar.append({
            "id": d.id,
            "name": d.name,
            "ip_address": d.ip_address,
            "device_type": d.device_type,
            "platform": d.platform,
            "location": d.location,
            # None counts as active: old rows from before the migration must not appear paused because the column is unset.
            "aktif": d.aktif != 0,
            "is_reachable": log.is_reachable if log else None,
            "response_time_ms": log.response_time_ms if log else None,
            "last_checked": log.timestamp.isoformat() if log else None,
            "avg_latency_ms": rata_latency(db, d.id, label, mulai),
            "flapping": not stability["stabil"],
            "tidak_stabil_sejak": stability["sejak"] if not stability["stabil"] else None,
            "tidak_stabil_lama_teks": stability["lama_teks"] if not stability["stabil"] else None,
            # Link quality differs from availability (see hitung_kualitas_sambungan()): a
            # device can be 100% up with many lost packets, so they are not merged into one number.
            "kehilangan_persen": kualitas["kehilangan_persen"],
            "kualitas_vonis": kualitas["vonis"],
            "latensi_maks_ms": kualitas["latensi_maks_ms"],
            **summarize,
        })

    return {
        "periode": label,
        "mulai": mulai.isoformat(),
        "selesai": selesai.isoformat(),
        "devices": daftar,
    }


def ringkasan(db, period):
    """Figures for the four main cards plus the secondary card strip."""
    data = availability_semua(db, period)
    all_device = data["devices"]
    mulai, selesai, label = rentang(period)

    # PAUSED devices are excluded from the overall numbers: a device deliberately not
    # monitored is not a device with a problem. Its history stays on its own page.
    devices = [x for x in all_device if x.get("aktif", True)]
    dijeda = len(all_device) - len(devices)

    total = len(devices)
    up = sum(1 for x in devices if x["is_reachable"])
    down = sum(1 for x in devices if x["is_reachable"] is False)

    value_avail = [x["availability"] for x in devices if x["availability"] is not None]
    avail_average = round(sum(value_avail) / len(value_avail), 3) if value_avail else None

    insiden_total = sum(x["insiden"] for x in devices)
    down_total = sum(x["total_down_detik"] for x in devices)

    lat = [x["avg_latency_ms"] for x in devices if x["avg_latency_ms"] is not None]
    lat_average = round(sum(lat) / len(lat), 2) if lat else None
    most_slow = None
    if lat:
        candidate = max(
            (x for x in devices if x["avg_latency_ms"] is not None),
            key=lambda x: x["avg_latency_ms"],
        )
        most_slow = {"name": candidate["name"], "ms": candidate["avg_latency_ms"]}

    # Combined MTTR = total recovery time / number of completed incidents, NOT the
    # average of per-device MTTRs. Example: device A with one 10-minute outage and B
    # with ten 1-minute outages give 20 min / 11 = 1.8 min, not (10 + 1) / 2 = 5.5.
    count_finish = sum(x["insiden_selesai"] for x in devices)
    duration_finish = sum(x["total_down_selesai_detik"] for x in devices)
    mttr = round(duration_finish / count_finish) if count_finish else None

    top = None
    bermasalah = [x for x in devices if x["insiden"] > 0]
    if bermasalah:
        t = max(bermasalah, key=lambda x: (x["insiden"], x["total_down_detik"]))
        top = {
            "name": t["name"],
            "insiden": t["insiden"],
            "total_down_teks": t["total_down_teks"],
            # Sent so the page can say "unstable since X" instead of "69x" for a flapping device.
            "flapping": t.get("flapping", False),
            "tidak_stabil_lama_teks": t.get("tidak_stabil_lama_teks"),
        }

    device_flapping = sum(1 for x in devices if x.get("flapping"))

    # Last incident (whole history, not just the period). SQL note: `category !=
    # 'baseline'` alone is not enough, since NULL compared with anything is NULL, so
    # DOWN events with an empty category would be dropped silently; NULL is named explicitly.
    last_down = (
        db.query(DeviceEvent, Device)
        .join(Device, Device.id == DeviceEvent.device_id)
        .filter(DeviceEvent.event_type == "DOWN",
                or_(DeviceEvent.category.is_(None),
                    DeviceEvent.category != "baseline"))
        .order_by(desc(DeviceEvent.timestamp), desc(DeviceEvent.id))
        .first()
    )
    # The "Insiden Terakhir" card compares two sources, device outages (ping) and
    # SERVICE outages, and shows the most recent: readers ask one question, what last had a problem here.
    insiden_terakhir = insiden_terakhir_lengkap(db, last_down)

    # Time running without an outage, counted from when the last outage ENDED
    # ('recovered' event), not started. No streak while any device is currently down.
    streak_second = None
    streak_text = "-"
    if down > 0:
        streak_text = "Sedang ada gangguan"
    else:
        recovery = (
            db.query(DeviceEvent)
            .filter(DeviceEvent.event_type == "UP",
                    DeviceEvent.category == "recovered")
            .order_by(desc(DeviceEvent.timestamp), desc(DeviceEvent.id))
            .first()
        )
        if recovery:
            streak_second = round((datetime.now() - recovery.timestamp).total_seconds())
            streak_text = format_durasi(streak_second)
        else:
            # Never had an outage -> count from the start of monitoring
            awal = db.query(func.min(DeviceEvent.timestamp)).scalar()
            if awal:
                streak_second = round((datetime.now() - awal).total_seconds())
                streak_text = format_durasi(streak_second) + " (sejak awal pemantauan)"

    # How long the system has actually been monitoring. A device added 40 minutes ago
    # makes the "24 Jam" figures cover only those 40 minutes, so this is sent for the
    # page to state it.
    periode_detik = round(PERIODE.get(label, PERIODE["24h"]).total_seconds())
    observed = [x["durasi_diamati_detik"] for x in devices
               if x["durasi_diamati_detik"] is not None]
    # `min`, not `max`: `max` reported the luckiest device while the combined
    # availability averages devices with different observation windows, so the
    # sentence read as if it applied to all. The most pessimistic value is used for
    # the decision, and the range is sent so the page can mention both.
    diamati_detik = min(observed) if observed else None
    diamati_maks_detik = max(observed) if observed else None
    # Range mentioned only when the difference matters; a few seconds between devices
    # is normal (the poller checks sequentially).
    diamati_beragam = (
        diamati_detik is not None
        and diamati_maks_detik - diamati_detik > max(60, periode_detik * 0.05)
    )
    # 1% tolerance so a few seconds' difference is not treated as "not full"
    periode_penuh = (diamati_detik is not None
                     and diamati_detik >= periode_detik * 0.99)

    hasil = {
        "periode": label,
        "mulai": mulai.isoformat(),
        "selesai": selesai.isoformat(),
        "dibuat": datetime.now().isoformat(),
        "periode_detik": periode_detik,
        "periode_teks": PERIODE_NAMA.get(label, label),
        "diamati_detik": diamati_detik,
        "diamati_teks": format_durasi(diamati_detik) if diamati_detik is not None else "-",
        "diamati_maks_detik": diamati_maks_detik,
        "diamati_maks_teks": (format_durasi(diamati_maks_detik)
                              if diamati_maks_detik is not None else "-"),
        "diamati_beragam": diamati_beragam,
        "periode_penuh": periode_penuh,
        # --- 4 card utama ---
        "total_device": total,
        "device_up": up,
        "device_down": down,
        "device_dijeda": dijeda,
        "availability_rata": avail_average,
        "insiden_total": insiden_total,
        "device_flapping": device_flapping,
        "total_down_detik": down_total,
        "total_down_teks": format_durasi(down_total) if down_total else "0 detik",
        "latency_rata_ms": lat_average,
        "device_paling_lambat": most_slow,
        # --- card sekunder ---
        "mttr_detik": mttr,
        "mttr_teks": format_durasi(mttr) if mttr is not None else "-",
        "top_offender": top,
        "insiden_terakhir": insiden_terakhir,
        "uptime_streak_detik": streak_second,
        "uptime_streak_teks": streak_text,
        # The report table still shows ALL devices (paused ones marked); card numbers use active ones only.
        "devices_semua": all_device,
        # Device list is sent here so the page fetches data ONCE; separate card and table
        # requests could land on different cache sides and differ by 1 second.
        "devices": devices,
    }
    return hasil


def riwayat_device(db, device_id, period, limit=100):
    """Outage history of one device (for the report accordion)."""
    mulai, selesai, label = rentang(period)
    d = db.query(Device).filter(Device.id == device_id).first()
    if not d:
        return {"error": "Device tidak ditemukan"}

    # Computed once and shared by the two callers below; separate lookups would use
    # slightly different windows and miss the cache.
    daftar_jeda = jeda.find_gaps(db, device_id, mulai, selesai)
    down_list, dipantau_sejak = selang_down(db, device_id, mulai, selesai,
                                            daftar_jeda)
    down_list.sort(key=lambda x: x["mulai"], reverse=True)

    riwayat = []
    for x in down_list[:limit]:
        durasi_bulat = round(x["durasi_detik"])
        jeda_bulat = round(x.get("jeda_detik") or 0)
        riwayat.append({
            # Row address, used by the incident card on the Report page to link to this outage.
            "event_id": x.get("event_id"),
            "mulai": x["mulai"].isoformat(),
            "selesai": x["selesai"].isoformat() if x["selesai"] else None,
            "berlangsung": x["selesai"] is None,
            "durasi_detik": durasi_bulat,
            "durasi_teks": format_durasi(durasi_bulat),
            # Part of this outage that was not observed (poller down or device paused
            # mid-outage); zero for almost all rows. Sent so the table can explain why the
            # Mulai-to-Pulih span is wider than the Lama Gangguan column.
            "jeda_detik": jeda_bulat,
            "jeda_teks": format_durasi(jeda_bulat) if jeda_bulat >= 1 else None,
            "kategori": x["kategori"],
            "kategori_teks": teks_kategori(x["kategori"]),
            "detail": x["detail"],
        })

    summarize = hitung_device(db, d, mulai, selesai, daftar_jeda)
    log = status_sekarang(db, device_id)
    periode_detik = round(PERIODE.get(label, PERIODE["24h"]).total_seconds())
    diamati_detik = summarize.get("durasi_diamati_detik")
    return {
        "periode_detik": periode_detik,
        "periode_teks": PERIODE_NAMA.get(label, label),
        "periode_penuh": (diamati_detik is not None
                          and diamati_detik >= periode_detik * 0.99),
        "device": {
            "id": d.id,
            "name": d.name,
            "ip_address": d.ip_address,
            "device_type": d.device_type,
            "platform": d.platform,
            "location": d.location,
            "is_reachable": log.is_reachable if log else None,
            "response_time_ms": log.response_time_ms if log else None,
            "last_checked": log.timestamp.isoformat() if log else None,
        },
        "periode": label,
        "dipantau_sejak": dipantau_sejak.isoformat() if dipantau_sejak else None,
        "total_riwayat": len(down_list),
        "avg_latency_ms": rata_latency(db, device_id, label, mulai),
        "ringkasan": summarize,
        "riwayat": riwayat,
    }


def format_bps(bps):
    """Convert bits per second to Mbps with 3 decimals: ONE unit everywhere, so a
    column can be read down like plain numbers ("863 Kbps" vs "1.2 Mbps" needs mental conversion).

    Trade-off: small traffic reads 0.000 (e.g. 205 bps = 0.0002 Mbps), so every
    place showing this value must also send the raw bps for the hover text; see
    `format_bps_lengkap()`. Three decimals, not two: 0.001 Mbps is still 1 Kbps.
    """
    if bps is None:
        return "-"
    return f"{bps / 1_000_000:.3f} Mbps"


def format_bps_lengkap(bps):
    """Display-ready Mbps plus the raw value for hover text, returned as a pair so
    callers cannot forget the second: a single unit is only honest if the original number stays reachable.
    """
    if bps is None:
        return "-", None
    # Always raw bits per second in one unit, with Indonesian-style thousands
    # separators ('.' for thousands would clash with a decimal point in a mixed format).
    return format_bps(bps), f"{bps:,.0f} bps".replace(",", ".")


# CSV export. Two decisions so the file opens cleanly in Indonesian-locale Excel:
# 1. Column separator is a semicolon (the Windows list separator there).
# 2. Decimals use a comma (99,55); with a dot Excel reads the value as text.
# A UTF-8 BOM is added at the start so accented characters survive.
PEMISAH = ";"


# Window of readings still considered current. The poller reads traffic every 30
# s, so 10 minutes tolerates delayed reads (SNMP timeout then SSH fallback can
# take a dozen seconds) without showing stale numbers as live; older samples are
# deliberately hidden, so an empty card means "no new reading".
JENDELA_BW_DETIK = 600


# When a reading is flagged as lagging. Looser than 30 s since one missed round
# is normal and flagging every small delay would make the marker ignored.
BW_BASI_DETIK = 120


def _periode_yang_memuat(waktu):
    """Smallest period that still contains a given time.

    Used by the last-incident card so its link never lands on a page that hides the
    incident: the card shows the latest event over all history, while the device
    page is limited to a period.
    """
    age = (datetime.now() - waktu).total_seconds()
    for label in ("1h", "24h", "7d", "30d"):
        if age <= PERIODE[label].total_seconds():
            return label
    return "30d"


def _urai_bukti(teks):
    """Turn stored evidence text into a display-ready list.

    Stored as "OK|sentence" per line; plain text rather than JSON because the
    column is also read by humans browsing the database. Three markers, not two:
    `INFO` is for facts that are neither success nor failure (e.g. a closed port
    where no service ever existed), which would read as an extra problem if shown in red.
    """
    hasil = []
    for line in (teks or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            mark, kalimat = line.split("|", 1)
            mark = mark.strip().upper()
            hasil.append({"ok": True if mark == "OK"
                                else None if mark == "INFO" else False,
                          "teks": kalimat.strip()})
        else:
            hasil.append({"ok": None, "teks": line})
    return hasil


def insiden_terakhir_lengkap(db, terakhir_down_device=None):
    """Latest outage, from devices AND services, with cause and evidence: which layer
    is down, which is still healthy, what NSM checked, and the next step.
    """
    if terakhir_down_device is None:
        terakhir_down_device = (
            db.query(DeviceEvent, Device)
            .join(Device, Device.id == DeviceEvent.device_id)
            .filter(DeviceEvent.event_type == "DOWN",
                    or_(DeviceEvent.category.is_(None),
                        DeviceEvent.category != "baseline"))
            .order_by(desc(DeviceEvent.timestamp), desc(DeviceEvent.id))
            .first()
        )

    last_svc = (
        db.query(ServiceEvent, Service, Device)
        .join(Service, Service.id == ServiceEvent.service_id)
        .join(Device, Device.id == ServiceEvent.device_id)
        .filter(ServiceEvent.event_type == "DOWN",
                or_(ServiceEvent.kategori.is_(None),
                    ServiceEvent.kategori != "baseline"))
        .order_by(desc(ServiceEvent.timestamp), desc(ServiceEvent.id))
        .first()
    )

    time_dev = terakhir_down_device[0].timestamp if terakhir_down_device else None
    time_svc = last_svc[0].timestamp if last_svc else None

    if time_svc and (time_dev is None or time_svc >= time_dev):
        ev, svc, dev = last_svc
        # Recovered or still ongoing? Read from events AFTER this one.
        pulih = (db.query(ServiceEvent)
                 .filter(ServiceEvent.service_id == svc.id,
                         ServiceEvent.event_type == "UP",
                         ServiceEvent.timestamp > ev.timestamp)
                 .order_by(ServiceEvent.timestamp)
                 .first())
        periode = _periode_yang_memuat(ev.timestamp)
        if pulih:
            old = round((pulih.timestamp - ev.timestamp).total_seconds())
        else:
            old = round((datetime.now() - ev.timestamp).total_seconds())
        return {
            "jenis": "layanan",
            "device": dev.name,
            "device_id": dev.id,
            "ip": dev.ip_address,
            "layanan": svc.nama,
            "layanan_jenis": svc.jenis,
            "port": svc.port,
            "event_id": ev.id,
            "waktu": ev.timestamp.isoformat(),
            "berlangsung": pulih is None,
            "lama_detik": old,
            "lama_teks": format_durasi(old),
            "kategori": ev.kategori,
            "kategori_teks": teks_kategori(ev.kategori),
            "kode": ev.kode,
            "detail": ev.detail,
            "bukti": _urai_bukti(ev.bukti),
            "saran": ev.saran,
            "punya_diagnosa": bool(ev.diagnosa_mulai or ev.diagnosa_pulih),
            # Link carries the period that guarantees the incident falls in the window, plus an anchor to the exact row.
            "periode_saran": periode,
            "tautan": "/report/device/%d?period=%s#insiden-svc-%d" % (dev.id, periode, ev.id),
        }

    if terakhir_down_device:
        ev, dev = terakhir_down_device
        pulih = (db.query(DeviceEvent)
                 .filter(DeviceEvent.device_id == dev.id,
                         DeviceEvent.event_type == "UP",
                         DeviceEvent.timestamp > ev.timestamp)
                 .order_by(DeviceEvent.timestamp)
                 .first())
        periode = _periode_yang_memuat(ev.timestamp)
        old = round(((pulih.timestamp if pulih else datetime.now())
                      - ev.timestamp).total_seconds())
        return {
            "jenis": "device",
            "device": dev.name,
            "device_id": dev.id,
            "ip": dev.ip_address,
            "layanan": None,
            "event_id": ev.id,
            "waktu": ev.timestamp.isoformat(),
            "berlangsung": pulih is None,
            "lama_detik": old,
            "lama_teks": format_durasi(old),
            "kategori": ev.category,
            "kategori_teks": teks_kategori(ev.category),
            "kode": None,
            "detail": ev.detail,
            "bukti": [],
            "saran": None,
            "punya_diagnosa": False,
            "periode_saran": periode,
            "tautan": "/report/device/%d?period=%s#insiden-%d" % (dev.id, periode, ev.id),
        }
    return None


def ringkas_layanan_per_device(db):
    """CURRENT state of each service, grouped per device.

    Used by the dashboard device cards and kept separate from `layanan_semua()`,
    which computes availability (sweeping `status_logs` and rebuilding all
    `service_events`). The dashboard refreshes every 5 s, so this relies only on the
    LAST check row of each service: one query, no period window.
    """
    # Last check row per service, found by max id rather than max timestamp: ids
    # increase monotonically and are indexed, while two checks can share a second.
    sub = (db.query(ServiceCheck.service_id.label("sid"),
                    func.max(ServiceCheck.id).label("mid"))
           .group_by(ServiceCheck.service_id).subquery())
    last = {
        c.service_id: c
        for c in db.query(ServiceCheck).join(sub, ServiceCheck.id == sub.c.mid).all()
    }

    per_device = {}
    for s in db.query(Service).order_by(Service.device_id, Service.id).all():
        c = last.get(s.id)
        dijeda = s.aktif == 0
        has_category = bool(c and c.kategori)
        content = per_device.setdefault(str(s.device_id), {
            "total": 0, "sehat": 0, "bermasalah": 0, "dijeda": 0, "layanan": [],
        })
        content["total"] += 1
        if dijeda:
            content["dijeda"] += 1
        elif c is not None and c.ok:
            content["sehat"] += 1
        elif c is not None:
            content["bermasalah"] += 1
        content["layanan"].append({
            "id": s.id,
            "nama": s.nama,
            "jenis": s.jenis,
            "port": s.port,
            "aktif": not dijeda,
            # None means never checked, kept distinct from False so a newly registered service does not read as down.
            "ok": (None if c is None else bool(c.ok)),
            "kode": c.kode if c else None,
            # The cause sentence comes from here, not from JavaScript.
            "kategori_teks": teks_kategori(c.kategori) if has_category else None,
            "terakhir_cek": c.timestamp.isoformat() if c else None,
        })

    return {"waktu": datetime.now().isoformat(), "per_device": per_device}


# NSM's own address, used to recognize NSM traffic so it is not read as an attack.
#
# Read from `.env` (default: detect this machine's address, see
# `config.get_alamat_nsm`). A hardcoded lab address would make the auto-ban
# allowlist miss NSM itself on another install, and with `AUTO_BAN_AKTIF` on NSM
# could become a ban candidate. `konfig.js ALAMAT_NSM` is duplicated on purpose
# (browser-side guard, a different process).
ALAMAT_NSM = config.get_alamat_nsm()


# SENSITIVE service ports (administrative/data/authentication entry points). A
# connection from an unregistered host to one of them signals a break-in, unlike
# public ports (80/443/8080/8443) that serve anyone. Deliberately NOT
# `PORT_LAYANAN` (used by `penolakan_acl()`): that list needs public ports to
# recognize reply traffic, this one must exclude them. Do not merge.
PORT_SENSITIF = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 110: "POP3", 143: "IMAP",
    389: "LDAP", 445: "SMB", 636: "LDAPS", 993: "IMAPS", 995: "POP3S",
    1433: "MSSQL", 3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL",
    5900: "VNC", 6379: "Redis", 11211: "Memcached", 27017: "MongoDB",
}


# Hostile-pattern thresholds clear enough to block AUTOMATICALLY (not just
# review), derived from the patterns the attacker card already uses.
AMBANG_PINDAI = 5  # >= 5 distinct destinations from one source = scan


AMBANG_GIGIH = 50  # >= 50 attempts from one source = repeated hammering


# {Device.location -> device_id of the ACL router guarding it}.
#
# Read from `config`, not from `ubah_acl_router`: the read-only report module
# must not import a module that changes router config just to get one table.
LOKASI_ACL_ROUTER = {v["lokasi"]: k for k, v in config.get_router_acl().items()
                     if v.get("lokasi")}


# How many days ahead a capacity forecast is shown as a warning. 45 days leaves
# time to add disk without hurry, yet is not so far that the warning is always on and gets ignored.
BATAS_PRAKIRAAN_HARI = 45


def _peta_device(db):
    """IP address -> device name, so numbers do not stop at an address."""
    peta = {}
    for d in db.query(Device).all():
        if d.ip_address:
            peta[d.ip_address] = d.name
    return peta


POLA_BLOK_ACL = re.compile(r"ip access-list extended (\S+)\n((?:[ \t].*\n?)*)")


POLA_BARIS_IZIN = re.compile(r"^\s*(permit|deny)\s", re.I)


def _perubahan_nsm_per_device(db, device_ids):
    """ALL successful `FirewallPerubahan` rows for a set of devices, grouped by
    `device_id`, with NO time limit; callers filter to their own window via
    `_pelaku_jendela()`. One query for many devices.

    Grouped raw, not filtered per window here: one device can have many snapshots
    in a list, each with its own window, and filtering per device would overwrite
    one snapshot's window with another's (a second snapshot showed "outside NSM"
    for a change that clearly went through NSM).

    Only results that actually changed the device (`BERHASIL` /
    `BERHASIL_TANPA_BUKTI`, see `penjaga_aksi.py`) count; rejected attempts changed nothing.
    """
    from models import FirewallPerubahan

    if not device_ids:
        return {}
    line = (db.query(FirewallPerubahan)
             .filter(FirewallPerubahan.device_id.in_(device_ids),
                     FirewallPerubahan.hasil.in_(
                         ("BERHASIL", "BERHASIL_TANPA_BUKTI")))
             .order_by(FirewallPerubahan.waktu).all())
    per_device = {}
    for b in line:
        per_device.setdefault(b.device_id, []).append(b)
    return per_device


def _pelaku_jendela(perubahan_device, sejak, sampai):
    """Filter ONE device's changes to the window (since, until] and reduce to a
    display-ready actor label. `None` means "no NSM record in this window"; the
    caller decides its meaning ("outside NSM" or "not applicable"). `sejak=None`
    (first snapshot, nothing to compare) always returns None.
    """
    if sejak is None or not perubahan_device:
        return None
    cocok = [b for b in perubahan_device
             if b.waktu is not None and sejak < b.waktu <= sampai]
    if not cocok:
        return None
    oleh = sorted(set(b.oleh for b in cocok if b.oleh))
    aksi = sorted(set(b.aksi for b in cocok if b.aksi))
    return {"lewat_nsm": True, "oleh": oleh, "aksi": aksi,
            "jumlah": len(cocok)}


# Ports that mean an entry point to the machine if open to anyone, not just a
# service it serves. Short and explicit on purpose: a long guessed list raises
# severity where it should not, and a tool that cries wolf gets turned off.
PORT_PINTU_MASUK = {
    22: "SSH", 3389: "RDP", 3306: "MySQL", 5432: "PostgreSQL",
    389: "LDAP", 636: "LDAPS", 27017: "MongoDB", 5900: "VNC",
}


def _peta_orang(db):
    """{uid: {nama, jabatan, ...}} from the directory copy.

    Read ONCE per request, not once per row: the table holds only a dozen people
    while transfer rows keep growing.
    """
    peta = {}
    for o in db.query(OrangLdap).all():
        peta[o.uid] = {
            "nama": o.nama,
            "jabatan": o.jabatan,
            "email": o.email,
            "grup": o.grup,
        }
    return peta


def _hias_orang(peta, uid):
    """Complete a uid with name and title when present in the directory copy.

    A uid missing from the directory is returned as is, with no name or title.
    That is meaningful (system account `nsmro`, local account, removed person), and
    inventing a name from the uid would make a machine account read like a person.
    """
    if not uid:
        return {"nama": None, "jabatan": None}
    return peta.get(uid) or {"nama": None, "jabatan": None}


# Span for "same session" on repeated SMB reads/writes of the SAME FILE. Half the
# similar value elsewhere (Flow ends a session after 5 idle minutes) because this
# measures "someone is still touching this file", not "the TCP connection is
# open"; gaps between reads in one engagement are typically under a minute.
SESI_GABUNG_DETIK = 60


# How many event-log rows are sent to the page, PER TABLE.
#
# Separate from `batas` (the Per Pengguna/Per Berkas summary tables, where 15 is
# enough as a ranking). The log tables once shared `batas * 2` = 30 rows and the
# page claimed 461 events while only 56 rows were ever sent, with no sign of it on
# screen. 200 stays below `BATAS_WAJAR = 500` in `static/js/halaman-tabel.js`; if
# a period routinely exceeds it, move to server-side pagination instead of raising this.
BATAS_LOG = 200


# Common port names, used when a port is not registered as a service in NSM, to
# answer "through which door was the data taken".
PORT_UMUM = {
    20: "FTP data", 21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP",
    53: "DNS", 67: "DHCP", 69: "TFTP", 80: "HTTP", 110: "POP3",
    123: "NTP", 143: "IMAP", 161: "SNMP", 162: "SNMP trap", 179: "BGP",
    389: "LDAP", 443: "HTTPS", 445: "SMB", 465: "SMTPS", 514: "Syslog",
    587: "SMTP", 636: "LDAPS", 993: "IMAPS", 995: "POP3S",
    1433: "MS SQL", 1521: "Oracle", 3128: "Proxy", 3306: "MySQL",
    3389: "Remote Desktop", 5432: "PostgreSQL", 5900: "VNC",
    6379: "Redis", 8080: "HTTP (port lain)", 8443: "HTTPS (port lain)",
    9090: "HTTP (port lain)", 9200: "Elasticsearch", 27017: "MongoDB",
}


def _ip_bersih(ip):
    """Normalize address forms that are really one machine.

    Linux writes dual-stack sockets as `::ffff:192.168.56.101`; without
    normalizing, one machine appears twice with split numbers, which readers would take as two parties.
    """
    if not ip:
        return ip
    t = ip.strip("[]")
    if t.lower().startswith("::ffff:"):
        return t[7:]
    return t


def _di_luar_jaringan(ip):
    """True if this address is not a local network address.

    A flag, not an accusation: a device fetching package updates from the internet
    is flagged too. It only says the conversation left the lab and deserves a look first.
    """
    if not ip:
        return False
    t = _ip_bersih(ip)
    if t in ("::1", "127.0.0.1") or t.startswith("127."):
        return False
    if t.startswith(("10.", "192.168.", "169.254.", "fe80:", "fd", "fc")):
        return False
    if t.startswith("172."):
        try:
            oktet2 = int(t.split(".")[1])
            if 16 <= oktet2 <= 31:
                return False
        except (IndexError, ValueError):
            pass
    section = t.split(".")
    if len(section) == 4 and all(b.isdigit() for b in section):
        return True
    # IPv6 addresses other than link-local/unique-local: treat as external.
    return ":" in t


def _peta_layanan_port(db):
    """(device_id, port) -> service name registered in NSM.

    A registered name is more precise than the generic port table (port 8080 on one
    host is "E-Canteen v2", not just "another HTTP port"). The device_id pair
    matters: port 22 on two hosts is two different services.
    """
    peta = {}
    for s in db.query(Service).filter(Service.aktif != 0).all():
        if s.port:
            peta[(s.device_id, int(s.port))] = s.nama
    return peta


# Topology map (Dashboard).
#
# Two kinds of links, which must not be conflated:
# `tautan_lalu_lintas`: real TCP connections recorded by the poller
# (`flow_koneksi`) within the last `JENDELA_TOPOLOGI_MENIT` minutes; the live map.
# `tautan_tetap`: physical/logical paths from `device_link`, filled in
# manually and empty so far, since NSM cannot detect real cabling.
#
# Both are always sent even when one is empty: an empty array says "checked,
# nothing there yet", while omitting it would hide that the link kind exists.
JENDELA_TOPOLOGI_MENIT = 10

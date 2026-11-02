"""Availability and latency reports for report_service; re-exported by `report_service/__init__.py`."""
from datetime import datetime, timedelta
from sqlalchemy import case, desc, func
import dialek
import jeda
import rollup
from models import (Device, StatusLog, DeviceEvent, BandwidthSample)

from ._inti import (_cache_ambil, _cache_simpan, format_durasi, rentang, selang_down, teks_kategori)



def statistik_latency(db, device_id, mulai):
    """Latency mean, min, max, and sample count over the period.

    Used by the `Statistik Latency` sheet in the Excel report. Only successful
    samples (is_reachable) count: an unreachable device has no latency, and
    counting zeros would skew the mean.

    Not cached: only called when generating reports (rare), not every 5 s like
    the charts.
    """
    # Mean, min, and max come from the hourly rollup (see `rata_latency`).
    # `jumlah_sampel` is still counted from raw rows on purpose: it reports how
    # often the device was checked AND reachable, including TCP-only liveness checks
    # with no latency value. `latency_sampel` counts something narrower and would
    # silently shrink this column for devices that block ICMP.
    jsum, jcac, minimum, maksimum = rollup.latency_periode(
        db, device_id, mulai, datetime.now())
    average = (jsum / jcac) if jcac else None
    jumlah = (
        db.query(func.count(StatusLog.id))
        .filter(StatusLog.device_id == device_id,
                StatusLog.timestamp >= mulai,
                StatusLog.is_reachable == True)  # noqa: E712
        .scalar()
    )
    return {
        "rata_ms": round(average, 2) if average is not None else None,
        "min_ms": round(minimum, 2) if minimum is not None else None,
        "max_ms": round(maksimum, 2) if maksimum is not None else None,
        "jumlah_sampel": jumlah or 0,
    }


def _irisan_detik(a1, a2, b1, b2):
    """Overlap of two time ranges in seconds (0 if they do not intersect)."""
    begin = max(a1, b1)
    end = min(a2, b2)
    return max(0.0, (end - begin).total_seconds())


def deret_per_jam(db, device_id, mulai, selesai):
    """Device availability and latency summarized per time bucket.

    Used by Excel report charts, which need a sensible number of points: 24 hours
    holds over ten thousand status_logs rows, too many to plot readably.

    Bucket size follows the period length: 1 hour -> per minute (otherwise the
    chart has one point), 30 days -> per day.

    Availability here is computed from TIME, not the share of successful samples:
    the on-screen Availability card uses outage durations (see `hitung_device`),
    and the poller does not sample at a fixed rate (some hours have 720 samples,
    others 55). Sample shares give a different number from the card, and a
    document with two numbers for the same thing is useless, so the chart uses
    the card's basis.

    Buckets with no monitoring at all return None, not 0: unobserved time is not
    downtime, and 0% would draw a false cliff. openpyxl plots empty cells as a
    gap, which is the right meaning.
    """
    diff = (selesai - mulai).total_seconds()
    if diff <= 3 * 3600:
        satuan, width = "menit", timedelta(minutes=1)
        cut = lambda t: t.replace(second=0, microsecond=0)
        fmt = "%d/%m %H:%M"
    elif diff <= 8 * 24 * 3600:
        satuan, width = "jam", timedelta(hours=1)
        cut = lambda t: t.replace(minute=0, second=0, microsecond=0)
        fmt = "%d/%m %H:00"
    else:
        satuan, width = "hari", timedelta(days=1)
        cut = lambda t: t.replace(hour=0, minute=0, second=0, microsecond=0)
        fmt = "%d/%m/%Y"

    pause_list = jeda.find_gaps(db, device_id, mulai, selesai)
    selang, monitored_since = selang_down(db, device_id, mulai, selesai, pause_list)
    if monitored_since is None:
        return {"satuan": satuan, "titik": []}
    awal_amat = max(mulai, monitored_since)

    # Latency still comes from samples: it only exists when measured.
    ember_sql = dialek.ember_waktu(
        db, StatusLog.timestamp,
        {"menit": "%Y-%m-%d %H:%M", "jam": "%Y-%m-%d %H:00",
         "hari": "%Y-%m-%d"}[satuan])
    map_latency = {
        kotak: (round(average, 2) if average is not None else None, jumlah or 0)
        for kotak, average, jumlah in (
            db.query(ember_sql,
                     func.avg(case((StatusLog.is_reachable == True,      # noqa: E712
                                    StatusLog.response_time_ms), else_=None)),
                     func.count(StatusLog.id))
            .filter(StatusLog.device_id == device_id,
                    StatusLog.timestamp >= mulai,
                    StatusLog.timestamp <= selesai)
            .group_by(ember_sql).all()
        )
    }
    kunci_fmt = {"menit": "%Y-%m-%d %H:%M", "jam": "%Y-%m-%d %H:00",
                 "hari": "%Y-%m-%d"}[satuan]

    hasil = []
    box_begin = cut(awal_amat)
    limit_safe = 2000  # 30 days hourly = 720; per-minute is capped
    while box_begin < selesai and len(hasil) < limit_safe:
        box_end = box_begin + width
        total = _irisan_detik(box_begin, box_end, awal_amat, selesai)
        if total > 0:
            tak_terpantau = jeda.detik_tak_terpantau(
                pause_list, max(box_begin, awal_amat), min(box_end, selesai))
            observed = max(0.0, total - tak_terpantau)
            down = 0.0
            for s in selang:
                end_s = s["selesai"] or selesai
                raw = _irisan_detik(box_begin, box_end, s["mulai"], end_s)
                if raw <= 0:
                    continue
                # Pauses within this slice were already cut from `diamati`; without cutting them
                # here too, down time could exceed observed time and availability go negative.
                down += max(0.0, raw - jeda.detik_tak_terpantau(
                    pause_list,
                    max(box_begin, s["mulai"]),
                    min(box_end, end_s)))
            down = min(down, observed)
            lat, sampel = map_latency.get(box_begin.strftime(kunci_fmt), (None, 0))
            hasil.append({
                "kotak": box_begin.strftime(fmt),
                "sampel": sampel,
                "diamati_detik": round(observed, 1),
                "down_detik": round(down, 1),
                "availability": (round((observed - down) * 100.0 / observed, 3)
                                 if observed > 0 else None),
                "latency_ms": lat,
            })
        box_begin = box_end

    return {"satuan": satuan, "titik": hasil}


def sparkline_semua(db, period, kotak=40):
    """Per-device up/down pattern over the period, for sparklines.

    The period is split into `kotak` equal buckets, each holding the fraction of
    successful checks: values 0 to 1, and `None` for buckets with no data (device
    not monitored yet, or poller down).

    Separate from /report/availability on purpose: this query scans status_logs,
    the largest table, costing about 80 ms for five devices. The report table
    refreshes every 10 s and the sparkline barely changes in that time, so the
    page can fetch this far less often.

    Grouping is done by the database (GROUP BY), not by pulling hundreds of
    thousands of rows into Python.
    """
    mulai, selesai, label = rentang(period)
    kotak = max(10, min(int(kotak), 120))
    lebar_detik = (selesai - mulai).total_seconds() / kotak
    if lebar_detik <= 0:
        return {"periode": label, "kotak": kotak, "devices": {}}

    kunci = f"sparkline:{label}:{kotak}"
    stored = _cache_ambil(kunci, 45)
    if stored is not None:
        return stored

    # Bucket number computed in SQL: elapsed seconds divided by bucket width.
    petak = dialek.petak_ke(
        db, StatusLog.timestamp, mulai, lebar_detik).label("petak")

    # CASE, not IIF: IIF needs SQLite 3.32+, while CASE works in every version and
    # in other databases too.
    rise = func.avg(case((StatusLog.is_reachable == True, 1.0), else_=0.0))  # noqa: E712

    hasil = {}
    for d in db.query(Device).all():
        line = (
            db.query(petak, rise)
            .filter(StatusLog.device_id == d.id,
                    StatusLog.timestamp >= mulai,
                    StatusLog.timestamp < selesai)
            .group_by(petak)
            .all()
        )
        series = [None] * kotak
        for nomor, average in line:
            if nomor is None or average is None:
                continue
            if 0 <= nomor < kotak:
                series[nomor] = round(float(average), 4)
        hasil[str(d.id)] = series

    return _cache_simpan(kunci, {
        "periode": label,
        "kotak": kotak,
        "mulai": mulai.isoformat(),
        "selesai": selesai.isoformat(),
        "lebar_detik": round(lebar_detik),
        "devices": hasil,
    })


def data_grafik(db, device_id, titik=60):
    """Latest points to PRE-FILL the chart on first page load.

    Without this the chart starts empty and takes many minutes to take shape,
    which looks broken.

    After that the chart grows from normal page refreshes and this endpoint is
    not called again, so the cost is once per page load, capped by `titik`.
    """
    d = db.query(Device).filter(Device.id == device_id).first()
    if not d:
        return {"error": "Device tidak ditemukan"}

    # --- ping: take the last N, then reverse to oldest -> newest ---
    line_ping = (
        db.query(StatusLog)
        .filter(StatusLog.device_id == device_id)
        .order_by(desc(StatusLog.timestamp), desc(StatusLog.id))
        .limit(titik)
        .all()
    )
    line_ping.reverse()
    ping = [{
        "t": b.timestamp.isoformat() if b.timestamp else None,
        # An unreachable device has no latency. Sent as null (not 0) so the chart line
        # breaks there; 0 ms would look impossibly fast.
        "ms": b.response_time_ms if b.is_reachable else None,
    } for b in line_ping]

    # --- bandwidth per interface ---
    iface_exists = [r[0] for r in (
        db.query(BandwidthSample.iface)
        .filter(BandwidthSample.device_id == device_id)
        .distinct().all()
    )]
    bandwidth = {}
    for nama in sorted(iface_exists):
        line = (
            db.query(BandwidthSample)
            .filter(BandwidthSample.device_id == device_id,
                    BandwidthSample.iface == nama)
            .order_by(desc(BandwidthSample.timestamp), desc(BandwidthSample.id))
            .limit(titik)
            .all()
        )
        line.reverse()
        bandwidth[nama] = [{
            "t": b.timestamp.isoformat() if b.timestamp else None,
            "in": b.in_bps,
            "out": b.out_bps,
        } for b in line]

    return {
        "device": d.name,
        "maks_titik": titik,
        "ping": ping,
        "bandwidth": bandwidth,
    }


def data_terbaru(db, device_id):
    """Latest single point only, for appending to the chart.

    Called every 5 s, so it must be cheap: two indexed "latest row" queries.
    Compare `riwayat_device()`, which rebuilds all outage intervals and is fine
    every 10 s, not every 5.
    """
    line = (
        db.query(StatusLog)
        .filter(StatusLog.device_id == device_id)
        .order_by(desc(StatusLog.timestamp), desc(StatusLog.id))
        .first()
    )
    ping = None
    if line:
        ping = {
            "t": line.timestamp.isoformat() if line.timestamp else None,
            # null (not 0) when the device is unreachable -> chart line breaks
            "ms": line.response_time_ms if line.is_reachable else None,
        }

    # Latest row for each interface
    iface_exists = [r[0] for r in (
        db.query(BandwidthSample.iface)
        .filter(BandwidthSample.device_id == device_id)
        .distinct().all()
    )]
    bandwidth = {}
    for nama in sorted(iface_exists):
        b = (
            db.query(BandwidthSample)
            .filter(BandwidthSample.device_id == device_id,
                    BandwidthSample.iface == nama)
            .order_by(desc(BandwidthSample.timestamp), desc(BandwidthSample.id))
            .first()
        )
        if b:
            bandwidth[nama] = {
                "t": b.timestamp.isoformat() if b.timestamp else None,
                "in": b.in_bps,
                "out": b.out_bps,
            }

    return {"ping": ping, "bandwidth": bandwidth}


def event_mentah(db, device_id, period, limit=200):
    """Raw event list (UP/DOWN/baseline) for detailed drill-down."""
    mulai, selesai, label = rentang(period)
    line = (
        db.query(DeviceEvent)
        .filter(DeviceEvent.device_id == device_id,
                DeviceEvent.timestamp >= mulai)
        .order_by(desc(DeviceEvent.timestamp), desc(DeviceEvent.id))
        .limit(limit)
        .all()
    )
    return {
        "periode": label,
        "events": [{
            "id": e.id,
            "event_type": e.event_type,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            "duration_sec": e.duration_sec,
            "duration_teks": format_durasi(e.duration_sec),
            "kategori": e.category,
            "kategori_teks": teks_kategori(e.category),
            "detail": e.detail,
            "last_rtt_ms": e.last_rtt_ms,
            "note": e.note,
        } for e in line],
    }

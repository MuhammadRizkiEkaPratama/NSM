"""Hourly summary of `status_logs`, so history survives pruning.

`status_logs` grows about 8 MB per day and `pangkas_data.py` prunes it at 35 days. One
summary row replaces the ~720 raw rows of an hour, so a year of history for six devices
is only about 52,000 rows.

Two rules:
1. Only COMPLETED hours are summarized. The current hour is still growing, and a
   half-finished figure stored permanently looks like fact.
2. Summarize first, prune after. `pangkas_data.py` refuses to delete raw rows that have
   not been summarized.

This module only READS `status_logs` and WRITES `status_rollup_jam`.
"""
from datetime import datetime, timedelta

from sqlalchemy import func, case

from models import StatusLog, StatusRollupJam, Device


def awal_jam(t):
    """Truncate a time to the start of its hour."""
    return t.replace(minute=0, second=0, microsecond=0)


def jam_terakhir_diringkas(db, device_id=None):
    """Latest hour that already has a summary row; None if there is none."""
    q = db.query(func.max(StatusRollupJam.jam))
    if device_id is not None:
        q = q.filter(StatusRollupJam.device_id == device_id)
    value = q.scalar()
    if value is None:
        return None
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def jam_tertua_mentah(db):
    """Hour of the oldest remaining `status_logs` row."""
    value = db.query(func.min(StatusLog.timestamp)).scalar()
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return awal_jam(value)


def compute_hour(db, device_id, jam):
    """Compute one hour's summary for one device from its raw rows.

    Returns a dict, or None when the hour has no rows. An empty hour deliberately yields no
    zero row: "zero samples" and "zero successful samples" differ, and a zero row would make
    an hour when the poller was down look like an hour when the device was down.
    """
    end = jam + timedelta(hours=1)
    line = (
        db.query(
            func.count(StatusLog.id),
            func.sum(case((StatusLog.is_reachable == True, 1), else_=0)),  # noqa: E712
            # Latency only from SUCCESSFUL samples. Checked against real data: rows recorded as down
            # still carried `response_time_ms`, always 0.0 (`icmplib` returns zero when there is no
            # reply), which dragged the average down and made `latency_min` 0.0 ms for every device.
            #
            # `rata_latency()` and `statistik_latency()` in report_service already filter on
            # `is_reachable`; filtering differently here would publish a second number for the same thing.
            #
            # `sampel_naik` and `latency_sampel` may still differ: a device proven alive over TCP is
            # recorded as reachable WITH empty latency.
            func.sum(case((StatusLog.is_reachable == True,               # noqa: E712
                           StatusLog.response_time_ms), else_=None)),
            func.count(case((StatusLog.is_reachable == True,             # noqa: E712
                             StatusLog.response_time_ms), else_=None)),
            func.min(case((StatusLog.is_reachable == True,               # noqa: E712
                           StatusLog.response_time_ms), else_=None)),
            func.max(case((StatusLog.is_reachable == True,               # noqa: E712
                           StatusLog.response_time_ms), else_=None)),
        )
        .filter(StatusLog.device_id == device_id,
                StatusLog.timestamp >= jam,
                StatusLog.timestamp < end)
        .first()
    )
    if not line or not line[0]:
        return None
    return {
        "device_id": device_id,
        "jam": jam,
        "sampel": int(line[0] or 0),
        "sampel_naik": int(line[1] or 0),
        "latency_jumlah": float(line[2] or 0.0),
        "latency_sampel": int(line[3] or 0),
        "latency_min": line[4],
        "latency_maks": line[5],
    }


def save_hour(db, data):
    """Write one summary row, overwriting if the hour was already computed.

    Overwrites rather than skips, so rebuilding an hour gives the same figures as the first computation.
    """
    old = (db.query(StatusRollupJam)
            .filter(StatusRollupJam.device_id == data["device_id"],
                    StatusRollupJam.jam == data["jam"])
            .first())
    if old is None:
        old = StatusRollupJam(device_id=data["device_id"], jam=data["jam"])
        db.add(old)
    old.sampel = data["sampel"]
    old.sampel_naik = data["sampel_naik"]
    old.latency_jumlah = data["latency_jumlah"]
    old.latency_sampel = data["latency_sampel"]
    old.latency_min = data["latency_min"]
    old.latency_maks = data["latency_maks"]
    old.dihitung = datetime.now()
    return old


def bangun(db, sampai=None, batas_jam=2000, ulang_dari=None):
    """Fill summaries for all completed hours not yet summarized.

    `sampai`      : upper bound, defaults to the start of the CURRENT hour (never included).
    `batas_jam`   : guard so one call does not sweep months and hold the write lock long;
                    the next call does the rest.
    `ulang_dari`  : recompute from this hour even if already summarized (when the rules change).

    Returns (rows_written, last_hour_summarized).
    """
    # `sampai` is an EXCLUSIVE bound: the hour itself is not summarized, so the running hour
    # is always left out.
    if sampai is None:
        sampai = awal_jam(datetime.now())
    else:
        sampai = awal_jam(sampai)

    oldest = jam_tertua_mentah(db)
    if oldest is None:
        return 0, None

    if ulang_dari is not None:
        mulai = max(awal_jam(ulang_dari), oldest)
    else:
        last = jam_terakhir_diringkas(db)
        # Resume from the hour AFTER the last one, not from the last one itself. A completed hour
        # cannot receive new rows, so recomputing it is pointless and would make "repeat until
        # nothing is written" loops never terminate. Use `ulang_dari` to recompute explicitly.
        mulai = oldest if last is None else last + timedelta(hours=1)
    if mulai >= sampai:
        return 0, None

    devices = [d.id for d in db.query(Device).all()]
    written = 0
    jam = mulai
    via = 0
    while jam < sampai and via < batas_jam:
        for did in devices:
            data = compute_hour(db, did, jam)
            if data is not None:
                save_hour(db, data)
                written += 1
        jam += timedelta(hours=1)
        via += 1
    return written, jam - timedelta(hours=1)


# Reads: figures computed FROM the summary
def ringkas_periode(db, device_id, mulai, selesai):
    """Combine hourly summaries into one figure.

    The average is computed as sum divided by count, not as the mean of hourly means (see
    `models.StatusRollupJam`): averaging averages weights a 720-sample hour like a 12-sample hour.
    """
    line = (
        db.query(
            func.sum(StatusRollupJam.sampel),
            func.sum(StatusRollupJam.sampel_naik),
            func.sum(StatusRollupJam.latency_jumlah),
            func.sum(StatusRollupJam.latency_sampel),
            func.min(StatusRollupJam.latency_min),
            func.max(StatusRollupJam.latency_maks),
        )
        .filter(StatusRollupJam.device_id == device_id,
                StatusRollupJam.jam >= awal_jam(mulai),
                StatusRollupJam.jam < selesai)
        .first()
    )
    sampel = int(line[0] or 0)
    if not sampel:
        return None
    lat_sample = int(line[3] or 0)
    return {
        "sampel": sampel,
        "sampel_naik": int(line[1] or 0),
        "latency_rata": (round(line[2] / lat_sample, 2)
                         if lat_sample else None),
        "latency_sampel": lat_sample,
        "latency_min": line[4],
        "latency_maks": line[5],
    }


def _naik_jam(t):
    """Round UP to the start of the next hour; an exact hour start stays unchanged."""
    p = awal_jam(t)
    return p if p == t else p + timedelta(hours=1)


def latency_periode(db, device_id, mulai, selesai):
    """Sum and count of latency for a period: summaries for the middle, raw rows for both edges.

    Returns `(sum, count, min, max)`; the caller computes the average as `sum / count`.

    Summaries alone are not enough. They only cover completed hours already computed, so
    reading them alone drops three pieces:
    1. The leading edge, when `mulai` falls mid-hour (that hour's row includes minutes before `mulai`).
    2. The trailing edge: the running hour, which is deliberately never summarized.
    3. Completed hours not yet summarized (the rollup job runs every 10 minutes).

    Each is small, so the error would only show as a slightly different number from another
    page. The summary bounds are used as-is and the rest is read from raw rows;
    `uji_rollup.py` checks the result matches a full raw computation exactly.
    """
    def dari_mentah(a, b):
        if a >= b:
            return 0.0, 0, None, None
        # The `is_reachable` condition must be IDENTICAL to the one in `hitung_jam()`, otherwise the
        # edges and the middle drift apart depending on where the window falls.
        r = (db.query(func.sum(StatusLog.response_time_ms),
                      func.count(StatusLog.response_time_ms),
                      func.min(StatusLog.response_time_ms),
                      func.max(StatusLog.response_time_ms))
             .filter(StatusLog.device_id == device_id,
                     StatusLog.timestamp >= a,
                     StatusLog.timestamp < b,
                     StatusLog.is_reachable == True)  # noqa: E712
             .first())
        return float(r[0] or 0.0), int(r[1] or 0), r[2], r[3]

    sampai = jam_terakhir_diringkas(db)
    limit_summary = None if sampai is None else sampai + timedelta(hours=1)

    begin_whole = _naik_jam(mulai)
    if limit_summary is None:
        # No summary at all: no middle part is covered, so EVERYTHING must be read from raw rows.
        # Otherwise the page would report almost no data when summaries have not been built yet.
        end_whole = begin_whole
    else:
        end_whole = max(begin_whole, min(awal_jam(selesai), limit_summary))

    jum, cac, small, large = 0.0, 0, None, None
    if end_whole > begin_whole:
        r = (db.query(func.sum(StatusRollupJam.latency_jumlah),
                      func.sum(StatusRollupJam.latency_sampel),
                      func.min(StatusRollupJam.latency_min),
                      func.max(StatusRollupJam.latency_maks))
             .filter(StatusRollupJam.device_id == device_id,
                     StatusRollupJam.jam >= begin_whole,
                     StatusRollupJam.jam < end_whole)
             .first())
        jum, cac = float(r[0] or 0.0), int(r[1] or 0)
        small, large = r[2], r[3]

    for a, b in ((mulai, min(begin_whole, selesai)), (max(end_whole, mulai), selesai)):
        j, c, k, s = dari_mentah(a, b)
        jum += j
        cac += c
        if k is not None:
            small = k if small is None else min(small, k)
        if s is not None:
            large = s if large is None else max(large, s)
    return jum, cac, small, large


def sampel_periode(db, device_id, mulai, selesai):
    """Samples and `sampel_naik` for a period (for packet loss), combined like `latency_periode()`:
    summaries for the middle, raw rows for both edges.

    A separate function from `latency_periode()` so callers that only need latency (refreshed
    every 10 seconds) do not pay for the sample query. `ringkas_periode()` is not used here
    because it only reads the summary table and drops the running hour and the edge pieces.

    Returns `(sampel, sampel_naik)`.
    """
    def dari_mentah(a, b):
        if a >= b:
            return 0, 0
        r = (db.query(
                func.count(StatusLog.id),
                func.sum(case((StatusLog.is_reachable == True, 1), else_=0)),  # noqa: E712
             )
             .filter(StatusLog.device_id == device_id,
                     StatusLog.timestamp >= a,
                     StatusLog.timestamp < b)
             .first())
        return int(r[0] or 0), int(r[1] or 0)

    sampai = jam_terakhir_diringkas(db)
    limit_summary = None if sampai is None else sampai + timedelta(hours=1)

    begin_whole = _naik_jam(mulai)
    if limit_summary is None:
        end_whole = begin_whole
    else:
        end_whole = max(begin_whole, min(awal_jam(selesai), limit_summary))

    sampel, sampel_naik = 0, 0
    if end_whole > begin_whole:
        r = (db.query(func.sum(StatusRollupJam.sampel),
                      func.sum(StatusRollupJam.sampel_naik))
             .filter(StatusRollupJam.device_id == device_id,
                     StatusRollupJam.jam >= begin_whole,
                     StatusRollupJam.jam < end_whole)
             .first())
        sampel, sampel_naik = int(r[0] or 0), int(r[1] or 0)

    for a, b in ((mulai, min(begin_whole, selesai)), (max(end_whole, mulai), selesai)):
        s, n = dari_mentah(a, b)
        sampel += s
        sampel_naik += n
    return sampel, sampel_naik


def laporkan(db):
    """Human-readable output, used by maintenance and test scripts."""
    total = db.query(func.count(StatusRollupJam.id)).scalar() or 0
    raw = db.query(func.count(StatusLog.id)).scalar() or 0
    last = jam_terakhir_diringkas(db)
    oldest_summarize = db.query(func.min(StatusRollupJam.jam)).scalar()
    return {
        "baris_ringkasan": total,
        "baris_mentah": raw,
        "jam_terakhir": last,
        "jam_tertua": oldest_summarize,
        "penyusutan": (round(raw / total, 1) if total else None),
    }

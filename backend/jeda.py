"""Time ranges during which a device was NOT being monitored.

Availability is computed from `device_events` (UP <-> DOWN transitions). The gap
between a DOWN event and the next UP event is counted as downtime, even when it
was NSM itself that stopped looking. That happens for two reasons:

1. **The poller was not running** (laptop closed, Ctrl+C, restart). Gaps of up to
   24 hours have been observed in `status_logs`.
2. **The device was paused** via the Pause button (`devices.aktif = 0`). A device
   paused while DOWN and resumed the next morning showed one unobserved 13-hour
   "outage" and roughly 46% availability while about 99% of its pings succeeded.

Both leave the same trace: **no `status_logs` rows**. So one mechanism catches
both, with no new table: look for time gaps between a device's `status_logs` rows.

Rule: unmonitored time is counted neither as downtime nor as uptime; it is removed
from the denominator. Availability answers "of what was actually observed, what
percentage was healthy". Guessing either way is wrong: counting it as down makes
healthy devices look bad, counting it as up hides real outages.
"""
from datetime import datetime, timedelta

from sqlalchemy import text

import dialek

from config import get_interval

# Gaps of at least this many seconds count as "unmonitored".
#
# Deliberately far above the 5 s ping interval. The poller occasionally skips a round
# while competing with the bandwidth job (gaps of up to ~12 s); counting those would
# create hundreds of fake pause segments that slow the calculation without changing
# the result meaningfully.
AMBANG_MINIMUM_DETIK = 60

# Gap results are cached briefly, like the average-latency cache in report_service:
# this query scans `status_logs`, the only table with hundreds of thousands of rows,
# and the Report page refreshes every 10 s and calls this for every device.
_UMUR_CACHE_DETIK = 30
_cache = {}

# Keys include a timestamp, so a new key appears every 30 s and old ones are never
# reused. The poller runs for days, so without this cap the cache grows until the
# process exits.
_BATAS_CACHE = 200


def ambang_detik():
    """Time-gap threshold treated as a monitoring interruption."""
    return max(AMBANG_MINIMUM_DETIK, get_interval() * 6)


def _bulatkan(waktu, detik=_UMUR_CACHE_DETIK):
    """Round down to a multiple of `detik`.

    Used as the cache key; with raw `datetime.now()` the key changes every millisecond
    and the cache never hits. Cost: the edge of a pause can be off by up to 30 s
    (0.03% of a 24-hour window).
    """
    epoch = waktu.timestamp()
    return datetime.fromtimestamp(epoch - (epoch % detik))


# The subquery is aliased `L`: SQLite accepts an unaliased subquery, MySQL rejects it
# with "Every derived table must have its own alias", and only at page load time.
#
# The SQL is built at call time, not at import time. The time-difference expression
# differs between SQLite and MySQL, and with the local buffer one process can switch
# between them (MySQL when healthy, SQLite when the database is unreachable). SQL
# frozen at import would be wrong for one of them, precisely during an outage.
_sql_lompatan = {}


def _lompatan(db):
    kunci = "mysql" if dialek._mysql(db) else "sqlite"
    if kunci not in _sql_lompatan:
        _sql_lompatan[kunci] = text("""
    SELECT sebelum, sesudah FROM (
        SELECT LAG(timestamp) OVER (ORDER BY timestamp) AS sebelum,
               timestamp                                AS sesudah
        FROM status_logs
        WHERE device_id = :did AND timestamp >= :a AND timestamp <= :b
    ) AS L
    WHERE sebelum IS NOT NULL
      AND %s > :ambang
    ORDER BY sebelum
""" % dialek.selisih_detik_sql(db, "sebelum", "sesudah"))
    return _sql_lompatan[kunci]

_SQL_TEPI = text("""
    SELECT MIN(timestamp), MAX(timestamp)
    FROM status_logs
    WHERE device_id = :did AND timestamp >= :a AND timestamp <= :b
""")


def _ke_waktu(nilai):
    """SQLite returns timestamps as text; convert to datetime."""
    if nilai is None:
        return None
    if isinstance(nilai, datetime):
        return nilai
    return datetime.fromisoformat(nilai)


def find_gaps(db, device_id, mulai, selesai):
    """List of (start, end) ranges when this device was not monitored.

    Includes gaps at both edges of the window: if the first ping row appears long after
    `mulai`, that leading part is unmonitored too. The trailing edge matters most,
    since that is where "the poller is down right now" shows up.
    """
    a = _bulatkan(mulai)
    b = _bulatkan(selesai)
    if b <= a:
        return []

    kunci = (device_id, a, b)
    simpan = _cache.get(kunci)
    if simpan is not None:
        time_save, nilai = simpan
        if (datetime.now() - time_save).total_seconds() <= _UMUR_CACHE_DETIK:
            return nilai

    ambang = ambang_detik()
    p = {"did": device_id, "a": a, "b": b, "ambang": ambang}

    hasil = [(_ke_waktu(x), _ke_waktu(y))
             for x, y in db.execute(_lompatan(db), p).all()]

    most_begin, most_end = db.execute(_SQL_TEPI, p).one()
    most_begin = _ke_waktu(most_begin)
    most_end = _ke_waktu(most_end)

    if most_begin is None:
        # No ping rows at all in this window -> the whole window is unmonitored. Happens for
        # devices paused for a long time or registered after the window started.
        hasil = [(a, b)]
    else:
        if (most_begin - a).total_seconds() > ambang:
            hasil.insert(0, (a, most_begin))
        if (b - most_end).total_seconds() > ambang:
            hasil.append((most_end, b))

    hasil.sort()
    if len(_cache) >= _BATAS_CACHE:
        limit = datetime.now() - timedelta(seconds=_UMUR_CACHE_DETIK)
        for k in [k for k, (w, _) in _cache.items() if w < limit]:
            del _cache[k]
        if len(_cache) >= _BATAS_CACHE:
            _cache.clear()  # everything is still fresh: start from the beginning
    _cache[kunci] = (datetime.now(), hasil)
    return hasil


def detik_tak_terpantau(daftar_jeda, mulai, selesai):
    """Seconds of the (mulai, selesai) range that fall inside pauses.

    Pause ranges are clipped to the requested bounds first, so a long pause that only
    touches the edge of an outage counts just the overlapping part.
    """
    if selesai <= mulai:
        return 0.0
    total = 0.0
    for begin, end in daftar_jeda:
        a = max(begin, mulai)
        b = min(end, selesai)
        if b > a:
            total += (b - a).total_seconds()
    return total


def tak_terpantau_antara(db, device_id, mulai, selesai):
    """One-shot version: find pauses and compute the overlap immediately.

    Used by the poller when writing a transition, where the range is short and the
    result need not be cached.
    """
    if selesai <= mulai:
        return 0.0
    # Allow a small margin at both ends so pauses touching the boundary are included.
    more = timedelta(seconds=1)
    daftar = find_gaps(db, device_id, mulai - more, selesai + more)
    return detik_tak_terpantau(daftar, mulai, selesai)


def lupakan_cache():
    """Clear the cache. Used by tests so one test does not inherit another's results."""
    _cache.clear()

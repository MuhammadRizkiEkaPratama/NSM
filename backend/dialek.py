"""SQL that differs between SQLite and MySQL, collected in one place.

Most of NSM does not care which database is used (SQLAlchemy hides it), but a few
places used SQLite-specific features: `sqlite_master`, `julianday()`, `strftime()`
and `PRAGMA journal_mode`. MySQL has none of these, and eight call sites broke
when the data moved to MySQL, three of them in core paths (availability in
`jeda.py`, chart grouping in `report_service.py`, retention in `pangkas_data.py`).

MySQL raises an error for an unknown function instead of returning NULL. That
matters: a silent NULL from `julianday()` would produce wrong availability numbers
with no visible sign.

The differences live here, not behind `if PAKAI_MYSQL` in eight files, so they can
be read together and tested together by `uji_dialek.py`.
"""
from sqlalchemy import Integer, inspect, text
from sqlalchemy.sql import func

import database

# Why the dialect is decided per connection, not once at import.
#
# An earlier version set `MYSQL = database.PAKAI_MYSQL` as a module constant. But
# the tests create their own SQLite databases (temporary file or in-memory), so a
# global constant made `dialek` emit MySQL SQL to a SQLite connection:
#
#     sqlite3.OperationalError: no such column: MICROSECOND
#
# "The database in use" is not one thing per process. With the local buffer, the
# same process can write to MySQL in one round and to SQLite in the next. So the
# connection actually in use always decides.
#
# Note for anyone adding dialect-aware code: never use `database.PAKAI_MYSQL`
# inside a function that receives a session; use `dialek._mysql(db)`. The
# process-wide setting is valid only for process-level questions ("which database
# is NSM configured for"), not for "where will this statement be sent". (Misusing
# it to choose between `information_schema` and `os.path.getsize` broke tests that
# install a temporary SQLite database.)


def _mysql(db):
    """Does this session/connection point to MySQL?"""
    if db is None:
        return database.PAKAI_MYSQL
    bind = db.get_bind() if hasattr(db, "get_bind") else db
    return bind.dialect.name == "mysql"


def tabel_ada(db, nama):
    """Does this table exist? Works on both engines.

    Uses the SQLAlchemy inspector, which queries the right catalog for each engine,
    so no system table names appear in application code.
    """
    return nama in inspect(db.get_bind()).get_table_names()


def selisih_detik_sql(db, awal, akhir):
    """Raw SQL fragment: (end - start) in seconds, with the fractional part.

    `awal` and `akhir` are column names or parameters, written into the SQL as is.
    NEVER fill them from user input.

    MySQL: TIMESTAMPDIFF with MICROSECOND, divided by a million. Using SECOND
    directly would DROP the fractional seconds, which is what tells a normal poller
    from a stalled one at a 5-second interval.
    """
    if _mysql(db):
        return "TIMESTAMPDIFF(MICROSECOND, %s, %s) / 1000000.0" % (awal, akhir)
    return "(julianday(%s) - julianday(%s)) * 86400.0" % (akhir, awal)


# Time format patterns used by the chart page. A key must produce EXACTLY the same
# text on both engines, because the result is matched against Python's
# `datetime.strftime`; one differing letter and every chart bucket fails to match,
# giving an empty chart with no error.
#
# One easy-to-miss difference: minutes are %i in MySQL, not %M (which means month
# NAME there).
_FORMAT_MYSQL = {
    "%Y-%m-%d %H:%M": "%Y-%m-%d %H:%i",
    "%Y-%m-%d %H:00": "%Y-%m-%d %H:00",
    "%Y-%m-%d": "%Y-%m-%d",
}


def ember_waktu(db, kolom, pola):
    """SQLAlchemy expression that groups time into minute/hour/day buckets.

    `pola` is written Python-style (`%Y-%m-%d %H:%M`) so the Python and SQL sides
    share one source of truth.
    """
    if _mysql(db):
        return func.date_format(kolom, _FORMAT_MYSQL[pola])
    return func.strftime(pola, kolom)


def petak_ke(db, kolom, titik_awal, lebar_detik):
    """Bucket number of a row: distance from `titik_awal` divided by bucket width.

    Used by sparklines, which split a time range into a fixed number of buckets and
    count them IN the database, rather than pulling hundreds of thousands of rows
    into Python.
    """
    if _mysql(db):
        distance = func.timestampdiff(
            text("MICROSECOND"), titik_awal, kolom) / 1000000.0
    else:
        distance = (func.julianday(kolom) - func.julianday(titik_awal)) * 86400.0
    return func.cast(distance / lebar_detik, Integer)


def keterangan_penyimpanan(db):
    """Description line for the Health panel, depending on the engine in use.
    The panel used to show `PRAGMA journal_mode` and warn when it was not WAL; that
    check means nothing on MySQL, where the statement raises an error.
    """
    if _mysql(db):
        version = db.execute(text("SELECT VERSION()")).scalar()
        komit = db.execute(
            text("SELECT @@innodb_flush_log_at_trx_commit")).scalar()
        return {
            "label": "Penyimpanan",
            "nilai": "MySQL %s" % version,
            "ket": ("Ditulis ke server, bukan ke berkas di laptop ini. "
                    "innodb_flush_log_at_trx_commit=%s." % komit),
            "sehat": True,
        }
    mode = db.execute(text("PRAGMA journal_mode")).scalar()
    return {
        "label": "Mode jurnal",
        "nilai": str(mode).upper(),
        "ket": ("WAL membuat pembaca tidak lagi antre menunggu poller "
                "selesai menulis."),
        "sehat": str(mode).lower() == "wal",
    }

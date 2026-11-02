"""NSM database connection: MySQL on the data host, with a local buffer.

Why MySQL: NSM data used to live in `nsm.db`, a single SQLite file on the
monitoring machine, so losing that machine meant losing all monitoring history.
Data now lives in MySQL on the always-on server that also runs LDAP and the
E-Canteen database. `nsm.db` is kept as the original source and a way back.

The problem this creates: a local file is never "unreachable", but a network
database can be, and a monitoring tool needs to keep recording exactly when the
network is in trouble. So the move to MySQL must not happen without a local
buffer; they are one package.

The buffer: `penyangga.db` is a local SQLite file with EXACTLY THE SAME SCHEMA as
MySQL (not another format, not a JSON queue). So:

  - writing code does not need to know where it writes; models and statements
    are the same.
  - moving buffer contents to MySQL is the same operation as moving `nsm.db` to
    MySQL. One copy engine serves both, so the rarely used path (recovery after
    an outage) runs the same code as the path tested every day.

Easy to miss: the device list itself. If MySQL is down, the poller loses not only
somewhere to write but somewhere to READ the devices and services to check.
Without a local copy it does not just stop recording, it stops working. So
`devices` and `services` are copied to the buffer on every successful round,
with the same ids so measurement rows still point to the right device when moved
later.

Going back to SQLite: empty `NSM_DB_HOST` in `.env`. No code change needed. If the
MySQL server is being rebuilt, NSM must still be able to run.

Backup note: for any SQLite file (`nsm.db` and `penyangga.db`), copying with
`shutil.copy` can lose the latest data because WAL keeps recent changes in a
side file. Use SQLite's backup API (`sumber.backup()`), as `backup_nsm.py` does.
"""
import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

# The path is anchored to the folder of THIS file, not to the folder the command
# was typed in.
#
# A relative `"sqlite:///nsm.db"` depends on the process's working directory, not
# on where the code lives. Run the poller from `C:\\Users\\<user>\\NSM` instead of
# `...\\NSM\\backend` and SQLite refuses nothing: `connect()` on a missing file
# CREATES an empty one, and everything runs smoothly on a database with no rows.
#
# That failure is expensive because it shows no error, just "zero rows": pages
# open, the poller loops, nothing turns red. It is indistinguishable from a
# legitimately empty state. A 0-byte `nsm.db` really did sit at the repo root,
# created by a command run from the wrong folder.
#
# `os.path.abspath(__file__)` always points at this file, so the path is the same
# from any working directory.
DIR = os.path.dirname(os.path.abspath(__file__))
JALUR_DB = os.path.join(DIR, "nsm.db")
JALUR_PENYANGGA = os.path.join(DIR, "penyangga.db")


def _env():
    """Read .env without importing config.

    `config.py` imports other modules that eventually import this file; reading it
    here breaks that cycle.
    """
    value = {}
    jalur = os.path.join(DIR, ".env")
    if os.path.exists(jalur):
        with open(jalur, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                value[k.strip()] = v.strip()
    # Environment variables override .env, so one command can run against another
    # database without editing the file.
    for k in ("NSM_DB_HOST", "NSM_DB_PORT", "NSM_DB_NAME",
              "NSM_DB_USER", "NSM_DB_PASS"):
        if os.environ.get(k):
            value[k] = os.environ[k]
    return value


def url_sqlite(jalur):
    # SQLAlchemy URLs use forward slashes, while `os.path.join` on Windows builds with
    # `\`. Swapped so the path is not misparsed.
    return "sqlite:///" + jalur.replace(os.sep, "/")


def _url_mysql(env):
    """MySQL URL, or None if .env gives no host."""
    host = env.get("NSM_DB_HOST", "").strip()
    if not host:
        return None
    from urllib.parse import quote_plus
    return (
        "mysql+pymysql://%s:%s@%s:%s/%s?charset=utf8mb4" % (
            quote_plus(env.get("NSM_DB_USER", "nsm_app")),
            # A random password can contain characters that are special in URLs. Without
            # quote_plus, a password containing `@` cuts the URL in the wrong place and the
            # error points at a host that does not exist.
            quote_plus(env.get("NSM_DB_PASS", "")),
            host,
            env.get("NSM_DB_PORT", "3306"),
            env.get("NSM_DB_NAME", "nsm"),
        )
    )


ENV = _env()
URL_UTAMA = _url_mysql(ENV) or url_sqlite(JALUR_DB)
PAKAI_MYSQL = URL_UTAMA.startswith("mysql")


def buat_engine(url):
    """Single place that creates the engine, so its settings do not diverge."""
    if url.startswith("mysql"):
        return create_engine(
            url,
            # IDLE CONNECTIONS GET CLOSED BY THE SERVER. MySQL closes idle connections after
            # `wait_timeout` (default 8 hours), and a dead pooled connection does not look
            # dead until used, then raises "MySQL server has gone away" on a perfectly valid
            # statement. `pool_pre_ping` tests the connection before use; the cost is one
            # tiny statement, and it removes that whole class of confusing errors.
            pool_pre_ping=True,
            # Recycled well before the server limit, so it never gets there.
            pool_recycle=3600,
            pool_size=5,
            max_overflow=5,
            # Do not hang forever if the data host does not answer. The poller loops every
            # 5 seconds; waiting without limit would stop all monitoring because of one
            # connection.
            connect_args={"connect_timeout": 10},
        )
    return create_engine(url, connect_args={"timeout": 15})


engine = buat_engine(URL_UTAMA)

# Buffer engine. ALWAYS created, even when NSM uses SQLite: the file is not
# created until something writes, so the cost is zero.
engine_penyangga = buat_engine(url_sqlite(JALUR_PENYANGGA))


@event.listens_for(engine, "connect")
@event.listens_for(engine_penyangga, "connect")
def _atur_sqlite(sambungan, _catatan):
    """Runs on every new connection. SQLite only.
    The `hasattr` check below tells the two apart: a pymysql connection must not run
    a PRAGMA, which would make every MySQL connection fail.
    """
    if type(sambungan).__module__.startswith("pymysql"):
        return
    kursor = sambungan.cursor()

    # Problem solved here: NSM runs TWO Python processes that write to the same file,
    # the poller (every 5 seconds) and uvicorn (when a user pauses a device). With the
    # default `delete` journal, a writer locks the WHOLE file until its transaction
    # ends and readers are held too. This was seen in the Audit Log: pausing a device
    # failed with a 500 Internal Server Error, then succeeded in the same second when
    # retried.
    #
    # WAL changes the rule: a writer no longer blocks readers.
    kursor.execute("PRAGMA journal_mode=WAL")

    # Second guard: this PRAGMA is per connection; `timeout` above is only read by
    # Python's sqlite3 library. Matched so all paths wait the same length of time.
    kursor.execute("PRAGMA busy_timeout=15000")

    # NORMAL, not FULL. With WAL, NORMAL is still safe against the application dying
    # suddenly; only a power cut or OS crash is at risk, and even then at most the
    # last few transactions are lost, the file is NOT corrupted. The payoff is large:
    # far fewer forced disk writes, so locks are held much more briefly.
    kursor.execute("PRAGMA synchronous=NORMAL")

    kursor.close()


SessionLocal = sessionmaker(bind=engine)
SessionPenyangga = sessionmaker(bind=engine_penyangga)
Base = declarative_base()


def keterangan():
    """One line to print at process start.

    Exists so "where is NSM writing to" is never a guess. The password is never
    printed.
    """
    if PAKAI_MYSQL:
        return "MySQL %s:%s/%s" % (ENV.get("NSM_DB_HOST"),
                                   ENV.get("NSM_DB_PORT", "3306"),
                                   ENV.get("NSM_DB_NAME", "nsm"))
    return "SQLite %s" % JALUR_DB


# ---------------------------------------------------------------------------
# FACTORY: create a SECOND database without touching the first
#
# The names above (`engine`, `SessionLocal`, `Base`) are module variables imported
# by dozens of files. That will not change; the app has only one database.
#
# The problem is TESTS. A test that needs its own database can only patch those
# module variables and remember to restore them. Many test files patched them and
# several never restored them. As separate scripts that does not matter (the
# process ends and the patch disappears). Inside one process (pytest) a leaked
# patch makes every later test run against an empty in-memory database, and the
# failure is silent: those tests do not blow up, they PASS on a database with
# nothing in it.
#
# `buat_lab()` removes the reason to patch: it returns a SELF-CONTAINED
# engine + session pair, and `lab_sementara()` patches and restores in `finally`.
#
# Note: `create_engine` does NOT open a connection. After `import database` the
# pool holds zero; it connects on first use. The import cost of this module is
# loading SQLAlchemy, not a database connection.
# ---------------------------------------------------------------------------

def create_lab(url=None):
    """Self-contained engine + session factory. Default: in-memory SQLite.

    Tables are NOT created here. The caller decides which schema it needs, and
    `models.Base.metadata.create_all(engine)` is a line better seen in the test
    itself than hidden here.
    """
    mesin = buat_engine(url or "sqlite://")
    return mesin, sessionmaker(bind=mesin)


import contextlib  # noqa: E402


@contextlib.contextmanager
def lab_sementara(url=None, buat_tabel=True):
    """Temporarily point `database.engine`/`SessionLocal` at a separate database.

        with database.lab_sementara() as (mesin, Sesi):
            db = Sesi()
            ...

    Restored in `finally`, so an error midway does not leave this module pointing at
    the test database. That is the only difference from patching by hand, and the
    one that was missed.

    `buat_tabel=True` also creates all tables; turn it off if the test wants to
    inspect an empty database.
    """
    global engine, SessionLocal
    engine_original, session_original = engine, SessionLocal
    mesin, factory = create_lab(url)
    engine, SessionLocal = mesin, factory
    if buat_tabel:
        # Imported inside the function, not at the top of the file: `models` imports `Base`
        # from here, so a module-level import would be circular.
        import models
        models.Base.metadata.create_all(mesin)
    try:
        yield mesin, factory
    finally:
        engine, SessionLocal = engine_original, session_original
        mesin.dispose()

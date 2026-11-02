"""Service monitoring migration: services, service_checks, service_events.

Ping proves the machine is up; these tables prove the services on it are
actually serving. The two can differ, and that gap is the most common real
outage: the server is up but Apache has stopped.

Safe to run repeatedly. Run with the poller and uvicorn STOPPED so the
database is not locked:

    cd C:\\\\Users\\\\<user>\\\\NSM\\\\backend
    venv\\\\Scripts\\\\activate
    python migrate_services.py
"""
import os
import sqlite3

# Path is pinned to this file's folder, not the current working directory.
# With a relative path, running from the wrong folder raises NO error: SQLite
# silently creates a new empty database there. See `database.py`.
DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

TABEL = {
    "services": """
        CREATE TABLE services (
            id             INTEGER PRIMARY KEY,
            device_id      INTEGER REFERENCES devices(id),
            nama           VARCHAR,
            jenis          VARCHAR,
            port           INTEGER,
            path           VARCHAR,
            harap_status   INTEGER,
            harap_teks     VARCHAR,
            timeout_detik  INTEGER DEFAULT 5,
            aktif          INTEGER DEFAULT 1
        )
    """,
    "service_checks": """
        CREATE TABLE service_checks (
            id          INTEGER PRIMARY KEY,
            service_id  INTEGER REFERENCES services(id),
            timestamp   DATETIME,
            ok          BOOLEAN,
            kode        INTEGER,
            waktu_ms    FLOAT,
            kategori    VARCHAR
        )
    """,
    "service_events": """
        CREATE TABLE service_events (
            id              INTEGER PRIMARY KEY,
            service_id      INTEGER REFERENCES services(id),
            device_id       INTEGER REFERENCES devices(id),
            event_type      VARCHAR,
            timestamp       DATETIME,
            duration_sec    FLOAT,
            kategori        VARCHAR,
            detail          TEXT,
            kode            INTEGER,
            bukti           TEXT,
            saran           TEXT,
            diagnosa_mulai  TEXT,
            diagnosa_pulih  TEXT,
            notif_terkirim  DATETIME
        )
    """,
}

INDEX = [
    # "Latest check for service X" and period scans for sparklines.
    ("ix_svc_check_service_ts", "service_checks (service_id, timestamp)"),
    # "Outage history for service X" and "latest incident" across all services.
    ("ix_svc_event_service_ts", "service_events (service_id, timestamp)"),
    ("ix_svc_event_ts", "service_events (timestamp)"),
    # Services belonging to a device.
    ("ix_services_device", "services (device_id)"),
]

conn = sqlite3.connect(DB)
cur = conn.cursor()

for nama, sql in TABEL.items():
    ada = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (nama,)
    ).fetchone()
    if ada:
        print(f"- tabel '{nama}' sudah ada, lewati CREATE")
    else:
        cur.execute(sql)
        print(f"- tabel '{nama}' dibuat")

# Columns added after the table was created by an earlier version.
# ALTER TABLE ADD COLUMN is cheap in SQLite and does not rewrite the data.
TAMBAHAN = {
    "service_events": [
        ("bukti", "TEXT"),
        ("saran", "TEXT"),
        ("diagnosa_mulai", "TEXT"),
        ("diagnosa_pulih", "TEXT"),
        ("notif_terkirim", "DATETIME"),
    ],
    "services": [
        ("harap_teks", "VARCHAR"),
        ("timeout_detik", "INTEGER DEFAULT 5"),
        ("aktif", "INTEGER DEFAULT 1"),
    ],
}

for tabel, kolom in TAMBAHAN.items():
    punya = {r[1] for r in cur.execute(f"PRAGMA table_info({tabel})").fetchall()}
    for nama_kolom, tipe in kolom:
        if nama_kolom in punya:
            continue
        cur.execute(f"ALTER TABLE {tabel} ADD COLUMN {nama_kolom} {tipe}")
        print(f"- kolom '{tabel}.{nama_kolom}' ditambahkan")

for nama, definisi in INDEX:
    cur.execute(f"CREATE INDEX IF NOT EXISTS {nama} ON {definisi}")
    print(f"- index {nama} siap")

conn.commit()

for nama in TABEL:
    print(f"\nStruktur {nama}:")
    for r in cur.execute(f"PRAGMA table_info({nama})").fetchall():
        print("   ", r[1], r[2])

# Existing tables are not touched; printed as proof.
print("\nTabel lama (harus utuh):")
for t in ("devices", "status_logs", "device_events", "bandwidth_samples"):
    try:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} baris")
    except sqlite3.OperationalError:
        print(f"  {t}: belum ada")

conn.close()
print("\nMigrasi selesai.")

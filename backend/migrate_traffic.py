"""Traffic log migration: akses_web, posisi_log, flow_koneksi.

Answers what interface counters CANNOT: who the peer is.
`bandwidth_samples` knows how many bytes crossed an interface, not from where
or to where. These three tables fill that gap.

Safe to run repeatedly. Run with the poller and uvicorn STOPPED:

    cd C:\\\\Users\\\\<user>\\\\NSM\\\\backend
    venv\\\\Scripts\\\\activate
    python migrate_traffic.py
"""
import os
import sqlite3

# Path is pinned to this file's folder, not the current working directory.
# With a relative path, running from the wrong folder raises NO error: SQLite
# silently creates a new empty database there. See `database.py`.
DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

TABEL = {
    "akses_web": """
        CREATE TABLE akses_web (
            id          INTEGER PRIMARY KEY,
            device_id   INTEGER REFERENCES devices(id),
            waktu       DATETIME,
            ip_klien    VARCHAR,
            metode      VARCHAR,
            path        VARCHAR,
            protokol    VARCHAR,
            status      INTEGER,
            byte_kirim  FLOAT,
            byte_terima FLOAT,
            rujukan     VARCHAR,
            user_agent  VARCHAR,
            dari_nsm    INTEGER DEFAULT 0
        )
    """,
    "posisi_log": """
        CREATE TABLE posisi_log (
            id              INTEGER PRIMARY KEY,
            device_id       INTEGER REFERENCES devices(id),
            jalur           VARCHAR,
            posisi          FLOAT DEFAULT 0,
            ukuran_terakhir FLOAT DEFAULT 0,
            diperbarui      DATETIME
        )
    """,
    "flow_koneksi": """
        CREATE TABLE flow_koneksi (
            id          INTEGER PRIMARY KEY,
            device_id   INTEGER REFERENCES devices(id),
            waktu       DATETIME,
            ip_lokal    VARCHAR,
            port_lokal  INTEGER,
            ip_lawan    VARCHAR,
            port_lawan  INTEGER,
            byte_masuk  FLOAT,
            byte_keluar FLOAT,
            keadaan     VARCHAR,
            proses      VARCHAR
        )
    """,
}

INDEX = [
    # "Who downloaded what in this period", the traffic page's main query.
    ("ix_akses_device_waktu", "akses_web (device_id, waktu)"),
    # "Total fetched by one address", for the per-client ranking.
    ("ix_akses_klien", "akses_web (ip_klien, waktu)"),
    ("ix_posisi_device_jalur", "posisi_log (device_id, jalur)"),
    ("ix_flow_device_waktu", "flow_koneksi (device_id, waktu)"),
    ("ix_flow_lawan", "flow_koneksi (ip_lawan, waktu)"),
]

conn = sqlite3.connect(DB, timeout=20)
cur = conn.cursor()
cur.execute("PRAGMA busy_timeout=20000")

for nama, sql in TABEL.items():
    ada = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (nama,)
    ).fetchone()
    if ada:
        print(f"- tabel '{nama}' sudah ada, lewati CREATE")
    else:
        cur.execute(sql)
        print(f"- tabel '{nama}' dibuat")

for nama, definisi in INDEX:
    cur.execute(f"CREATE INDEX IF NOT EXISTS {nama} ON {definisi}")
    print(f"- index {nama} siap")

conn.commit()

for nama in TABEL:
    print(f"\nStruktur {nama}:")
    for r in cur.execute(f"PRAGMA table_info({nama})").fetchall():
        print("   ", r[1], r[2])

print("\nTabel lama (harus utuh):")
for t in ("devices", "status_logs", "device_events", "bandwidth_samples",
          "services", "service_checks", "service_events"):
    try:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} baris")
    except sqlite3.OperationalError:
        print(f"  {t}: belum ada")

conn.close()
print("\nMigrasi selesai.")

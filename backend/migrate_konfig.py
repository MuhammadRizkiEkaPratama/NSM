"""Migration: table `konfig_snapshots`, device configuration history.

The first part of the config-sending feature, and deliberately the READ-ONLY part.

WHY IT COMES BEFORE THE WRITE PATH
----------------------------------
Config backup is the safety net for being able to change configs. Until NSM has
stored a device's configuration, a "send change" button would change something whose
previous state is recorded nowhere. Order: save first, then change.

Its value stands even if the write path is never built: "the router config changed
last night, which exact lines?" has no answer at all in a manual workflow.

Rows stay few because a snapshot is stored only WHEN ITS FINGERPRINT CHANGES, so
row count equals the number of real changes.

Safe to re-run. Run with the poller and uvicorn STOPPED:

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\activate
    python migrate_konfig.py
"""
import os
import sqlite3

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

TABEL = {
    "konfig_snapshots": """
        CREATE TABLE konfig_snapshots (
            id            INTEGER PRIMARY KEY,
            device_id     INTEGER REFERENCES devices(id),
            waktu         DATETIME,
            sidik         VARCHAR,
            teks          VARCHAR,
            baris_tambah  INTEGER,
            baris_hapus   INTEGER
        )
    """,
}

INDEX = [
    ("ix_konfig_device_waktu", "konfig_snapshots (device_id, waktu)"),
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

print("\nStruktur konfig_snapshots:")
for r in cur.execute("PRAGMA table_info(konfig_snapshots)").fetchall():
    print("   ", r[1], r[2])

print("\nTabel lama (harus utuh):")
for t in ("devices", "status_logs", "device_events", "bandwidth_samples",
          "services", "service_checks", "service_events",
          "akses_web", "flow_koneksi", "posisi_log", "nama_alamat"):
    try:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} baris")
    except sqlite3.OperationalError:
        print(f"  {t}: belum ada")

conn.close()
print("\nMigrasi selesai.")

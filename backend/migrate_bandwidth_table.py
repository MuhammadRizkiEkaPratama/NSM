"""Migration: table bandwidth_samples.

Stores traffic per interface. Raw counters are kept too, so the delta (rate) can
still be computed even if the poller stopped for a while.

Safe to re-run. Run with the poller and uvicorn STOPPED so the database is not locked:

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\activate
    python migrate_bandwidth_table.py
"""
import os
import sqlite3

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

conn = sqlite3.connect(DB)
cur = conn.cursor()

ada = cur.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='bandwidth_samples'"
).fetchone()

if ada:
    print("- tabel 'bandwidth_samples' sudah ada, lewati CREATE")
else:
    cur.execute(
        """
        CREATE TABLE bandwidth_samples (
            id          INTEGER PRIMARY KEY,
            device_id   INTEGER REFERENCES devices(id),
            iface       VARCHAR,
            timestamp   DATETIME,
            in_octets   FLOAT,
            out_octets  FLOAT,
            in_bps      FLOAT,
            out_bps     FLOAT,
            source      VARCHAR
        )
        """
    )
    print("- tabel 'bandwidth_samples' dibuat")

cur.execute(
    "CREATE INDEX IF NOT EXISTS ix_bw_device_iface_ts "
    "ON bandwidth_samples (device_id, iface, timestamp)"
)
print("- index ix_bw_device_iface_ts siap")

conn.commit()

print("\nStruktur bandwidth_samples:")
for r in cur.execute("PRAGMA table_info(bandwidth_samples)").fetchall():
    print("   ", r[1], r[2])

jml = cur.execute("SELECT COUNT(*) FROM bandwidth_samples").fetchone()[0]
print(f"\nJumlah baris saat ini: {jml}")

for t in ("devices", "status_logs", "device_events"):
    try:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} baris (utuh)")
    except sqlite3.OperationalError:
        print(f"  {t}: belum ada")

conn.close()
print("\nMigrasi selesai.")

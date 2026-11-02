"""Report migration: `device_events` table + index for `status_logs`.

Why:
- `status_logs` records EVERY poll (5 s). Fine as raw data, but scanning
  millions of rows on each report refresh is slow.
- `device_events` is written only when status CHANGES (UP<->DOWN), so it stays
  small and "when down, for how long, why" can be read instantly.
- `status_logs` is never pruned; only an INDEX is added to keep average
  latency queries fast.

Idempotent. Run with the poller and uvicorn STOPPED so the database is not
locked:

    python migrate_report_tables.py
"""
import os
import sqlite3

# Path is pinned to this file's folder, not the current working directory.
# With a relative path, running from the wrong folder raises NO error: SQLite
# silently creates a new empty database there. See `database.py`.
DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

conn = sqlite3.connect(DB)
cur = conn.cursor()


def tabel_ada(nama):
    row = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (nama,)
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# 1. device_events table
# ---------------------------------------------------------------------------
if tabel_ada("device_events"):
    print("- tabel 'device_events' sudah ada, lewati CREATE")
else:
    cur.execute(
        """
        CREATE TABLE device_events (
            id            INTEGER PRIMARY KEY,
            device_id     INTEGER REFERENCES devices(id),
            event_type    VARCHAR,
            timestamp     DATETIME,
            duration_sec  FLOAT,
            category      VARCHAR,
            detail        VARCHAR,
            last_rtt_ms   FLOAT,
            note          VARCHAR
        )
        """
    )
    print("- tabel 'device_events' dibuat")

# Index: nearly every report query is "events for device X in a time range".
cur.execute(
    "CREATE INDEX IF NOT EXISTS ix_events_device_ts "
    "ON device_events (device_id, timestamp)"
)
print("- index ix_events_device_ts siap")

# ---------------------------------------------------------------------------
# 2. Index for status_logs (all raw data is kept)
# ---------------------------------------------------------------------------
cur.execute(
    "CREATE INDEX IF NOT EXISTS ix_status_device_ts "
    "ON status_logs (device_id, timestamp)"
)
print("- index ix_status_device_ts siap (status_logs tidak dihapus, hanya diindeks)")

conn.commit()

# ---------------------------------------------------------------------------
# 3. Visual check
# ---------------------------------------------------------------------------
print("\nStruktur device_events:")
for r in cur.execute("PRAGMA table_info(device_events)").fetchall():
    print("   ", r[1], r[2])

jml_event = cur.execute("SELECT COUNT(*) FROM device_events").fetchone()[0]
jml_log = cur.execute("SELECT COUNT(*) FROM status_logs").fetchone()[0]
print(f"\nJumlah baris: device_events={jml_event}, status_logs={jml_log} (utuh)")

conn.close()
print("\nMigrasi selesai.")

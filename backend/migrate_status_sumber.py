"""Migration: add column `status_logs.sumber`.

Why this column exists
----------------------
A host can drop every ICMP echo while its TCP ports still answer in a few
milliseconds. Such a host is alive, but NSM used to mark it DOWN, count the
downtime against availability, and report it as unreachable, even though the
poller already ran `cek_port_terbuka()` on ping failure and tagged the event
`ping_blocked`. That knowledge never affected the verdict.

This column lets the verdict change without hiding how it was reached: the
device is marked reachable, and HOW it was proven is stored.

    NULL / "icmp"  ping answered (all older rows fall here)
    "tcp"          no ping reply, a TCP port answered
    "lokal"        read via psutil on this machine itself

Existing rows are NOT touched. The column is nullable and NULL deliberately
means "icmp": backfilling hundreds of thousands of rows just to write an
implied value is risk with no benefit.

Safe to run repeatedly. Run with the poller and uvicorn STOPPED:

    cd C:\\\\Users\\\\<user>\\\\NSM\\\\backend
    venv\\\\Scripts\\\\activate
    python migrate_status_sumber.py
"""
import os
import sqlite3

# Path is pinned to this file's folder, not the current working directory.
# With a relative path, running from the wrong folder raises NO error: SQLite
# silently creates a new empty database there. See `database.py`.
DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

conn = sqlite3.connect(DB, timeout=20)
cur = conn.cursor()
cur.execute("PRAGMA busy_timeout=20000")

kolom = [r[1] for r in cur.execute("PRAGMA table_info(status_logs)").fetchall()]
if "sumber" in kolom:
    print("- kolom 'sumber' sudah ada, lewati ALTER TABLE")
else:
    # ALTER TABLE ADD COLUMN in SQLite does not rewrite the table, so this is
    # instant even with hundreds of thousands of rows in status_logs.
    cur.execute("ALTER TABLE status_logs ADD COLUMN sumber VARCHAR")
    print("- kolom 'sumber' ditambahkan ke status_logs")

conn.commit()

print("\nStruktur status_logs:")
for r in cur.execute("PRAGMA table_info(status_logs)").fetchall():
    print("   ", r[1], r[2])

# Row counts after migration, as proof that no data was lost.
print("\nTabel (harus utuh):")
for t in ("devices", "status_logs", "device_events", "bandwidth_samples",
          "services", "service_checks", "service_events",
          "akses_web", "flow_koneksi", "posisi_log", "nama_alamat"):
    try:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} baris")
    except sqlite3.OperationalError:
        print(f"  {t}: belum ada")

n_null = cur.execute(
    "SELECT COUNT(*) FROM status_logs WHERE sumber IS NULL").fetchone()[0]
print(f"\nBaris lama dengan sumber NULL (artinya 'icmp'): {n_null}")

conn.close()
print("\nMigrasi selesai.")

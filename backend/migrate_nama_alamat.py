"""Migration: table `nama_alamat`, cache of reverse DNS lookups.

WHY THIS TABLE EXISTS
---------------------
The Traffic page shows raw addresses. `91.189.91.99` means nothing until someone
looks it up; it turns out to be `snapstore-content-cache-1.ps6.canonical.com`, and
the 114.63 MB pulled from it is explained at once as package updates, not something
to investigate. The name turns a list of numbers into something readable.

WHY RESULTS ARE STORED, NOT LOOKED UP WHEN THE PAGE OPENS
---------------------------------------------------------
Measured from this machine:

    91.189.91.99      4.698 ms   snapstore-content-cache-1.ps6.canonical.com
    192.168.56.101    9.006 ms   (no PTR)

That is 4.5 to 9 seconds per address (the unit in the table is as measured), and the
slowest are the ones that FAIL. The page refreshes every 30 seconds and can load 25
addresses at once, so looking them up inside the page request would freeze the page
for minutes on every open.

Safe to re-run. Run with the poller and uvicorn STOPPED:

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\activate
    python migrate_nama_alamat.py
"""
import os
import sqlite3

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

TABEL = {
    "nama_alamat": """
        CREATE TABLE nama_alamat (
            ip        VARCHAR PRIMARY KEY,
            nama      VARCHAR,
            ditemukan INTEGER DEFAULT 0,
            diperiksa DATETIME
        )
    """,
}

INDEX = [
    ("ix_nama_diperiksa", "nama_alamat (diperiksa)"),
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
          "services", "service_checks", "service_events",
          "akses_web", "flow_koneksi", "posisi_log"):
    try:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} baris")
    except sqlite3.OperationalError:
        print(f"  {t}: belum ada")

conn.close()
print("\nMigrasi selesai.")

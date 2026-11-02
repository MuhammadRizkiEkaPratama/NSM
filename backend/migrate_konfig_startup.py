"""Migration: add startup-config columns to `konfig_snapshots`.

WHY
---
The gap between `running-config` (in effect now) and `startup-config` (in effect
after a reboot) is one of the costliest events in networking: a change that was made,
tested, and considered done is silently lost when the device loses power because it
was never saved. There is no manual way to notice this except remembering whether
you saved.

    `sidik_startup`   sha256 of the processed startup-config
    `teks_startup`    its content, masked the same way as running
    `belum_disimpan`  number of lines that differ between running and startup
                    0    = saved permanently
                    >0   = there are changes that will be lost on reboot
                    NULL = the platform has no startup-config concept, which is
                           NOT the same as zero

Old rows are untouched. All three columns are nullable, and old snapshots never read
startup-config, so NULL is the honest value for them.

Safe to re-run. Run with the poller and uvicorn STOPPED:

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\activate
    python migrate_konfig_startup.py
"""
import os
import sqlite3

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

KOLOM_BARU = [
    ("sidik_startup", "VARCHAR"),
    ("teks_startup", "VARCHAR"),
    ("belum_disimpan", "INTEGER"),
]

conn = sqlite3.connect(DB, timeout=20)
cur = conn.cursor()
cur.execute("PRAGMA busy_timeout=20000")

ada = cur.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='konfig_snapshots'"
).fetchone()
if not ada:
    print("- tabel 'konfig_snapshots' belum ada. Jalankan migrate_konfig.py lebih dulu.")
    conn.close()
    raise SystemExit(1)

kolom = [r[1] for r in cur.execute("PRAGMA table_info(konfig_snapshots)").fetchall()]
for nama, tipe in KOLOM_BARU:
    if nama in kolom:
        print(f"- kolom '{nama}' sudah ada, lewati ALTER TABLE")
    else:
        # ALTER TABLE ADD COLUMN in SQLite does not rewrite the table.
        cur.execute(f"ALTER TABLE konfig_snapshots ADD COLUMN {nama} {tipe}")
        print(f"- kolom '{nama}' ditambahkan")

conn.commit()

print("\nStruktur konfig_snapshots:")
for r in cur.execute("PRAGMA table_info(konfig_snapshots)").fetchall():
    print("   ", r[1], r[2])

print("\nTabel (harus utuh):")
for t in ("devices", "status_logs", "device_events", "bandwidth_samples",
          "services", "service_checks", "service_events",
          "akses_web", "flow_koneksi", "posisi_log", "nama_alamat",
          "konfig_snapshots"):
    try:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} baris")
    except sqlite3.OperationalError:
        print(f"  {t}: belum ada")

conn.close()
print("\nMigrasi selesai.")

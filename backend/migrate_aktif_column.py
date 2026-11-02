"""Migration: column `aktif` in the devices table.

Pauses monitoring of a device without deleting it, e.g. a laptop that moves between
networks or an office device that is away.

When a device is paused:
  - the poller skips it (no ping, no bandwidth read)
  - it is not counted in overall availability
  - its past incident history is KEPT and stays viewable

All existing devices are set to aktif = 1.

Safe to re-run. Run with the poller and uvicorn STOPPED:

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\activate
    python migrate_aktif_column.py
"""
import os
import sqlite3

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

conn = sqlite3.connect(DB)
cur = conn.cursor()

kolom = {r[1] for r in cur.execute("PRAGMA table_info(devices)").fetchall()}

if "aktif" in kolom:
    print("- kolom 'aktif' sudah ada, lewati")
else:
    # DEFAULT 1 matters: without it existing devices would be NULL and would all be
    # paused as soon as the poller starts.
    cur.execute("ALTER TABLE devices ADD COLUMN aktif INTEGER DEFAULT 1")
    print("- kolom 'aktif' ditambahkan (default 1)")

diperbaiki = cur.execute(
    "UPDATE devices SET aktif = 1 WHERE aktif IS NULL").rowcount
if diperbaiki:
    print(f"- {diperbaiki} device yang nilainya kosong diisi aktif = 1")

conn.commit()

print("\nStatus device sekarang:")
for r in cur.execute(
    "SELECT id, name, ip_address, aktif FROM devices ORDER BY id"
).fetchall():
    print(f"   {r[0]}. {r[1]:20} {r[2]:16} "
          f"{'AKTIF' if r[3] else 'DIJEDA'}")

conn.close()
print("\nMigrasi selesai. Semua device tetap dipantau seperti biasa "
      "sampai kamu menjedanya sendiri lewat dashboard.")

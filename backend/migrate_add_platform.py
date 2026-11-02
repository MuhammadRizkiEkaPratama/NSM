"""Migration: add column `platform` to the existing devices table.

`Base.metadata.create_all()` does not alter existing tables, so new columns must be
added with a manual ALTER TABLE.

Safe to re-run (idempotent): skips the column if it exists. Run with the poller and
uvicorn stopped so the DB is not locked.

    python migrate_add_platform.py
"""
import os
import sqlite3

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

conn = sqlite3.connect(DB)
cur = conn.cursor()

kolom = [row[1] for row in cur.execute("PRAGMA table_info(devices)").fetchall()]
if "platform" in kolom:
    print("- kolom 'platform' sudah ada, lewati ALTER")
else:
    cur.execute("ALTER TABLE devices ADD COLUMN platform VARCHAR")
    print("- kolom 'platform' ditambahkan")

# Fill in data for the Ubuntu VM (id 4); the rest are left empty on purpose.
# Credentials are read from `.env`; if the value is missing the column is skipped
# instead of being filled with an empty password.
_USER = os.environ.get("DEVICE_SSH_USER") or ""
_SANDI = os.environ.get("DEVICE_SSH_PASS") or ""
if _USER and _SANDI:
    cur.execute(
        "UPDATE devices SET platform=?, username=?, password=? WHERE id=?",
        ("linux", _USER, _SANDI, 4),
    )
    print(f"- id 4 diperbarui: platform=linux, username={_USER} ({cur.rowcount} baris)")
else:
    cur.execute("UPDATE devices SET platform=? WHERE id=?", ("linux", 4))
    print(f"- id 4 diperbarui: platform=linux saja ({cur.rowcount} baris). "
          f"DEVICE_SSH_USER/PASS kosong, jadi kredensial TIDAK disentuh.")

conn.commit()

print("\nIsi tabel devices sekarang:")
for r in cur.execute("SELECT id, name, device_type, platform, username FROM devices").fetchall():
    print("  ", r)

conn.close()

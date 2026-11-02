"""Migration: SNMP v3 credential columns on the devices table.

Adds 6 nullable columns. Devices with empty SNMP columns are still read over
SSH as before, so nothing breaks.

Safe to run repeatedly. Run with the poller and uvicorn STOPPED:

    cd C:\\\\Users\\\\<user>\\\\NSM\\\\backend
    venv\\\\Scripts\\\\activate
    python migrate_snmp_columns.py
"""
import os
import sqlite3

# Path is pinned to this file's folder, not the current working directory.
# With a relative path, running from the wrong folder raises NO error: SQLite
# silently creates a new empty database there. See `database.py`.
DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

KOLOM = [
    ("snmp_user", "VARCHAR"),
    ("snmp_auth_pass", "VARCHAR"),
    ("snmp_priv_pass", "VARCHAR"),
    ("snmp_auth_proto", "VARCHAR"),
    ("snmp_priv_proto", "VARCHAR"),
    ("snmp_port", "INTEGER"),
]

conn = sqlite3.connect(DB)
cur = conn.cursor()

sudah_ada = {r[1] for r in cur.execute("PRAGMA table_info(devices)").fetchall()}

for nama, tipe in KOLOM:
    if nama in sudah_ada:
        print(f"- kolom '{nama}' sudah ada, lewati")
    else:
        cur.execute(f"ALTER TABLE devices ADD COLUMN {nama} {tipe}")
        print(f"- kolom '{nama}' ditambahkan")

conn.commit()

print("\nStruktur tabel devices sekarang:")
for r in cur.execute("PRAGMA table_info(devices)").fetchall():
    print("   ", r[1], r[2])

print("\nIsi device (kredensial tidak ditampilkan):")
for r in cur.execute(
    "SELECT id, name, ip_address, platform, snmp_user FROM devices ORDER BY id"
).fetchall():
    snmp = r[4] if r[4] else "(belum diatur)"
    print(f"   {r[0]}. {r[1]:18} {r[2]:16} platform={str(r[3]):12} snmp_user={snmp}")

conn.close()
print("\nMigrasi selesai. Data lama utuh; device tanpa SNMP tetap dibaca lewat SSH.")

"""Device identity migration: table `identitas_perangkat` plus two columns.

WHY
---
NSM recognizes devices by IP address alone, and FOUR of the six devices in this lab
use default addresses that would match on someone else's network:
`192.168.1.1`, `192.168.56.101`, `192.168.56.103`, `192.168.56.1`.

While NSM only reads, hitting the wrong target yields wrong data. Once it can send
config, it changes the configuration of someone else's device, and `reload in 5`
does not help there: it protects against a wrong command, not a wrong device.
See docs/design/TRAFFIC-IDENTITY-FW.md.

ONLY ADDS one table, two columns, and one index. No existing row is changed or
removed. Safe to re-run. Run with the poller and uvicorn STOPPED:

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\activate
    python migrate_identitas.py
"""
import os
import sqlite3

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

TABEL = {
    "identitas_perangkat": """
        CREATE TABLE identitas_perangkat (
            id        INTEGER PRIMARY KEY,
            device_id INTEGER REFERENCES devices(id),
            jenis     VARCHAR,
            nilai     VARCHAR,
            pertama   DATETIME,
            terakhir  DATETIME,
            sumber    VARCHAR
        )
    """,
}

# New columns on `devices`. Both are nullable, and NULL means exactly today's behavior:
# never checked, write path not yet allowed.
KOLOM = [
    ("devices", "identitas_vonis", "VARCHAR"),
    ("devices", "identitas_diperiksa", "DATETIME"),
]

INDEX = [
    # NOT unique on (device_id, jenis), deliberately. One kind may hold several values
    # over time: a changed hostname leaves its old row, because overwriting would erase
    # the only evidence that a difference ever existed.
    ("ux_identitas_nilai", "identitas_perangkat (device_id, jenis, nilai)", True),
    ("ix_identitas_device", "identitas_perangkat (device_id)", False),
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

for tabel, kolom, tipe in KOLOM:
    punya = [r[1] for r in cur.execute(f"PRAGMA table_info({tabel})").fetchall()]
    if kolom in punya:
        print(f"- kolom {tabel}.{kolom} sudah ada")
    else:
        cur.execute(f"ALTER TABLE {tabel} ADD COLUMN {kolom} {tipe}")
        print(f"- kolom {tabel}.{kolom} ditambahkan")

for nama, definisi, unik in INDEX:
    kata = "UNIQUE INDEX" if unik else "INDEX"
    cur.execute(f"CREATE {kata} IF NOT EXISTS {nama} ON {definisi}")
    print(f"- {'index unik' if unik else 'index'} {nama} siap")

conn.commit()

print("\nStruktur identitas_perangkat:")
for r in cur.execute("PRAGMA table_info(identitas_perangkat)").fetchall():
    print("   ", r[1], r[2])

print("\nTabel lama (harus utuh):")
for t in ("devices", "status_logs", "device_events", "bandwidth_samples",
          "services", "service_checks", "service_events", "akses_web",
          "flow_koneksi", "posisi_log", "nama_alamat", "konfig_snapshots",
          "status_rollup_jam", "konfig_temuan"):
    try:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} baris")
    except sqlite3.OperationalError:
        print(f"  {t}: belum ada")

conn.close()
print("\nMigrasi selesai.")
print("Kumpulkan hostname dari potret yang sudah ada:")
print("    python kumpul_identitas.py --jalankan")

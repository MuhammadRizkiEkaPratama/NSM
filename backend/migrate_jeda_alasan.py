"""Migration: pausing a device records the REASON and WHEN.

WHY
---
Pausing a device used to write only `devices.aktif = 0`: no reason, no time, no who.
In the data, a legitimate pause could not be told apart from a forgotten one. A
device that was paused on purpose (its owner was away) could be misread as
"paused for 8.5 days and nobody asked", which is exactly the intended use of the
button. The failure pattern is a tool stating something untrue because the truth was
never recorded.

WHY THE REASON IS NOT BACKFILLED
--------------------------------
Existing pauses get no guessed reason. `jeda_alasan` stays NULL and the page shows
it as is ("alasan tidak tercatat"). An invented reason would make a record nobody
ever wrote look like one somebody did, the hardest kind of falsehood to find later.

ONLY ADDS three columns. No row is changed or removed. Safe to re-run. Run with the
poller and uvicorn STOPPED:

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\activate
    python migrate_jeda_alasan.py
"""
import os
import sqlite3

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

KOLOM = [
    ("devices", "jeda_alasan", "VARCHAR"),
    ("devices", "jeda_sejak", "DATETIME"),
    ("devices", "jeda_oleh", "VARCHAR"),
]

conn = sqlite3.connect(DB, timeout=20)
cur = conn.cursor()
cur.execute("PRAGMA busy_timeout=20000")

for tabel, kolom, tipe in KOLOM:
    punya = [r[1] for r in cur.execute(f"PRAGMA table_info({tabel})").fetchall()]
    if kolom in punya:
        print(f"- kolom {tabel}.{kolom} sudah ada")
    else:
        cur.execute(f"ALTER TABLE {tabel} ADD COLUMN {kolom} {tipe}")
        print(f"- kolom {tabel}.{kolom} ditambahkan")

conn.commit()

print("\nPerangkat yang sedang dijeda:")
for r in cur.execute(
        "SELECT name, jeda_alasan, jeda_sejak FROM devices WHERE aktif = 0"):
    print(f"  {r[0]}: alasan={r[1] or '(tidak tercatat)'} sejak={r[2] or '-'}")
print("\n  Jeda yang sudah ada SENGAJA tidak diberi alasan tebakan.")
print("  Halaman akan menuliskannya 'alasan tidak tercatat', dan itu jujur.")

print("\nTabel lama (harus utuh):")
for t in ("devices", "status_logs", "device_events", "konfig_snapshots",
          "konfig_temuan", "identitas_perangkat", "status_rollup_jam"):
    try:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} baris")
    except sqlite3.OperationalError:
        print(f"  {t}: belum ada")

conn.close()
print("\nMigrasi selesai.")

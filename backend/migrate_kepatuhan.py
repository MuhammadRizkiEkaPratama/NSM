"""Migration: table `konfig_temuan`, compliance assessment results per snapshot.

WHY THIS TABLE EXISTS
---------------------
NSM stores device configurations but never READ them. Config backup answers "what
changed?"; this table holds the answer to a different and equally important
question: "is what is there now safe?". See docs/design/CONFIG-COMPLIANCE.md.

WHY RESULTS ARE STORED, NOT RECOMPUTED ON EACH PAGE VIEW
--------------------------------------------------------
Recomputing is cheaper (the assessment just reads text, in milliseconds), but it can
only answer about TODAY. What people actually ask the compliance page is "when did
this hole appear?" and "is it getting better?", which need history. A finding that
was fixed and then came back also never shows as a pattern without one row per
snapshot.

WHY `baris_bukti` IS STORED
---------------------------
A finding without its line forces the reader to open the snapshot and search for
it, and findings that are costly to check stop being checked. The line is already
masked by `konfig.samarkan()` before the snapshot is stored, so keeping it here
adds no secret to the database.

ONLY ADDS a table and indexes. Safe to re-run. Run with the poller and uvicorn
STOPPED:

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\activate
    python migrate_kepatuhan.py
"""
import os
import sqlite3

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

TABEL = {
    "konfig_temuan": """
        CREATE TABLE konfig_temuan (
            id           INTEGER PRIMARY KEY,
            snapshot_id  INTEGER REFERENCES konfig_snapshots(id),
            device_id    INTEGER REFERENCES devices(id),
            aturan_id    VARCHAR,
            hasil        VARCHAR,
            keparahan    VARCHAR,
            baris_bukti  VARCHAR,
            nomor_baris  INTEGER,
            dinilai      DATETIME
        )
    """,
}

INDEX = [
    # UNIQUE: one rule may have only one result per snapshot. Without this guard,
    # re-assessing would duplicate rows and every finding count would multiply silently.
    ("ux_temuan_snapshot_aturan", "konfig_temuan (snapshot_id, aturan_id)", True),
    ("ix_temuan_device", "konfig_temuan (device_id, dinilai)", False),
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

for nama, definisi, unik in INDEX:
    kata = "UNIQUE INDEX" if unik else "INDEX"
    cur.execute(f"CREATE {kata} IF NOT EXISTS {nama} ON {definisi}")
    print(f"- {'index unik' if unik else 'index'} {nama} siap")

conn.commit()

print("\nStruktur konfig_temuan:")
for r in cur.execute("PRAGMA table_info(konfig_temuan)").fetchall():
    print("   ", r[1], r[2])

print("\nTabel lama (harus utuh):")
for t in ("devices", "status_logs", "device_events", "bandwidth_samples",
          "services", "service_checks", "service_events",
          "akses_web", "flow_koneksi", "posisi_log", "nama_alamat",
          "konfig_snapshots", "status_rollup_jam"):
    try:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} baris")
    except sqlite3.OperationalError:
        print(f"  {t}: belum ada")

conn.close()
print("\nMigrasi selesai.")
print("Nilai potret yang sudah ada dengan: python nilai_kepatuhan.py --jalankan")

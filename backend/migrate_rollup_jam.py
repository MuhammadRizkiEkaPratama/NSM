"""Migration for `status_rollup_jam`: hourly history that survives pruning.

Why this table exists
---------------------
`status_logs` grows about 8 MB/day and `pangkas_data.py` drops rows older
than 35 days. A tool meant to answer "how often does this device fail, and is
it improving" cannot afford to lose that history.

One hour holds about 720 raw rows (5 s polls). One row here replaces all 720,
so a year of history for six devices is only about 52,000 rows, small enough
to keep forever.

Why SUM and COUNT, not average
------------------------------
An average of averages is WRONG when hours have different sample counts: an
hour with 720 samples and one with 12 would get equal weight. Details in
`models.StatusRollupJam`.

Only ADDS a table and index; no row in any other table is changed or removed.
Safe to run repeatedly.

Run with the poller and uvicorn STOPPED:

    cd C:\\\\Users\\\\<user>\\\\NSM\\\\backend
    venv\\\\Scripts\\\\activate
    python migrate_rollup_jam.py
"""
import os
import sqlite3

# Path is pinned to this file's folder, not the current working directory.
# With a relative path, running from the wrong folder raises NO error: SQLite
# silently creates a new empty database there. See `database.py`.
DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

TABEL = {
    "status_rollup_jam": """
        CREATE TABLE status_rollup_jam (
            id             INTEGER PRIMARY KEY,
            device_id      INTEGER REFERENCES devices(id),
            jam            DATETIME,
            sampel         INTEGER,
            sampel_naik    INTEGER,
            latency_jumlah FLOAT,
            latency_sampel INTEGER,
            latency_min    FLOAT,
            latency_maks   FLOAT,
            dihitung       DATETIME
        )
    """,
}

INDEX = [
    # UNIQUE for correctness, not just speed: one row per device per hour.
    # Without it, rebuilding the rollup would duplicate rows and silently double
    # every number derived from them.
    ("ux_rollup_device_jam", "status_rollup_jam (device_id, jam)", True),
    # Long-range report query: "all hours between date A and B for this device".
    ("ix_rollup_jam", "status_rollup_jam (jam)", False),
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

print("\nStruktur status_rollup_jam:")
for r in cur.execute("PRAGMA table_info(status_rollup_jam)").fetchall():
    print("   ", r[1], r[2])

# Row counts after migration, as proof that no data was silently lost.
print("\nTabel lama (harus utuh):")
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
print("Ringkasan belum diisi. Isi dengan: python bangun_rollup.py --jalankan")

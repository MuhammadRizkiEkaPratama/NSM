"""Add tables `firewall_snapshot` and `firewall_aturan`.

Safe to re-run.

    python migrate_firewall.py
"""
import os
import sqlite3

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

TABEL = {
    "firewall_snapshot": """
        CREATE TABLE firewall_snapshot (
            id               INTEGER PRIMARY KEY,
            device_id        INTEGER REFERENCES devices(id),
            waktu            DATETIME,
            sidik            VARCHAR,
            aktif            INTEGER,
            kebijakan_masuk  VARCHAR,
            kebijakan_keluar VARCHAR,
            kebijakan_rute   VARCHAR,
            logging          VARCHAR,
            jumlah_aturan    INTEGER DEFAULT 0,
            teks             TEXT
        )
    """,
    "firewall_aturan": """
        CREATE TABLE firewall_aturan (
            id          INTEGER PRIMARY KEY,
            snapshot_id INTEGER REFERENCES firewall_snapshot(id),
            device_id   INTEGER REFERENCES devices(id),
            nomor       INTEGER,
            ke          VARCHAR,
            aksi        VARCHAR,
            arah        VARCHAR,
            dari        VARCHAR,
            komentar    VARCHAR
        )
    """,
}

INDEKS = [
    ("idx_fw_snap_device", "firewall_snapshot(device_id, waktu)"),
    ("idx_fw_aturan_snap", "firewall_aturan(snapshot_id)"),
]


def main():
    if not os.path.exists(DB):
        print("BERHENTI: %s tidak ada." % DB)
        raise SystemExit(1)

    db = sqlite3.connect(DB)
    ada = set(r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"))
    for nama, sql in TABEL.items():
        if nama in ada:
            print("  lewat  tabel %s sudah ada" % nama)
        else:
            db.execute(sql)
            print("  BUAT   tabel %s" % nama)
    for nama, target in INDEKS:
        db.execute("CREATE INDEX IF NOT EXISTS %s ON %s" % (nama, target))
    print("  indeks siap (%d)" % len(INDEKS))
    db.commit()
    db.close()
    print("\nSelesai.")


if __name__ == "__main__":
    main()

"""Add table `firewall_perubahan`: history of firewall changes made through NSM.

Safe to re-run.

    python migrate_firewall_perubahan.py
"""
import os
import sqlite3

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

SQL = """
CREATE TABLE firewall_perubahan (
    id         INTEGER PRIMARY KEY,
    device_id  INTEGER REFERENCES devices(id),
    waktu      DATETIME,
    aksi       VARCHAR,
    ip_sasaran VARCHAR,
    menit      INTEGER,
    alasan     VARCHAR,
    oleh       VARCHAR,
    hasil      VARCHAR,
    bukti      TEXT
)
"""


def main():
    if not os.path.exists(DB):
        print("BERHENTI: %s tidak ada." % DB)
        raise SystemExit(1)

    db = sqlite3.connect(DB)
    ada = set(r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"))
    if "firewall_perubahan" in ada:
        print("  lewat  tabel firewall_perubahan sudah ada")
    else:
        db.execute(SQL)
        print("  BUAT   tabel firewall_perubahan")
    db.execute("CREATE INDEX IF NOT EXISTS idx_fwubah_waktu "
               "ON firewall_perubahan(waktu)")
    print("  indeks siap")
    db.commit()
    db.close()
    print("\nSelesai.")


if __name__ == "__main__":
    main()

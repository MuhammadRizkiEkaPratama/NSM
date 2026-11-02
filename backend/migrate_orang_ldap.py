"""Add table `orang_ldap`: copy of names and titles from the directory.

Safe to re-run.

    python migrate_orang_ldap.py
"""
import os
import sqlite3

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

SQL = """
CREATE TABLE orang_ldap (
    uid        VARCHAR PRIMARY KEY,
    nama       VARCHAR,
    jabatan    VARCHAR,
    email      VARCHAR,
    grup       VARCHAR,
    diperbarui DATETIME
)
"""


def main():
    if not os.path.exists(DB):
        print("BERHENTI: %s tidak ada." % DB)
        raise SystemExit(1)

    db = sqlite3.connect(DB)
    ada = set(r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"))
    if "orang_ldap" in ada:
        print("  lewat  tabel orang_ldap sudah ada")
    else:
        db.execute(SQL)
        print("  BUAT   tabel orang_ldap")
    db.commit()
    db.close()
    print("\nSelesai.")


if __name__ == "__main__":
    main()

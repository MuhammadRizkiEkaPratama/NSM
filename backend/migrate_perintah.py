"""Migration: create table `perintah_pengguna` (command history from auditd).

Only adds one new table. Uses the active `database.engine`, like
`migrate_ban.py` and `migrate_smb_audit.py`, so it works on MySQL (primary
lab instance) and SQLite.

Run with the poller and uvicorn STOPPED:

    cd C:\\\\Users\\\\<user>\\\\NSM\\\\backend
    venv\\\\Scripts\\\\python.exe migrate_perintah.py
"""
import sys

import database
from models import PerintahPengguna

INDEKS = [
    ("idx_perintah_waktu", "perintah_pengguna(waktu)"),
    ("idx_perintah_pengguna", "perintah_pengguna(pengguna, waktu)"),
]


def main():
    table = PerintahPengguna.__table__
    exists = database.engine.dialect.has_table(database.engine.connect(), table.name)
    if exists:
        print("Tabel '%s' sudah ada — tidak ada yang dikerjakan." % table.name)
        return
    table.create(database.engine, checkfirst=True)
    print("Tabel '%s' dibuat di %s." % (table.name, database.engine.url))

    with database.engine.begin() as conn:
        from sqlalchemy import text
        for nama, target in INDEKS:
            try:
                conn.execute(text("CREATE INDEX %s ON %s" % (nama, target)))
                print("  INDEKS %s dibuat" % nama)
            except Exception as e:
                if "exist" in str(e).lower() or "duplicate" in str(e).lower():
                    print("  lewat  indeks %s sudah ada" % nama)
                else:
                    raise


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("GAGAL: %s" % e)
        sys.exit(1)

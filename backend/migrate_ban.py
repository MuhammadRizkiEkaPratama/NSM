"""Migration: create table `ban_aktif` (auto-ban).

ONLY ADDS one table; no existing row is changed. Safe to re-run
(checkfirst=True). Unlike older migrations that target `nsm.db` (SQLite), this uses
the active `database.engine`, so it works for MySQL (the current database) AND SQLite.

Run with the poller and uvicorn STOPPED:

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\python.exe migrate_ban.py
"""
import sys

import database
from models import BanAktif


def main():
    table = BanAktif.__table__
    exists = database.engine.dialect.has_table(
        database.engine.connect(), table.name)
    if exists:
        print("Tabel '%s' sudah ada — tidak ada yang dikerjakan." % table.name)
        return
    table.create(database.engine, checkfirst=True)
    print("Tabel '%s' dibuat di %s." % (table.name, database.engine.url))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("GAGAL: %s" % e)
        sys.exit(1)

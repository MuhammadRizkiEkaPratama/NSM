r"""Add table `syslog_pesan` (Package A).

Only ADDS one new table; no existing table is touched. Same pattern as
`migrate_sot.py`: uses `database.Base.metadata` (loaded from `models.py`)
with `create(checkfirst=True)`, so it works on MySQL and SQLite and is safe
to run repeatedly.

Run with the poller and uvicorn STOPPED:
    venv\Scripts\python.exe migrate_syslog.py
"""
import sys

import database
import models


def main():
    mesin = database.engine
    table = models.SyslogPesan.__table__
    ada = table.exists(mesin) if hasattr(table, "exists") else None
    table.create(mesin, checkfirst=True)
    from sqlalchemy import inspect
    column = [c["name"] for c in inspect(mesin).get_columns("syslog_pesan")]
    print("tabel syslog_pesan siap (%s kolom): %s"
          % (len(column), ", ".join(column)))
    if ada is False:
        print("(baru dibuat)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

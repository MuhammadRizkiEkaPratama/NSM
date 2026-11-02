r"""Add tables `insiden` and `insiden_gejala`.

ONLY ADDS two new tables; no existing table is touched. Same pattern as
`migrate_syslog.py`.

Run with the poller and uvicorn STOPPED:
    venv\\Scripts\\python.exe migrate_insiden.py
"""
import sys

import database
import models


def main():
    mesin = database.engine
    from sqlalchemy import inspect
    for t in (models.Insiden.__table__, models.InsidenGejala.__table__):
        t.create(mesin, checkfirst=True)
    ins = inspect(mesin)
    for nama in ("insiden", "insiden_gejala"):
        column = [c["name"] for c in ins.get_columns(nama)]
        print("  %-16s siap (%d kolom)" % (nama, len(column)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

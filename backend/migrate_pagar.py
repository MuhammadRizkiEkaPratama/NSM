"""Create table `pagar_tindakan` (automation gate actions).

ONLY ADDS one new table; no existing table is touched. Same pattern as
`migrate_sot.py`, including its fix: uses `sqlalchemy.inspect()`, NOT a bare
`database.engine.connect()`, which leaves a dangling connection holding a metadata
lock that freezes the next `CREATE TABLE`.

Run with the poller and uvicorn STOPPED:

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\python.exe migrate_pagar.py
"""
import sys

from sqlalchemy import inspect

import database
import models  # noqa: F401 -- registrasi kelas ke Base.metadata

TABEL = "pagar_tindakan"


def main():
    insp = inspect(database.engine)
    md = database.Base.metadata
    if TABEL not in md.tables:
        print("BERHENTI: '%s' tidak terdaftar di models.py." % TABEL)
        raise SystemExit(1)

    already_exists = insp.has_table(TABEL)
    md.tables[TABEL].create(database.engine, checkfirst=True)
    print(("  lewat  tabel %s sudah ada" if already_exists
          else "  BUAT   tabel %s") % TABEL)

    # Explicit `str(...)` on purpose, not a style slip: `sqlalchemy.engine.URL` is a
    # NamedTuple, so `"%s" % engine.url` without wrapping it in a tuple is unpacked by
    # Python into many substitution arguments and raises "not all arguments converted
    # during string formatting".
    print("\nSelesai di %s." % str(database.engine.url))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print("GAGAL: %s" % e)
        sys.exit(1)

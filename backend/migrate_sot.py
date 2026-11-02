"""Create the five Source of Truth tables.

    intent_nilai       intent value per (device, key) -- see sot/katalog.py
    intent_interface   intended interfaces per device
    intent_vlan        intended VLANs per device
    intent_rute        intended static routes per device
    intent_riwayat     audit trail of all changes above

Only ADDS new tables; no existing table is touched. Same pattern as
`migrate_ketergantungan.py`: uses `database.Base.metadata` (already loaded
from `models.py`) with `create(checkfirst=True)` per table, so it works on
MySQL and SQLite and is safe to run repeatedly.

Run with the poller and uvicorn STOPPED:

    cd C:\\\\Users\\\\<user>\\\\NSM\\\\backend
    venv\\\\Scripts\\\\python.exe migrate_sot.py
"""
import sys

from sqlalchemy import inspect

import database
import models  # noqa: F401 -- registrasi kelas ke Base.metadata

TABEL = [
    "intent_nilai",
    "intent_interface",
    "intent_vlan",
    "intent_rute",
    "intent_riwayat",
]


def main():
    # Use `inspect(database.engine)`, NOT a bare `database.engine.connect()`:
    # an unclosed connection leaves a dangling transaction holding a METADATA
    # LOCK, and every later `CREATE TABLE` (even for an unrelated table) waits
    # on it forever ("Waiting for table metadata lock" in `SHOW PROCESSLIST`).
    # `inspect()` manages its own connection lifecycle, like every other
    # `migrate_*.py`.
    insp = inspect(database.engine)
    md = database.Base.metadata
    created = 0
    for nama in TABEL:
        if nama not in md.tables:
            print("BERHENTI: '%s' tidak terdaftar di models.py." % nama)
            raise SystemExit(1)
        already_exists = insp.has_table(nama)
        md.tables[nama].create(database.engine, checkfirst=True)
        print(("  lewat  tabel %s sudah ada" if already_exists
              else "  BUAT   tabel %s") % nama)
        if not already_exists:
            created += 1
            insp = inspect(database.engine)  # inspector cache is stale after DDL

    print("\nSelesai. %d tabel baru dibuat di %s." % (created, database.engine.url))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print("GAGAL: %s" % e)
        sys.exit(1)

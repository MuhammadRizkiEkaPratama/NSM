"""Widen `intent_riwayat.kunci` from 30 to 150 characters.

WHY
---
Saving a ROUTE to the Source of Truth failed immediately:

    DataError (1406, "Data too long for column 'kunci' at row 1")
    kunci: "('0.0.0.0', '0.0.0.0', '10.10.10.2')"

For the 'rute' category, `kunci` is not a short name but the combination of
destination/mask/next_hop; the example above is already 36 characters, past
`KODE = String(30)`. Anyone saving a route through the SoT page hits this, and it
fails mid-transaction: the value and interface are stored, the route is not, and the
history stays empty.

Only WIDENS one column. No data is lost: enlarging a varchar in MySQL does not
truncate existing content.

Run with the poller and uvicorn STOPPED:
    venv\\Scripts\\python.exe migrate_lebarkan_kunci_riwayat.py
"""
import sys

import database
from sqlalchemy import text

LEBAR_BARU = 150


def main():
    db = database.SessionLocal()
    try:
        dialek = db.bind.dialect.name if db.bind is not None else ""
        if dialek != "mysql":
            print("Dialek '%s' -- SQLite tidak menegakkan panjang VARCHAR, "
                  "jadi tidak ada yang perlu diubah." % dialek)
            return 0

        line = db.execute(text(
            "select column_type from information_schema.columns "
            "where table_schema = database() and table_name = 'intent_riwayat' "
            "and column_name = 'kunci'")).fetchone()
        if line is None:
            print("Tabel/kolom tidak ditemukan -- tidak ada yang diubah.")
            return 0
        print("sebelum : intent_riwayat.kunci = %s" % line[0])
        if "(%d)" % LEBAR_BARU in (line[0] or ""):
            print("sudah selebar %d -- tidak ada yang diubah." % LEBAR_BARU)
            return 0

        db.execute(text("alter table intent_riwayat "
                        "modify column kunci varchar(%d) null" % LEBAR_BARU))
        db.commit()

        line = db.execute(text(
            "select column_type from information_schema.columns "
            "where table_schema = database() and table_name = 'intent_riwayat' "
            "and column_name = 'kunci'")).fetchone()
        print("sesudah : intent_riwayat.kunci = %s" % line[0])
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

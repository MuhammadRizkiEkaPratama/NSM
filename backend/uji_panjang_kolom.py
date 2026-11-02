"""Does EXISTING data fit the new column lengths?

Run before the migration: SQLite never checks text length, but MySQL in strict
mode (the default since 5.7) rejects oversized rows ("Data too long for column
'path' at row 1"). Finding out midway through moving 727,000 rows would leave
half-filled tables, and the longest values are the most likely to matter (long
URLs, deep file paths, odd user agents). Length is measured in CHARACTERS, like
MySQL VARCHAR, not bytes.

Changes nothing.
"""
import io
import os
import sqlite3
import sys

from sqlalchemy import String, Text, inspect

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

import database  # noqa: E402
import models  # noqa: E402  (mendaftarkan tabel ke metadata)


def batas_kolom():
    """{table_name: {column_name: limit}}, only length-limited text columns.

    `Text` columns are deliberately excluded: they are unbounded, and an invented
    limit would make the report lie.
    """
    hasil = {}
    for nama, table in database.Base.metadata.tables.items():
        column = {}
        for k in table.columns:
            if isinstance(k.type, Text):
                continue
            if isinstance(k.type, String) and k.type.length:
                column[k.name] = k.type.length
        if column:
            hasil[nama] = column
    return hasil


def main():
    # Follows wherever the data lives rather than a specific file: this goes through
    # the same engine NSM uses, so it measures the data actually in use.
    from sqlalchemy import text as _text

    engine = database.engine
    with engine.connect() as k:
        ada = set(inspect(engine).get_table_names())

        print("=" * 74)
        print("Panjang data nyata vs batas kolom")
        print("  sumber: %s" % database.keterangan())
        print("=" * 74)
        return _periksa(k, ada, _text)


def _periksa(k, ada, _text):

    more = []
    checked = 0
    for table, column in sorted(batas_kolom().items()):
        if table not in ada:
            continue
        # A database column may lag behind the model if a migration has not run. Missing
        # columns are skipped, not treated as empty: "column missing" and "column empty"
        # are different states.
        has = {c["name"] for c in inspect(k.engine).get_columns(table)}
        for nama, limit in sorted(column.items()):
            if nama not in has:
                continue
            checked += 1
            # `length()` exists in both SQLite and MySQL and counts CHARACTERS, the unit
            # VARCHAR uses. `char_length()` is more explicit but absent in SQLite.
            line = k.execute(_text(
                'select max(length(`%s`)), count(*) from `%s` '
                'where `%s` is not null' % (nama, table, nama)
                if k.dialect.name == "mysql" else
                'select max(length("%s")), count(*) from "%s" '
                'where "%s" is not null' % (nama, table, nama))).one()
            maks, content = line[0] or 0, line[1] or 0
            if maks > limit:
                kut = "`" if k.dialect.name == "mysql" else '"'
                n = k.execute(_text(
                    'select count(*) from {0}{2}{0} where length({0}{1}{0}) > {3}'
                    .format(kut, nama, table, limit))).scalar()
                example = k.execute(_text(
                    'select {0}{1}{0} from {0}{2}{0} where length({0}{1}{0}) > {3} '
                    'limit 1'.format(kut, nama, table, limit))).scalar()
                more.append((table, nama, limit, maks, n, example))
            elif maks > limit * 0.8 and content:
                print("  DEKAT  %-22s %-16s %4d dari %4d"
                      % (table, nama, maks, limit))

    print()
    if not more:
        print("%d kolom diperiksa. Tidak ada yang melebihi batas." % checked)
        print("Data yang ada muat seluruhnya di MySQL.")
        return 0

    print("MELEBIHI BATAS — pemindahan akan ditolak MySQL:")
    for table, nama, limit, maks, n, example in more:
        print()
        print("  %s.%s" % (table, nama))
        print("    batas %d, terpanjang %d, %d baris kelebihan" % (limit, maks, n))
        print("    contoh: %s..." % str(example)[:70])
    print()
    print("Perbesar ukurannya di models.py, JANGAN memotong datanya.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

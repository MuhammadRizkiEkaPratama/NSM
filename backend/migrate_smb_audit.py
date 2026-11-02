"""SMB file server migration: add 4 columns to `transfer_berkas`.

Only ADDS columns; no existing row or column is changed. All columns are
NULLABLE, so existing SFTP rows stay valid, and readers treat
`sumber IS NULL` as "SFTP" (the only source before SMB was added).

Uses the active `database.engine`, so it works on MySQL (primary lab
instance) AND SQLite, same pattern as `migrate_ban.py`, unlike
`migrate_sftp.py` which targets nsm.db directly.

Safe to run repeatedly: existing columns are skipped.

Run with the poller and uvicorn STOPPED:

    cd C:\\\\Users\\\\<user>\\\\NSM\\\\backend
    venv\\\\Scripts\\\\python.exe migrate_smb_audit.py
"""
import sys

from sqlalchemy import inspect, text

import database

TABEL = "transfer_berkas"

# (column_name, SQL type). Generic types understood by both MySQL and SQLite,
# so this migration does not fork the schema.
KOLOM = [
    ("sumber", "VARCHAR(20)"),
    ("mesin_klien", "VARCHAR(100)"),
    ("berbagi", "VARCHAR(100)"),
    ("hasil", "VARCHAR(20)"),
]

# The page filters "SMB activity in this period" and "who touched files from a
# given host". Without indexes every page load scans the whole table, fast now
# while data is small, then gradually slower (see migrate_sftp.py).
INDEKS = [
    ("idx_transfer_sumber", "transfer_berkas(sumber, waktu)"),
]


def main():
    insp = inspect(database.engine)
    if not insp.has_table(TABEL):
        print("BERHENTI: tabel '%s' belum ada. Jalankan migrate_sftp.py dulu."
              % TABEL)
        raise SystemExit(1)

    exists = {k["name"] for k in insp.get_columns(TABEL)}
    added = 0
    with database.engine.begin() as conn:
        for nama, tipe in KOLOM:
            if nama in exists:
                print("  lewat  kolom %s sudah ada" % nama)
                continue
            conn.execute(text("ALTER TABLE %s ADD COLUMN %s %s NULL"
                              % (TABEL, nama, tipe)))
            print("  TAMBAH kolom %s %s" % (nama, tipe))
            added += 1

        for nama, target in INDEKS:
            try:
                conn.execute(text("CREATE INDEX %s ON %s" % (nama, target)))
                print("  INDEKS %s dibuat" % nama)
            except Exception as e:
                # MySQL has no CREATE INDEX IF NOT EXISTS; an existing index raises an
                # error, which is not a migration failure.
                if "exist" in str(e).lower() or "duplicate" in str(e).lower():
                    print("  lewat  indeks %s sudah ada" % nama)
                else:
                    raise

    print("\nSelesai. %d kolom ditambahkan di %s." % (added, database.engine.url))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print("GAGAL: %s" % e)
        sys.exit(1)

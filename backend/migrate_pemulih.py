"""Add 3 rollback columns to `pagar_tindakan`.

Only adds columns, all NULLABLE; existing rows are untouched and stay valid,
just without rollback data.

Same pattern as `migrate_smb_audit.py`: uses `inspect()`, works on MySQL and
SQLite, safe to run repeatedly.

Run with the poller and uvicorn STOPPED:

    cd C:\\\\Users\\\\<user>\\\\NSM\\\\backend
    venv\\\\Scripts\\\\python.exe migrate_pemulih.py
"""
import sys

from sqlalchemy import inspect, text

import database

# {table: [(column, type), ...]}: `pagar_tindakan` gets rollback columns,
# `services.unit_systemd` maps a service to its systemd unit.
TABEL_KOLOM = {
    "pagar_tindakan": [
        ("state_sebelum", "TEXT"),
        ("state_sesudah", "TEXT"),
        ("rollback_dilakukan", "BOOLEAN"),
    ],
    "services": [
        ("unit_systemd", "VARCHAR(64)"),
    ],
}


def main():
    insp = inspect(database.engine)
    added = 0
    with database.engine.begin() as conn:
        for table, column_list in TABEL_KOLOM.items():
            if not insp.has_table(table):
                print("  lewat  tabel '%s' tidak ada (dilewati)" % table)
                continue
            exists = {k["name"] for k in insp.get_columns(table)}
            for nama, tipe in column_list:
                if nama in exists:
                    print("  lewat  %s.%s sudah ada" % (table, nama))
                    continue
                conn.execute(text("ALTER TABLE %s ADD COLUMN %s %s NULL"
                                  % (table, nama, tipe)))
                print("  TAMBAH %s.%s %s" % (table, nama, tipe))
                added += 1

    print("\nSelesai. %d kolom ditambahkan di %s." % (added, str(database.engine.url)))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print("GAGAL: %s" % e)
        sys.exit(1)

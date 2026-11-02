# -*- coding: utf-8 -*-
"""Add the `backup_laporan` table. Adds only, never deletes.

Called by `kirim_ke_nsmapp.py` in its migration step; safe to re-run, and does
nothing if the table already exists.
"""
import sys

import sqlalchemy as sa

import database
import models


def jalankan():
    mesin = database.engine if hasattr(database, "engine") else database.buat_engine()
    checker = sa.inspect(mesin)

    if checker.has_table("backup_laporan"):
        kol = {k["name"] for k in checker.get_columns("backup_laporan")}
        print("  lewat  tabel backup_laporan sudah ada (%d kolom)" % len(kol))
        less = {c.name for c in models.BackupLaporan.__table__.columns} - kol
        if less:
            # Deliberately STOPS instead of adding columns itself: altering a table whose shape
            # has already diverged means guessing what happened to it, and guessing in a
            # migration is the fastest way to lose data.
            print("  PERHATIAN kolom yang kurang: %s" % ", ".join(sorted(less)))
            print("  Tidak diubah otomatis. Periksa dulu kenapa bentuknya berbeda.")
            return 1
    else:
        models.BackupLaporan.__table__.create(mesin)
        print("  DIBUAT tabel backup_laporan")

    with mesin.connect() as c:
        n = c.execute(sa.text("SELECT COUNT(*) FROM backup_laporan")).scalar()
    print("  %d laporan tersimpan" % n)
    print()
    print("  Berikutnya: jalankan `lapor_backup.py` DI LAPTOP (mesin yang")
    print("  benar-benar punya berkas backup-nya), lalu buka halaman Backup.")
    return 0


if __name__ == "__main__":
    sys.exit(jalankan())

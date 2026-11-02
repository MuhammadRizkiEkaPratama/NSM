r"""Add the Package C tables (behavior baseline, log patterns, agent proposals).

Five new tables; no existing table is touched:

    baseline_perilaku     per-device behavior by hour-of-week (C1)
    baseline_posisi       marker of status_logs rows already folded in
    log_templat           log message patterns mined by Drain3 (C2)
    log_templat_posisi    marker of syslog_pesan rows already mined
    usulan_agen           SOC agent proposals + guard verdict (C4)

RUN A BACKUP AFTER THIS. A live table missing from the backup cannot be
restored, and `uji_pulih_backup.py` will (correctly) fail. `backup_nsm.py`
checks its own dump for completeness, so a backup taken before this
migration will report these five tables as missing.

Run:
    venv\Scripts\python.exe migrate_paket_c.py
"""
import sys

from sqlalchemy import inspect

import database
import models

TABEL = [
    models.BaselinePerilaku,
    models.BaselinePosisi,
    models.LogTemplat,
    models.LogTemplatPosisi,
    models.UsulanAgen,
]


def main():
    mesin = database.engine
    before = set(inspect(mesin).get_table_names())

    for kelas in TABEL:
        kelas.__table__.create(mesin, checkfirst=True)

    # "No error" is not proof of success: re-read the table list from the
    # database instead of inferring it from the absence of an exception.
    ins = inspect(mesin)
    after = set(ins.get_table_names())
    less = [k.__tablename__ for k in TABEL
              if k.__tablename__ not in after]
    if less:
        print("  [GAGAL] tabel ini TIDAK ADA sesudah create(): %s"
              % ", ".join(less))
        return 1

    for kelas in TABEL:
        nama = kelas.__tablename__
        column = [c["name"] for c in ins.get_columns(nama)]
        mark = "BARU" if nama not in before else "sudah ada"
        print("  %-22s %-10s (%d kolom)" % (nama, mark, len(column)))

    print()
    print("  Berikutnya: jalankan backup (see docs/BACKUP.md), lalu")
    print("  `py uji_pulih_backup.py` untuk membuktikan tabel baru ini")
    print("  benar-benar bisa dipulihkan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

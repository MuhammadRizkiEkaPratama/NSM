# -*- coding: utf-8 -*-
r"""Report backup status to the database. Run ON THE LAPTOP.

WHY THIS FILE EXISTS
--------------------
Backups run from the Windows laptop. Since NSM moved to `nsm-app` (Linux), the
Backup Monitor page cannot check anything itself (`C:\...` paths cannot exist on a
Linux machine), so it shows only a "backup runs on another machine" sentence and an
empty table. This file closes the gap in the right direction: the machine that RUNS
the backup knows its state, so it reports it. No new network path or credential:
both machines already use the same MySQL.

WHAT IS SENT
------------
The whole output of `backup_status.ringkasan()` as JSON, as is, so the page on
nsm-app shows exactly what the laptop SEES: file list, zip contents, manifest
history, and Task Scheduler state.

WHAT IS NOT SENT
----------------
No backup contents, no passphrase, not one byte of any zip. Only METADATA: file
names, sizes, times, verification results. This limit is deliberate: the report must
never become a channel that carries backup data out of the backup folder.

HOW TO RUN
----------
    cd C:\Users\<user>\NSM\backend
    venv\Scripts\python.exe lapor_backup.py

Schedule it right AFTER the daily backup task so the report reflects the latest
backup. Run before the backup, it would report the pre-backup state, which is
correct but misleading to whoever reads it ten minutes later.
"""
import json
import platform
import sys
from datetime import datetime

import backup_status
import database
import models
from sqlalchemy.orm import Session

# Keep only the most recent reports: a few are useful to see whether the backup is
# growing or shrinking, but one JSON row per day would grow without limit.
SIMPAN_LAPORAN = 30


def lapor(cetak=True):
    summarize = backup_status.ringkasan()

    # If it reads "another machine" HERE too, this file is being run in the wrong place.
    # Stop with a clear message: a report saying "no backup files" would make the page
    # present emptiness as fact, which is worse than not reporting.
    if summarize.get("mesin_lain"):
        print("BERHENTI: mesin ini bukan tempat backup dijalankan.")
        print("  Folder backup di setelan: %s" % summarize.get("folder_utama"))
        print("  Jalankan berkas ini DI LAPTOP yang punya folder itu.")
        return 2

    mesin = platform.node() or "tidak-diketahui"
    line = models.BackupLaporan(
        waktu_lapor=datetime.now(),
        mesin=mesin,
        isi=json.dumps(summarize, ensure_ascii=False, default=str),
        sehat=bool(summarize.get("sehat")),
        jumlah_berkas=summarize.get("jumlah_berkas"),
        total_mb=summarize.get("total_mb"),
    )

    e = database.engine if hasattr(database, "engine") else database.buat_engine()
    with Session(e) as db:
        db.add(line)
        db.commit()

        old = db.query(models.BackupLaporan).order_by(
            models.BackupLaporan.waktu_lapor.desc()).offset(SIMPAN_LAPORAN).all()
        for x in old:
            db.delete(x)
        if old:
            db.commit()

        n = db.query(models.BackupLaporan).count()

    if cetak:
        print("Laporan backup terkirim.")
        print("  mesin          : %s" % mesin)
        print("  sehat          : %s" % ("ya" if summarize.get("sehat") else "TIDAK"))
        print("  berkas backup  : %s (%s MB)"
              % (summarize.get("jumlah_berkas"), summarize.get("total_mb")))
        print("  terbaru        : %s" % (summarize.get("umur_teks") or "-"))
        if summarize.get("masalah"):
            print("  masalah        :")
            for m in summarize["masalah"]:
                print("    - %s" % m)
        print("  laporan tersimpan: %d (maksimal %d)" % (n, SIMPAN_LAPORAN))
        print()
        print("  Buka halaman Backup di NSM; detailnya sekarang ada di sana.")
    return 0


if __name__ == "__main__":
    sys.exit(lapor())

r"""Recompute `syslog_pesan.sidik_templat` for old rows.

Before the parser fix, the Cisco timestamp stripper missed the `.` marker
(authoritative clock, NTP not synced), so the same message from devices with
different clock markers got different fingerprints and
`syslog_service.templat_baru()` counted it as two patterns. Already-stored rows
keep the wrong fingerprint; this script fixes them.

Only `sidik_templat` is touched (it is derived and can always be recomputed from
`pesan`); `pesan` is received data and is never rewritten.

Report-only by default; writing requires an explicit `--jalankan`.

Run:
    venv\Scripts\python.exe perbaiki_sidik_syslog.py
    venv\Scripts\python.exe perbaiki_sidik_syslog.py --jalankan
"""
import sys

from sqlalchemy import select

import database
import models
import syslog_terima


def main():
    run = "--jalankan" in sys.argv
    db = database.SessionLocal()
    try:
        line = db.execute(select(models.SyslogPesan)).scalars().all()
        changed = []
        for r in line:
            clean = syslog_terima.buang_stempel_cisco((r.pesan or "").strip())
            baru = syslog_terima.sidik_templat(clean)
            if baru != (r.sidik_templat or ""):
                changed.append((r, baru, clean))

        print("  %d baris syslog diperiksa" % len(line))
        print("  %d sidik templat perlu dihitung ulang" % len(changed))
        for r, baru, clean in changed[:8]:
            print("    id=%-6d %s -> %s" % (r.id, (r.sidik_templat or "")[:10],
                                            baru[:10]))
            print("           %s" % clean[:88])
        if len(changed) > 8:
            print("    ... dan %d lagi" % (len(changed) - 8))

        if not changed:
            print("  Tidak ada yang perlu diubah.")
            return 0

        if not run:
            print()
            print("  MODE LAPORAN -- tidak ada yang ditulis.")
            print("  Tambahkan --jalankan untuk benar-benar memperbaiki.")
            return 0

        for r, baru, _clean in changed:
            r.sidik_templat = baru
        db.commit()

        # No error is not proof of success: re-read from the database.
        remaining = 0
        for r in db.execute(select(models.SyslogPesan)).scalars().all():
            clean = syslog_terima.buang_stempel_cisco((r.pesan or "").strip())
            if syslog_terima.sidik_templat(clean) != (r.sidik_templat or ""):
                remaining += 1
        if remaining:
            print("  [GAGAL] masih ada %d baris yang sidiknya tidak cocok "
                  "sesudah ditulis." % remaining)
            return 1
        print("  %d sidik templat diperbaiki, diverifikasi ulang: 0 sisa"
              % len(changed))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

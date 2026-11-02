"""One-off: fill empty `ip_klien` in `perintah_pengguna` for sessions whose
address is known from other rows of the same session.

The `USER_START` row (SSH session address) appears only once per session in
the auditd log. Before the fix in `poller.simpan_traffic_device()`, once that
row scrolled out of the poller's read window, later events of the same session
lost the address. The poller fix covers new rows; this script repairs old rows
left empty.

Only fills a session that has EXACTLY ONE known address (no guessing among
several, no invention for sessions that never had one). Safe to re-run: filled
rows are skipped. The poller may keep running; this only UPDATEs old rows and
does not touch the read position.

Run:
    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\python.exe backfill_ip_sesi_perintah.py
"""
import sys

from sqlalchemy import func

import database
from models import PerintahPengguna


def main():
    db = database.SessionLocal()
    try:
        candidate = (
            db.query(PerintahPengguna.device_id, PerintahPengguna.sesi,
                     func.count(func.distinct(PerintahPengguna.ip_klien)),
                     func.max(PerintahPengguna.ip_klien))
            .filter(PerintahPengguna.sesi.isnot(None),
                    PerintahPengguna.ip_klien.isnot(None))
            .group_by(PerintahPengguna.device_id, PerintahPengguna.sesi)
            .all())

        diperbaiki_total = 0
        dilewati_ambigu = 0
        for device_id, sesi, n_distinct, ip in candidate:
            if n_distinct != 1:
                dilewati_ambigu += 1
                print("  LEWAT  device=%s sesi=%s punya %d alamat BERBEDA -- "
                      "ambigu, tidak dibackfill" % (device_id, sesi, n_distinct))
                continue
            n = (db.query(PerintahPengguna)
                 .filter(PerintahPengguna.device_id == device_id,
                         PerintahPengguna.sesi == sesi,
                         PerintahPengguna.ip_klien.is_(None))
                 .update({"ip_klien": ip}, synchronize_session=False))
            if n:
                print("  ISI    device=%s sesi=%s -> %s (%d baris)"
                      % (device_id, sesi, ip, n))
                diperbaiki_total += n
        db.commit()

        print("\nSelesai. %d baris diisi, %d sesi ambigu dilewati."
              % (diperbaiki_total, dilewati_ambigu))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

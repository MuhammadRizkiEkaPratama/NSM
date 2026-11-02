"""Re-attach orphaned `konfig_temuan` rows in the buffer to their parent snapshots in MySQL.

One-off repair: a failed buffer flush left `konfig_snapshots` rows in MySQL with
new ids while their `konfig_temuan` rows stayed in the buffer pointing at the
old `snapshot_id`. Without the findings, the Compliance page would show those
devices as clean instead of missing data.

Matching is strict, and rows that do not qualify are left alone (missing data is
better than data attached to the wrong place):
    1. `device_id` must be identical
    2. the snapshot must be earlier than the finding
    3. the time difference must be under 5 seconds

    python perbaiki_temuan_yatim.py           show the plan
    python perbaiki_temuan_yatim.py --jalan   apply
"""
import sys
from datetime import timedelta

from sqlalchemy import func, select, text

import database
import models  # noqa: F401

BATAS_DETIK = 5.0


def main():
    path = "--jalan" in sys.argv
    md = database.Base.metadata
    t_finding = md.tables["konfig_temuan"]

    with database.engine_penyangga.connect() as p:
        kelompok = p.execute(
            select(t_finding.c.snapshot_id,
                   t_finding.c.device_id,
                   func.min(t_finding.c.dinilai),
                   func.count())
            .group_by(t_finding.c.snapshot_id, t_finding.c.device_id)
            .order_by(t_finding.c.snapshot_id)).all()

    if not kelompok:
        print("Tidak ada konfig_temuan di penyangga. Tidak ada yang diperbaiki.")
        return 0

    print("=" * 74)
    print("Memasangkan konfig_temuan yatim ke potret konfigurasi di MySQL")
    print("=" * 74)
    print()
    print("  %-10s %-8s %-28s %-8s %s"
          % ("snapshot", "device", "dinilai", "baris", "induk di MySQL"))
    print("  " + "-" * 74)

    peta = {}
    with database.engine.connect() as k:
        for old, device_id, dinilai, jumlah in kelompok:
            prospective = k.execute(text("""
                SELECT id, waktu FROM konfig_snapshots
                WHERE device_id = :d AND waktu <= :w
                ORDER BY waktu DESC LIMIT 1
            """), {"d": device_id, "w": dinilai}).first()

            verdict = "TIDAK ADA PASANGAN"
            if prospective:
                difference = (dinilai - prospective[1]).total_seconds()
                if 0 <= difference <= BATAS_DETIK:
                    # A parent that already has findings is not an orphan here; attaching would duplicate.
                    already = k.execute(text(
                        "SELECT COUNT(*) FROM konfig_temuan "
                        "WHERE snapshot_id = :s"), {"s": prospective[0]}).scalar()
                    if already:
                        verdict = "induk %d sudah punya %d temuan - DILEWATI" % (
                            prospective[0], already)
                    else:
                        peta[old] = prospective[0]
                        verdict = "-> %d  (selisih %.3f dtk)" % (prospective[0], difference)
                else:
                    verdict = "selisih %.1f dtk, di luar batas" % difference

            print("  %-10s %-8s %-28s %-8s %s"
                  % (old, device_id, dinilai, jumlah, verdict))

    print()
    if not peta:
        print("Tidak ada yang bisa dipasangkan dengan aman.")
        return 1

    if not path:
        print("Ini baru rencana. Jalankan dengan --jalan untuk mengerjakannya.")
        return 0

    with database.engine_penyangga.begin() as p:
        for old, baru in peta.items():
            p.execute(t_finding.update()
                      .where(t_finding.c.snapshot_id == old)
                      .values(snapshot_id=baru))
    print("%d kelompok dipasangkan ulang di penyangga." % len(peta))
    print("Jalankan pengosongan penyangga untuk mengirimkannya.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Fill `status_rollup_jam` from the raw `status_logs` rows.

Reports first and only changes data with `--jalankan`, like `pangkas_data.py`.

    python bangun_rollup.py                    show what would be summarized
    python bangun_rollup.py --jalankan         actually summarize
    python bangun_rollup.py --jalankan --ulang-semua
                                               recompute ALL history; use
                                               when the calculation rules change

The poller also runs this every 10 minutes via `poll_rollup`, so this script
is mainly for the first backfill and for inspecting state.

Safe to run while the poller is running: it only reads `status_logs` and
writes `status_rollup_jam`, and never touches the hour in progress. Two
writers to `nsm.db` still exist, so for a large first backfill stop the
poller first.
"""
import sys
from datetime import datetime, timedelta

from database import SessionLocal
import rollup


def main():
    run = "--jalankan" in sys.argv
    retry = "--ulang-semua" in sys.argv
    db = SessionLocal()
    try:
        print("=" * 74)
        print("RINGKASAN PER JAM" + ("" if run else
                                     "  (uji coba, tidak mengubah apa pun)"))
        print("=" * 74)

        before = rollup.laporkan(db)
        print(f"  baris mentah `status_logs`  : {before['baris_mentah']:,}")
        print(f"  baris ringkasan sekarang    : {before['baris_ringkasan']:,}")
        print(f"  jam tertua yang diringkas   : {before['jam_tertua'] or '-'}")
        print(f"  jam terakhir yang diringkas : {before['jam_terakhir'] or '-'}")

        oldest = rollup.jam_tertua_mentah(db)
        limit = rollup.awal_jam(datetime.now())
        if oldest is None:
            print("\n  Tidak ada baris mentah sama sekali. Tidak ada yang diringkas.")
            return 0

        start = oldest if (retry or before["jam_terakhir"] is None) \
            else before["jam_terakhir"]
        count_hour = max(0, int((limit - start).total_seconds() // 3600))
        print(f"\n  akan meringkas dari {start} sampai {limit}")
        print(f"  yaitu sekitar {count_hour:,} jam")
        print("\n  Jam yang SEDANG BERJALAN sengaja tidak ikut: barisnya belum")
        print("  lengkap, dan angka setengah jadi yang tersimpan permanen jauh")
        print("  lebih berbahaya daripada angka yang belum ada.")

        if not run:
            print("\n  Tambahkan --jalankan untuk benar-benar meringkas.")
            return 0

        start_time = datetime.now()
        total = 0
        putaran = 0
        # Repeat until done: `bangun()` caps itself at 2000 hours per call so it does
        # not hold the write lock for long. Stop based on the HOUR REACHED, not on "no
        # rows written": an hour with no samples writes nothing, so stopping at
        # `ditulis == 0` would give up inside a monitoring gap and leave all later
        # history unsummarized.
        previous = None
        while putaran < 60:
            putaran += 1
            written, until_hour = rollup.bangun(
                db, ulang_dari=(oldest if retry and putaran == 1 else None))
            db.commit()
            total += written
            print(f"  putaran {putaran}: {written:,} baris ditulis, "
                  f"sampai {until_hour}")
            if until_hour is None or until_hour == previous:
                break
            previous = until_hour

        old = (datetime.now() - start_time).total_seconds()
        after = rollup.laporkan(db)
        print()
        print(f"  selesai dalam {old:.1f} detik, {total:,} baris ditulis")
        print(f"  baris ringkasan sekarang    : {after['baris_ringkasan']:,}")
        print(f"  penyusutan                  : {after['penyusutan']}x "
              f"({after['baris_mentah']:,} mentah -> "
              f"{after['baris_ringkasan']:,} ringkasan)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

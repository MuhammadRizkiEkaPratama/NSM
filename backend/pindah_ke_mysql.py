"""One-off move of `nsm.db` into the MySQL server on the primary lab instance.

    python pindah_ke_mysql.py           show the plan, changes nothing
    python pindah_ke_mysql.py --jalan   apply

Everything is moved (moving only the last 7 days of raw data would save only
about 40% and leave gaps in history); size is controlled by the daily pruning in
`pangkas_data.py`. `nsm.db` is only read, never deleted or modified, so it stays
a full fallback copy and `.env` can switch back to SQLite.
"""
import sys
import time

import database
import models  # noqa: F401  (mendaftarkan tabel ke metadata)
import pindah_data
from sqlalchemy import func, select


def ringkas_sumber(engine, metadata):
    total = 0
    line = []
    for nama in pindah_data.URUTAN:
        if nama not in metadata.tables:
            continue
        n = pindah_data.jumlah(engine, metadata.tables[nama])
        total += n
        line.append((nama, n))
    return line, total


def main():
    path = "--jalan" in sys.argv

    if not database.PAKAI_MYSQL:
        print("NSM_DB_HOST kosong di .env — tujuannya masih SQLite.")
        print("Isi dulu NSM_DB_* sebelum menjalankan perintah ini.")
        return 1

    metadata = database.Base.metadata
    source = database.buat_engine(database.url_sqlite(database.JALUR_DB))
    destination = database.engine

    print("=" * 74)
    print("Pindah data NSM")
    print("  dari  : %s" % database.JALUR_DB)
    print("  ke    : %s" % database.keterangan())
    print("=" * 74)

    line, total = ringkas_sumber(source, metadata)
    print()
    print("Isi sumber:")
    for nama, n in line:
        if n:
            print("  %-24s %8d" % (nama, n))
    print("  %-24s %8d" % ("TOTAL", total))

    if not path:
        print()
        print("Ini baru rencana. Tidak ada yang diubah.")
        print("Jalankan lagi dengan --jalan untuk mengerjakannya.")
        return 0

    print()
    print("1. Membuat tabel dan indeks di tujuan (yang sudah ada dilewati)")
    metadata.create_all(destination)
    with destination.connect() as k:
        exists = set(destination.dialect.get_table_names(k))
    print("   %d tabel siap" % len(exists & set(metadata.tables)))

    print()
    print("2. Menyalin (bisa dijalankan ulang, melanjutkan dari yang tertinggal)")
    start = time.time()
    hasil = pindah_data.copy_all(source, destination, metadata)
    second = time.time() - start
    copied = sum(hasil.values())
    print("   %d baris dalam %.0f detik (%.0f baris/detik)"
          % (copied, second, copied / second if second else 0))

    print()
    print("3. Membuktikan sampai — jumlah baris DAN rentang waktunya")
    diff = pindah_data.bandingkan(source, destination, metadata)
    if diff:
        print()
        print("   TIDAK COCOK:")
        for nama, apa, a, b in diff:
            print("     %-22s %-16s sumber=%s tujuan=%s" % (nama, apa, a, b))
        print()
        print("   Data di sumber TIDAK diubah. Perbaiki lalu jalankan ulang.")
        return 1

    for nama in pindah_data.URUTAN:
        if nama not in metadata.tables:
            continue
        n = pindah_data.jumlah(destination, metadata.tables[nama])
        if n:
            print("   COCOK  %-24s %8d" % (nama, n))

    print()
    print("=" * 74)
    print("SELESAI. NSM sekarang menulis ke %s" % database.keterangan())
    print("`nsm.db` dibiarkan utuh sebagai jalan mundur.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())

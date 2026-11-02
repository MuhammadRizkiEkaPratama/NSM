r"""Add column `insiden_gejala.pulih_pada` (MTTR fix).

WHY
---
Before this column, `korelasi.tutup_yang_selesai()` computed an incident's end time
from `max(waktu_terakhir)`, i.e. when the symptom was LAST SEEN STILL BROKEN, not
when it recovered. For an outage that recovered before the next correlation round
(60 s), both equal `mulai`, so `mttr_detik` came out 0, which reads as "recovered
instantly" rather than "not measured".

ONLY ADDS one nullable column. Old rows stay valid: `pulih_pada` NULL means "this
symptom recovered before NSM started recording it", and `korelasi.py` deliberately
falls back to `waktu_terakhir` for such rows; old numbers are not rewritten into
invented ones.

Run (safe even with the poller up, since it only ALTERs a table to add a column):
    venv\\Scripts\\python.exe migrate_gejala_pulih_pada.py
"""
import sys

from sqlalchemy import inspect, text

import database


def main():
    mesin = database.engine
    ins = inspect(mesin)

    if "insiden_gejala" not in ins.get_table_names():
        print("  [BERHENTI] tabel insiden_gejala belum ada. "
              "Jalankan migrate_insiden.py lebih dulu.")
        return 1

    column = [c["name"] for c in ins.get_columns("insiden_gejala")]
    if "pulih_pada" in column:
        print("  pulih_pada sudah ada (%d kolom) -- tidak ada yang diubah"
              % len(column))
        return 0

    with mesin.begin() as c:
        c.execute(text("ALTER TABLE insiden_gejala ADD COLUMN pulih_pada DATETIME NULL"))

    column = [c["name"] for c in inspect(mesin).get_columns("insiden_gejala")]
    if "pulih_pada" not in column:
        print("  [GAGAL] ALTER TABLE tidak melempar, tetapi kolomnya "
              "TIDAK ADA sesudahnya.")
        return 1
    print("  insiden_gejala.pulih_pada ditambahkan (%d kolom sekarang)"
          % len(column))
    return 0


if __name__ == "__main__":
    sys.exit(main())

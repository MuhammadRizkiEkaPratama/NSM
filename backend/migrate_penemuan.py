r"""Table `perangkat_ditemukan`: holding queue for network scan results.

See docs/design/DEVICE-AGNOSTIC.md.

    py migrate_penemuan.py

Adds ONE table. Changes no existing table, moves no rows, and runs no scan.

The table is deliberately separate from `devices`. A monitor that auto-adds
anything it sees lets anyone who can assign an IP address add load to it
(one rogue device becomes one device pinged every five seconds forever).
Storing findings in `devices` with `aktif=0` would still let the device
list be flooded from the network.

Findings accumulate here, and only `penemuan.setujui()` moves them into
`devices`, which requires a human to approve.

SAFE TO RUN REPEATEDLY: `checkfirst=True` leaves existing tables alone and
the script writes no data rows.

RUN A BACKUP AFTER THIS (see CONTRIBUTING.md).
"""
from sqlalchemy import inspect

import database
import models


def main():
    mesin = database.engine
    ins = inspect(mesin)

    already = "perangkat_ditemukan" in ins.get_table_names()
    models.PerangkatDitemukan.__table__.create(mesin, checkfirst=True)
    print("  tabel perangkat_ditemukan   %s" % ("sudah ada" if already else "DIBUAT"))

    # Re-check against the database instead of assuming the call above worked;
    # a migration that reports success without checking will also report success
    # when it fails.
    column = {k["name"] for k in inspect(mesin).get_columns("perangkat_ditemukan")}
    harus = {"id", "ip_address", "pertama_terlihat", "terakhir_terlihat",
             "rtt_ms", "port_terbuka", "sysobjectid", "platform", "catatan",
             "status", "device_id", "tenant_id"}
    less = harus - column
    if less:
        raise SystemExit("GAGAL: kolom belum lengkap -> %s" % sorted(less))

    print("  kolom lengkap               %d kolom" % len(column))
    print()
    print("Selesai. Tidak ada baris data yang ditulis, dan tidak ada")
    print("pemindaian yang dijalankan. Pemindaian dimulai dari halaman")
    print("Penemuan, atau lewat POST /penemuan/pindai.")


if __name__ == "__main__":
    main()

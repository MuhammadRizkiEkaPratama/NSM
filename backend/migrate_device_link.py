"""Create table `device_link`: FIXED paths between devices (physical/logical).

EMPTY WHEN CREATED. NSM cannot detect real cables itself; this schema is prepared
now so fixed paths (router -> switch -> server, per the lab) can be added later
without a second schema migration. See the docstring of `models.DeviceLink`.

The Dashboard topology map does NOT touch this table (it is drawn from the existing
`flow_koneksi`). Run this migration so `report_service.topologi()` can read the
table (zero rows is valid and is answered as an empty list, not an error) without
waiting for the physical layout to be filled in.

Safe to re-run. The indexes (`ix_devicelink_a`, `ix_devicelink_b`, declared in
models.py) are created automatically by `.create()` below, the same pattern as
migrate_ketergantungan.py.

    python migrate_device_link.py
"""
import database
import models  # noqa: F401  (mendaftarkan DeviceLink ke database.Base.metadata)


def main():
    md = database.Base.metadata
    md.tables["device_link"].create(database.engine, checkfirst=True)
    print("  tabel device_link siap (dan indeksnya)")
    print("\nSelesai. Tabel kosong: jalur fisik belum diisi, dan itu memang "
          "belum jadi pekerjaan tahap ini.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

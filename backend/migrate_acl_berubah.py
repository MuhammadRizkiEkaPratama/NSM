"""Migration: add column `acl_berubah` to table `konfig_snapshots`.

`baris_tambah`/`baris_hapus` count changed lines but cannot tell a banner change
from an ACL change, and the two need very different treatment.
`connectors/konfig.deteksi_acl_berubah()` checks whether the changed lines touch
access-control definitions, and the result is stored here so the Firewall page can
show a warning badge without recomputing the diff.

Values:
    1     ACL lines changed in this snapshot
    0     differs from the previous snapshot, but not in the ACL
    NULL  first snapshot of the device (nothing to compare), OR a snapshot from
          before this migration ran

Old snapshots are left NULL on purpose, not recomputed: that would reopen hundreds
of snapshots at once. NULL means "not checked", not "confirmed no ACL change".

Safe to re-run. Run with the poller and uvicorn STOPPED:

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\activate
    python migrate_acl_berubah.py
"""
from sqlalchemy import text

import database


def main():
    with database.engine.begin() as conn:
        line = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() "
            "AND table_name = 'konfig_snapshots' "
            "AND column_name = 'acl_berubah'"
        )).scalar()

        if line:
            print("- kolom 'konfig_snapshots.acl_berubah' sudah ada, lewati")
        else:
            conn.execute(text(
                "ALTER TABLE konfig_snapshots ADD COLUMN acl_berubah INT NULL"
            ))
            print("- kolom 'konfig_snapshots.acl_berubah' ditambahkan (NULL)")

    print("\nSelesai. Potret konfigurasi yang sudah ada tetap NULL di kolom "
          "ini — hanya potret BARU (mulai putaran poller berikutnya) yang "
          "akan diisi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

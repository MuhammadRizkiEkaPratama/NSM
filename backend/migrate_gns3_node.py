"""Migration: add column `devices.gns3_node` and fill in the 4 existing lab nodes.

ONLY ADDS one column; no other row is changed. NULL means "not a GNS3 node"; the
column is filled only for the 4 routers/switches that really are Dynamips nodes in
this lab. Same pattern as `migrate_smb_audit.py`: uses the active `database.engine`,
works for MySQL and SQLite, safe to re-run.

Why it exists: `kirim_perintah.py` must tell ordinary physical/VM devices apart from
GNS3 emulated nodes, because `reload` behaves DIFFERENTLY on each. See the comment
on `models.Device.gns3_node` and docs/POSTMORTEM-R1.md.

Run with the poller and uvicorn STOPPED:

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\python.exe migrate_gns3_node.py
"""
import sys

from sqlalchemy import inspect, text

import database

TABEL = "devices"
KOLOM = ("gns3_node", "VARCHAR(20)")

# (device.id, GNS3 node name) for ONLY the 4 Cisco nodes that run on Dynamips in this
# lab, matched to the existing `devices.name`/`ip_address` (Router/Switch Site A =
# R1/SW-A, Site B = R2/SW-B).
ISI = [
    (5, "R1"),    # Router Lokasi A, 192.168.56.60
    (8, "SW-A"),  # Switch Lokasi A, 192.168.56.61
    (9, "R2"),    # Router Lokasi B, 192.168.20.1
    (10, "SW-B"), # Switch Lokasi B, 192.168.20.2
]


def main():
    insp = inspect(database.engine)
    if not insp.has_table(TABEL):
        print("BERHENTI: tabel '%s' tidak ada." % TABEL)
        raise SystemExit(1)

    exists = {k["name"] for k in insp.get_columns(TABEL)}
    nama, tipe = KOLOM
    with database.engine.begin() as conn:
        if nama in exists:
            print("  lewat  kolom %s sudah ada" % nama)
        else:
            conn.execute(text("ALTER TABLE %s ADD COLUMN %s %s NULL"
                              % (TABEL, nama, tipe)))
            print("  TAMBAH kolom %s %s" % (nama, tipe))

        for device_id, node in ISI:
            hasil = conn.execute(
                text("UPDATE %s SET gns3_node = :node "
                     "WHERE id = :did AND "
                     "(gns3_node IS NULL OR gns3_node <> :node)" % TABEL),
                {"node": node, "did": device_id})
            line = conn.execute(
                text("SELECT name, gns3_node FROM %s WHERE id = :did" % TABEL),
                {"did": device_id}).first()
            if line is None:
                print("  PERINGATAN device id=%s tidak ditemukan, dilewati"
                      % device_id)
                continue
            print("  device id=%-3s %-25s gns3_node=%s"
                  % (device_id, line[0], line[1]))

    print("\nSelesai di %s." % (database.engine.url,))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print("GAGAL: %s" % e)
        sys.exit(1)

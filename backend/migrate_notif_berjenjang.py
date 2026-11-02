"""Migration: two marker columns for TIERED notifications.

See docs/design/TIERED-NOTIFICATIONS.md. The columns:

    `devices.notif_mati_dikirim`   when the "DOWN" email (down a full 15 minutes) was
                                 last sent FOR THE OUTAGE IN PROGRESS. NULL = no
                                 email pending. Set when the DOWN email goes out,
                                 cleared when the device recovers and the recovery
                                 email goes out.
    `devices.notif_flap_dikirim`   when the "UNSTABLE" email (>=N DOWN events within 1
                                 hour) was last sent. Marks "already warned, wait
                                 for calm"; see `NOTIF_FLAP_TENANG_JAM`.

WHY ONLY TWO TIMESTAMPS, NOT A ROUND COUNTER: "how long has it been down" is
recomputed every round straight from status_logs (already indexed on
device_id+timestamp, cheap), not stored as a rising counter. A stored counter can
drift from its source and silently go wrong. These two columns only answer "have we
already sent for THIS outage/pattern", not "how long".

Same pattern as migrate_gns3_node.py: uses the active database.engine, works for
MySQL and SQLite, safe to re-run.

Run with the poller and uvicorn STOPPED:
    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\python.exe migrate_notif_berjenjang.py
"""
import sys

from sqlalchemy import inspect, text

import database

TABEL = "devices"
KOLOM = [
    ("notif_mati_dikirim", "DATETIME"),
    ("notif_flap_dikirim", "DATETIME"),
]


def main():
    insp = inspect(database.engine)
    if not insp.has_table(TABEL):
        print("BERHENTI: tabel '%s' tidak ada." % TABEL)
        raise SystemExit(1)

    exists = {k["name"] for k in insp.get_columns(TABEL)}
    with database.engine.begin() as conn:
        for nama, tipe in KOLOM:
            if nama in exists:
                print("  lewat  kolom %s sudah ada" % nama)
            else:
                conn.execute(text("ALTER TABLE %s ADD COLUMN %s %s NULL"
                                  % (TABEL, nama, tipe)))
                print("  TAMBAH kolom %s %s" % (nama, tipe))

    print("\nSelesai di %s." % (database.engine.url,))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print("GAGAL: %s" % e)
        sys.exit(1)

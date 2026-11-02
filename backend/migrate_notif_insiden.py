r"""Add per-incident notification columns.

Two nullable columns on `insiden`:

  notif_keparahan       severity at the time the LAST email was sent
  notif_pulih_terkirim  whether the "recovered" email has been sent

WHY THE EXISTING `notif_terkirim` IS NOT ENOUGH
-----------------------------------------------
The rule is "one email per incident; a follow-up ONLY if severity RISES".
`notif_terkirim` is a boolean: it can say "sent or not", never "sent at what level".

Without `notif_keparahan`, an incident that rises from `perhatian` to `bahaya`
cannot be told apart from one that was already notified and did not change. Both
then end the same way: either both stay silent (the severity increase is never
announced, the one follow-up the rule promises), or both send (an email flood, the
very thing the rule exists to stop).

Run (safe even with the poller up, since it only ALTERs a table to add columns):
    venv\\Scripts\\python.exe migrate_notif_insiden.py
"""
import sys

from sqlalchemy import inspect, text

import database

KOLOM = (
    ("notif_keparahan", "VARCHAR(30) NULL"),
    ("notif_pulih_terkirim", "TINYINT(1) NULL DEFAULT 0"),
)

# SQLite has no TINYINT(1); it accepts BOOLEAN and VARCHAR as they are.
KOLOM_SQLITE = (
    ("notif_keparahan", "VARCHAR(30)"),
    ("notif_pulih_terkirim", "BOOLEAN DEFAULT 0"),
)


def main():
    mesin = database.engine
    ins = inspect(mesin)

    if "insiden" not in ins.get_table_names():
        print("  [BERHENTI] tabel insiden belum ada. "
              "Jalankan migrate_insiden.py lebih dulu.")
        return 1

    sqlite = mesin.dialect.name == "sqlite"
    daftar = KOLOM_SQLITE if sqlite else KOLOM

    exists = {c["name"] for c in ins.get_columns("insiden")}
    added = []
    for nama, tipe in daftar:
        if nama in exists:
            print("  %-22s sudah ada" % nama)
            continue
        with mesin.begin() as c:
            c.execute(text("ALTER TABLE insiden ADD COLUMN %s %s" % (nama, tipe)))
        added.append(nama)

    after = {c["name"] for c in inspect(mesin).get_columns("insiden")}
    less = [n for n, _t in daftar if n not in after]
    if less:
        print("  [GAGAL] ALTER TABLE tidak melempar, tetapi kolom ini TIDAK "
              "ADA sesudahnya: %s" % ", ".join(less))
        return 1

    print("  insiden siap (%d kolom; %d ditambahkan: %s)"
          % (len(after), len(added), ", ".join(added) or "-"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

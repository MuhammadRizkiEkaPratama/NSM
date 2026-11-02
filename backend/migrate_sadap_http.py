"""Create table `sadapan_http`: real packet capture of plain HTTP (E-Canteen,
port 8080) instead of guessing from the access log.

Background is in the `models.SadapanHttp` docstring. In short, the access log
never sees what the CLIENT sent, so "someone uploaded a file via the web"
cannot be proven from it. Packet capture reads the actual request body.

DELIBERATELY PLAIN HTTP ONLY, on one interface and one port. Never touches
encrypted SSH/LDAP/MySQL.

Safe to run repeatedly.

One-time prerequisite on the server (192.168.56.103), done by an admin
outside this script because it needs root:

    sudo usermod -aG wireshark nsmro
    sudo apt install -y tshark
"""
import sys

import database
import models  # noqa: F401  -- registrasi SadapanHttp ke Base.metadata

TABEL = "sadapan_http"


def main():
    md = database.Base.metadata
    print("=" * 74)
    print("Tabel sadapan_http")
    print("=" * 74)
    md.tables[TABEL].create(database.engine, checkfirst=True)
    print("  tabel %r siap" % TABEL)
    return 0


if __name__ == "__main__":
    sys.exit(main())

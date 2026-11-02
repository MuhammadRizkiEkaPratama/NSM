"""IOS configuration for the two-site topology.

    SITE A 192.168.56.0/24              WAN 10.10.10.0/30       SITE B 192.168.20.0/24
      laptop/NSM  .1                      R1 .1  <-->  R2 .2      R2       .1
      R1          .60                                            SW-B     .2
      SW-A        .61                                            nsm-ubuntu .101
      testUbuntu  .103

R1 is only added to, never overwritten: its `nsm` user, SSH v2, SNMP and Fa0/0
address stay untouched; only Fa1/0 and one static route are written.

Credentials are not stored in this file. They are read from `devices` in nsm.db,
the same source NSM uses to log in.
"""
import os
import sqlite3
import sys

import konsol

DB = r"C:\Users\<user>\NSM\backend\nsm.db"
HOST = "192.168.56.102"

# nama, port console, daftar perintah
def rencana(sandi):
    return [
        ("R1", 5000, [
            "configure terminal",
            "interface FastEthernet1/0",
            " description WAN ke R2 (lokasi B)",
            " ip address 10.10.10.1 255.255.255.252",
            " no shutdown",
            " exit",
            # Static route rather than a routing protocol: two routers with a single path
            # between them have nothing to choose, so OSPF would only add failure modes.
            "ip route 192.168.20.0 255.255.255.0 10.10.10.2",
            "end",
        ]),
        ("R2", 5004, [
            "configure terminal",
            "no ip domain lookup",
            "ip domain name lab.local",
            "username nsm privilege 15 secret " + sandi,
            "interface FastEthernet0/0",
            " description LAN lokasi B ke SW-B",
            " ip address 192.168.20.1 255.255.255.0",
            " no shutdown",
            " exit",
            "interface FastEthernet0/1",
            " description WAN ke R1 (lokasi A)",
            " ip address 10.10.10.2 255.255.255.252",
            " no shutdown",
            " exit",
            "ip route 192.168.56.0 255.255.255.0 10.10.10.1",
            "ip ssh version 2",
            "line vty 0 4",
            " login local",
            " transport input ssh",
            " exit",
            # `general-keys` is required, not a style choice. R2 runs IOS 12.4 (c2691) and R1
            # runs 15.2 (c7200); 15.2 accepts `crypto key generate rsa modulus 1024`, but 12.4
            # rejects it with "% Invalid input detected". The modulus is given on the same
            # line so IOS does not prompt and hang this script.
            "crypto key generate rsa general-keys modulus 1024",
            "end",
        ]),
        ("SW-A", 5002, [
            "configure terminal",
            "no ip domain lookup",
            "ip domain name lab.local",
            "username nsm privilege 15 secret " + sandi,
            "interface Vlan1",
            " ip address 192.168.56.61 255.255.255.0",
            " no shutdown",
            " exit",
            # An L2 switch does not route. `ip default-gateway` only applies to the switch's
            # own traffic (incoming SSH, outgoing replies), not to transit packets.
            "ip default-gateway 192.168.56.60",
            "ip ssh version 2",
            "line vty 0 4",
            " login local",
            " transport input ssh",
            " exit",
            "crypto key generate rsa modulus 1024",
            "end",
        ]),
        ("SW-B", 5003, [
            "configure terminal",
            "no ip domain lookup",
            "ip domain name lab.local",
            "username nsm privilege 15 secret " + sandi,
            "interface Vlan1",
            " ip address 192.168.20.2 255.255.255.0",
            " no shutdown",
            " exit",
            "ip default-gateway 192.168.20.1",
            "ip ssh version 2",
            "line vty 0 4",
            " login local",
            " transport input ssh",
            " exit",
            "crypto key generate rsa modulus 1024",
            "end",
        ]),
    ]


def sandi_router():
    d = sqlite3.connect(DB)
    try:
        r = d.execute("SELECT password FROM devices WHERE id = 5").fetchone()
    finally:
        d.close()
    if not r or not r[0]:
        raise RuntimeError("Sandi router tidak ada di nsm.db (devices id=5).")
    return r[0]


def main():
    sandi = sandi_router()
    gagal_total = 0

    for nama, port, perintah in rencana(sandi):
        print("=" * 66)
        print(nama)
        print("=" * 66)
        try:
            k = konsol.Konsol(HOST, port, timeout=30)
        except Exception as e:
            print("  tidak bisa membuka console: %s" % e)
            gagal_total += 1
            continue
        try:
            konsol.masuk_enable(k)
            k.kirim("terminal length 0", 1.0)
            # Key generation takes longer than ordinary commands.
            _keluar, galat = k.jalankan(perintah, jeda=0.8)
            if galat:
                gagal_total += len(galat)
                for p, pesan in galat:
                    print("  DITOLAK  %-45s" % p)
                    print("           %s" % pesan.replace("\r\n", " ")[:150])
            else:
                print("  semua perintah diterima")

            # Save so the configuration survives node shutdown.
            simpan = k.kirim("write memory", 4.0) + k.baca(4.0)
            print("  simpan: %s" % ("OK" if "[OK]" in simpan or "Building" in simpan
                                    else simpan.strip()[-120:]))
        finally:
            k.tutup()
        print()

    print("=" * 66)
    print("Perintah ditolak: %d" % gagal_total)
    print("=" * 66)
    return 1 if gagal_total else 0


if __name__ == "__main__":
    sys.exit(main())

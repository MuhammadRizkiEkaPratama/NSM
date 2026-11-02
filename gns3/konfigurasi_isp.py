"""Configure the three-hop WAN path: R1 - ISP - R2.

    SITE A                       ISP                    SITE B
    R1 Fa1/0 .1 ---- 10.10.10.0/30 ---- .2 Fa0/0
                         ISP
                         Fa0/1 .1 ---- 10.10.20.0/30 ---- .2 Fa0/1 R2

Simplification: the ISP has static routes to both private LANs (192.168.56.0/24
and 192.168.20.0/24). Real carriers do not route private addresses; branches
build tunnels (VPN/GRE/MPLS) over the carrier path. It is used here to show a
three-hop path without an extra tunnel layer.
"""
import sqlite3
import sys

import konsol

DB = r"C:\Users\<user>\NSM\backend\nsm.db"
HOST = "192.168.56.102"


def sandi_router():
    d = sqlite3.connect(DB)
    try:
        r = d.execute("SELECT password FROM devices WHERE id = 5").fetchone()
    finally:
        d.close()
    if not r or not r[0]:
        raise RuntimeError("Sandi router tidak ada di nsm.db.")
    return r[0]


def rencana(sandi):
    return [
        ("ISP", 5006, [
            "configure terminal",
            "hostname ISP",
            "no ip domain lookup",
            "ip domain name lab.local",
            "username nsm privilege 15 secret " + sandi,
            "interface FastEthernet0/0",
            " description ke R1 (lokasi A)",
            " ip address 10.10.10.2 255.255.255.252",
            " no shutdown",
            " exit",
            "interface FastEthernet0/1",
            " description ke R2 (lokasi B)",
            " ip address 10.10.20.1 255.255.255.252",
            " no shutdown",
            " exit",
            "ip route 192.168.56.0 255.255.255.0 10.10.10.1",
            "ip route 192.168.20.0 255.255.255.0 10.10.20.2",
            "ip ssh version 2",
            "line vty 0 4",
            " login local",
            " transport input ssh",
            " exit",
            "crypto key generate rsa general-keys modulus 1024",
            "end",
        ]),
        # R2: WAN leg moves to another subnet, return route goes via the ISP
        ("R2", 5004, [
            "configure terminal",
            "interface FastEthernet0/1",
            " description WAN ke ISP",
            " ip address 10.10.20.2 255.255.255.252",
            " no shutdown",
            " exit",
            # The old route points at 10.10.10.1 (R1 directly). R2's neighbor is now the ISP,
            # so the old route would point at an address with no neighbor and return packets
            # would be dropped silently.
            "no ip route 192.168.56.0 255.255.255.0 10.10.10.1",
            "ip route 192.168.56.0 255.255.255.0 10.10.20.1",
            "end",
        ]),
        # R1's route is unchanged: its neighbor is still 10.10.10.2 (formerly R2, now the ISP).
    ]


def main():
    sandi = sandi_router()
    gagal = 0
    for nama, port, perintah in rencana(sandi):
        print("=" * 66)
        print(nama)
        try:
            k = konsol.Konsol(HOST, port, timeout=40)
        except Exception as e:
            print("  console tidak bisa dibuka: %s" % e)
            gagal += 1
            continue
        try:
            konsol.masuk_enable(k)
            k.kirim("terminal length 0", 1.0)
            _out, salah = k.jalankan(perintah, jeda=0.9)
            if salah:
                gagal += len(salah)
                for p, pesan in salah:
                    print("  DITOLAK  %s" % p)
                    print("           %s" % pesan.replace("\r\n", " ")[:150])
            else:
                print("  semua perintah diterima")
            simpan = k.kirim("write memory", 5.0) + k.baca(5.0)
            # `write memory` on older IOS may ask for confirmation; an empty Enter answers it.
            # Without it the configuration is not saved.
            if "[confirm]" in simpan:
                simpan += k.kirim("", 4.0)
            print("  simpan: %s" % ("OK" if "[OK]" in simpan
                                    else simpan.strip()[-100:]))
        finally:
            k.tutup()
        print()

    print("=" * 66)
    print("Perintah ditolak: %d" % gagal)
    return 1 if gagal else 0


if __name__ == "__main__":
    sys.exit(main())

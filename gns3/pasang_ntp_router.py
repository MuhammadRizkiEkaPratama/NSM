"""Sync the clocks of the three routers to the lab time source (192.168.56.104).

Router clocks start from zero at boot, so ACL deny logs are stamped "Mar 1" and
cannot be correlated with other hosts' logs. This is also why `penolakan_acl`
stores two timestamps.

Routers are synced to UTC, like the three Linux servers, so logs from different
hosts sort without conversion.

R2 (site B) needs an ACL entry because the NTP reply arrives through the ACL and
`permit tcp any any established` does not cover UDP. It is added in `acl_lokasi_b.py`:

    permit udp host 192.168.56.104 eq ntp 192.168.20.0 0.0.0.255
"""
import sys
import time

import konsol

HOST = "192.168.56.102"
SUMBER = "192.168.56.104"

ROUTER = [("R1", 5000), ("R2", 5004), ("ISP", 5006)]

PERINTAH = [
    "configure terminal",
    # Set the time zone explicitly even though UTC is the default.
    "clock timezone UTC 0",
    "ntp server " + SUMBER,
    # Routers only sync, they do not serve time: a second time source on the network
    # would be worse than one slightly wrong source.
    "no ntp master",
    "end",
]


def main():
    print("=" * 70)
    print("Menyelaraskan jam router ke %s" % SUMBER)
    print("=" * 70)

    gagal = 0
    for nama, port in ROUTER:
        print()
        print("-- %s --" % nama)
        k = konsol.Konsol(HOST, port, timeout=60)
        try:
            konsol.masuk_enable(k)
            k.kirim("terminal length 0", 1.0)

            sebelum = k.kirim("show clock", 2.0)
            print("   sebelum: %s" % " ".join(sebelum.split("\n")[1:2]).strip())

            _out, salah = k.jalankan(PERINTAH, jeda=0.6)
            # `no ntp master` complains if it was never set; that is not a failure.
            salah = [(p, m) for p, m in salah if not p.strip().startswith("no ntp")]
            if salah:
                for p, m in salah:
                    print("   DITOLAK  %s" % p)
                    print("            %s" % m.replace("\r\n", " ")[:120])
                gagal += 1
                continue

            simpan = k.kirim("write memory", 5.0) + k.baca(5.0)
            if "[confirm]" in simpan:
                simpan += k.kirim("", 4.0)
            print("   simpan : %s" % ("OK" if "[OK]" in simpan else
                                      simpan.strip()[-60:]))
        finally:
            k.tutup()

    # IOS NTP sync takes several minutes: it measures several times to confirm the
    # source is stable instead of jumping straight to it.
    print()
    print("Menunggu penyelarasan (IOS mengukur beberapa kali dulu, "
          "bisa 2-5 menit)...")
    batas = time.time() + 420
    belum = [n for n, _ in ROUTER]
    while time.time() < batas and belum:
        time.sleep(30)
        masih = []
        for nama in belum:
            port = dict(ROUTER)[nama]
            try:
                k = konsol.Konsol(HOST, port, timeout=30)
                konsol.masuk_enable(k)
                k.kirim("terminal length 0", 0.8)
                st = k.kirim("show ntp status", 2.5)
                jam = k.kirim("show clock", 2.0)
                k.tutup()
            except Exception:
                masih.append(nama)
                continue
            if "Clock is synchronized" in st:
                print("   %-5s SINKRON  %s" % (
                    nama, " ".join(jam.split("\n")[1:2]).strip()))
            else:
                masih.append(nama)
        belum = masih
        if belum:
            print("   belum sinkron: %s" % ", ".join(belum))

    if belum:
        print()
        print("Masih belum sinkron: %s" % ", ".join(belum))
        print("IOS kadang butuh lebih lama. Periksa lagi dengan "
              "`show ntp associations` di konsolnya.")
        return 1

    print()
    print("Ketiga router sinkron. Cap waktu log sekarang bisa disandingkan "
          "dengan log mesin lain.")
    return 0 if not gagal else 1


if __name__ == "__main__":
    sys.exit(main())

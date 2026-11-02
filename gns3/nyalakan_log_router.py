"""Enable log buffering on the routers so NSM can read ACL denials.

The `DARI-LOKASI-A` ACL on R2 ends with `deny ip any any log`, but with
"Buffer logging: disabled" the deny messages go only to the console and are not
stored. The change is minimal:

    logging buffered 16384 informational

This uses 16 KB of router RAM, does not touch forwarding or rules, and is undone
with `no logging buffered`. The level is `informational` because
`%SEC-6-IPACCESSLOGP` is level 6; `debugging` would fill the buffer with noise.
`logging rate-limit` is also set so a flood of denied packets cannot keep the
router busy writing messages.

The ISP node is treated as a provider device in the lab story; configuring it is
a deliberate choice.
"""
import sys

import konsol

HOST = "192.168.56.102"

ROUTER = [
    ("R1", 5000),
    ("R2", 5004),
    ("ISP", 5006),
]

PERINTAH = [
    "configure terminal",
    # 16 KB holds thousands of deny lines, far below the smallest router RAM here (256 MB).
    "logging buffered 16384 informational",
    # Rate-limit message writing so a flood of denied packets does not starve forwarding.
    "logging rate-limit 20 except errors",
    # Full timestamp with date and zone; without `datetime` messages carry router
    # uptime, which cannot be correlated with other hosts' logs.
    "service timestamps log datetime msec localtime show-timezone",
    "end",
]


def main():
    hanya = sys.argv[1] if len(sys.argv) > 1 else None

    print("=" * 70)
    print("Menyalakan penyimpanan log di router")
    print("=" * 70)

    gagal_total = 0
    for nama, port in ROUTER:
        if hanya and nama != hanya:
            continue
        print()
        print("-- %s (console %d) --" % (nama, port))
        k = konsol.Konsol(HOST, port, timeout=60)
        try:
            konsol.masuk_enable(k)
            k.kirim("terminal length 0", 1.0)

            _out, salah = k.jalankan(PERINTAH, jeda=0.6)
            if salah:
                for p, pesan in salah:
                    print("   DITOLAK  %s" % p)
                    print("            %s" % pesan.replace("\r\n", " ")[:130])
                gagal_total += 1
                continue
            print("   semua perintah diterima")

            simpan = k.kirim("write memory", 5.0) + k.baca(5.0)
            if "[confirm]" in simpan:
                simpan += k.kirim("", 4.0)
            print("   simpan: %s" % ("OK" if "[OK]" in simpan else
                                     simpan.strip()[-70:]))

            # Verify the result instead of trusting the output of the command that sent it.
            hasil = k.kirim("show logging | include Buffer logging", 2.5)
            print("   bukti : %s" % " ".join(hasil.split("\n")[1:2]).strip())
        finally:
            k.tutup()

    print()
    print("=" * 70)
    print("Selesai." if not gagal_total
          else "ADA YANG GAGAL: %d router" % gagal_total)
    print("=" * 70)
    return 1 if gagal_total else 0


if __name__ == "__main__":
    sys.exit(main())

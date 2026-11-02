"""Tests for saturation parsing: number parsing and thresholds.
The parser is tested apart from the device because `df`, `free` and `/proc/loadavg` output varies by distribution and version. Malformed output (missing lines, absurd numbers, empty output) matters most: a read failure must not become zero, or an unreadable machine would look like the most idle one.
"""
import sys

from connectors import sumberdaya as sd

lolos, gagal = [], []


def cek(nama, dapat, harap):
    if dapat == harap:
        lolos.append(nama)
        print("  LOLOS  %s" % nama)
    else:
        gagal.append(nama)
        print("  GAGAL  %s\n         dapat %r\n         harap %r"
              % (nama, dapat, harap))


NORMAL = "disk=47\nmem=72.0\nload1=1.12\ninti=2\n"


def main():
    print("=" * 74)
    print("Pembacaan saturasi")
    print("=" * 74)

    print("\n1. Keluaran normal")
    n = sd.urai(NORMAL)
    cek("disk terbaca", n.get("disk"), 47.0)
    cek("memori terbaca", n.get("mem"), 72.0)
    cek("beban DIBAGI jumlah inti", n.get("load"), 0.56)
    print("       (1,12 dibagi 2 inti = 0,56 — supaya bisa dibandingkan "
          "dengan mesin berjumlah inti lain)")

    print("\n2. Keluaran kosong tidak menghasilkan angka nol")
    cek("kosong -> tidak ada nilai sama sekali", sd.urai(""), {})
    cek("None -> tidak ada nilai sama sekali", sd.urai(None), {})
    cek("vonis atas nilai kosong juga kosong", sd.vonis({}), {})
    print("       (kalau kosong dibaca 0%, mesin yang gagal dibaca akan "
          "terlihat paling lega di seluruh jaringan)")

    print("\n3. Baris yang hilang tidak merusak yang lain")
    n = sd.urai("disk=91\ninti=4\n")
    cek("disk tetap terbaca", n.get("disk"), 91.0)
    cek("memori tidak diisi tebakan", "mem" in n, False)
    cek("beban tidak dihitung tanpa load1", "load" in n, False)

    print("\n4. Beban tanpa jumlah inti tidak dibagi sembarangan")
    n = sd.urai("load1=3.0\n")
    cek("load1 mentah tetap ada", n.get("load1"), 3.0)
    cek("load per inti TIDAK dikarang", "load" in n, False)

    print("\n5. Ambang dua tingkat")
    cek("disk 79 -> sehat", sd.vonis({"disk": 79.0})["disk"], "sehat")
    cek("disk 80 -> perhatian", sd.vonis({"disk": 80.0})["disk"], "perhatian")
    cek("disk 89 -> perhatian", sd.vonis({"disk": 89.9})["disk"], "perhatian")
    cek("disk 90 -> bahaya", sd.vonis({"disk": 90.0})["disk"], "bahaya")

    print("\n6. Memori memakai `available`, bukan `used`")
    # total 2000, available 400 -> terpakai 80%
    n = sd.urai("mem=80.0\n")
    cek("80% terbaca sebagai perhatian", sd.vonis(n).get("mem"), "sehat")
    cek("86% terbaca sebagai perhatian",
        sd.vonis({"mem": 86.0})["mem"], "perhatian")
    print("       (kalau memakai kolom `used`, Linux menghitung singgahan "
          "sebagai terpakai dan mesin sehat akan selalu terbaca 90%)")

    print("\n7. Tiap ukuran punya kalimat dan langkahnya")
    for k in ("disk", "mem", "load"):
        cek("%-5s punya arti" % k, bool(sd.ARTI.get(k)), True)
        cek("%-5s punya langkah" % k, len(sd.LANGKAH.get(k, [])) >= 2, True)

    print()
    print("=" * 74)
    print("HASIL: %d lolos, %d gagal" % (len(lolos), len(gagal)))
    print("=" * 74)
    return 1 if gagal else 0


if __name__ == "__main__":
    sys.exit(main())

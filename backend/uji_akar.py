"""Test cause/effect separation with synthetic scenarios.

Synthetic data rather than stopping real servers: the logic must be correct for
states that have never occurred, and `akar.nilai()` is pure (it takes the list of
failed items as an argument instead of reading the database).
"""
import sys

import akar

lolos, gagal = [], []


def cek(nama, dapat, harap):
    if dapat == harap:
        lolos.append(nama)
        print("  LOLOS  %s" % nama)
    else:
        gagal.append(nama)
        print("  GAGAL  %s\n         dapat %r\n         harap %r"
              % (nama, dapat, harap))


# Synthetic map modeled on this lab:
#   service 3 = MySQL on device 11 (data server)
#   service 5 = E-Canteen on device 6 (web server)
#   service 7 = LDAP on device 4 (directory)
#   service 2 = SSH on device 6
PETA = {
    5: [(3, None, "E-Canteen menyimpan datanya di basis data ini"),
        (7, None, "sandi diperiksa ke direktori")],
    2: [(7, None, "sssd mengenali pemakai dari direktori")],
    8: [(None, 11, "aplikasinya berjalan di mesin itu")],
}


def vonis(hasil, sid):
    return hasil[sid]["vonis"]


def main():
    print("=" * 74)
    print("Memisahkan sebab dari akibat")
    print("=" * 74)

    print("\n1. Data server mati — MySQL sebab, E-Canteen akibat")
    h = akar.nilai(None, {3: 11, 5: 6}, {11}, peta=PETA)
    cek("MySQL disebut akibat (mesinnya sendiri mati)", vonis(h, 3), "akibat")
    cek("  dan alasannya menunjuk ke perangkat", h[3]["karena_device"], 11)
    cek("E-Canteen disebut akibat", vonis(h, 5), "akibat")
    cek("  dan alasannya menunjuk ke MySQL", h[5]["karena_layanan"], 3)

    print("\n2. HANYA MySQL yang mati, mesinnya sehat — MySQL jadi sebab")
    h = akar.nilai(None, {3: 11, 5: 6}, set(), peta=PETA)
    cek("MySQL disebut sebab", vonis(h, 3), "sebab")
    cek("E-Canteen tetap akibat", vonis(h, 5), "akibat")

    print("\n3. Direktori mati — dua layanan di dua mesin berbeda ikut jatuh")
    h = akar.nilai(None, {7: 4, 5: 6, 2: 6}, set(), peta=PETA)
    cek("LDAP disebut sebab", vonis(h, 7), "sebab")
    cek("E-Canteen akibat", vonis(h, 5), "akibat")
    cek("SSH server web akibat", vonis(h, 2), "akibat")

    print("\n4. Dua gangguan yang TIDAK berhubungan tetap dua sebab")
    h = akar.nilai(None, {3: 11, 2: 6}, set(), peta=PETA)
    cek("MySQL sebab", vonis(h, 3), "sebab")
    cek("SSH server web sebab (LDAP-nya sehat)", vonis(h, 2), "sebab")

    print("\n5. Bergantung pada PERANGKAT, bukan layanan")
    h = akar.nilai(None, {8: 6}, {11}, peta=PETA)
    cek("layanan 8 akibat karena perangkat 11 mati", vonis(h, 8), "akibat")

    print("\n6. Lingkaran ketergantungan tidak membuatnya menggantung")
    circle = {1: [(2, None, "a butuh b")], 2: [(1, None, "b butuh a")]}
    h = akar.nilai(None, {1: 9, 2: 9}, set(), peta=circle)
    cek("keduanya dinilai, tidak ada yang hilang", sorted(h), [1, 2])
    print("       (yang penting berhenti, bukan jawabannya benar — "
          "lingkaran memang tidak punya jawaban benar)")

    print("\n7. Semuanya sehat")
    h = akar.nilai(None, {}, set(), peta=PETA)
    cek("tidak ada vonis sama sekali", h, {})
    cek("ringkasannya kosong", akar.ringkas(h), "")

    print("\n8. Kalimat ringkasan untuk kepala halaman")
    h = akar.nilai(None, {3: 11, 5: 6, 2: 6}, {11}, peta=PETA)
    r = akar.ringkas(h)
    cek("menyebut jumlah sebab dan terdampak", "ikut terdampak" in r, True)
    print("       -> %s" % r)

    print()
    print("=" * 74)
    print("HASIL: %d lolos, %d gagal" % (len(lolos), len(gagal)))
    print("=" * 74)
    return 1 if gagal else 0


if __name__ == "__main__":
    sys.exit(main())

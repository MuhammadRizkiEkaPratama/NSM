"""Test the FLOW reader (`connectors/flow.py`): TCP conversations from `ss -tin`.

The old `POLA_ALAMAT` used `\\S+` for local/peer addresses, the same pattern that
let NUL bytes become a huge `ip_klien` in `akseslog.py`. Here the source is live
`ss -tin` output, so risk is lower, but the pattern is tightened anyway.

Pure in-memory; touches neither nsm.db nor any device.
"""
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

lolos = 0
gagal = 0


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print("  LOLOS  %s" % nama)
    else:
        gagal += 1
        print("  GAGAL  %s %s" % (nama, ket))


def sama(nama, dapat, harap):
    benar(nama, dapat == harap, "-> dapat %r, harusnya %r" % (dapat, harap))


print("=" * 74)
print("UJI PEMBACA FLOW (connectors/flow.py)")
print("=" * 74)

from connectors import flow

# ---------------------------------------------------------------------------
print("\n1. Baris ss -tin NORMAL (IPv4) tetap terurai benar (dasar)")

keluaran_normal = (
    "0      0      192.168.56.103:22   192.168.56.1:50393\n"
    "\t bytes_sent:1234 bytes_received:5678\n"
)
hasil = flow.urai(keluaran_normal)
sama("jumlah koneksi", len(hasil), 1)
if hasil:
    sama("ip_lokal benar", hasil[0]["ip_lokal"], "192.168.56.103")
    sama("ip_lawan benar", hasil[0]["ip_lawan"], "192.168.56.1")
    sama("port_lokal benar", hasil[0]["port_lokal"], 22)
    sama("byte_keluar terbaca", hasil[0]["byte_keluar"], 1234.0)
    sama("byte_masuk terbaca", hasil[0]["byte_masuk"], 5678.0)

# ---------------------------------------------------------------------------
print("\n2. Alamat IPv6 dengan kurung siku tetap terurai (bukan regresi)")

keluaran_v6 = "0      0      [::1]:8080   [::ffff:192.168.56.1]:443\n"
hasil2 = flow.urai(keluaran_v6)
sama("jumlah koneksi ipv6", len(hasil2), 1)
if hasil2:
    sama("ip_lokal ipv6 (kurung dibuang)", hasil2[0]["ip_lokal"], "::1")

# ---------------------------------------------------------------------------
print("\n3. REGRESI 18 Agustus 2026: byte NUL di alamat TIDAK tertelan")

keluaran_rusak = ("0      0      " + ("\x00" * 300)
                  + "192.168.56.103:22   192.168.56.1:50393\n")
hasil3 = flow.urai(keluaran_rusak)
sama("baris ber-NUL TIDAK menghasilkan koneksi (pola tidak cocok)",
    len(hasil3), 0)

# ---------------------------------------------------------------------------
print("\n3b. REGRESI 18 Agustus 2026 (percobaan KEDUA): alamat dengan penanda")
print("    zona antarmuka Linux (mis. '10.0.2.15%enp0s3') TETAP terbaca.")
print("    Percobaan PERTAMA memperketat pola jadi daftar-putih karakter IP")
print("    murni -- ternyata terlalu sempit, akan diam-diam MEMBUANG bentuk")
print("    alamat sah seperti ini. Diperbaiki jadi \"larang NUL saja\", uji")
print("    ini mengunci supaya tidak diperketat berlebihan lagi nanti.")

keluaran_zona = "0      0      10.0.2.15%enp0s3:68   10.0.2.2:67\n"
hasil3b = flow.urai(keluaran_zona)
sama("alamat berpenanda zona TETAP menghasilkan satu koneksi", len(hasil3b), 1)
if hasil3b:
    sama("ip_lokal membawa penanda zonanya utuh",
        hasil3b[0]["ip_lokal"], "10.0.2.15%enp0s3")

# ---------------------------------------------------------------------------
print("\n4. Jaring KEDUA: alamat tetap dipotong <=45 karakter walau lolos regex")

alamat_panjang = "1" * 500
keluaran_panjang = "0      0      %s:22   192.168.56.1:50393\n" % alamat_panjang
hasil4 = flow.urai(keluaran_panjang)
if hasil4:
    benar("ip_lokal dipotong ke <=45 karakter",
         len(hasil4[0]["ip_lokal"]) <= 45,
         "-> panjangnya %d" % len(hasil4[0]["ip_lokal"]))
else:
    benar("alamat tidak sah (500 digit) ditolak regex (lebih baik lagi)", True)

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

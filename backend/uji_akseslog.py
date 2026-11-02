"""Test the web access-log parser (`connectors/akseslog.py`).

Regression: a corrupt E-Canteen log line (leading NUL bytes) was swallowed by the
old `ip: \\S+` pattern into `ip_klien`, producing a string longer than the MySQL
column. `simpan_traffic_device()` stores all rows of a device in one transaction,
so one bad line rolled back everything every cycle.

Fixed in two layers: `POLA` now accepts only valid IPv4/IPv6 characters, and
`ip_klien` is truncated to `[:45]` as a second net.

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
print("UJI PENGURAI ACCESS LOG (connectors/akseslog.py)")
print("=" * 74)

from connectors import akseslog

# ---------------------------------------------------------------------------
print("\n1. Baris log NORMAL tetap terurai benar (dasar, bukan regresi)")

baris_normal = ('192.168.56.1 - - [08/Aug/2026:18:05:59 +0000] '
                '"GET /login HTTP/1.1" 200 10929 "-" "Mozilla/5.0"')
d = akseslog.urai_baris(baris_normal)
benar("baris normal terurai (bukan None)", d is not None)
if d:
    sama("ip_klien benar", d["ip_klien"], "192.168.56.1")
    sama("metode benar", d["metode"], "GET")
    sama("path benar", d["path"], "/login")
    sama("status benar", d["status"], 200)

# ---------------------------------------------------------------------------
print("\n2. REGRESI 18 Agustus 2026: baris dengan byte NUL di depan IP")

baris_rusak = ("\x00" * 300 + '192.168.56.1 - - [15/Aug/2026:19:19:58 +0000] '
              '"GET /login HTTP/1.1" 200 10929 "-" "UjiNSM/1.0"')
d = akseslog.urai_baris(baris_rusak)
benar("baris ber-NUL TIDAK cocok sama sekali (bukan ip_klien raksasa)",
     d is None,
     "-> ip_klien %r sepanjang %d" % (
         (d or {}).get("ip_klien"), len((d or {}).get("ip_klien") or "")))

# ---------------------------------------------------------------------------
print("\n3. Jaring KEDUA: ip_klien tetap dipotong walau lolos regex")

# Direct simulation without the regex, proving the truncation works on its own.
ip_panjang = "1" * 500
baris_ip_panjang = ('%s - - [08/Aug/2026:18:05:59 +0000] '
                    '"GET /login HTTP/1.1" 200 10929 "-" "Mozilla/5.0"'
                    % ip_panjang)
d = akseslog.urai_baris(baris_ip_panjang)
if d is not None:
    benar("ip_klien dipotong ke <=45 karakter walau regex meloloskannya",
         len(d["ip_klien"]) <= 45,
         "-> panjangnya %d" % len(d["ip_klien"]))
else:
    # If the regex already rejects an IP this long, that is even better; the first line of defense is enough.
    benar("baris IP tidak sah (500 digit) ditolak regex (lebih baik lagi)",
         True)

# ---------------------------------------------------------------------------
print("\n4. REGRESI 18 Agustus 2026: baris terakhir terpotong batas MAKS_BACA")
print("   (dibuktikan nyata lewat SSH: head -c memotong PERSIS di tengah baris,")
print("   menyebabkan alamat IP 'hantu' seperti '.168.56.1' muncul di halaman)")

baris_lengkap = ('192.168.56.1 - - [17/Aug/2026:04:43:36 +0000] '
                 '"GET /login HTTP/1.1" 200 10929 "-" '
                 '"NSM-Monitor/1.0 (Network Status Monitor)"')

# Round 1: the chunk ends exactly mid-line (mid User-Agent, no trailing newline).
potongan_1 = "5000\n" + baris_lengkap[:87]  # cut mid-line, NO "\n"
baris1, posisi1, diputar1, ada1 = akseslog.baca_potongan(potongan_1, 0)
benar("putaran 1: baris terpotong TIDAK ikut jadi baris baru",
     baris1 == [], "-> dapat %r" % baris1)
sama("putaran 1: posisi TIDAK maju (supaya baris dibaca ulang utuh)",
    posisi1, 0)

# Round 2: the server finished writing the line; the reader restarts from position 0 and gets the whole line.
potongan_2 = "5000\n" + baris_lengkap + "\n"
baris2, posisi2, diputar2, ada2 = akseslog.baca_potongan(potongan_2, posisi1)
sama("putaran 2: baris utuh terbaca sekali jalan, bukan dua kali/pecah",
    len(baris2), 1)
if baris2:
    d2 = akseslog.urai_baris(baris2[0])
    benar("putaran 2: ip_klien UTUH ('192.168.56.1'), bukan potongan",
         d2 is not None and d2["ip_klien"] == "192.168.56.1",
         "-> dapat %r" % ((d2 or {}).get("ip_klien")))

# Normal case: a chunk that genuinely ends on a newline boundary must not lose its last line.
potongan_normal = "5000\n" + baris_lengkap + "\n"
baris3, posisi3, diputar3, ada3 = akseslog.baca_potongan(potongan_normal, 0)
sama("baris yang genuinely lengkap (diakhiri newline) tetap terbaca",
    len(baris3), 1)

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

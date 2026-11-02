"""Test: the evidence chain of a service incident names the service's own port.

Two defects fixed:
  1. The service's own port never appeared (a card about port 80 never mentioned port 80).
  2. Port 443 was marked failed although HTTPS was never installed on that server.

Touches neither the network nor the database; tests the sentence builder.

Run: py uji_bukti_layanan.py
"""
import sys

import diagnosa
import report_service as rs

lolos = 0
gagal = 0


def cek(nama, dapat, harap):
    global lolos, gagal
    if dapat == harap:
        lolos += 1
        print(f"  LOLOS  {nama}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama}\n         dapat  : {dapat}\n         harusnya: {harap}")


def benar(nama, syarat, keterangan=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print(f"  LOLOS  {nama}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama} {keterangan}")


print("=" * 74)
print("J8: rantai bukti insiden layanan")
print("=" * 74)

# Case 1: web server, port 80 down, HTTPS never installed. Only port 80 is registered
# there, so 22 answering is good news and a closed 443 is no news.
print("\nKasus 1: HTTP 80 mati di device yang tidak pernah memasang HTTPS")
teks = diagnosa.build_evidence(
    "192.168.1.103", ping_ok=True, ping_ms=1.23,
    port_lain={22: True, 443: False},
    port_layanan=80, port_layanan_ok=False,
    diharapkan={80},
)
baris = rs._urai_bukti(teks)

benar("port layanannya sendiri disebut di bukti",
      any("Port 80" in b["teks"] for b in baris),
      "-> kartu tentang port 80 tidak menyebut port 80")

b80 = next(b for b in baris if "Port 80" in b["teks"])
cek("port 80 ditandai GAGAL", b80["ok"], False)

b443 = next(b for b in baris if "Port 443" in b["teks"])
cek("port 443 ditandai netral, bukan gagal", b443["ok"], None)
benar("alasan port 443 tertutup ikut ditulis",
      "tidak ada layanan terdaftar" in b443["teks"],
      f"-> dapat: {b443['teks']}")

b22 = next(b for b in baris if "Port 22" in b["teks"])
cek("port 22 yang menjawab tetap OK", b22["ok"], True)

cek("port layanan disebut sebelum port pembanding",
    [i for i, b in enumerate(baris) if "Port 80" in b["teks"]][0] <
    [i for i, b in enumerate(baris) if "Port 22" in b["teks"]][0], True)

# Case 2: SSH 22 down, and the device does have a service on 80. A closed 80 IS bad
# news there, so the failure mark must still appear.
print("\nKasus 2: port pembanding yang memang punya layanan tetap ditandai gagal")
teks2 = diagnosa.build_evidence(
    "192.168.56.104", ping_ok=False, ping_ms=None,
    port_lain={80: False, 443: False},
    port_layanan=22, port_layanan_ok=False,
    diharapkan={22, 80},
)
baris2 = rs._urai_bukti(teks2)
cek("port 80 (punya layanan) ditandai GAGAL",
    next(b for b in baris2 if "Port 80" in b["teks"])["ok"], False)
cek("port 443 (tanpa layanan) tetap netral",
    next(b for b in baris2 if "Port 443" in b["teks"])["ok"], None)

# Case 3: process alive but answering badly (Apache returning 500 on every request): port open, service failing.
print("\nKasus 3: port terbuka tetapi jawaban layanan salah (HTTP 500)")
teks3 = diagnosa.build_evidence(
    "192.168.1.103", ping_ok=True, ping_ms=0.8,
    port_lain={22: True, 443: False},
    port_layanan=80, port_layanan_ok=True,
    diharapkan={80},
)
b80c = next(b for b in rs._urai_bukti(teks3) if "Port 80" in b["teks"])
cek("port 80 ditandai OK karena masih menerima koneksi", b80c["ok"], True)
benar("kalimatnya menyebut prosesnya belum mati",
      "belum mati" in b80c["teks"], f"-> dapat: {b80c['teks']}")

kesimpulan = diagnosa.simpulkan(True, False, {22: True, 443: False},
                                port_terbuka=True)
benar("kesimpulan membedakan 'rusak di dalam' dari 'mati'",
      "rusak di dalam" in kesimpulan, f"-> dapat: {kesimpulan}")

# Case 4: regression guard. Conclusions that were already right must not change.
print("\nKasus 4: penjaga regresi kesimpulan lama")
cek("port layanan tertutup, port lain menjawab -> layanan yang berhenti",
    "berhenti benar-benar layanan ini" in
    diagnosa.simpulkan(True, False, {22: True}, port_terbuka=False), True)
cek("ping mati dan semua port mati -> gangguan device",
    "gangguan device" in
    diagnosa.simpulkan(False, False, {22: False, 80: False}, port_terbuka=False), True)
cek("ping mati tapi port menjawab -> ping diblokir",
    "Ping diblokir" in
    diagnosa.simpulkan(False, False, {22: True}, port_terbuka=False), True)
cek("ping hidup, tidak satu pun port menjawab -> kewalahan/firewall",
    "kewalahan" in
    diagnosa.simpulkan(True, False, {22: False, 80: False}, port_terbuka=False), True)

# Case 5: the old form still reads correctly. Evidence rows already stored have no
# service port and no INFO marker, and must not change meaning.
print("\nKasus 5: baris bukti lama di database tetap terbaca sama")
lama = rs._urai_bukti("OK|Ping menjawab (1.00 ms), mesinnya hidup\n"
                      "GAGAL|Port 443 tidak menjawab")
cek("baris OK lama tetap OK", lama[0]["ok"], True)
cek("baris GAGAL lama tetap GAGAL", lama[1]["ok"], False)
cek("jumlah baris tidak berubah", len(lama), 2)

# The form without a pipe (used for free-form notes) stays neutral.
cek("baris tanpa penanda tetap netral",
    rs._urai_bukti("sekadar catatan")[0]["ok"], None)

print()
print("=" * 74)
print(f"HASIL: {lolos} lolos, {gagal} gagal")
print("=" * 74)
sys.exit(1 if gagal else 0)

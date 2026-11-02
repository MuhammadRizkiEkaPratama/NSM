"""Tests for the traffic baseline and anomaly detection.

An anomaly detector always outputs something that looks convincing, so the costly
failures are firing constantly (people stop reading) or staying silent. Guards, in order:
  1. EVERY finding carries its comparison number
  2. the baseline refuses to compute when data is insufficient
  3. median, not mean (one 200 MB hour must not raise the threshold)
  4. error bursts use ALL rows, including NSM's own requests
  5. findings are grouped, not one row per request

Regressions: `unduhan_besar()` once emitted one finding per request, and
`ledakan_galat()` once dropped `dari_nsm` rows and missed the only real service
outage (`/hello.php` returning 500 229 times), which was visible only via NSM requests.

Touches neither the database nor the network.
"""
import os
import sys
from datetime import datetime, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

import anomali

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


def baris(waktu, ip="192.168.1.5", path="/a.html", status=200, byte=1000,
          agen="Mozilla/5.0", nsm=0):
    return {"waktu": waktu, "ip_klien": ip, "path": path, "status": status,
            "byte_kirim": float(byte), "user_agent": agen, "dari_nsm": nsm}


# ---------------------------------------------------------------------------
print("\n1. TIAP TEMUAN MEMBAWA ANGKA PEMBANDINGNYA")
print("   (label tanpa angka akan diabaikan setelah dilihat dua kali, dan")
print("    pada saat itu ia berhenti berguna sekaligus tetap memakan")
print("    perhatian)")

campur = (
    [baris("2026-08-01 10:%02d:00" % i, byte=60 * 1024 * 1024,
           path="/besar.bin") for i in range(2)]
    + [baris("2026-08-01 03:30:00", byte=5 * 1024 * 1024, path="/malam.zip")]
    + [baris("2026-08-01 11:%02d:00" % i, status=404, path="/tebak%d" % i)
       for i in range(25)]
    + [baris("2026-08-01 12:00:00", path="/dump.sql", status=200)]
    + [baris("2026-08-01 13:00:00", byte=3 * 1024 * 1024, agen="curl/8.5.0")]
)
h = anomali.periksa(campur)
benar("ada temuan", len(h["temuan"]) > 0)
for t in h["temuan"]:
    benar("temuan %-28s punya pembanding" % t["jenis"][:28],
          bool(str(t.get("pembanding") or "").strip()),
          "-> %r" % t.get("pembanding"))
    benar("temuan %-28s punya alasan" % t["jenis"][:28],
          bool(str(t.get("kenapa") or "").strip()))
    benar("temuan %-28s punya angka" % t["jenis"][:28],
          bool(str(t.get("angka") or "").strip()))

# ---------------------------------------------------------------------------
print("\n2. GARIS DASAR MENOLAK DIHITUNG KALAU DATANYA BELUM CUKUP")
print("   (pada 9 Agustus 2026 basis data nyata hanya punya 6 jam berisi")
print("    lalu lintas pengguna; rata-rata dari 6 sampel bukan kebiasaan)")

sedikit = anomali.per_jam([baris("2026-08-01 %02d:00:00" % j) for j in range(6)])
d = anomali.garis_dasar(sedikit)
benar("dinyatakan belum siap", d["siap"] is False)
sama("jam terkumpul disebut", d["jam_terkumpul"], 6)
sama("jam yang dibutuhkan disebut", d["jam_dibutuhkan"],
     anomali.MIN_JAM_GARIS_DASAR)
benar("alasannya menyebut kedua angka",
      "6" in d["alasan"] and str(anomali.MIN_JAM_GARIS_DASAR) in d["alasan"],
      "-> %r" % d["alasan"])
benar("tidak ada angka median yang dikarang", "byte_median" not in d)

sama("tanpa garis dasar, nol temuan lonjakan",
     [t for t in anomali.lonjakan_volume(sedikit, d)], [])

cukup = anomali.per_jam(
    [baris("2026-08-%02d %02d:00:00" % (1 + j // 24, j % 24)) for j in range(30)])
d2 = anomali.garis_dasar(cukup)
benar("dengan 30 jam, garis dasar siap", d2["siap"] is True,
      "-> %r" % d2.get("alasan"))

# ---------------------------------------------------------------------------
print("\n3. MEDIAN, BUKAN RATA-RATA")
print("   (satu jam berisi 200 MB akan menarik rata-rata begitu jauh")
print("    sehingga jam 200 MB BERIKUTNYA terlihat normal — kejadian luar")
print("    biasa yang ikut menaikkan ambangnya sendiri)")

jam_biasa = {"2026-08-01 %02d" % j: {"permintaan": 1, "byte": 1000.0}
             for j in range(30)}
jam_biasa["2026-08-02 05"] = {"permintaan": 1, "byte": 200 * 1024 * 1024.0}
dm = anomali.garis_dasar(jam_biasa)
benar("median tetap kecil walau ada satu jam raksasa",
      dm["byte_median"] < 5000, "-> %r" % dm["byte_median"])
rata = sum(v["byte"] for v in jam_biasa.values()) / len(jam_biasa)
benar("dan jauh lebih kecil daripada rata-ratanya",
      dm["byte_median"] < rata / 100,
      "-> median %.0f vs rata-rata %.0f" % (dm["byte_median"], rata))

# ---------------------------------------------------------------------------
print("\n4. LEDAKAN GALAT MEMAKAI SELURUH BARIS, TERMASUK PERMINTAAN NSM")
print("   (status 5xx adalah kegagalan SERVER, tidak peduli siapa yang")
print("    bertanya — dan NSM yang bertanya paling rutin. Versi pertama")
print("    membuangnya, dan melaporkan 'tidak ada temuan' untuk satu-satunya")
print("    gangguan layanan yang pernah tercatat)")

insiden = [baris("2026-07-29 16:%02d:00" % (i % 60), status=500,
                 path="/hello.php", agen="NSM-Monitor/1.0", nsm=1)
           for i in range(96)]
h2 = anomali.periksa(insiden)
lima = [t for t in h2["temuan"] if t["jenis"] == "ledakan_galat_5xx"]
sama("insiden 5xx yang hanya terlihat NSM tetap ditemukan", len(lima), 1)
benar("jumlahnya disebut", "96" in lima[0]["angka"], "-> %r" % lima[0]["angka"])
benar("disebutkan bahwa itu terlihat lewat pemeriksaan NSM",
      "NSM" in lima[0]["angka"], "-> %r" % lima[0]["angka"])
sama("keparahannya tinggi", lima[0]["keparahan"], anomali.TINGGI)

# Conversely, the USER BEHAVIOR detectors still drop NSM rows, otherwise the monitoring heartbeat would show up as the busiest user.
sama("tetapi baris NSM tidak dihitung sebagai lalu lintas pengguna",
     h2["diperiksa"], 0)
sama("dan jumlah yang dilewati disebutkan", h2["dilewati_dari_nsm"], 96)

# ---------------------------------------------------------------------------
print("\n4b. WAKTU TEMUAN HARUS BISA DIURAI PERAMBAN")
print("    (cacat yang terlihat di LAYAR USER, bukan di uji: kunci")
print("     pengelompokan '2026-07-29 16' dikirim apa adanya sebagai waktu,")
print("     dan peramban menuliskan 'Invalid Date' di sudut tiap kartu")
print("     berbasis jam. Uji lama memeriksa isinya tetapi tidak pernah")
print("     mencoba MENGURAINYA sebagai tanggal)")


def bisa_diurai(teks):
    """Mimic the browser's `new Date(text)` for the forms used here."""
    import re as _re
    t = str(teks)
    if _re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?", t):
        return True
    return False


semua_jenis = anomali.periksa(
    campur + insiden_awal if False else campur)["temuan"]
for t in semua_jenis:
    benar("waktu temuan %-24s bisa diurai" % t["jenis"][:24],
          bisa_diurai(t["kapan"]), "-> %r" % t["kapan"])

# Hour-based findings cover a RANGE, so they also carry a time note naming the range.
per_jam_jenis = [t for t in semua_jenis
                 if t["jenis"].startswith(("ledakan_galat", "lonjakan_volume",
                                           "di_luar_jam_kerja"))]
for t in per_jam_jenis:
    benar("temuan berbasis jam %-18s menyebut rentangnya" % t["jenis"][:18],
          bool(t.get("kapan_teks")), "-> %r" % t.get("kapan_teks"))

# ---------------------------------------------------------------------------
print("\n4c. JAM BERURUTAN DISATUKAN JADI SATU INSIDEN")
print("    (terlihat di layar user: gangguan /hello.php 29 Juli 16:10–18:07")
print("     tampil sebagai DUA kartu, dan jam ketiganya yang berisi 14 galat")
print("     hilang sama sekali karena sendirian ia di bawah ambang)")

tiga_jam = ([baris("2026-07-29 16:%02d:00" % (i % 60), status=500,
                   path="/hello.php", nsm=1) for i in range(96)]
            + [baris("2026-07-29 17:%02d:00" % (i % 60), status=500,
                     path="/hello.php", nsm=1) for i in range(119)]
            + [baris("2026-07-29 18:%02d:00" % (i % 60), status=500,
                     path="/hello.php", nsm=1) for i in range(14)])
tg3 = anomali.ledakan_galat(tiga_jam)
sama("tiga jam berurutan jadi SATU temuan", len(tg3), 1)
benar("seluruh galatnya dijumlahkan (96+119+14 = 229)",
      "229" in tg3[0]["angka"], "-> %r" % tg3[0]["angka"])
benar("jam ketiga yang di bawah ambang IKUT, tidak hilang",
      "229" in tg3[0]["angka"])
benar("lamanya disebut", "3 jam" in tg3[0]["angka"], "-> %r" % tg3[0]["angka"])
benar("rentang waktunya disebut", "16:00" in (tg3[0]["kapan_teks"] or ""),
      "-> %r" % tg3[0]["kapan_teks"])

# Separate hours must not be merged; two different outages are two events.
terpisah = ([baris("2026-07-29 10:%02d:00" % (i % 60), status=500) for i in range(25)]
            + [baris("2026-07-29 20:%02d:00" % (i % 60), status=500) for i in range(25)])
sama("jam yang berjauhan tetap dua temuan", len(anomali.ledakan_galat(terpisah)), 2)

# ---------------------------------------------------------------------------
print("\n5. 4xx DAN 5xx DIPISAH")
print("   (4xx = peminta meminta yang tidak ada; 5xx = server sendiri gagal.")
print("    Menggabungkannya membuat gangguan layanan tidak bisa dibedakan")
print("    dari usaha pemindaian)")

campur2 = ([baris("2026-08-03 10:%02d:00" % i, status=404) for i in range(25)]
           + [baris("2026-08-03 10:%02d:30" % i, status=500) for i in range(25)])
t2 = anomali.ledakan_galat(campur2)
jenis = {t["jenis"] for t in t2}
benar("keduanya muncul terpisah",
      jenis == {"ledakan_galat_4xx", "ledakan_galat_5xx"}, "-> %r" % jenis)
p5 = [t for t in t2 if t["jenis"] == "ledakan_galat_5xx"][0]
p4 = [t for t in t2 if t["jenis"] == "ledakan_galat_4xx"][0]
benar("5xx lebih parah daripada 4xx",
      anomali.URUT_PARAH[p5["keparahan"]] < anomali.URUT_PARAH[p4["keparahan"]])
benar("di bawah ambang tidak dilaporkan",
      anomali.ledakan_galat([baris("2026-08-03 11:00:00", status=500)]) == [])

# ---------------------------------------------------------------------------
print("\n6. TEMUAN DIKELOMPOKKAN, BUKAN SATU BARIS PER PERMINTAAN")
print("   (halaman berisi seratus temuan yang berbunyi sama tidak lebih")
print("    berguna daripada satu; yang benar-benar berbeda akan tenggelam)")

empat = [baris("2026-07-28 09:%02d:00" % (39 + i), byte=52 * 1024 * 1024,
               path="/uji-50mb.bin", ip="192.168.56.1") for i in range(4)]
tg = anomali.unduhan_besar(empat)
sama("empat unduhan berkas yang sama jadi SATU temuan", len(tg), 1)
benar("jumlah pengulangannya disebut", "4 kali" in tg[0]["angka"],
      "-> %r" % tg[0]["angka"])
# The total is computed from the contents, not hardcoded; hardcoded numbers break the test whenever the data changes.
harap_total = sum(b["byte_kirim"] for b in empat)
sama("totalnya dijumlahkan, bukan diambil salah satu",
     tg[0]["bukti"][0]["byte"], harap_total)
benar("dan totalnya yang tertulis di angkanya",
      anomali._teks_byte(harap_total) in tg[0]["angka"],
      "-> %r" % tg[0]["angka"])

# A DIFFERENT file stays a separate finding; grouping must not swallow distinct events.
beda = [baris("2026-07-28 09:00:00", byte=60 * 1024 * 1024, path="/a.bin"),
        baris("2026-07-28 09:05:00", byte=60 * 1024 * 1024, path="/b.bin")]
sama("berkas berbeda tetap dua temuan", len(anomali.unduhan_besar(beda)), 2)

# ---------------------------------------------------------------------------
print("\n7. BERKAS SENSITIF: BERHASIL vs DITOLAK BEDA ARTINYA")

diambil = anomali.berkas_sensitif([baris("2026-08-04 09:00:00",
                                         path="/backup/dump.sql", status=200)])
ditolak = anomali.berkas_sensitif([baris("2026-08-04 09:00:00",
                                         path="/backup/dump.sql", status=404)])
sama("yang BERHASIL diambil berkeparahan tinggi",
     diambil[0]["keparahan"], anomali.TINGGI)
sama("yang DITOLAK berkeparahan rendah",
     ditolak[0]["keparahan"], anomali.RENDAH)
benar("yang ditolak tetap dicatat, tidak dibuang", len(ditolak) == 1)
benar("alasannya membedakan keduanya",
      "BERHASIL" in diambil[0]["kenapa"] and "penjagaannya bekerja" in ditolak[0]["kenapa"])
sama("berkas biasa tidak ikut",
     anomali.berkas_sensitif([baris("2026-08-04 09:00:00", path="/gambar.png")]), [])

print("\n7b. '/admin' POLOS TIDAK LAGI DIANGGAP SENSITIF")
print("    (ketahuan nyata 19 Agustus 2026: E-Canteen punya panel admin SAH")
print("    di jalur ini -- staf kantin kelola menu/pesanan setiap hari, dan")
print("    itu memenuhi 15 dari 16 temuan pada satu hari biasa)")

sama("/admin milik E-Canteen TIDAK dianggap sensitif",
     anomali.berkas_sensitif([baris("2026-08-19 09:00:00", path="/admin", status=200)]), [])
sama("/admin/menu TIDAK dianggap sensitif",
     anomali.berkas_sensitif([baris("2026-08-19 09:00:00", path="/admin/menu", status=200)]), [])
sama("/admin/orders/advance TIDAK dianggap sensitif",
     anomali.berkas_sensitif([baris("2026-08-19 09:00:00",
                                    path="/admin/orders/advance", status=302)]), [])

print("\n7c. TAPI panel admin aplikasi LAIN (yang TIDAK terpasang di lab) tetap kena")
print("    (menebak wp-admin/phpmyadmin cuma masuk akal kalau memang bukan aplikasi kita)")

wp = anomali.berkas_sensitif([baris("2026-08-19 09:00:00",
                                    path="/wp-admin/install.php", status=200)])
pma = anomali.berkas_sensitif([baris("2026-08-19 09:00:00",
                                     path="/phpmyadmin/index.php", status=200)])
benar("percobaan wp-admin tetap terdeteksi", len(wp) == 1)
benar("percobaan phpmyadmin tetap terdeteksi", len(pma) == 1)

# ---------------------------------------------------------------------------
print("\n8. KLIEN BARU BUTUH SEJARAH")
print("   (tanpa pembanding SEMUA alamat terlihat baru, dan peringatan yang")
print("    menyala untuk semuanya sama tidak bergunanya dengan yang tidak")
print("    pernah menyala)")

sekarang = [baris("2026-08-05 10:00:00", ip="10.9.9.9", byte=5 * 1024 * 1024)]
sama("tanpa sejarah, nol temuan", anomali.klien_baru(sekarang, []), [])
lama = [baris("2026-08-01 10:00:00", ip="192.168.1.5")]
tk = anomali.klien_baru(sekarang, lama)
sama("dengan sejarah, alamat baru ketahuan", len(tk), 1)
benar("alamatnya disebut", "10.9.9.9" in tk[0]["angka"])
sama("alamat yang SUDAH pernah ada tidak dilaporkan",
     anomali.klien_baru([baris("2026-08-05 10:00:00", ip="192.168.1.5",
                               byte=5 * 1024 * 1024)], lama), [])

# ---------------------------------------------------------------------------
print("\n9. DI LUAR JAM KERJA HANYA UNTUK VOLUME YANG BERARTI")
print("   (satu permintaan halaman pukul sebelas malam bukan kejadian;")
print("    menarik 80 MB pada jam yang sama adalah kejadian)")

sama("satu halaman kecil tengah malam diabaikan",
     anomali.di_luar_jam_kerja([baris("2026-08-06 23:00:00", byte=2000)]), [])
tm = anomali.di_luar_jam_kerja([baris("2026-08-06 23:00:00", byte=80 * 1024 * 1024)])
sama("80 MB tengah malam dilaporkan", len(tm), 1)
benar("jam kerjanya disebut sebagai pembanding",
      "07" in tm[0]["pembanding"] and "18" in tm[0]["pembanding"],
      "-> %r" % tm[0]["pembanding"])
sama("siang hari tidak dilaporkan",
     anomali.di_luar_jam_kerja([baris("2026-08-06 10:00:00",
                                      byte=80 * 1024 * 1024)]), [])

# ---------------------------------------------------------------------------
print("\n10. TIDAK ADA DATA BUKAN KEADAAN GALAT")

kosong = anomali.periksa([])
sama("nol temuan", kosong["temuan"], [])
sama("cacahnya nol semua", kosong["cacah"],
     {"tinggi": 0, "sedang": 0, "rendah": 0})
benar("garis dasarnya menerangkan kenapa belum siap",
      kosong["garis_dasar"]["siap"] is False
      and bool(kosong["garis_dasar"]["alasan"]))
benar("periksa(None) tidak meledak", anomali.periksa(None)["temuan"] == [])

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

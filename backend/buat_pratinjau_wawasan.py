"""Build a STATIC preview of the Insights / SOC Agent / Tenant pages.

The Thymeleaf test proves the page renders and the controller test proves the
time window is bounded, but neither can see a card shrinking until its name is
unreadable, two colors clashing, or a `<select>` taking the whole page width.
The REAL CSS and JavaScript are loaded; only `ambilJson()` is replaced.

Data comes from the primary lab instance when reachable and falls back to
built-in samples otherwise. Real numbers expose layout defects invented ones
do not (longest rows, longest names, non-round values).

Run:     venv\\Scripts\\python.exe buat_pratinjau_wawasan.py
Output:  <project-folder>/pratinjau-wawasan.html
"""
import io
import json
import os
import urllib.error
import urllib.request

_PROYEK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AKAR = os.path.join(_PROYEK, "frontend", "src", "main", "resources", "static")
_REL = "frontend/src/main/resources/static/"
KELUAR = os.path.join(_PROYEK, "pratinjau-wawasan.html")

# Fetched from the running API: localhost first (uvicorn on the laptop), then
# nsm-app, whose port 8000 listens on localhost only, so in practice localhost.
DASAR = "http://127.0.0.1:8000"


def baca(rel):
    with io.open(os.path.join(AKAR, rel), encoding="utf-8") as f:
        return f.read()


def ambil(jalur, bawaan):
    try:
        with urllib.request.urlopen(DASAR + jalur, timeout=40) as r:
            d = json.load(r)
            print("  %-24s dari LAB" % jalur)
            return d
    except Exception as e:                        # noqa: BLE001
        print("  %-24s pakai contoh bawaan (%s)" % (jalur, str(e)[:60]))
        return bawaan


CONTOH_BASELINE = {
    "ambang": 3.0, "mengejar": False, "tertinggal_baris": 0, "catatan": None,
    "belum_cukup": 1,
    "aneh": [], "semua": [
        {"layak": True, "device": "Direktori LDAP (Lokasi B)", "slot": 159,
         "slot_teks": "Minggu pukul 15.00", "nilai": 401.9, "biasanya": 352.6,
         "simpangan": 54.0, "n": 720, "sigma": 0.73, "aneh": False,
         "kalimat": "Direktori LDAP (Lokasi B) biasanya 352.6 ms pada Minggu "
                    "pukul 15.00. Sekarang 401.9 ms -- 0.7 simpangan dari "
                    "kebiasaannya."}]}

CONTOH_POLA = {
    "jam": 24, "tersedia": True, "total_templat": 10, "total_pesan": 968,
    "baru": [{"id": 23, "templat": "%SEC-6-IPACCESSLOGP: list <*> denied tcp <*> -> <*>",
              "jumlah": 7, "pertama": "2026-08-23T11:03:40",
              "terakhir": "2026-08-23T15:07:35", "severity_min": 6,
              "jumlah_device": 1, "ditinjau": False}],
    "tersering": [{"id": 18, "templat": "%CDP-4-DUPLEX_MISMATCH: duplex mismatch discovered on <*> (not <*> duplex), with <*> <*> <*> duplex).",
                   "jumlah": 857, "pertama": "2026-08-23T08:19:28",
                   "terakhir": "2026-08-23T15:30:00", "severity_min": 4,
                   "jumlah_device": 2, "ditinjau": False}]}

CONTOH_PRAKIRAAN = {
    "bandwidth": [{"nama": "Router Lokasi A", "vonis": "tidak_yakin",
                   "puncak_bps": 12000.0, "laju_bps_per_hari": 12300.0,
                   "horizon_teks": None,
                   "alasan": "Trennya terukur tetapi titiknya BERSERAK (R2 0.12), "
                             "jadi angkanya kasar (naik 12.3 kbit/s per hari), "
                             "tetapi kapasitas link ini tidak pernah dinyatakan "
                             "di NSM."}],
    "latency": [{"nama": "Switch Lokasi A", "vonis": "tidak_yakin",
                 "latency_kini_ms": 82.7, "laju_persen_per_minggu": 124.2,
                 "alasan": "Titiknya berserak, jadi angka ini kasar: Latency "
                           "Switch Lokasi A naik 124.2% per minggu selama 4 "
                           "minggu terakhir -- kini 82.7 ms."}]}

CONTOH_ANGGARAN = {"anggaran": [
    {"nama": "Gateway WiFi", "vonis": "habis", "sisa_persen": -12.0,
     "target_persen": 99.0, "horizon_teks": None,
     "alasan": "Anggaran galat sudah habis terlampaui. Prakiraan tidak lagi "
               "relevan -- yang dibutuhkan keputusan, bukan angka."}]}

CONTOH_AGEN = {"jam": 24, "aktif": False, "mode": "usul", "narasi_ai": False,
               "usulan": [], "diusulkan": 0, "diizinkan_pagar": 0,
               "ditolak_pagar": 0}

CONTOH_TENANT = {"tenant": [
    {"id": 1, "nama": "BSP (lab)", "kontak": None, "aktif": True,
     "kuota_device": None, "device": 11, "penuh": False,
     "dibuat": "2026-08-23T14:00:00",
     "catatan": "Dibuat migrate_tenant.py sebagai pemilik seluruh perangkat "
                "lab yang sudah ada sebelum Paket D."}],
    "tanpa_tenant": []}


print("Mengambil data:")
DATA = {
    "/api/baseline": ambil("/baseline", CONTOH_BASELINE),
    "/api/pola-log": ambil("/pola-log?jam=24", CONTOH_POLA),
    "/api/prakiraan": ambil("/prakiraan", CONTOH_PRAKIRAAN),
    "/api/prakiraan/anggaran": ambil("/prakiraan/anggaran", CONTOH_ANGGARAN),
    "/api/agen-soc": ambil("/agen-soc?jam=24", CONTOH_AGEN),
    "/api/tenant": ambil("/tenant", CONTOH_TENANT),
}

BAGIAN = """
<div class="pemisah-pratinjau">%s</div>
%s
"""

HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PRATINJAU - Wawasan / Agen SOC / Tenant</title>
<link rel="stylesheet" href="%(css_nsm)s">
<link rel="stylesheet" href="%(css_hal)s">
<style>
  .spanduk-tiruan {
    background: #7c2d12; color: #fed7aa; border: 1px solid #c2410c;
    padding: 8px 14px; border-radius: 6px; font-size: 13px;
    margin: 0 0 16px; font-weight: 600;
  }
  .pemisah-pratinjau {
    margin: 46px 0 20px; border-top: 2px dashed #444; padding-top: 18px;
    color: #8a8a8a; font-size: 12px; text-transform: uppercase;
    letter-spacing: .6px;
  }
</style>
</head>
<body>

<div class="spanduk-tiruan">
  PRATINJAU TATA LETAK &mdash; CSS dan JavaScript SUNGGUHAN, data dari API
  lab (atau contoh bawaan kalau API tidak terjangkau).
</div>

<div class="pita-merek"></div>
<div class="bilah">
  <div class="judul-kiri">
    <h1>Wawasan</h1>
    <span class="anak-judul">apa yang NSM pelajari dari jaringannya sendiri</span>
  </div>
  <nav class="nav" aria-label="Menu utama">
    <a href="#">Dashboard</a><a href="#">Report</a><a href="#">Insiden</a>
    <a href="#">Layanan</a><a href="#">Lalu Lintas</a>
    <a href="#" class="aktif">Wawasan</a>
    <a href="#">Backup</a><a href="#">Kesehatan</a>
    <details class="menu-nav"><summary>Admin</summary></details>
    <details class="menu-nav"><summary>Akun</summary></details>
  </nav>
</div>

<div class="jalur">
  <span class="kini">Wawasan</span><span class="pisah">|</span>
  <a href="#">Agen SOC</a><span class="pisah">|</span><a href="#">Tenant</a>
</div>

<div class="pemisah-pratinjau">HALAMAN 1 &mdash; /wawasan</div>

<h4 class="kepala judul-ikon">Kebiasaan perangkat &mdash; dan yang menyimpang darinya</h4>
<div id="baseline-catatan"></div>
<div id="baseline-ringkas" class="kisi-4"></div>
<div id="baseline"></div>

<h4 class="kepala judul-ikon">Pola pesan log</h4>
<div id="pola-ringkas" class="kisi-4"></div>
<div class="wsn-dua">
  <div><h5 class="wsn-subjudul">Pola BARU (24 jam terakhir)</h5>
    <div id="pola-baru"></div></div>
  <div><h5 class="wsn-subjudul">Pola tersering</h5>
    <div id="pola-sering"></div></div>
</div>

<h4 class="kepala judul-ikon">Ke mana angkanya menuju</h4>
<h5 class="wsn-subjudul">Tren latency</h5>
<div id="prakiraan-latency"></div>
<h5 class="wsn-subjudul">Saturasi bandwidth</h5>
<div id="prakiraan-bandwidth"></div>
<h5 class="wsn-subjudul">Anggaran galat</h5>
<div id="prakiraan-anggaran"></div>

<div class="pemisah-pratinjau">HALAMAN 2 &mdash; /agen</div>
<h4 class="kepala judul-ikon">Keadaan saklar</h4>
<div id="agen-saklar"></div>
<h4 class="kepala judul-ikon">Rekam jejak</h4>
<div id="agen-ringkas" class="kisi-4"></div>
<div id="alat">
  <label for="jendela" class="kecil redup">Jendela</label>
  <select id="jendela"><option value="24">24 jam terakhir</option></select>
  <span id="meta" class="kecil redup"></span>
</div>
<h4 class="kepala judul-ikon">Usulan</h4>
<div id="agen-usulan"></div>

<div class="pemisah-pratinjau">HALAMAN 3 &mdash; /admin/tenant</div>
<h4 class="kepala judul-ikon">Penyewa</h4>
<div id="tenant-daftar"></div>
<h4 class="kepala judul-ikon">Perangkat yang belum punya pemilik</h4>
<div id="tenant-yatim"></div>

<script>
var DATA = %(data)s;
function ambilJson(url) {
  var bersih = url.split("?")[0];
  return new Promise(function (res, rej) {
    if (DATA[bersih] === undefined) rej(new Error("tidak ada data tiruan untuk " + bersih));
    else res(DATA[bersih]);
  });
}
</script>
<script src="%(js_waktu)s"></script>
<script src="%(js_hal)s"></script>
<script>
// `wawasan.js` memilih SATU halaman dari elemen yang ada. Di pratinjau ini
// ketiganya ada sekaligus, jadi dua sisanya dipanggil langsung.
setTimeout(function () {
  ambilJson("/api/agen-soc").then(gambarAgen);
  ambilJson("/api/tenant").then(gambarTenant);
}, 80);
</script>
</body>
</html>
""" % {
    "css_nsm": _REL + "css/nsm.css",
    "css_hal": _REL + "css/wawasan.css",
    "js_waktu": _REL + "js/waktu.js",
    "js_hal": _REL + "wawasan.js",
    # `</script>` INSIDE DATA WOULD TERMINATE THE SCRIPT BLOCK.
    #
    # Log templates come from unauthenticated UDP syslog messages, so anyone on the
    # network could embed `</script>`. The replacement is a form that is valid inside
    # a JavaScript string and parses to exactly the same text.
    "data": (json.dumps(DATA, ensure_ascii=False, default=str)
             .replace("</", r"<\/")),
}

with io.open(KELUAR, "w", encoding="utf-8") as f:
    f.write(HTML)
print()
print("Ditulis: %s (%.0f KB)" % (KELUAR, len(HTML) / 1024.0))

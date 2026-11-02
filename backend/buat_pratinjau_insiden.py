"""Build a STATIC preview of the Incidents page using the REAL CSS and JS.

`InsidenTemplateTest` proves the page renders and `uji_insiden.js` proves the
logic, but neither can see a card shrinking until its name is unreadable or two
colors clashing. This does not replace opening the real page with a real
account; it covers what needs no account: layout, color, size, and whether the
JavaScript actually draws something.

The data is SIMULATED and clearly labeled as such in the title, so screenshots
are never mistaken for real data.
"""
import io
import json
import os

_PROYEK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

AKAR = os.path.join(_PROYEK, "frontend", "src", "main",
                    "resources", "static")
# Paths are RELATIVE from the project root to the static files. They are
# referenced, not inlined, so the preview stays small and always uses the files
# currently on disk.
_REL = "frontend/src/main/resources/static/"
KELUAR = os.path.join(_PROYEK, "pratinjau-insiden.html")


def baca(rel):
    with io.open(os.path.join(AKAR, rel), encoding="utf-8") as f:
        return f.read()


DAFTAR = {
    "terbuka": [{
        "id": 12, "mulai": "2026-08-23T14:05:00", "selesai": None,
        "status": "terbuka", "akar": "Router Lokasi A", "akar_pasti": True,
        "keparahan": "bahaya",
        "ringkas": "Router Lokasi A bermasalah, dan 3 perangkat lain ikut "
                   "terdampak. 4 gejala tercatat.",
        "jumlah_gejala": 4, "mttr_detik": None,
    }],
    "pulih": [
        {"id": 11, "mulai": "2026-08-23T09:12:00",
         "selesai": "2026-08-23T09:20:30", "status": "pulih",
         "akar": "Direktori LDAP (Lokasi B)", "akar_pasti": True,
         "keparahan": "perhatian",
         "ringkas": "Direktori LDAP (Lokasi B) bermasalah. 2 gejala tercatat.",
         "jumlah_gejala": 2, "mttr_detik": 510},
        {"id": 10, "mulai": "2026-08-23T03:44:00",
         "selesai": "2026-08-23T03:46:12", "status": "pulih",
         "akar": None, "akar_pasti": False, "keparahan": "info",
         "ringkas": "Gangguan yang akarnya belum bisa dipastikan. 1 gejala "
                    "tercatat.",
         "jumlah_gejala": 1, "mttr_detik": 132},
    ],
    "jam": 24,
}

DETAIL = {
    "ada": True, "id": 12, "status": "terbuka",
    "mulai": "2026-08-23T14:05:00", "selesai": None,
    "akar": "Router Lokasi A", "akar_id": 5, "akar_pasti": True,
    "keparahan": "bahaya", "mttr_detik": None, "jumlah_gejala": 4,
    "ringkas": "Router Lokasi A bermasalah, dan 3 perangkat lain ikut "
               "terdampak. 4 gejala tercatat.",
    "gejala": [
        {"jenis": "device", "device_id": 5, "device": "Router Lokasi A",
         "adalah_akar": True, "waktu": "2026-08-23T14:05:00",
         "waktu_terakhir": "2026-08-23T14:11:00", "pulih_pada": None,
         "jumlah": 7, "pulih": False,
         "detail": "Device Router Lokasi A tidak terjangkau"},
        {"jenis": "device", "device_id": 9, "device": "Router Lokasi B",
         "adalah_akar": False, "waktu": "2026-08-23T14:05:40",
         "waktu_terakhir": "2026-08-23T14:11:00", "pulih_pada": None,
         "jumlah": 6, "pulih": False,
         "detail": "Device Router Lokasi B tidak terjangkau"},
        {"jenis": "device", "device_id": 10, "device": "Switch Lokasi B",
         "adalah_akar": False, "waktu": "2026-08-23T14:06:10",
         "waktu_terakhir": "2026-08-23T14:09:00",
         "pulih_pada": "2026-08-23T14:10:20", "jumlah": 4, "pulih": True,
         "detail": "Device Switch Lokasi B tidak terjangkau"},
        {"jenis": "device", "device_id": 4,
         "device": "Direktori LDAP (Lokasi B)", "adalah_akar": False,
         "waktu": "2026-08-23T14:06:55", "waktu_terakhir": "2026-08-23T14:11:00",
         "pulih_pada": None, "jumlah": 5, "pulih": False,
         "detail": "Device Direktori LDAP (Lokasi B) tidak terjangkau"},
    ],
}

HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PRATINJAU (data tiruan) - Halaman Insiden NSM</title>
<link rel="stylesheet" href="%(css_nsm)s">
<link rel="stylesheet" href="%(css_hal)s">
<style>
  .spanduk-tiruan {
    background: #7c2d12; color: #fed7aa; border: 1px solid #c2410c;
    padding: 8px 14px; border-radius: 6px; font-size: 13px;
    margin: 0 0 16px; font-weight: 600;
  }
  .pemisah-pratinjau {
    margin: 44px 0 20px; border-top: 2px dashed #444; padding-top: 18px;
    color: #8a8a8a; font-size: 12px; text-transform: uppercase;
    letter-spacing: .6px;
  }
</style>
<meta name="insiden-id" content="12">
</head>
<body>

<div class="spanduk-tiruan">
  PRATINJAU TATA LETAK &mdash; datanya TIRUAN, bukan dari lab.
  CSS dan JavaScript-nya sungguhan.
</div>

<div class="pita-merek"></div>
<div class="bilah">
  <div class="judul-kiri">
    <h1>Insiden</h1>
    <span class="anak-judul">satu gangguan, bukan satu gejala</span>
  </div>
  <nav class="nav" aria-label="Menu utama">
    <a href="#">Dashboard</a>
    <a href="#">Report</a>
    <a href="#" class="aktif">Insiden</a>
    <a href="#">Layanan</a>
    <a href="#">Lalu Lintas</a>
    <a href="#">Backup</a>
    <a href="#">Kesehatan</a>
    <details class="menu-nav"><summary>Admin</summary></details>
    <details class="menu-nav"><summary>Akun</summary></details>
  </nav>
</div>

<div class="pemisah-pratinjau">Halaman 1 &mdash; daftar insiden (/insiden)</div>

<div id="alat">
  <label for="jendela" class="kecil redup">Jendela</label>
  <select id="jendela">
    <option value="24" selected>24 jam terakhir</option>
    <option value="72">3 hari terakhir</option>
  </select>
  <span id="meta" class="kecil redup"></span>
</div>

<div id="ringkas-insiden" class="kisi-4"></div>

<h4 class="kepala judul-ikon">Sedang berlangsung</h4>
<div id="terbuka"></div>

<h4 class="kepala judul-ikon">Sudah pulih</h4>
<div id="pulih"></div>

<div class="pemisah-pratinjau">
  Halaman 2 &mdash; garis waktu satu insiden (/insiden/12)
</div>

<div class="jalur"><a class="pulang" href="#">&larr; Semua insiden</a></div>
<div id="kepala-insiden"></div>
<h4 class="kepala judul-ikon">Garis waktu</h4>
<div id="garis-waktu"></div>

<script>
// Tiruan `ambilJson` dari js/halaman.js -- SATU-SATUNYA bagian yang ditiru.
// Sisanya (waktu.js, insiden.js) dimuat apa adanya.
var DATA_DAFTAR = %(daftar)s;
var DATA_DETAIL = %(detail)s;
function ambilJson(url) {
  return new Promise(function (res) {
    res(url.indexOf("/api/insiden/") === 0 ? DATA_DETAIL : DATA_DAFTAR);
  });
}
</script>
<script src="%(js_waktu)s"></script>
<script src="%(js_hal)s"></script>
<script>
// insiden.js memilih SATU halaman dari elemen yang ada. Di pratinjau ini
// keduanya ada, jadi bagian detailnya dipanggil sekali lagi secara langsung.
setTimeout(function () { muatDetail(12); }, 60);
</script>
</body>
</html>
""" % {
    "css_nsm": _REL + "css/nsm.css",
    "css_hal": _REL + "css/insiden.css",
    "js_waktu": _REL + "js/waktu.js",
    "js_hal": _REL + "insiden.js",
    "daftar": json.dumps(DAFTAR, ensure_ascii=False),
    "detail": json.dumps(DETAIL, ensure_ascii=False),
}

with io.open(KELUAR, "w", encoding="utf-8") as f:
    f.write(HTML)
print("Ditulis: %s (%.0f KB)" % (KELUAR, len(HTML) / 1024.0))

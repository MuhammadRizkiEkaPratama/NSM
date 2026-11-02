"""Build a STATIC preview of the Syslog page.

The Thymeleaf test proves the page renders and the Python test proves the
numbers, but neither can see a column shrinking until unreadable, two colors
clashing in light mode, or an ECharts chart overlapping its title.

Two differences from the other preview scripts:

1. `window.fetch` is intercepted, not `ambilJson`. `syslog.js` calls `fetch`
   directly to send filters as parameters, so the replacement also READS those
   parameters; tag buttons, sender, pagination, and search then work in the
   preview.

2. Data comes from the DATABASE, not the API. `uvicorn` on nsm-app listens on
   `127.0.0.1` only (a deliberate security choice), so the API is unreachable
   from the laptop. This script calls `syslog_service` directly against the
   primary lab MySQL; the result matches what the API would send, since the API
   only wraps the same functions.

Run:     venv\\Scripts\\python.exe buat_pratinjau_syslog.py
Output:  <project-folder>/pratinjau-syslog.html
"""
import io
import json
import os

_PROYEK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REL = "frontend/src/main/resources/static/"
KELUAR = os.path.join(_PROYEK, "pratinjau-syslog.html")


def aset(rel):
    """Static file paths plus their modification time as a version marker.

    The files are referenced, not inlined, so the preview uses the CSS and
    JavaScript currently on disk. Browsers cache files with the same path, so an
    edited CSS could keep showing the old version after a rebuild and reload; the
    timestamp busts that cache.
    """
    full = os.path.join(_PROYEK, _REL.replace("/", os.sep), rel.replace("/", os.sep))
    stamp = int(os.path.getmtime(full)) if os.path.exists(full) else 0
    return "%s%s?v=%d" % (_REL, rel, stamp)

JAM = 24
PER_HALAMAN = 5


def fetch_data():
    """Call syslog_service directly. If the database is unreachable, stop with a
    clear message instead of building a preview from invented samples: real data
    finds layout defects invented numbers never do (longest names, non-round
    values, overflowing rows).
    """
    import database
    import syslog_service as ss
    from sqlalchemy.orm import Session

    mesin = database.engine if hasattr(database, "engine") else database.buat_engine()
    with Session(mesin) as db:
        dasbor = ss.dasbor(db, jam=JAM)

        halaman = {}
        for h in range(1, 4):
            halaman["h%d" % h] = ss.daftar(db, jam=JAM, halaman=h,
                                           per_halaman=PER_HALAMAN)
        penting = ss.daftar(db, jam=JAM, hanya_penting=True,
                            per_halaman=PER_HALAMAN)
        per_tag = {}
        for t in dasbor["per_tag"][:4]:
            per_tag[t["tag"]] = ss.daftar(db, jam=JAM, tag=t["tag"],
                                          per_halaman=PER_HALAMAN)
        per_dev = {}
        for d in dasbor["per_device"][:4]:
            if d["device_id"] is not None:
                per_dev[str(d["device_id"])] = ss.daftar(
                    db, jam=JAM, device_id=d["device_id"],
                    per_halaman=PER_HALAMAN)

    return {"dasbor": dasbor, "halaman": halaman, "penting": penting,
            "per_tag": per_tag, "per_dev": per_dev}


print("Mengambil data dari MySQL lab...")
DATA = fetch_data()
d = DATA["dasbor"]
print("  %d pesan, %d pengirim, %d tag, %d titik grafik"
      % (d["total"], len(d["per_device"]), len(d["per_tag"]), len(d["deret"])))

# Page skeleton copied from the Thymeleaf template with th:* attributes removed.
# Copied, not rendered: rendering would mean starting all of Spring Boot for one
# HTML file.
ISI = io.open(os.path.join(_PROYEK, "frontend", "src", "main", "resources",
                           "templates", "syslog.html"), encoding="utf-8").read()
awal = ISI.index("<!-- ===================== BARIS KENDALI")
akhir = ISI.index('<script src="/vendor/echarts.min.js">')
BADAN = ISI[awal:akhir]

HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PRATINJAU - Syslog</title>
<script src="%(js_tema)s"></script>
<link rel="stylesheet" href="%(font)s">
<link rel="stylesheet" href="%(css_nsm)s">
<link rel="stylesheet" href="%(css_hal)s">
<style>
  .spanduk-tiruan {
    background: var(--permukaan-3); color: var(--teks-2);
    border: 1px solid var(--garis); padding: 9px 15px;
    border-radius: var(--r-sedang); font-size: 13px; margin: 0 0 18px;
  }
  .spanduk-tiruan b { color: var(--teks); }
  .saklar-pratinjau {
    display: inline-flex; gap: 2px; padding: 2px; margin-left: 10px;
    background: var(--permukaan); border: 1px solid var(--garis);
    border-radius: 999px; vertical-align: middle;
  }
  .saklar-pratinjau button {
    font: inherit; font-size: 12px; font-weight: 600; padding: 3px 12px;
    border: 0; border-radius: 999px; background: transparent;
    color: var(--teks-redup); cursor: pointer;
  }
  .saklar-pratinjau button[aria-pressed="true"] {
    background: var(--permukaan-3); color: var(--teks);
  }
</style>
</head>
<body>

<div class="spanduk-tiruan">
  <b>PRATINJAU TATA LETAK</b> &mdash; CSS dan JavaScript SUNGGUHAN, data
  sungguhan dari MySQL lab. Hanya <code>fetch</code> yang diganti.
  Tema:
  <span class="saklar-pratinjau">
    <button type="button" data-p-tema="dark" aria-pressed="true">Gelap</button>
    <button type="button" data-p-tema="light" aria-pressed="false">Terang</button>
  </span>
</div>

<div class="pita-merek"></div>
<div class="bilah">
  <div class="judul-kiri">
    <h1>Syslog</h1>
    <span class="anak-judul">apa yang perangkat kabarkan sendiri</span>
  </div>
  <nav class="nav" aria-label="Menu utama">
    <a href="#">Dashboard</a><a href="#">Report</a><a href="#">Insiden</a>
    <a href="#">Layanan</a><a href="#">Lalu Lintas</a><a href="#">Wawasan</a>
    <a href="#" class="aktif">Syslog</a>
    <a href="#">Backup</a><a href="#">Kesehatan</a>
  </nav>
</div>

%(badan)s

<script>
var TIRUAN = %(data)s;

/* `syslog.js` memanggil `fetch` langsung, jadi yang dihadang adalah `fetch`
   itu sendiri -- dan penggantinya IKUT MEMBACA parameter penyaringnya,
   supaya tombol tag, pengirim, paginasi, dan pencarian benar-benar bisa
   dicoba. Pratinjau yang tombolnya mati hanya membuktikan setengahnya. */
window.fetch = function (url) {
  var u = new URL(url, "http://x");
  var jalur = u.pathname;
  var p = u.searchParams;

  function balas(obj) {
    return Promise.resolve({ ok: true, status: 200,
                             json: function () { return Promise.resolve(obj); } });
  }

  if (jalur === "/api/syslog/dasbor") return balas(TIRUAN.dasbor);

  if (jalur === "/api/syslog/pesan") {
    if (p.get("penting") === "true") return balas(TIRUAN.penting);
    if (p.get("tag") && TIRUAN.per_tag[p.get("tag")]) {
      return balas(TIRUAN.per_tag[p.get("tag")]);
    }
    if (p.get("deviceId") && TIRUAN.per_dev[p.get("deviceId")]) {
      return balas(TIRUAN.per_dev[p.get("deviceId")]);
    }
    if (p.get("cari")) {
      /* Pencarian disaring di sisi klien dari halaman pertama saja. Cukup
         untuk memeriksa TAMPILANNYA -- termasuk keadaan "tidak ada yang
         cocok", yang justru paling sering lupa didesain. */
      var dasar = TIRUAN.halaman.h1;
      var kata = p.get("cari").toLowerCase();
      var cocok = dasar.pesan.filter(function (x) {
        return x.pesan.toLowerCase().indexOf(kata) >= 0 ||
               (x.tag || "").toLowerCase().indexOf(kata) >= 0;
      });
      return balas({ total: cocok.length, halaman: 1, per_halaman: 5,
                     jumlah_halaman: 1, pesan: cocok });
    }
    var h = "h" + (p.get("halaman") || "1");
    return balas(TIRUAN.halaman[h] || TIRUAN.halaman.h1);
  }

  return Promise.reject(new Error("tidak ada data tiruan untuk " + jalur));
};
</script>
<script src="%(echarts)s"></script>
<script src="%(js_waktu)s"></script>
<script src="%(js_hal)s"></script>
<script src="%(js_pratinjau_tema)s"></script>
</body>
</html>
""" % {
    "js_tema": aset("js/tema.js"),
    "font": aset("vendor/font/manrope.css"),
    "css_nsm": aset("css/nsm.css"),
    "css_hal": aset("css/syslog.css"),
    "echarts": aset("vendor/echarts.min.js"),
    "js_waktu": aset("js/waktu.js"),
    "js_hal": aset("syslog.js"),
    "js_pratinjau_tema": aset("js/pratinjau-tema.js"),
    "badan": BADAN,
    # `</script>` INSIDE DATA WOULD TERMINATE THE SCRIPT BLOCK.
    #
    # Message text comes from unauthenticated UDP syslog: anyone on the network can
    # send a message containing `</script>`, and once embedded as-is the rest of the
    # file stops being JavaScript and becomes HTML.
    "data": (json.dumps(DATA, ensure_ascii=False, default=str)
             .replace("</", r"<\/")),
}

io.open(KELUAR, "w", encoding="utf-8", newline="\n").write(HTML)
print("Ditulis: %s (%d KB)" % (KELUAR, os.path.getsize(KELUAR) // 1024))

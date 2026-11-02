# -*- coding: utf-8 -*-
"""Static preview of the three Dashboard charts, using data from the primary lab instance.

Why: the Thymeleaf test proves the panels render and the Python test proves
the numbers, but neither can see whether ECharts actually draws, whether the
horizontal Capacity bars leave room for server names PLUS the percentage, or
whether the clipped vertical Availability axis pushes the line out of the box.
Those can only be seen, and the real page needs a login.
"""
import io
import json
import os

_PROYEK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REL = "frontend/src/main/resources/static/"
KELUAR = os.path.join(_PROYEK, "pratinjau-dasbor-grafik.html")


def aset(rel):
    full = os.path.join(_PROYEK, _REL.replace("/", os.sep), rel.replace("/", os.sep))
    stamp = int(os.path.getmtime(full)) if os.path.exists(full) else 0
    return "%s%s?v=%d" % (_REL, rel, stamp)


import database                     # noqa: E402
import dasbor_grafik as dg          # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

mesin = database.engine if hasattr(database, "engine") else database.buat_engine()
with Session(mesin) as db:
    DATA = dg.semua(db, jam=24)

print("Data lab: %d titik ketersediaan, %d titik pesan, %d server"
      % (len(DATA["ketersediaan"]), len(DATA["pesan"]), len(DATA["kapasitas"])))

# The panel markup is COPIED from the template, not rewritten; a rewrite could
# look right while the real page is broken.
TPL = io.open(os.path.join(_PROYEK, "frontend", "src", "main", "resources",
                           "templates", "dashboard.html"), encoding="utf-8").read()
awal = TPL.index("<!-- TIGA GRAFIK TAMBAHAN")
akhir = TPL.index("</div>", TPL.index('id="dg-kapasitas-kaki"')) + len("</div>")
PANEL = TPL[awal:akhir] + "\n  </div>"

HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PRATINJAU - Tiga Grafik Dashboard</title>
<script src="%(tema)s"></script>
<link rel="stylesheet" href="%(font)s">
<link rel="stylesheet" href="%(nsm)s">
<style>
  body { padding: 20px; }
  .spanduk {
    background: var(--permukaan-3); color: var(--teks-2);
    border: 1px solid var(--garis); padding: 9px 15px;
    border-radius: var(--r-sedang); font-size: 13px; margin: 0 0 16px;
  }
  .spanduk b { color: var(--teks); }
  .saklar { display: inline-flex; gap: 2px; padding: 2px; margin-left: 10px;
            background: var(--permukaan); border: 1px solid var(--garis);
            border-radius: 999px; vertical-align: middle; }
  .saklar button { font: inherit; font-size: 12px; font-weight: 600;
                   padding: 3px 12px; border: 0; border-radius: 999px;
                   background: transparent; color: var(--teks-redup); cursor: pointer; }
  .saklar button[aria-pressed="true"] { background: var(--permukaan-3); color: var(--teks); }
  /* Lebar kolom kanan yang SAMA dengan di dashboard. Kalau di pratinjau
     dibuat lebar, cacat "angka persen menabrak tepi" tidak akan pernah
     terlihat -- dan itu justru cacat yang paling mungkin ada. */
  .kolom { width: 330px; display: grid; gap: 14px; align-content: start; }
  .papan { background: var(--permukaan); border: 1px solid var(--garis);
           border-radius: var(--r-besar); overflow: hidden; }
  .papan-kepala { padding: 9px 12px; border-bottom: 1px solid var(--garis); }
  .papan-kepala h3 { margin: 0; font-size: var(--f-bagian); font-weight: 700; }
  .dg-grafik { height: 132px; margin: 4px 4px 0; }
  .dg-grafik.dg-tinggi { height: 118px; }
  .dg-kaki { padding: 6px 12px 11px; font-size: var(--f-xs);
             color: var(--teks-redup); line-height: 1.45; }
  .jelas-isi { display: none; }
</style>
</head>
<body>

<div class="spanduk">
  <b>PRATINJAU</b> &mdash; CSS dan JavaScript SUNGGUHAN, data sungguhan dari
  MySQL lab, lebar kolom sama dengan di Dashboard. Tema:
  <span class="saklar">
    <button type="button" data-p-tema="dark" aria-pressed="true">Gelap</button>
    <button type="button" data-p-tema="light" aria-pressed="false">Terang</button>
  </span>
</div>

<div class="kolom">
%(panel)s

<script>
var TIRUAN = %(data)s;
window.fetch = function (url) {
  if (String(url).indexOf("/api/dasbor/grafik") >= 0) {
    return Promise.resolve({ ok: true, status: 200,
      json: function () { return Promise.resolve(TIRUAN); } });
  }
  return Promise.reject(new Error("tidak ada data tiruan untuk " + url));
};
</script>
<script src="%(echarts)s"></script>
<script src="%(dg)s"></script>
<script src="%(pratinjau_tema)s"></script>
</body>
</html>
""" % {
    "tema": aset("js/tema.js"),
    "font": aset("vendor/font/manrope.css"),
    "nsm": aset("css/nsm.css"),
    "echarts": aset("vendor/echarts.min.js"),
    "dg": aset("js/dasbor-grafik.js"),
    "pratinjau_tema": aset("js/pratinjau-tema.js"),
    "panel": PANEL,
    # `</` is escaped so data cannot terminate the script block.
    "data": json.dumps(DATA, ensure_ascii=False, default=str).replace("</", r"<\/"),
}

io.open(KELUAR, "w", encoding="utf-8", newline="\n").write(HTML)
print("Ditulis: %s (%d KB)" % (KELUAR, os.path.getsize(KELUAR) // 1024))

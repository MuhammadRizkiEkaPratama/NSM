"""Tests table structure in the UI: every table must have a direct wrapper.
`table { display: block; overflow-x: auto; }` made tables shrink to their content. The fix splits roles: the table handles column width (`display: table; width: 100%`) and the wrapper `div.gulir-tabel { overflow-x: auto }` handles scrolling. A table added without the wrapper would push the whole page sideways.
Pure check of the template files; no network, database or browser.
Run: py uji_templat_tabel.py
"""
import glob
import io
import os
import re
import sys

lolos = 0
gagal = 0


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print(f"  LOLOS  {nama}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama} {ket}")


# Templates live on the Java side; located relative to this file so the test runs from any folder.
DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLAT = os.path.normpath(os.path.join(
    DIR, "..", "frontend", "src", "main", "resources", "templates"))
STATIK = os.path.normpath(os.path.join(
    DIR, "..", "frontend", "src", "main", "resources", "static"))

print("=" * 74)
print("1. SETIAP <table> DI TEMPLAT PUNYA PEMBUNGKUS PENGGULIR")
print("   Tanpa pembungkus, tabel lebar mendorong SELURUH halaman ke")
print("   samping alih-alih menggulir sendiri.")
print("=" * 74)

benar("folder templat ketemu", os.path.isdir(TEMPLAT), "-> %s" % TEMPLAT)

# `(?s)` so `.` crosses newlines; non-greedy so each table pairs with its own closing tag.
POLA_TABEL = re.compile(r"<table\b[^>]*>.*?</table>", re.S)

tanpa_bungkus = []
jumlah_tabel = 0
for p in sorted(glob.glob(os.path.join(TEMPLAT, "*.html"))):
    s = io.open(p, encoding="utf-8").read()
    for m in POLA_TABEL.finditer(s):
        jumlah_tabel += 1
        # Checks the 200 characters just before <table>; the wrapper must be the direct one.
        sebelum = s[max(0, m.start() - 200):m.start()]
        if 'class="gulir-tabel"' not in sebelum:
            tanpa_bungkus.append("%s:%d" % (os.path.basename(p),
                                            s[:m.start()].count("\n") + 1))

print("   -> %d tabel diperiksa di %d berkas templat"
      % (jumlah_tabel, len(glob.glob(os.path.join(TEMPLAT, "*.html")))))
benar("ada tabel untuk diperiksa (uji ini tidak boleh lolos karena kosong)",
      jumlah_tabel >= 25, "-> cuma %d" % jumlah_tabel)
benar("semua tabel templat terbungkus",
      not tanpa_bungkus, "-> tanpa pembungkus: %s" % ", ".join(tanpa_bungkus[:6]))


print()
print("=" * 74)
print("2. CSS-nya MEMANG dua peran terpisah, bukan dirangkap satu elemen")
print("=" * 74)

css_mentah = io.open(os.path.join(STATIK, "css", "nsm.css"),
                     encoding="utf-8").read()

# Strip comments first: the old, wrong rule is quoted in a CSS comment on purpose, and must not be read as an active rule.
css = re.sub(r"/\*.*?\*/", "", css_mentah, flags=re.S)

# The rule that caused the defect must no longer exist as a rule (its wording may remain in comments).
aturan_lama = re.search(r"^\s*table\s*\{[^}]*display:\s*block", css, re.M)
benar("aturan `table { display: block }` sudah TIDAK ada",
      aturan_lama is None,
      "-> masih ada di posisi %s" % (aturan_lama.start() if aturan_lama else "-"))

benar("kelas `.gulir-tabel` didefinisikan",
      re.search(r"^\.gulir-tabel\s*\{", css, re.M) is not None)
benar("dan ia yang memegang overflow-x: auto",
      re.search(r"^\.gulir-tabel\s*\{[^}]*overflow-x:\s*auto", css, re.M | re.S)
      is not None)
benar("tabel tetap width: 100% supaya mengisi pembungkusnya",
      re.search(r"^table\s*\{[^}]*width:\s*100%", css, re.M | re.S) is not None)

# `min-width: max-content` is wrong: it forces every column to its longest sentence, so tables with comment columns would always scroll.
benar("tabel TIDAK dipaksa `min-width: max-content` (bikin teks tak membungkus)",
      re.search(r"^table\s*\{[^}]*min-width:\s*max-content", css, re.M | re.S)
      is None)

# Paper cannot scroll: content cut off on screen is acceptable, on paper it is lost.
benar("saat dicetak, pembungkus dibuat overflow: visible",
      re.search(r"@media print\s*\{[^}]*\.gulir-tabel\s*\{[^}]*overflow:\s*visible",
                css, re.S) is not None)


print()
print("=" * 74)
print("3. TABEL YANG DIBANGUN DARI JS JUGA DIBUNGKUS")
print("   Templat bukan satu-satunya sumber tabel. `report_device.js`")
print("   membangun enam tabel sendiri; kalau yang ini terlewat, cacatnya")
print("   kembali persis di halaman rincian device.")
print("=" * 74)

for berkas in ["report_device.js", "drift.js", "konfig.js"]:
    jalur = os.path.join(STATIK, berkas)
    if not os.path.exists(jalur):
        benar("%s ada" % berkas, False, "-> tidak ketemu")
        continue
    js = io.open(jalur, encoding="utf-8").read()
    benar("%s punya helper bungkusTabel()" % berkas,
          "function bungkusTabel(" in js)
    # Every variable assigned from el("table") must pass through bungkusTabel().
    belum = [v for v in re.findall(r'var (\w+)\s*=\s*el\("table"', js)
             if ("bungkusTabel(%s)" % v) not in js]
    benar("%s: semua tabelnya dibungkus" % berkas, not belum,
          "-> belum: %s" % ", ".join(sorted(set(belum))))


print()
print("=" * 74)
print("4. KONTROL PAGINASI TIDAK IKUT HANYUT KE SAMPING")
print("   Kontrol disisipkan sebagai penyibling tabel. Sesudah tabel punya")
print("   pembungkus, 'sesudah tabel' berarti DI DALAM pembungkus -- jadi")
print("   tombol Berikutnya ikut menggulir dan hilang dari layar persis")
print("   ketika tabelnya cukup lebar untuk butuh digulir.")
print("=" * 74)

pag = io.open(os.path.join(STATIK, "js", "halaman-tabel.js"),
              encoding="utf-8").read()
benar("kontrol dijangkarkan ke pembungkus, bukan ke tabel",
      "gulir-tabel" in pag and "jangkar" in pag)
benar("penyisipannya memakai jangkar itu",
      re.search(r"jangkar\.parentNode\.insertBefore\(\s*kontrol", pag) is not None)
benar("pencarian kontrol lama juga lewat jangkar (bukan wadah)",
      re.search(r"var lama = jangkar\.nextElementSibling", pag) is not None)


if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

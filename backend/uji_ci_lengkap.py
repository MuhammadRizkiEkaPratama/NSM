# -*- coding: utf-8 -*-
"""CI must not silently skip test files.

`jalankan_ci.py` runs ONLY what `ci_manifest.json` lists, and the manifest is
measured once by `ci_klasifikasi.py`; it cannot know when it is stale. A CI report
saying "61 green, 0 RED" would then be true about what ran and misleading about
what was checked. This file stops that from returning silently.

Run: py uji_ci_lengkap.py
"""
import glob
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.dirname(os.path.abspath(__file__))

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


def cek(nama, dapat, harap):
    global lolos, gagal
    if dapat == harap:
        lolos += 1
        print("  LOLOS  %s: %r" % (nama, dapat))
    else:
        gagal += 1
        print("  GAGAL  %s: dapat %r, harusnya %r" % (nama, dapat, harap))


print("=" * 74)
print("Uji kelengkapan CI -- manifest tidak boleh basi diam-diam")
print("=" * 74)

import jalankan_ci

# ===========================================================================
print("\n1. `tak_terklasifikasi()` menemukan yang hilang")
# Tested with a SYNTHETIC manifest so the result does not depend on the real folder contents. The file names do exist on disk, so the difference is really measured.
semua = sorted(os.path.basename(x)
               for x in glob.glob(os.path.join(DIR, "uji_*.py")))
benar("ada berkas uji untuk diperiksa", len(semua) > 20,
      "-> %d berkas" % len(semua))

# A manifest listing EVERYTHING -> nothing missing.
penuh = {"murni": semua, "butuh_lab": [], "merah_saat_diukur": [],
         "tidak_terukur": [], "dikecualikan": []}
cek("manifest lengkap -> tidak ada yang tertinggal",
    jalankan_ci.tak_terklasifikasi(penuh), [])

# A manifest missing two files -> both must be named.
kurang = {"murni": semua[2:], "butuh_lab": [], "merah_saat_diukur": [],
          "tidak_terukur": [], "dikecualikan": []}
cek("dua berkas hilang -> keduanya ketahuan",
    jalankan_ci.tak_terklasifikasi(kurang), semua[:2])

# Any bucket counts, not just `murni`. A deliberately EXCLUDED file was decided by
# someone and must not be reported as an omission, otherwise the warning would
# always fire and stop being read.
for keranjang in ("butuh_lab", "merah_saat_diukur", "tidak_terukur",
                  "dikecualikan"):
    m = {"murni": semua[1:], "butuh_lab": [], "merah_saat_diukur": [],
         "tidak_terukur": [], "dikecualikan": []}
    m[keranjang] = [semua[0]]
    cek("berkas di '%s' terhitung sudah terklasifikasi" % keranjang,
        jalankan_ci.tak_terklasifikasi(m), [])

# Empty manifest -> ALL files missing. Without this, a function that always returns [] would pass every other test.
cek("manifest kosong -> semuanya dilaporkan hilang",
    jalankan_ci.tak_terklasifikasi(
        {"murni": [], "butuh_lab": [], "merah_saat_diukur": [],
         "tidak_terukur": [], "dikecualikan": []}),
    semua)

# ===========================================================================
print("\n2. MANIFEST YANG SEBENARNYA harus lengkap HARI INI")
# This test goes RED whenever someone adds a test file without re-measuring the manifest. That is intended.
jalur = os.path.join(DIR, "ci_manifest.json")
benar("ci_manifest.json ada", os.path.exists(jalur))

sumber_penjalan = io.open(os.path.join(DIR, "jalankan_ci.py"),
                          encoding="utf-8").read()

m = json.load(io.open(jalur, encoding="utf-8"))
hilang = jalankan_ci.tak_terklasifikasi(m)

# REPORTED, NOT ASSERTED, deliberately. The manifest is written only at the END of
# `ci_klasifikasi.py`, so during measurement it is always stale; asserting freshness
# here would make this file RED when measured and drop it into the
# `merah_saat_diukur` bucket, which runs in no mode.
#
# Enforcement lives in `jalankan_ci.py`, which checks the same thing and sets the
# exit code after the manifest is written. Section 1 proves the check logic is
# correct; this part only informs a human who runs it.
if hilang:
    print("  [CATATAN] %d berkas uji di luar manifest -- BUKAN kegagalan uji"
          % len(hilang))
    print("            ini ditegakkan oleh jalankan_ci.py (kode keluar),")
    print("            bukan di sini, sebab manifest baru ditulis di AKHIR")
    print("            pengukuran. Ukur ulang bila perlu:")
    print("            venv\\Scripts\\python.exe ci_klasifikasi.py")
    for x in hilang[:12]:
        print("              %s" % x)
else:
    print("  [CATATAN] manifest lengkap terhadap isi folder saat ini")

# Still ASSERTED: the enforcer must exist in jalankan_ci.py. Otherwise someone could remove the guard there and no test would go red.
benar("penegakan kesegaran manifest ADA di jalankan_ci.py",
      "tak_terklasifikasi(m)" in sumber_penjalan
      and "merah or not_yet" in sumber_penjalan)

# The opposite direction: a manifest naming a file that no longer exists makes CI try to run a ghost file and fail.
tercatat = set()
for kunci in ("murni", "butuh_lab", "merah_saat_diukur",
              "tidak_terukur", "dikecualikan"):
    tercatat |= set(m.get(kunci) or [])
di_disk = set(os.path.basename(x)
              for x in glob.glob(os.path.join(DIR, "*.py")))
hantu = sorted(x for x in tercatat if x not in di_disk)
benar("manifest tidak menyebut berkas yang sudah tidak ada", hantu == [],
      "-> %s" % ", ".join(hantu))

# ===========================================================================
print("\n3. Manifest basi menjatuhkan KODE KELUAR, bukan cuma mencetak")
# A warning that does not change the exit code stops nothing: the scheduler only sees the number.
sumber = io.open(os.path.join(DIR, "jalankan_ci.py"),
                 encoding="utf-8").read()
benar("kode keluar ikut memperhitungkan berkas yang hilang",
      "merah or not_yet" in sumber,
      "-> baris `return` tidak menyebut `not_yet`")
benar("dan pemeriksaannya dipanggil di dalam main()",
      "tak_terklasifikasi(m)" in sumber)

# ===========================================================================
print("\n4. CACAT 18: satu bita liar tidak boleh menghapus keluaran uji")
# Both CI runners used to call `subprocess.run(..., text=True)` without an encoding.
# On Windows that decodes as utf-8, so a byte such as 0x97 (an em dash in cp1252,
# common from tools like mysqldump or net.exe) crashed the reader thread with
# `UnicodeDecodeError` and the test output was LOST, although `jalankan_ci.py`
# promises to print failed output in full.
import subprocess
import tempfile

folder18 = tempfile.mkdtemp(prefix="uji_ci_bita_")
korban = os.path.join(folder18, "berkas_bita_liar.py")

# A script writing RAW cp1252 bytes to stdout, bypassing Python's text layers, like a Windows tool called by a test.
with io.open(korban, "w", encoding="utf-8") as f:
    f.write(
        "import sys\n"
        "sys.stdout.buffer.write(b'sebelum \\x97 sesudah\\n')\n"
        "sys.stdout.buffer.write('PENANDA-YANG-HARUS-TERBACA\\n'.encode())\n"
        "sys.stdout.buffer.flush()\n"
        "sys.exit(1)\n")

try:
    ok18, keluaran18, dtk18 = jalankan_ci.run_one(korban)
    benar("penjalan TIDAK meledak oleh bita liar", True)
except UnicodeDecodeError as e:
    ok18, keluaran18 = None, ""
    benar("penjalan TIDAK meledak oleh bita liar", False, "-> %s" % e)

if ok18 is not None:
    benar("kode keluar tetap terbaca (uji ini sengaja gagal)", ok18 is False,
          "-> ok=%r" % ok18)
    # The point: the output is still there, not lost.
    benar("keluaran uji TETAP TERBACA, tidak hilang",
          "PENANDA-YANG-HARUS-TERBACA" in keluaran18,
          "-> %s" % ascii(keluaran18[:160]))
    benar("dan bita liarnya diganti, bukan menggagalkan pembacaan",
          "sebelum" in keluaran18 and "sesudah" in keluaran18,
          "-> %s" % ascii(keluaran18[:160]))
    # `ascii()`, not `%r`: repr() leaves U+FFFD as-is, and printing that to a cp1252 console
    # raises UnicodeEncodeError. CI passes only because `jalankan_semua_uji.py` runs the
    # child with `-X utf8`; run directly from a console this line would crash.
    print("       keluaran terbaca: %s" % ascii(keluaran18.strip()[:90]))

# The counterpart in the measurer needs the same branch, since there the effect is worse: the file reads as FAILED and is dropped from every CI mode.
sumber_ukur = io.open(os.path.join(DIR, "ci_klasifikasi.py"),
                      encoding="utf-8").read()
for nama_berkas, isi in (("jalankan_ci.py", sumber),
                         ("ci_klasifikasi.py", sumber_ukur)):
    benar("%s membaca dengan errors='replace'" % nama_berkas,
          'errors="replace"' in isi)
    benar("%s memaksa anaknya utf-8 (-X utf8)" % nama_berkas,
          '"-X", "utf8"' in isi)

try:
    os.remove(korban)
    os.rmdir(folder18)
except OSError:
    pass

print()
print("=" * 74)
print("%d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

# -*- coding: utf-8 -*-
"""Every text-reading `subprocess` MUST specify its encoding.

On Windows, `subprocess.run(..., text=True)` without `encoding=` decodes child
output as utf-8, but console tools (`arp`, `tasklist`, `mysqldump`, `net`) write
in the OEM codepage. One non-ASCII byte kills the reader thread SILENTLY:
`subprocess.run` returns normally with `stdout = None`, and callers then treat it as
empty (`(r.stdout or "")`), swallow the parse error (`baca_arp`), or print
"RED: uji_x" with no explanation.

Found in `jalankan_ci.py` (failed test output lost), `identitas_sumber.tabel_arp()`
(an identity source vanished) and `backup_nsm` (OneDrive check wrongly answered NO).
This file scans the WHOLE folder so a fourth case cannot slip in.

Run: py uji_encoding_subprocess.py
"""
import glob
import io
import os
import re
import sys

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


def buang_komentar_dan_teks(s):
    """Strip `#` comments and string contents so only CODE is scanned.

    Otherwise files that EXPLAIN the old pattern (like `uji_ci_lengkap.py` and this one) would read as violations.
    """
    # Triple-quoted strings first, then ordinary strings, then comments.
    s = re.sub(r'"""[\s\S]*?"""', '""', s)
    s = re.sub(r"'''[\s\S]*?'''", "''", s)
    s = re.sub(r'"(?:\\.|[^"\\])*"', '""', s)
    s = re.sub(r"'(?:\\.|[^'\\])*'", "''", s)
    s = re.sub(r"#.*$", "", s, flags=re.M)
    return s


def panggilan_subprocess(s):
    """(line, block) of each subprocess call in the code."""
    hasil = []
    for m in re.finditer(r"subprocess\.(?:run|Popen|check_output)\(", s):
        j = m.end()
        d = 1
        while j < len(s) and d:
            if s[j] == "(":
                d += 1
            elif s[j] == ")":
                d -= 1
            j += 1
        hasil.append((s[:m.start()].count("\n") + 1, s[m.start():j]))
    return hasil


print("=" * 74)
print("Uji §25c-bis -- subprocess baca-teks wajib menyebut encoding")
print("=" * 74)

# ===========================================================================
print("\n1. Pemindainya sendiri benar (kalau tidak, hijaunya tak berarti)")
# A scanning test must be proven able to FIND a violation; otherwise "0 violations" only means the scanner is blind.
contoh_buruk = 'x = subprocess.run(["a"], capture_output=True, text=True)\n'
contoh_baik = ('y = subprocess.run(["a"], capture_output=True, text=True,\n'
               '                   encoding="utf-8", errors="replace")\n')

p_buruk = panggilan_subprocess(buang_komentar_dan_teks(contoh_buruk))
benar("menemukan panggilan di kode contoh", len(p_buruk) == 1,
      "-> %d" % len(p_buruk))
benar("dan tahu yang TANPA encoding itu melanggar",
      p_buruk and "text=True" in p_buruk[0][1]
      and "encoding=" not in p_buruk[0][1])

p_baik = panggilan_subprocess(buang_komentar_dan_teks(contoh_baik))
benar("yang PAKAI encoding tidak dianggap melanggar",
      p_baik and "encoding=" in p_baik[0][1])

# Comments and strings must really be stripped.
dalam_komentar = '# subprocess.run(["a"], text=True)\nz = 1\n'
benar("panggilan di dalam KOMENTAR diabaikan",
      len(panggilan_subprocess(buang_komentar_dan_teks(dalam_komentar))) == 0)
dalam_teks = 'pesan = "subprocess.run([a], text=True)"\n'
benar("panggilan di dalam STRING diabaikan",
      len(panggilan_subprocess(buang_komentar_dan_teks(dalam_teks))) == 0)

# ===========================================================================
print("\n2. SELURUH folder backend/ patuh")
berkas = sorted(glob.glob(os.path.join(DIR, "*.py"))
                + glob.glob(os.path.join(DIR, "*", "*.py")))
benar("ada berkas untuk dipindai", len(berkas) > 50, "-> %d" % len(berkas))

pelanggar = []
n_panggilan = 0
for f in berkas:
    s = buang_komentar_dan_teks(
        io.open(f, encoding="utf-8", errors="replace").read())
    for baris, blok in panggilan_subprocess(s):
        n_panggilan += 1
        baca_teks = ("text=True" in blok
                     or "universal_newlines=True" in blok
                     or "check_output" in blok)
        if baca_teks and "encoding=" not in blok:
            pelanggar.append("%s:%d" % (os.path.basename(f), baris))

print("       %d panggilan subprocess dipindai di %d berkas"
      % (n_panggilan, len(berkas)))
benar("tidak ada yang membaca teks tanpa menyebut encoding",
      pelanggar == [],
      "\n         -> %d pelanggar: %s\n         Tambahkan: "
      'encoding="utf-8", errors="replace"'
      % (len(pelanggar), ", ".join(pelanggar)))

# ===========================================================================
print("\n3. Tiga tempat yang sudah pernah gigit, dijaga khusus")
# Named one by one so that if someone later removes one, the test names it rather than just a count.
JAGA = [
    ("jalankan_ci.py", "keluaran uji yang gagal"),
    ("ci_klasifikasi.py", "vonis MURNI/MERAH"),
    ("identitas_sumber.py", "tabel ARP"),
    ("backup_nsm.py", "pemeriksa OneDrive"),
]
for nama, apa in JAGA:
    jalur = os.path.join(DIR, nama)
    if not os.path.exists(jalur):
        benar("%s ada" % nama, False, "-> berkasnya hilang")
        continue
    s = buang_komentar_dan_teks(io.open(jalur, encoding="utf-8").read())
    buruk = [b for b, blok in panggilan_subprocess(s)
             if ("text=True" in blok or "check_output" in blok)
             and "encoding=" not in blok]
    benar("%-22s (%s) tetap dijaga" % (nama, apa), buruk == [],
          "-> baris %s" % buruk)

# ===========================================================================
print("\n4. SETIAP berkas .py harus benar-benar bisa DIKOMPILASI")
# A mechanical edit once inserted `errors="replace"` into a call that already had
# `errors=`, giving `SyntaxError: keyword argument repeated: errors`. `ast.parse()`
# does NOT catch repeated keyword arguments (that check happens at COMPILE time,
# not parse time), so that verification was green while the file was broken.
# Use `compile()`.
tidak_kompilasi = []
for f in berkas:
    isi = io.open(f, encoding="utf-8", errors="replace").read()
    try:
        compile(isi, f, "exec")
    except SyntaxError as e:
        tidak_kompilasi.append("%s:%s %s" % (os.path.basename(f), e.lineno,
                                             e.msg))

benar("semua berkas .py bisa dikompilasi", tidak_kompilasi == [],
      "\n         -> %s" % "\n            ".join(tidak_kompilasi))
print("       %d berkas dikompilasi tanpa galat" % len(berkas))

# And prove the checker is sharper than `ast.parse`; otherwise this part only repeats guarantees given elsewhere.
import ast
CONTOH_RUSAK = 'f(a=1, errors="x", errors="y")\n'
try:
    ast.parse(CONTOH_RUSAK)
    ast_lolos = True
except SyntaxError:
    ast_lolos = False
try:
    compile(CONTOH_RUSAK, "<contoh>", "exec")
    compile_lolos = True
except SyntaxError:
    compile_lolos = False
benar("ast.parse MELEWATKAN argumen kata kunci ganda", ast_lolos is True,
      "-> ast.parse ternyata menangkapnya; komentar di atas perlu dikoreksi")
benar("compile MENANGKAPNYA", compile_lolos is False,
      "-> compile tidak menangkapnya")

print()
print("=" * 74)
print("%d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

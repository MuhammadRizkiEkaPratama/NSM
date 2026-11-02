# -*- coding: utf-8 -*-
"""Prose checker for comments and docstrings. It does not translate.

Identifiers are symbols with a right answer; prose is not, and a bad
translation just becomes a confusing sentence. Humans translate. This tool
does one thing: prove the code did not change.

Invariant: every token other than comments and docstrings must be identical
(kind, content, order). Plain strings are user-facing text and stay in
Indonesian, so any change to a non-docstring string is rejected.
"""

import ast
import io
import os
import re
import subprocess
import sys
import tokenize

import terjemah as tj


# Words rare in English prose and common in Indonesian. Used only to measure
# progress, so the list can be rough.
PENANDA_INDONESIA = frozenset("""
yang dan di itu tidak dengan untuk dari pada ini bukan sebab karena atau jadi
bisa sudah akan lebih tetapi tapi kalau saat ketika juga saja masih belum
setiap semua hanya harus perlu supaya agar sebuah adalah ada dalam oleh
kemudian lalu maka begitu seperti sendiri sekali pun antara sampai tanpa
""".split())


# ----------------------------------------------------------------- pembacaan

def posisi_docstring(pohon):
    """{(line, column)} of every string that is a docstring."""
    out = set()
    for n in ast.walk(pohon):
        if not isinstance(n, (ast.Module, ast.ClassDef,
                              ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        badan = getattr(n, "body", None)
        if not badan:
            continue
        p = badan[0]
        if isinstance(p, ast.Expr) and isinstance(p.value, ast.Constant) \
                and isinstance(p.value.value, str):
            out.add((p.value.lineno, p.value.col_offset))
    return out


def token_kode(src):
    """Every token except comments, docstrings, and layout.

    Layout tokens (NEWLINE, NL, INDENT, DEDENT) are dropped because a rewritten
    docstring may change the line count without changing behavior.
    """
    pohon = ast.parse(src)
    doc = posisi_docstring(pohon)
    abaikan = (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
               tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER)
    out = []
    for t in tokenize.generate_tokens(io.StringIO(src).readline):
        if t.type in abaikan:
            continue
        if t.type == tokenize.STRING and t.start in doc:
            continue
        out.append((t.type, t.string))
    return out


# ------------------------------------------------------------------ penjaga

def bandingkan(sebelum, sesudah):
    """`None` if safe; otherwise a sentence explaining why not."""
    try:
        a = token_kode(sebelum)
    except (SyntaxError, tokenize.TokenError) as e:
        return "sumber SEBELUM tidak bisa diurai: %s" % e
    try:
        b = token_kode(sesudah)
    except (SyntaxError, tokenize.TokenError) as e:
        return "hasilnya tidak bisa diurai: %s" % e

    if a == b:
        return None
    if len(a) != len(b):
        return "jumlah token kode berubah: %d -> %d" % (len(a), len(b))
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return ("token kode ke-%d berubah: %r -> %r "
                    "(kode tidak boleh disentuh di Lapis C)" % (i, x[1], y[1]))
    return "token kode berubah"


def periksa_berkas(jalur, acuan="HEAD"):
    """Compare the file on disk with its version in the reference (Git)."""
    akar = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, cwd=os.path.dirname(
                              os.path.abspath(jalur)) or ".").stdout
    akar = akar.decode("utf-8", "replace").strip()
    rel = os.path.relpath(os.path.abspath(jalur), akar).replace("\\", "/")
    lama = subprocess.run(["git", "show", "%s:%s" % (acuan, rel)],
                          capture_output=True, cwd=akar)
    if lama.returncode:
        return "tidak ada di %s (berkas baru)" % acuan
    baru = io.open(jalur, encoding="utf-8", errors="replace").read()
    return bandingkan(lama.stdout.decode("utf-8", "replace"), baru)


# ------------------------------------------------------------------ ukuran

def prosa_berkas(jalur):
    """Returns (comment lines, docstring lines, lines with Indonesian markers)."""
    src = io.open(jalur, encoding="utf-8", errors="replace").read()
    try:
        pohon = ast.parse(src)
    except SyntaxError:
        return 0, 0, 0
    doc = posisi_docstring(pohon)

    baris = []
    for t in tokenize.generate_tokens(io.StringIO(src).readline):
        if t.type == tokenize.COMMENT:
            baris.append(("kom", t.string))
        elif t.type == tokenize.STRING and t.start in doc:
            for b in t.string.splitlines():
                baris.append(("doc", b))

    kom = sum(1 for j, _ in baris if j == "kom")
    dok = sum(1 for j, _ in baris if j == "doc")
    indo = sum(1 for _j, b in baris
               if PENANDA_INDONESIA & set(re.findall(r"[a-z]+", b.lower())))
    return kom, dok, indo


def lapor(akar=".", batas=25):
    """How much Indonesian prose remains, and in which files."""
    per = {}
    for j in tj.berkas_python(akar):
        k, d, i = prosa_berkas(j)
        if k or d:
            per[j] = (k, d, i)
    tk = sum(v[0] for v in per.values())
    td = sum(v[1] for v in per.values())
    ti = sum(v[2] for v in per.values())
    print("berkas berprosa            : %d" % len(per))
    print("baris komentar             : %d" % tk)
    print("baris docstring            : %d" % td)
    print("baris berpenanda Indonesia : %d  (%.0f%% dari %d)"
          % (ti, 100.0 * ti / max(1, tk + td), tk + td))
    print()
    print("%d berkas dengan sisa terbanyak:" % batas)
    for j, (k, d, i) in sorted(per.items(), key=lambda x: -x[1][2])[:batas]:
        print("   %-46s %4d baris Indonesia (dari %d)"
              % (j.replace(".\\", "").replace("./", ""), i, k + d))
    return per


# --------------------------------------------------------------------- utama

def main():
    if "--lapor" in sys.argv:
        lapor()
        return 0

    berkas = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not berkas:
        print("pakai: terjemah_prosa.py --lapor")
        print("       terjemah_prosa.py <berkas.py> [...]   periksa vs HEAD")
        return 2

    buruk = 0
    for j in berkas:
        sebab = periksa_berkas(j)
        if sebab:
            print("  GAGAL  %-44s %s" % (j, sebab))
            buruk += 1
        else:
            print("  aman   %-44s kode identik token demi token" % j)
    return 1 if buruk else 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""Public function renaming, applied to the whole repo at once.

Unlike `terjemah.py` (per file, local names only), public function names are
defined in one module and called from many others through two import styles,
so a per-file tool would leave callers pointing at missing names.

Design: a strict guard first, then a deliberately dumb token replacement. If a
name is defined in exactly one place and is never a method, a variable, or a
string, every NAME token with that spelling in the repo is that function.
Names that fail the guard are left in Indonesian and keep working.

Deliberately not handled:
1. Module names (file names): referenced from non-Python files and docs.
2. Noun-headed names: Indonesian is head-first and English head-last, so word
   order differs (`backup_terbaru` should be `latest_backup`, not
   `backup_latest`). These are written by hand in the `pengenal` section of
   the glossary.
"""

import ast
import collections
import io
import os
import re
import sys
import tokenize

import terjemah as tj


# ---------------------------------------------------------------- kata kerja

# Heads that are clearly verbs. Single-word names do not depend on order, so
# this list is not used for them.
#
# `daftar`, `isi`, `nilai`, `ringkas`, `verifikasi`, `laporan` are left out on
# purpose: they are also common nouns, and read as nouns the order flips
# (`daftar_berkas` is `file_list`, not `list_file`).
KEPALA_KERJA = frozenset("""
ambil atur baca bandingkan banding bangun bersihkan blokir buat buka cari catat
cek coba gabung ganti geser hapus hitung jalankan kirim lewati muat mulai olah
pasang periksa pilih ping poll putuskan rakit salin samarkan saring set siapkan
sidik simpan suntik susun tambah tambal test tulis tutup ubah uji urai
""".split())


# ------------------------------------------------------------------ pemindai

def _muat(akar="."):
    """{path: (source, tree)} for every parseable .py file."""
    out = {}
    for j in tj.berkas_python(akar):
        try:
            src = io.open(j, encoding="utf-8", errors="replace").read()
            out[j] = (src, ast.parse(src))
        except (SyntaxError, ValueError, OSError):
            continue
    return out


def _alias_modul(pohon):
    """{bound_name: module} for `import X` and `import X as Y`.

    Lexical, not type inference: after `import poller`, `poller.poll_konfig` is
    certainly a function of module `poller`. `import a.b.c` without an alias is
    not handled (it binds `a`, and access is an attribute of an attribute), so it
    falls into the rejection path. Aliases rebound anywhere in the same file are
    dropped entirely.
    """
    alias, diikat_ulang = {}, set()
    for n in ast.walk(pohon):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.asname:
                    alias[a.asname] = a.name.split(".")[-1]
                elif "." not in a.name:
                    alias[a.name] = a.name
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            diikat_ulang.add(n.id)
    for nama in diikat_ulang:
        alias.pop(nama, None)
    return alias


def _def_publik(repo):
    """{name: {modules}} from the first pass, needed before attributes can be judged."""
    out = collections.defaultdict(set)
    for jalur, (_src, pohon) in repo.items():
        modul = os.path.splitext(os.path.basename(jalur))[0]
        for n in pohon.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and not n.name.startswith("_"):
                out[n.name].add(modul)
    return out


def sensus(repo):
    """Two passes over the whole repo; returns everything the guard below needs.

    Two passes because judging `a.olah` requires knowing first which module
    defines `olah`. Kept separate from the guard so it can be tested alone and so
    the decision rests on evidence from the whole repo.
    """
    milik = _def_publik(repo)
    d = {
        "def_publik": collections.defaultdict(set),   # nama -> {modul}
        "def_lain": collections.Counter(),  # name also used as another def/class
        "metode": collections.defaultdict(set),   # nama -> {kelas}
        "atribut": collections.Counter(),  # `X.name` anywhere
        "variabel": collections.Counter(),  # `name = ...` anywhere
        "parameter": collections.Counter(),  # parameter name anywhere
        "kata_kunci": collections.Counter(),   # `f(nama=...)`
        "string": collections.Counter(),   # "nama" sbg tetapan string
        "semua_nama": set(),  # every identifier in the repo
    }
    d["def_publik"] = milik
    for jalur, (_src, pohon) in repo.items():
        alias = _alias_modul(pohon)

        atas = set()
        for n in pohon.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                atas.add(n.name)

        for n in ast.walk(pohon):
            if isinstance(n, ast.ClassDef):
                d["def_lain"][n.name] += 1
                d["semua_nama"].add(n.name)
                for m in n.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        d["metode"][m.name].add(n.name)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                d["semua_nama"].add(n.name)
                if n.name not in atas:
                    d["def_lain"][n.name] += 1
                for a in (list(n.args.posonlyargs) + list(n.args.args)
                          + list(n.args.kwonlyargs)
                          + ([n.args.vararg] if n.args.vararg else [])
                          + ([n.args.kwarg] if n.args.kwarg else [])):
                    d["parameter"][a.arg] += 1
                    d["semua_nama"].add(a.arg)
            elif isinstance(n, ast.Name):
                d["semua_nama"].add(n.id)
                if isinstance(n.ctx, (ast.Store, ast.Del)):
                    d["variabel"][n.id] += 1
            elif isinstance(n, ast.Attribute):
                d["semua_nama"].add(n.attr)
                # `poller.poll_konfig` in a file that writes `import poller` is a module
                # function reference, not an arbitrary object attribute. Anything else counts
                # as a blocker.
                lewat_modul = (
                    isinstance(n.value, ast.Name)
                    and n.value.id in alias
                    and alias[n.value.id] in milik.get(n.attr, ()))
                if not lewat_modul:
                    d["atribut"][n.attr] += 1
            elif isinstance(n, ast.keyword) and n.arg:
                d["kata_kunci"][n.arg] += 1
            elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                d["string"][n.value] += 1
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    d["semua_nama"].add(a.asname or a.name.split(".")[0])
    return d


# ------------------------------------------------------------------ penjaga

def alasan_tolak(nama, sasaran, s):
    """Why `nama` may NOT be renamed; `None` means it may. Reasons are ordered from
    cheapest to most fundamental so the report names the root cause.
    """
    if nama in tj.BAWAAN_PYTHON or sasaran in tj.BAWAAN_PYTHON:
        return "kata bawaan Python"

    modul = s["def_publik"].get(nama, set())
    if len(modul) != 1:
        return "didefinisikan di %d modul" % len(modul)

    # If the name is also a method, token replacement would drag along a method
    # that belongs to another class.
    if nama in s["metode"]:
        return "juga nama metode di kelas %s" % ", ".join(sorted(s["metode"][nama])[:2])
    if s["def_lain"][nama]:
        return "juga nama fungsi/kelas lain (%d kali)" % s["def_lain"][nama]

    # `X.name` whose receiver is not a module could be any object attribute, and a
    # legitimate use cannot be told apart without type inference, so all are rejected.
    if s["atribut"][nama]:
        return "muncul sebagai atribut `X.%s` (%d kali)" % (nama, s["atribut"][nama])

    if s["variabel"][nama]:
        return "juga dipakai sebagai variabel (%d kali)" % s["variabel"][nama]
    if s["parameter"][nama]:
        return "juga nama parameter (%d kali)" % s["parameter"][nama]
    if s["kata_kunci"][nama]:
        return "dikirim sebagai kata kunci `%s=` (%d kali)" % (nama, s["kata_kunci"][nama])

    # Names inside strings are not replaced, so `getattr(m, "nama")` and route
    # tables would point at a name that no longer exists.
    if s["string"][nama]:
        return "muncul sebagai string (%d kali)" % s["string"][nama]

    if sasaran in s["semua_nama"]:
        return "sasaran `%s` sudah dipakai di repo" % sasaran
    return None


def irisan_aman(nama, kamus, biarkan, utuh):
    """Can this name be translated automatically?

    Only two shapes qualify, because only there Indonesian and English word
    order are certainly the same: a single word, or a verb plus one word
    (`baca_sandi` = `read_password`). Longer names are rejected: a verb head only
    guarantees the first word, and later words stay in Indonesian order (noun
    first), so `poll_pola_log` would become `poll_pattern_log` instead of
    `poll_log_pattern`. `test_*` names are sentences, not verb phrases, and are
    filtered out too.

    Escape hatch: names written by hand in the `pengenal` section of the glossary
    pass unchecked, since those entries are human judgment.
    """
    if utuh and nama in utuh:
        return True
    kata = tj.pecah(nama)
    if len(kata) == 1:
        return True
    return len(kata) == 2 and kata[0] in KEPALA_KERJA


def peta(repo=None, akar=".", glos=None):
    """(rename_map, rejected). The full decision, writing nothing.

    `glos` lets tests pass a small glossary; if empty, the repo glossary is used.
    """
    if repo is None:
        repo = _muat(akar)
    kamus, biarkan, utuh = glos if glos else tj.muat_glosarium()
    s = sensus(repo)

    calon, ditolak = {}, []
    for nama in sorted(s["def_publik"]):
        sasaran = tj.terjemahkan(nama, kamus, biarkan, utuh)
        if not sasaran:
            continue
        if not irisan_aman(nama, kamus, biarkan, utuh):
            ditolak.append((nama, "kepala kata benda -- urutan kata bisa terbalik"))
            continue
        sebab = alasan_tolak(nama, sasaran, s)
        if sebab:
            ditolak.append((nama, sebab))
            continue
        calon[nama] = sasaran

    # Two names mapping to one target are both dropped; picking one would merge two
    # different things.
    lawan = collections.defaultdict(list)
    for a, b in calon.items():
        lawan[b].append(a)
    for sasaran, asal in lawan.items():
        if len(asal) > 1:
            for a in asal:
                calon.pop(a, None)
                ditolak.append((a, "bertabrakan: %s sama-sama jadi `%s`"
                                % (" & ".join(sorted(asal)), sasaran)))
    return calon, sorted(set(ditolak))


# ---------------------------------------------------------------- penggantian

def _ganti_sumber(src, peta_ganti):
    """Replace every NAME token in the map. Comments and strings are not touched,
    which is why this uses `tokenize` and not `str.replace`.
    """
    baris = src.splitlines(keepends=True)
    edit, jumlah = {}, 0
    for t in tokenize.generate_tokens(io.StringIO(src).readline):
        if t.type == tokenize.NAME and t.string in peta_ganti:
            edit.setdefault(t.start[0], []).append(
                (t.start[1], t.end[1], peta_ganti[t.string]))
            jumlah += 1
    for no, daftar in edit.items():
        b = baris[no - 1]
        for a, z, teks in sorted(daftar, reverse=True):
            b = b[:a] + teks + b[z:]
        baris[no - 1] = b
    return "".join(baris), jumlah


def _tetapan(src):
    """Every comment and string in the file, as is."""
    return [t.string for t in tokenize.generate_tokens(io.StringIO(src).readline)
            if t.type in (tokenize.COMMENT, tokenize.STRING)]


DOKUMEN = (".md", ".java", ".js", ".html", ".sql", ".yaml", ".yml",
           ".sh", ".txt", ".ps1", ".service")

_ABAIKAN = frozenset({".git", "venv", "node_modules", "target",
                      "__pycache__", ".pytest_cache"})


def berkas_dokumen(akar=".."):
    for dp, dn, fn in os.walk(akar):
        dn[:] = [d for d in dn if d not in _ABAIKAN]
        for f in fn:
            if f.endswith(DOKUMEN):
                yield os.path.join(dp, f)


def _ganti_dokumen(peta_ganti, akar="..", tulis=False):
    """Update function references in docs, Java, and JS.

    Only underscored names are rewritten. A one-word name like `baris` appears in
    hundreds of Markdown files as a plain Indonesian word, which text matching
    cannot tell apart from a function reference.
    """
    aman = {a: b for a, b in peta_ganti.items() if "_" in a}
    pola = {a: re.compile(r"\b%s\b" % re.escape(a)) for a in aman}
    sentuh = {}
    for p in berkas_dokumen(akar):
        try:
            s = io.open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        baru, n = s, 0
        for a, b in aman.items():
            baru, k = pola[a].subn(b, baru)
            n += k
        if n:
            sentuh[p] = (baru, n)
    if tulis:
        for p, (baru, _n) in sentuh.items():
            io.open(p, "w", encoding="utf-8", newline="").write(baru)
    return {p: n for p, (_b, n) in sentuh.items()}


def jalankan(akar=".", tulis=False, glos=None, akar_dok=None):
    """Apply to the whole repo with all-or-nothing rollback.

    Everything is computed and checked first; if one file fails, nothing is
    written, since a half-renamed repo cannot run at all.
    """
    repo = _muat(akar)
    peta_ganti, ditolak = peta(repo, glos=glos)
    if not peta_ganti:
        return {"peta": {}, "ditolak": ditolak, "dokumen": {},
                "berkas": 0, "ganti": 0, "gagal": []}

    hasil, gagal, total = {}, [], 0
    for jalur, (src, _pohon) in repo.items():
        baru, n = _ganti_sumber(src, peta_ganti)
        if not n:
            continue
        try:
            ast.parse(baru)
        except SyntaxError as e:
            gagal.append((jalur, "hasil tidak bisa diurai: %s" % e))
            continue
        # Comments and strings must be identical. If they changed, user-facing text
        # was altered, which is outside this tool's authority.
        if _tetapan(src) != _tetapan(baru):
            gagal.append((jalur, "komentar/string ikut berubah"))
            continue
        hasil[jalur] = baru
        total += n

    if gagal:
        return {"peta": peta_ganti, "ditolak": ditolak, "dokumen": {},
                "berkas": 0, "ganti": 0, "gagal": gagal}

    # Docs are part of the same rollback: if any Python file above failed, the docs
    # are not touched either.
    dok = _ganti_dokumen(
        peta_ganti,
        akar_dok if akar_dok is not None else os.path.join(akar, ".."),
        tulis=tulis)

    if tulis:
        for jalur, baru in hasil.items():
            io.open(jalur, "w", encoding="utf-8", newline="").write(baru)
    return {"peta": peta_ganti, "ditolak": ditolak, "dokumen": dok,
            "berkas": len(hasil), "ganti": total, "gagal": []}


# --------------------------------------------------------------------- utama

def main():
    tulis = "--tulis" in sys.argv
    rinci = "--rinci" in sys.argv
    h = jalankan(".", tulis=tulis)

    print("nama fungsi publik yang diganti : %d" % len(h["peta"]))
    print("nama yang ditolak               : %d" % len(h["ditolak"]))
    print("berkas tersentuh                : %d" % h["berkas"])
    print("token diganti                   : %d" % h["ganti"])
    print("dokumen ikut diperbarui         : %d" % len(h.get("dokumen", {})))
    if h["gagal"]:
        print("\nDIBATALKAN SELURUHNYA -- %d berkas gagal:" % len(h["gagal"]))
        for j, sebab in h["gagal"][:20]:
            print("   %-44s %s" % (j, sebab))
        return 1

    if rinci:
        print("\n--- diganti ---")
        for a, b in sorted(h["peta"].items()):
            print("   %-34s -> %s" % (a, b))
        print("\n--- ditolak (sebab) ---")
        sebab = collections.Counter(s for _n, s in h["ditolak"])
        for s, c in sebab.most_common(15):
            print("   %3d  %s" % (c, s))
    if not tulis:
        print("\n(uji coba -- belum ada yang ditulis; tambahkan --tulis)")
    else:
        print("\nDITULIS. JALANKAN SELURUH UJI SEKARANG.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

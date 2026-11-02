r"""Indonesian -> English identifier translator. Refuses to guess.

    py terjemah.py --lapor                  measure, change nothing
    py terjemah.py --lapor --kata           words missing from the glossary
    py terjemah.py --ganti <berkas.py>      rename LOCAL names in one file
    py terjemah.py --ganti <berkas.py> --tulis   write the changes
    py terjemah.py --semua                  dry run over the whole repo
    py terjemah.py --semua --tulis          write, with all-or-nothing rollback

Works on the syntax tree, not on text: `nama` can be a local variable, a DB
column, a JSON key read by the Java side, and a word in a user-facing
sentence, and text search/replace cannot tell them apart.

Four classes of names; only the first is touched:

    1. Local names                         <- renamed by this tool
       Live inside one function only; a wrong rename fails tests at once.
       (Parameters count as crossing; see `_Lokal`.)

    2. Module names and public functions   <- separate step
       Referenced across files; needs all imports updated in a standalone,
       separately revertible change.

    3. Dict keys and JSON field names      <- never, unless Java changes too
       e.g. read by `penemuan.js` and `NetmonApiClient`. Renaming them only
       in Python makes pages silently render empty.

    4. Model attributes and DB columns     <- needs a migration
       Tied to the schema; renaming without a migration loses data.

Classes 3 and 4 are enforced in code (see `TERLARANG`).

Refusing to guess: identifiers are translated word by word via
`glosarium.yaml`. If any word is missing, the whole identifier is left as-is
and reported. A wrong translation is worse than none, because it looks done.
"""
import ast
import io
import keyword
import os
import re
import sys

import yaml

DIR = os.path.dirname(os.path.abspath(__file__))
GLOSARIUM = os.path.join(DIR, "glosarium.yaml")
LEWAT = {"venv", "__pycache__", "target", ".git", "node_modules"}

# Names that must never be renamed even if every word is in the glossary.
# Each crosses a boundary (database, JSON read by Java, or an external
# library); renaming one breaks something silently.
TERLARANG = {
    # Model attributes / database columns.
    "platform", "aktif", "penting", "teks", "sidik", "waktu", "nama",
    "alamat", "jenis", "status", "keparahan", "hasil", "alasan", "oleh",
    "kategori", "kunci", "jeda_alasan", "jeda_sejak", "jeda_oleh",
    "gns3_node", "tenant_id", "device_id", "snapshot_id", "aturan_id",
    "baris_bukti", "nomor_baris", "dinilai", "acl_berubah",
    "baris_tambah", "baris_hapus", "teks_startup", "sidik_startup",
    "belum_disimpan", "pertama_terlihat", "terakhir_terlihat",
    "port_terbuka", "sysobjectid", "catatan", "rtt_ms", "ip_address",

    # JSON keys read by the Java/JS side.
    "temuan", "jumlah", "total", "baru", "diperbarui", "jaringan",
    "teruji", "keterangan_platform", "didukung", "ditolak", "ok",
    "device", "perintah", "memutus", "urutan", "menit_reload",
    "daftar_putih", "jam_mulai", "jam_selesai", "keputusan",

    # Section names in device definition files (perangkat/*.yaml).
    "deteksi", "akses", "baca", "tulis", "kemampuan", "rahasia",
    "jaring_pengaman", "pasang", "bukti", "kukuhkan", "penanda_terpasang",
    "penanda_lepas", "reload_aman", "mode_konfig", "simpan", "netmiko_device_type",
}


def muat_glosarium(jalur=GLOSARIUM):
    """Flatten all glossary sections into one word -> word dictionary.

    The `biarkan` section is deliberately excluded: its words are used as-is, and
    adding them would "translate" `snmp` to `snmp`, which looks like progress but
    hides words that are genuinely undecided.
    """
    with open(jalur, encoding="utf-8") as f:
        content = yaml.safe_load(f) or {}
    utuh = {str(k): str(v) for k, v in (content.get("pengenal") or {}).items()}
    kamus = {}
    for section in ("kata", "domain", "umum"):
        for k, v in (content.get(section) or {}).items():
            k = str(k).lower()
            if k in kamus and kamus[k] != v:
                raise SystemExit(
                    "glosarium bentrok: %r diterjemahkan %r dan %r. Satu kata "
                    "Indonesia harus punya TEPAT SATU kata Inggris -- lihat "
                    "aturan 1 di kepala glosarium.yaml" % (k, kamus[k], v))
            kamus[k] = str(v)
    biarkan = set(content.get("biarkan") or {})

    # Output vocabulary is also accepted as-is: if `baris` translates to `line`,
    # then `line` must be valid input, or partially translated names could never be
    # finished. Derived here rather than retyped in the glossary, so the two lists
    # cannot drift.
    for target in list(kamus.values()) + list(utuh.values()):
        biarkan.update(pecah(target))
    return kamus, biarkan, utuh


# Python builtins AND keywords. A translation that produces one is rejected.
#
#   `daftar` -> `list`, `peta` -> `map`     shadows a builtin; fails later with
#                                           "TypeError: 'dict' object is not
#                                           callable", which hides the cause.
#
#   `lolos` -> `pass`, `dari` -> `from`     a keyword; the file no longer parses.
#
# `dir(__builtins__)` does NOT include keywords, hence `keyword.kwlist`.
#
# Rejected rather than auto-fixed to `list_`: spreading trailing underscores
# across the repo creates many ugly names. Put the right translation in the
# `pengenal:` section of the glossary instead.
BAWAAN_PYTHON = (frozenset(dir(__builtins__) if isinstance(__builtins__, dict)
                           else dir(__builtins__))
                 | frozenset(keyword.kwlist)
                 | frozenset(keyword.softkwlist)
                 | frozenset("""
list map dict set str int float bytes tuple type id input print open filter
next iter len range sum min max all any sorted reversed format hash object
vars dir eval exec compile globals locals super property staticmethod
""".split()))


def pecah(nama):
    r"""Identifier -> list of lowercase words. Handles snake_case and camelCase.

    Digits stay attached to their word rather than being dropped. Splitting on
    `[_\d]+` would lose them:

        jam4  -> ["jam"]  -> hour        <- digit lost
        jam1  -> ["jam"]  -> hour        <- and `jam1` and `jam2`
        jam2  -> ["jam"]  -> hour           become the SAME name

    Digits in variable names are almost always meaningful (e.g. first vs second
    test case); dropping them gives names that read fine but mean the wrong thing.
    """
    return [w.lower() for w in re.split(r"(?<=[a-z0-9])(?=[A-Z])|_+", nama) if w]


def _kata_angka(w):
    r"""`hour4` -> `("hour", "4")`.

    The trailing digits are split off so the word can be looked up, then
    reattached unchanged to the translation.
    """
    m = re.match(r"^(\D*)(\d*)$", w)
    return (m.group(1), m.group(2)) if m else (w, "")


def terjemahkan(nama, kamus, biarkan, utuh=None):
    """New name, or None if any word is still undecided.

    None is not a failure; it is the correct answer for a word missing from the
    glossary. See "Refusing to guess" in the module docstring.
    """
    if nama in TERLARANG or nama.lstrip("_") in TERLARANG:
        return None

    # Whole identifiers are checked first. Indonesian and English word order are
    # reversed (`peta ping` -> `ping_map`, not `map_ping`), which word-by-word
    # translation cannot fix.
    prefix = re.match(r"^_*", nama).group(0)
    if utuh and nama[len(prefix):] in utuh:
        baru = prefix + utuh[nama[len(prefix):]]
        return None if baru.lstrip("_") in BAWAAN_PYTHON else baru

    core = nama[len(prefix):]
    if not core:
        return None

    kata = pecah(core)
    if not kata:
        return None

    hasil = []
    changed = False
    for w in kata:
        inti_w, angka = _kata_angka(w)
        if inti_w in kamus:
            # Digits are reattached unchanged: `jam4` -> `hour4`, not `hour`.
            # See `pecah()`.
            hasil.append(kamus[inti_w] + angka)
            changed = True
        elif inti_w in biarkan or (not inti_w and angka):
            hasil.append(w)
        else:
            return None  # one unknown word -> leave untouched
    if not changed:
        return None
    baru = prefix + "_".join(hasil)
    if baru == nama:
        return None
    if baru.lstrip("_") in BAWAAN_PYTHON:
        return None
    return baru


def berkas_python(akar="."):
    for dp, dn, fn in os.walk(akar):
        dn[:] = [d for d in dn if d not in LEWAT]
        for f in fn:
            if f.endswith(".py"):
                yield os.path.join(dp, f)


class _Lokal(ast.NodeVisitor):
    """Collect LOCAL names per function.

    Only names that live entirely inside one function. Names that also appear as
    parameters, `global`, `nonlocal`, attributes, or keyword arguments in calls
    count as crossing and are skipped (classes 2-4 in the module docstring).
    """

    def __init__(self):
        self.lokal = set()
        self.menyeberang = set()

    def visit_FunctionDef(self, node):          # noqa: N802
        self._fungsi(node)

    def visit_AsyncFunctionDef(self, node):     # noqa: N802
        self._fungsi(node)

    def _fungsi(self, node):
        # Parameters cross the boundary; they are not local. A parameter name is part
        # of the function's interface, since callers in ANY file may pass it by keyword:
        #
        #     rollup.bangun(sampai=kemarin)
        #     -> TypeError: bangun() got an unexpected keyword argument
        #
        # The `ast.keyword` guard only sees calls in the same file, and this tool works
        # per file. `uji_permukaan_paket.py` also pins signatures, so renaming a
        # parameter is an interface change.
        a = node.args
        for arg in (list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)
                    + ([a.vararg] if a.vararg else []) + ([a.kwarg] if a.kwarg else [])):
            self.menyeberang.add(arg.arg)
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                self.lokal.add(n.id)
            elif isinstance(n, (ast.Global, ast.Nonlocal)):
                self.menyeberang.update(n.names)
            elif isinstance(n, ast.Attribute):
                self.menyeberang.add(n.attr)
            elif isinstance(n, ast.keyword) and n.arg:
                # `fungsi(nama=...)`: the name belongs to the callee, not the caller.
                # Renaming it here breaks the call.
                self.menyeberang.add(n.arg)
        self.generic_visit(node)


def nama_dalam_string(pohon):
    """Names referenced from inside a STRING, which therefore cross the boundary.

    `@pytest.mark.parametrize("nilai", [...])` names a parameter as TEXT. Renaming
    the parameter (NAME token) but not the text (STRING token) breaks collection:

        function uses no argument 'nilai'

    The same pattern appears with pytest fixtures, `getattr(obj, "nama")`,
    `**{"nama": ...}`, and dict keys used as keyword arguments.

    So the rule is general, not pytest-specific: a name that appears as a whole
    string anywhere in the same file is treated as crossing and left alone.
    Stricter than necessary, by design.
    """
    hasil = set()
    for n in ast.walk(pohon):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            t = n.value.strip()
            if t and t.isidentifier():
                hasil.add(t)
            else:
                # `parametrize("a,b", ...)` names two parameters at once.
                for section in t.replace(" ", "").split(","):
                    if section.isidentifier():
                        hasil.add(section)
    return hasil


def nama_lokal(pohon):
    v = _Lokal()
    v.visit(pohon)

    # Module-level names also cross: other files can import them.
    tingkat_modul = set()
    for n in pohon.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            tingkat_modul.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    tingkat_modul.add(t.id)
    return v.lokal - v.menyeberang - tingkat_modul - nama_dalam_string(pohon)


def nama_terpakai(pohon):
    """ALL names already used in this file, in any role.

    Used to reject translations that COLLIDE with an existing name. This is the
    most dangerous failure because it passes every other check: the file still
    parses, comments and strings are identical, pytest still collects. Only the
    meaning breaks:

        anomali.py:  jam1 -> hour
                     jam2 -> hour      <- two variables become ONE

    The code still runs and still produces numbers, just wrong ones.
    """
    ada = set()
    for n in ast.walk(pohon):
        if isinstance(n, ast.Name):
            ada.add(n.id)
        elif isinstance(n, ast.Attribute):
            ada.add(n.attr)
        elif isinstance(n, ast.arg):
            ada.add(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ada.add(n.name)
        elif isinstance(n, ast.keyword) and n.arg:
            ada.add(n.arg)
    return ada


def peta_aman(pohon, kamus, biarkan, utuh):
    """{old_name: new_name} guaranteed not to collide with anything in this file.

    Two kinds of collision are rejected, both of which merge two things into one:

      1. the target is already used by another name in this file
      2. two different names translate to the SAME target
         (`jam1` and `jam2` both become `hour`)

    Both are rejected silently; the name simply stays untranslated, which is the
    correct outcome: an untranslated name is still readable, a merged one
    produces wrong results.
    """
    ada = nama_terpakai(pohon)
    prospective = {}
    for nm in sorted(nama_lokal(pohon)):
        baru = terjemahkan(nm, kamus, biarkan, utuh)
        if baru:
            prospective.setdefault(baru, []).append(nm)
    peta = {}
    for baru, old_old in prospective.items():
        if baru in ada:
            continue  # collision type 1
        if len(old_old) > 1:
            continue  # collision type 2
        peta[old_old[0]] = baru
    return peta


def ganti_di_berkas(jalur, kamus, biarkan, tulis=False, utuh=None):
    """(count_replaced, pair_list). Renames LOCAL names only."""
    src = open(jalur, encoding="utf-8").read()
    try:
        pohon = ast.parse(src)
    except SyntaxError as e:
        return 0, [("(gagal diurai)", str(e))]

    peta = peta_aman(pohon, kamus, biarkan, utuh)
    if not peta:
        return 0, []

    # Replaced via `tokenize`, NOT `str.replace`. Plain text replacement would also
    # change the same word inside comments, docstrings, and user-facing strings.
    import tokenize
    keluar = []
    replaced = 0
    line_new = src.splitlines(keepends=True)
    tok = list(tokenize.generate_tokens(io.StringIO(src).readline))
    edit = {}
    for t in tok:
        if t.type == tokenize.NAME and t.string in peta:
            edit.setdefault(t.start[0], []).append(
                (t.start[1], t.end[1], peta[t.string]))
            replaced += 1
    for no, daftar in edit.items():
        b = line_new[no - 1]
        for a, z, teks in sorted(daftar, reverse=True):
            b = b[:a] + teks + b[z:]
        line_new[no - 1] = b
    keluar = "".join(line_new)

    # Check the result still parses. A rename that breaks the file must stop here,
    # not in `pytest` later.
    try:
        ast.parse(keluar)
    except SyntaxError as e:
        return 0, [("(hasil ganti tidak bisa diurai)", str(e))]

    if tulis:
        open(jalur, "w", encoding="utf-8", newline="").write(keluar)
    return replaced, sorted(peta.items())


def _token(src, jenis):
    import tokenize
    return [t.string for t in tokenize.generate_tokens(io.StringIO(src).readline)
            if t.type in jenis]


def semua(kamus, biarkan, utuh, tulis=False):
    """Apply to the WHOLE repo, all-or-nothing.

    All changes are computed and checked first; if even ONE file fails a check,
    no file is written. A half-translated repo is worse than an untranslated one,
    since readers cannot tell whether `hasil` here and `result` there mean
    different things.

    Two checks per file:

      1. the result still parses as Python
      2. all COMMENT and STRING tokens are IDENTICAL before and after

    The second proves that user-facing Indonesian text, docstrings, and dict keys
    read by the Java side are untouched; only name tokens change.

    These checks only catch syntactic breakage. Names referenced as text, as in
    `parametrize("nilai", ...)`, are handled by `nama_dalam_string()`.
    """
    import ast as _ast
    import tokenize

    plan = []
    reject = []
    n_check = 0

    for jalur in sorted(berkas_python(".")):
        n_check += 1
        old = open(jalur, encoding="utf-8").read()
        try:
            pohon = _ast.parse(old)
        except SyntaxError:
            continue

        peta = peta_aman(pohon, kamus, biarkan, utuh)
        if not peta:
            continue

        line = old.splitlines(keepends=True)
        edit = {}
        jumlah = 0
        for t in tokenize.generate_tokens(io.StringIO(old).readline):
            if t.type == tokenize.NAME and t.string in peta:
                edit.setdefault(t.start[0], []).append(
                    (t.start[1], t.end[1], peta[t.string]))
                jumlah += 1
        for no, list_edit in edit.items():
            b = line[no - 1]
            for a, z, teks in sorted(list_edit, reverse=True):
                b = b[:a] + teks + b[z:]
            line[no - 1] = b
        baru = "".join(line)

        try:
            _ast.parse(baru)
        except SyntaxError as e:
            reject.append((jalur, "hasilnya tidak bisa diurai: %s" % e))
            continue
        broken = None
        for name_kind, jenis in (("KOMENTAR", {tokenize.COMMENT}),
                                  ("STRING", {tokenize.STRING})):
            try:
                if _token(old, jenis) != _token(baru, jenis):
                    broken = "token %s berubah" % name_kind
                    break
            except tokenize.TokenError as e:
                broken = "gagal ditokenkan: %s" % e
                break
        if broken:
            reject.append((jalur, broken))
        else:
            plan.append((jalur, baru, jumlah, peta))

    print("=" * 70)
    print("TERJEMAHAN SELURUH REPO  %s" % ("MENULIS" if tulis else "JALAN KERING"))
    print("=" * 70)
    print("berkas diperiksa      : %d" % n_check)
    print("berkas akan berubah   : %d" % len(plan))
    print("penggantian           : %d" % sum(r[2] for r in plan))
    name_unique = set()
    for _j, _b, _n, peta in plan:
        name_unique.update(peta)
    print("nama unik             : %d" % len(name_unique))

    if reject:
        print()
        print("BERHENTI: %d berkas gagal pemeriksaan." % len(reject))
        for jalur, why in reject[:10]:
            print("   %-46s %s" % (jalur, why))
        print()
        print("Tidak ada satu berkas pun ditulis. Repo yang setengah")
        print("diterjemahkan lebih buruk daripada yang belum sama sekali.")
        return 1

    if not tulis:
        print()
        print("TIDAK DITULIS. Tambahkan --tulis kalau angkanya masuk akal.")
        return 0

    for jalur, baru, _n, _p in plan:
        open(jalur, "w", encoding="utf-8", newline="").write(baru)
    print()
    print("%d berkas ditulis." % len(plan))
    print("JALANKAN SELURUH UJI SEKARANG -- itu pemeriksaan perilakunya, dan")
    print("ia menangkap yang tidak bisa ditangkap pemeriksaan sintaks.")
    return 0


def lapor(kamus, biarkan, tampilkan_kata=False, utuh=None):
    import collections
    can = collections.Counter()
    not_yet = collections.Counter()
    kata_belum = collections.Counter()
    n_file = 0

    for jalur in berkas_python("."):
        n_file += 1
        try:
            pohon = ast.parse(open(jalur, encoding="utf-8").read())
        except SyntaxError:
            continue
        for nm in nama_lokal(pohon):
            if terjemahkan(nm, kamus, biarkan, utuh):
                can[nm] += 1
            else:
                not_yet[nm] += 1
                for w in pecah(nm.lstrip("_")):
                    if w not in kamus and w not in biarkan:
                        kata_belum[w] += 1

    print("=" * 70)
    print("TERJEMAHAN NAMA LOKAL -- LAPORAN")
    print("=" * 70)
    print("berkas Python diperiksa : %d" % n_file)
    print("kata di glosarium       : %d (+%d dibiarkan)" % (len(kamus), len(biarkan)))
    print()
    print("nama lokal yang BISA diterjemahkan  : %d" % len(can))
    print("nama lokal yang BELUM bisa          : %d" % len(not_yet))
    tot = len(can) + len(not_yet)
    if tot:
        print("cakupan                             : %.0f%%" % (100 * len(can) / tot))
    if tampilkan_kata:
        print()
        print("40 kata yang paling sering menghalangi (belum di glosarium):")
        for w, c in kata_belum.most_common(40):
            print("   %-20s %d" % (w, c))
    return 0


def main():
    kamus, biarkan, utuh = muat_glosarium()
    arg = sys.argv[1:]
    if "--lapor" in arg or not arg:
        return lapor(kamus, biarkan, "--kata" in arg, utuh)
    if "--semua" in arg:
        return semua(kamus, biarkan, utuh, "--tulis" in arg)
    if "--ganti" in arg:
        i = arg.index("--ganti")
        target = arg[i + 1] if len(arg) > i + 1 else None
        if not target or not os.path.exists(target):
            print("berkas tidak ada: %r" % target)
            return 1
        tulis = "--tulis" in arg
        n, peta = ganti_di_berkas(target, kamus, biarkan, tulis, utuh)
        print("%s: %d penggantian, %d nama" % (target, n, len(peta)))
        for old, baru in peta:
            print("   %-28s -> %s" % (old, baru))
        if not tulis and n:
            print("\nTIDAK DITULIS. Tambahkan --tulis kalau daftar di atas benar.")
        return 0
    print(__doc__.strip().splitlines()[0])
    return 1


if __name__ == "__main__":
    sys.exit(main())

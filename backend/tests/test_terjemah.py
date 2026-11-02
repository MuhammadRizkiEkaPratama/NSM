"""Tests for the identifier translator, focused on what it must NOT touch.

The tool renames identifiers across the whole repo, so a mistake breaks
everything at once, often silently. Most tests therefore check refusals,
not capabilities.

Three guarantees:

1. Comments and strings never change. `nama` can be a local variable, a word
   in user-facing Indonesian text, and a JSON key read by Java. The tool works
   on tokens, and the tests compare all COMMENT and STRING tokens before and
   after.

2. Undecided words are not guessed. An identifier containing any word outside
   the glossary is left as is. A wrong translation is worse than none because
   it looks finished.

3. Names that cross a boundary are not touched: attributes, keyword arguments,
   module-level names, and the TERLARANG list are referenced from outside
   their function, so renaming them in one place breaks the others.

No project files are modified; all tests use temporary files.
"""
import io
import tokenize

import pytest

import terjemah as tj

pytestmark = pytest.mark.murni


@pytest.fixture(scope="module")
def glosarium():
    return tj.muat_glosarium()


# ---------------------------------------------------------------------------
# 1. Glossary
# ---------------------------------------------------------------------------
def test_glosarium_termuat(glosarium):
    kamus, biarkan, utuh = glosarium
    assert len(kamus) > 200, "glosarium terlalu kecil untuk berguna"
    assert biarkan and utuh


def test_satu_kata_indonesia_satu_kata_inggris(glosarium):
    """Glossary rule 1 (one Indonesian word, one English word), enforced by `muat_glosarium()` raising.

    If `hasil` could map to `result` in one place and `output` in another,
    paired functions would stop looking paired.
    """
    kamus, _b, _u = glosarium
    assert len(set(kamus)) == len(kamus)


def test_kata_dan_biarkan_tidak_tumpang_tindih(glosarium):
    """A word both translated and kept would have two rules, and the winner
    would depend on code order.
    """
    kamus, biarkan, _u = glosarium
    assert not (set(kamus) & biarkan), "-> %s" % sorted(set(kamus) & biarkan)


# ---------------------------------------------------------------------------
# 2. Refusing to guess
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nama", [
    "kata_yang_tidak_ada_di_glosarium",
    "zxqv",
    "hasil_zxqv",  # one known word, one unknown -> still refused
], ids=["frasa_asing", "kata_asing", "sebagian_dikenal"])
def test_kata_asing_membuat_seluruh_pengenal_dibiarkan(nama, glosarium):
    kamus, biarkan, utuh = glosarium
    assert tj.terjemahkan(nama, kamus, biarkan, utuh) is None


def test_kata_yang_dikenal_memang_diterjemahkan(glosarium):
    """Reverse guard: a tool that refuses everything would keep all the refusal
    tests above green.
    """
    kamus, biarkan, utuh = glosarium
    assert tj.terjemahkan("berkas", kamus, biarkan, utuh) == "file"
    assert tj.terjemahkan("pesan_gagal", kamus, biarkan, utuh) == "message_fail"


def test_awalan_garis_bawah_dipertahankan(glosarium):
    """A leading underscore marks "internal" in Python; dropping it changes meaning."""
    kamus, biarkan, utuh = glosarium
    assert tj.terjemahkan("_berkas", kamus, biarkan, utuh) == "_file"
    assert tj.terjemahkan("__berkas", kamus, biarkan, utuh) == "__file"


def test_nama_yang_sudah_inggris_tidak_diutak_atik(glosarium):
    kamus, biarkan, utuh = glosarium
    for nm in ("device", "session", "timeout", "db", "conn"):
        assert tj.terjemahkan(nm, kamus, biarkan, utuh) is None


# ---------------------------------------------------------------------------
# 3. Whole-identifier entries win over word-by-word translation
# ---------------------------------------------------------------------------
def test_pengenal_utuh_membetulkan_susunan_kata(glosarium):
    """Indonesian puts the head word first, English last.

    Word by word gives `map_ping`; the correct result is `ping_map`.
    """
    kamus, biarkan, utuh = glosarium
    assert tj.terjemahkan("peta_ping", kamus, biarkan, utuh) == "ping_map"
    assert tj.terjemahkan("peta_hostname", kamus, biarkan, utuh) == "hostname_map"


def test_terlarang_menang_atas_pengenal_utuh(glosarium):
    """Lookup order matters, and this order is correct.

    `daftar_putih` is in both lists: in `pengenal:` as `allow_list`, and in
    TERLARANG because it is a JSON key read by `konfig.js` (`s.daftar_putih`).
    If `pengenal:` won, the automation guardrails page would silently stop
    showing its allow list.
    """
    kamus, biarkan, utuh = glosarium
    assert "daftar_putih" in utuh, "prasyarat uji ini berubah"
    assert tj.terjemahkan("daftar_putih", kamus, biarkan, utuh) is None


def test_pengenal_utuh_diperiksa_lebih_dulu(glosarium):
    """If the order were reversed, word-by-word would win and the `pengenal:`
    glossary section would never be used.
    """
    kamus, biarkan, utuh = glosarium
    # Without the `pengenal` section, word-by-word gives `map_ping`
    # (`peta` -> `map`, `ping` kept as is).
    assert tj.terjemahkan("peta_ping", kamus, biarkan, utuh=None) == "map_ping"
    assert tj.terjemahkan("peta_ping", kamus, biarkan, utuh) == "ping_map"


def test_terjemahan_tidak_boleh_menimpa_nama_bawaan_python(glosarium):
    """Translations that shadow builtins are refused.

    `daftar` -> `list` and `peta` -> `map` are valid glossary entries, but both
    shadow builtins. The code runs until a later `list(...)` in the same
    function, then fails with "TypeError: 'dict' object is not callable", which
    does not name the cause.
    """
    kamus, biarkan, utuh = glosarium
    assert kamus["daftar"] == "list", "prasyarat uji ini berubah"
    assert kamus["peta"] == "map"
    assert tj.terjemahkan("daftar", kamus, biarkan, utuh) is None
    assert tj.terjemahkan("peta", kamus, biarkan, utuh) is None


def test_terjemahan_tidak_boleh_menghasilkan_kata_kunci_python(glosarium):
    """Translations that produce Python keywords are refused.

    `lolos` -> `pass` and `dari` -> `from` are correct translations but yield
    invalid Python:

        pass = 0        <- SyntaxError

    `dir(__builtins__)` alone is not enough: it lists builtin functions and
    classes, not keywords.
    """
    kamus, biarkan, utuh = glosarium
    assert tj.terjemahkan("dari", kamus, biarkan, utuh) is None, "`from` kata kunci"
    assert tj.terjemahkan("tidak", kamus, biarkan, utuh) is None, "`not` kata kunci"


def test_kata_kunci_tetap_boleh_jadi_BAGIAN_nama(glosarium):
    """Reverse guard, so the keyword check is not too strict.

    `not` alone is a keyword; `not_exists` is not. Rejecting both would discard
    valid translations just because one word happens to be a keyword.
    """
    kamus, biarkan, utuh = glosarium
    assert tj.terjemahkan("tidak_ada", kamus, biarkan, utuh) == "not_exists"


def test_penjaga_bawaan_tidak_menolak_yang_bukan_bawaan(glosarium):
    kamus, biarkan, utuh = glosarium
    assert tj.terjemahkan("daftar_jeda", kamus, biarkan, utuh) == "pause_list"


# ---------------------------------------------------------------------------
# 3b. Names referenced from inside STRINGS
# ---------------------------------------------------------------------------
#
# Sample files are written as triple-quoted text rather than chained "\n"
# so they stay readable; the tool under test processes Python source.
PARAMETRIZE_SATU = '''\
import pytest


@pytest.mark.parametrize("nilai", [1, 2])
def test_x(nilai):
    assert nilai
'''

PARAMETRIZE_DUA = '''\
import pytest


@pytest.mark.parametrize("baris,nilai", [(1, 2)])
def test_x(baris, nilai):
    assert baris and nilai
'''

GETATTR_BERTEKS = '''\
def f(obj):
    nilai = getattr(obj, "nilai", None)
    return nilai
'''

TANPA_TEKS = '''\
def f(x):
    berkas = x + 1
    return berkas
'''


def _peta_ganti(tmp_path, isi, glosarium, nama="contoh.py"):
    p = tmp_path / nama
    p.write_text(isi, encoding="utf-8")
    kamus, biarkan, utuh = glosarium
    _n, peta = tj.ganti_di_berkas(str(p), kamus, biarkan, tulis=False, utuh=utuh)
    return dict(peta)


PARAMETER_PUBLIK = '''def bangun(db, sampai=None):
    hasil_lokal = sampai or 1
    return hasil_lokal
'''


def test_nama_parameter_tidak_pernah_diganti(tmp_path, glosarium):
    """Parameter names are refused: they are part of the function's interface.

    A parameter looks local, but callers in any file may pass it by keyword:

        rollup.bangun(sampai=kemarin)
        -> TypeError: bangun() got an unexpected keyword argument 'sampai'

    The `ast.keyword` guard only sees calls in the same file, and the tool works
    per file. `uji_permukaan_paket.py` also pins signatures on purpose, so a
    renamed parameter is an interface change.
    """
    peta = _peta_ganti(tmp_path, PARAMETER_PUBLIK, glosarium)
    assert "sampai" not in peta, "nama parameter ikut diganti -> %r" % peta


def test_nama_di_badan_fungsi_tetap_diganti(tmp_path, glosarium):
    """Reverse guard: if both parameters and bodies were refused, the tool would
    translate nothing while staying green.
    """
    peta = _peta_ganti(tmp_path, PARAMETER_PUBLIK, glosarium)
    assert peta.get("hasil_lokal") == "result_local"


def test_nama_parameter_yang_disebut_parametrize_tidak_disentuh(tmp_path, glosarium):
    """Names used in `pytest.mark.parametrize` strings are refused.

    `@pytest.mark.parametrize("nilai", [...])` names a parameter as TEXT. The
    tool renames the parameter (NAME token) but leaves the text (STRING token),
    so they stop matching and collection fails:

        function uses no argument 'nilai'

    Neither the syntax check nor the COMMENT/STRING token comparison catches
    this; only pytest does.
    """
    peta = _peta_ganti(tmp_path, PARAMETRIZE_SATU, glosarium, "test_contoh.py")
    assert "nilai" not in peta, "-> %r" % peta


def test_parametrize_banyak_nama_sekaligus(tmp_path, glosarium):
    """`parametrize("baris,nilai", ...)` names TWO parameters in one string."""
    peta = _peta_ganti(tmp_path, PARAMETRIZE_DUA, glosarium, "test_contoh.py")
    assert not ({"baris", "nilai"} & set(peta)), "-> %r" % peta


def test_getattr_berteks_tidak_ikut_terputus(tmp_path, glosarium):
    """Same pattern outside pytest: `getattr(obj, "nilai")` names an attribute as text.

    The rule is deliberately general, not a pytest special case: a name that
    appears as a whole string in the same file is treated as crossing a boundary.
    """
    assert "nilai" not in _peta_ganti(tmp_path, GETATTR_BERTEKS, glosarium)


def test_nama_yang_TIDAK_disebut_teks_tetap_diganti(tmp_path, glosarium):
    """Reverse guard: the "name appears as text" rule is stricter than needed,
    but it must not swallow everything, or the tool translates nothing while
    staying green.
    """
    assert _peta_ganti(tmp_path, TANPA_TEKS, glosarium).get("berkas") == "file"




# ---------------------------------------------------------------------------
# 4. Names that cross a boundary
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nama", ["platform", "teks", "temuan", "jumlah",
                                  "jaring_pengaman", "ip_address"])
def test_nama_terlarang_tidak_pernah_diterjemahkan(nama, glosarium):
    """Database columns and JSON keys. Renaming them only in Python makes pages
    render empty with no error, which reads as "no data" rather than breakage.
    """
    kamus, biarkan, utuh = glosarium
    assert tj.terjemahkan(nama, kamus, biarkan, utuh) is None


def test_atribut_dan_argumen_kata_kunci_dikecualikan(tmp_path, glosarium):
    """`d.hasil` and `f(hasil=...)` are referenced from OUTSIDE the function.

    The first belongs to the model, the second to the callee. Renaming either
    here breaks the other side, and not always loudly.
    """
    p = tmp_path / "contoh.py"
    p.write_text(
        "def f(x):\n"
        "    hasil = x.hasil\n"  # `hasil` also appears as an attribute
        "    return hasil\n"
        "def g(y):\n"
        "    return f(hasil=y)\n",  # and as a keyword argument
        encoding="utf-8")
    kamus, biarkan, utuh = glosarium
    n, peta = tj.ganti_di_berkas(str(p), kamus, biarkan, tulis=False, utuh=utuh)
    assert dict(peta).get("hasil") is None, "atribut/kwarg ikut diganti -> %r" % peta


def test_nama_tingkat_modul_dikecualikan(tmp_path, glosarium):
    """Other files may import it. Renaming it in one file breaks every caller,
    so that is a separate step, not a side effect.
    """
    p = tmp_path / "contoh.py"
    p.write_text("HASIL = 1\n\ndef hitung():\n    return HASIL\n", encoding="utf-8")
    kamus, biarkan, utuh = glosarium
    _n, peta = tj.ganti_di_berkas(str(p), kamus, biarkan, tulis=False, utuh=utuh)
    assert "HASIL" not in dict(peta)
    assert "hitung" not in dict(peta)


# ---------------------------------------------------------------------------
# 5. MAIN GUARD: comments and strings never change
# ---------------------------------------------------------------------------
CONTOH = '''\
"""Docstring berbahasa Indonesia yang menyebut hasil dan baris.

Kalimat ini tidak boleh berubah satu huruf pun.
"""


def olah(masukan):
    # Komentar yang menyebut berkas, baris, dan nilai.
    berkas = []
    for baris in masukan:
        nilai = baris.strip()
        if nilai:
            berkas.append({"hasil": nilai, "baris": baris})
    return {"pesan": "hasil diolah, %d baris" % len(berkas), "isi": berkas}
'''


def _token(src, jenis):
    return [t.string for t in tokenize.generate_tokens(io.StringIO(src).readline)
            if t.type in jenis]


@pytest.fixture
def sesudah_diganti(tmp_path, glosarium):
    p = tmp_path / "contoh.py"
    p.write_text(CONTOH, encoding="utf-8")
    kamus, biarkan, utuh = glosarium
    tj.ganti_di_berkas(str(p), kamus, biarkan, tulis=True, utuh=utuh)
    return p.read_text(encoding="utf-8")


def test_komentar_tidak_berubah_satu_huruf_pun(sesudah_diganti):
    assert _token(CONTOH, {tokenize.COMMENT}) == _token(sesudah_diganti, {tokenize.COMMENT})


def test_string_dan_docstring_tidak_berubah_satu_huruf_pun(sesudah_diganti):
    """Includes DICT KEYS. `{"hasil": ...}` is a JSON field name read by Java;
    renaming the key only in Python fails silently.
    """
    assert _token(CONTOH, {tokenize.STRING}) == _token(sesudah_diganti, {tokenize.STRING})
    assert '"hasil"' in sesudah_diganti, "kunci dict ikut terganti"
    assert "hasil diolah" in sesudah_diganti, "kalimat Indonesia ikut terganti"


def test_nama_lokalnya_memang_berubah(sesudah_diganti):
    """Without this, the three tests above would pass for a tool that does nothing."""
    assert "file = []" in sesudah_diganti
    assert "value = line_of.strip()" not in sesudah_diganti  # not the expected form
    assert "value = " in sesudah_diganti

    # `baris` is intentionally unchanged: it also appears as the dict key
    # `"baris"` in the same file, so the string guard treats it as crossing a
    # boundary.
    assert "for baris in" in sesudah_diganti


def test_hasil_gantinya_masih_bisa_diurai(sesudah_diganti):
    import ast
    ast.parse(sesudah_diganti)


def test_berkas_yang_hasilnya_rusak_tidak_ditulis(tmp_path, glosarium):
    """A rename that yields a broken file must stop in the tool, not later in
    `pytest`.
    """
    p = tmp_path / "rusak.py"
    p.write_text("def f(:\n    pass\n", encoding="utf-8")
    kamus, biarkan, utuh = glosarium
    n, _peta = tj.ganti_di_berkas(str(p), kamus, biarkan, tulis=True, utuh=utuh)
    assert n == 0
    assert p.read_text(encoding="utf-8") == "def f(:\n    pass\n", "berkas rusak tertimpa"


# ---------------------------------------------------------------------------
# 3c. Name collisions
# ---------------------------------------------------------------------------
#
# Dangerous because collisions pass every other check: the result parses,
# comments and strings are identical, and pytest still collects it. Only the
# meaning breaks, and the code keeps producing numbers, just wrong ones.
SASARAN_SUDAH_DIPAKAI = '''\
def f(hour):
    jam = hour + 1
    return jam
'''

DUA_JADI_SATU = '''\
def f(a, b):
    periksa = a
    cek = b
    return periksa + cek
'''

ANGKA_DI_EKOR = '''\
def f(a, b):
    jam1 = a
    jam2 = b
    return jam1 + jam2
'''


def test_sasaran_yang_sudah_dipakai_ditolak(tmp_path, glosarium):
    """`jam` -> `hour`, but `hour` is already a parameter name in that file.

    Proceeding would make two different things share one name and silently
    overwrite each other.
    """
    peta = _peta_ganti(tmp_path, SASARAN_SUDAH_DIPAKAI, glosarium)
    assert "jam" not in peta, "-> %r" % peta


def test_dua_nama_yang_jadi_satu_sasaran_ditolak(tmp_path, glosarium):
    r"""Two different Indonesian words mapping to one English word.

    The glossary has eleven such pairs: `periksa` and `cek` both map to
    `check`, `tindakan` and `aksi` both to `action`. If both appear in one
    file, two variables merge into one name and silently overwrite each other.
    The numeric-suffix case (`jam1`/`jam2`) is handled in `pecah()` (see the
    next test); this different-word case cannot be, so this guard is needed.
    """
    peta = _peta_ganti(tmp_path, DUA_JADI_SATU, glosarium)
    assert not ({"periksa", "cek"} & set(peta)), "-> %r" % peta


def test_angka_di_ekor_nama_tidak_hilang(tmp_path, glosarium):
    r"""`jam1` -> `hour1`, not `hour`.

    A word splitter using `[_\d]+` would drop the digits, so `jam1` and `jam2`
    both become `hour`. Duplicates are caught by the collision guard, but a lone
    name losing its digit is caught by nothing: `hour` is a valid name and the
    file runs with silently changed meaning.
    """
    peta = _peta_ganti(tmp_path, ANGKA_DI_EKOR, glosarium)
    assert peta.get("jam1") == "hour1", "-> %r" % peta
    assert peta.get("jam2") == "hour2", "-> %r" % peta


def test_sasaran_yang_bebas_tetap_dipakai(tmp_path, glosarium):
    """Reverse guard: collision refusal must not swallow translations whose target
    name is not used anywhere.
    """
    isi = "def f(x):\n    jam = x + 1\n    return jam\n"
    assert _peta_ganti(tmp_path, isi, glosarium).get("jam") == "hour"

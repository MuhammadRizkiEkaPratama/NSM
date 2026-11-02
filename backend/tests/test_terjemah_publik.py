# -*- coding: utf-8 -*-
"""Tests for `terjemah_publik.py`, the repo-wide public function renamer.

Almost all tests check REFUSALS, on purpose. The tool renames names that
cross files, so a mistake breaks every caller, often silently until the code
runs. Its value lies in what it correctly refuses.

Each refusal test notes what would happen if its guard were removed.
"""

import io
import os

import pytest

import terjemah_publik as tp


# Small glossary so tests do not change whenever the repo glossary is edited.
KAMUS = {
    "ambil": "fetch", "data": "data", "baca": "read", "sandi": "password",
    "simpan": "save", "jam": "hour", "hari": "day", "periksa": "check",
    "cek": "check", "layanan": "service", "daftar": "list", "berkas": "file",
    "backup": "backup", "terbaru": "latest", "sesi": "session",
    "olah": "process",
}
BIARKAN = {"http", "sftp", "mysql", "data", "backup"}
GLOS = (KAMUS, BIARKAN, {})


def _repo(tmp_path, berkas):
    """Create a fake repo in `tmp_path`; return its path as a string."""
    for nama, isi in berkas.items():
        p = tmp_path / nama
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(isi, encoding="utf-8")
    return str(tmp_path)


def _peta(tmp_path, berkas):
    akar = _repo(tmp_path, berkas)
    ganti, _tolak = tp.peta(akar=akar, glos=GLOS)
    return ganti


def _sebab(tmp_path, berkas, nama):
    akar = _repo(tmp_path, berkas)
    _ganti, tolak = tp.peta(akar=akar, glos=GLOS)
    return dict(tolak).get(nama)


# ------------------------------------------------------------------ allowed

def test_fungsi_publik_satu_kata_diganti(tmp_path):
    """A one-word name has no word order to get wrong."""
    assert _peta(tmp_path, {"a.py": "def olah():\n    return 1\n"}) == {"olah": "process"}


def test_kata_kerja_tambah_satu_kata_diganti(tmp_path):
    """`baca_sandi` -> `read_password`: Indonesian and English order happen to
    match for verb + one object.
    """
    assert _peta(tmp_path, {"a.py": "def baca_sandi():\n    return 1\n"}) \
        == {"baca_sandi": "read_password"}


def test_pemanggil_di_berkas_lain_ikut_diganti(tmp_path):
    """This is why the tool exists.

    `terjemah.py` works per file, so it would rename the definition and leave
    callers pointing at a missing name. Both import styles used in this repo
    must be updated.
    """
    akar = _repo(tmp_path, {
        "a.py": "def baca_sandi():\n    return 1\n",
        "b.py": "from a import baca_sandi\n\nx = baca_sandi()\n",
        "c.py": "import a\n\ny = a.baca_sandi()\n",
    })
    tp.jalankan(akar=akar, tulis=True, glos=GLOS, akar_dok=str(tmp_path / "kosong"))
    for nama in ("a.py", "b.py", "c.py"):
        isi = io.open(os.path.join(akar, nama), encoding="utf-8").read()
        assert "read_password" in isi
        assert "baca_sandi" not in isi


def test_nama_privat_tidak_pernah_disentuh(tmp_path):
    """Layer B covers the public SURFACE; underscore-prefixed names are not part of it."""
    assert _peta(tmp_path, {"a.py": "def _olah():\n    return 1\n"}) == {}


# ------------------------------------------------------------------ refused

def test_didefinisikan_di_dua_modul_ditolak(tmp_path):
    """If `olah` exists in two modules, token replacement cannot tell which caller
    belongs to which and would rename both.
    """
    s = _sebab(tmp_path, {"a.py": "def olah():\n    return 1\n",
                          "b.py": "def olah():\n    return 2\n"}, "olah")
    assert s and "2 modul" in s


def test_nama_yang_juga_metode_ditolak(tmp_path):
    """Token replacement cannot tell function `olah()` from method
    `sesuatu.olah()`. Proceeding would rename another class's method but not
    its callers.
    """
    s = _sebab(tmp_path, {
        "a.py": "def olah():\n    return 1\n",
        "b.py": "class K:\n    def olah(self):\n        return 2\n"}, "olah")
    assert s and "metode" in s


def test_nama_yang_juga_atribut_ditolak(tmp_path):
    """`x.olah` could be an attribute of any object. Telling it apart from a
    module alias needs type inference, and half-correct inference fails
    silently.
    """
    s = _sebab(tmp_path, {"a.py": "def olah():\n    return 1\n",
                          "b.py": "def f(x):\n    return x.olah\n"}, "olah")
    assert s and "atribut" in s


def test_nama_yang_juga_variabel_ditolak(tmp_path):
    s = _sebab(tmp_path, {"a.py": "def olah():\n    return 1\n",
                          "b.py": "def f():\n    olah = 2\n    return olah\n"}, "olah")
    assert s and "variabel" in s


def test_nama_yang_juga_parameter_ditolak(tmp_path):
    s = _sebab(tmp_path, {"a.py": "def olah():\n    return 1\n",
                          "b.py": "def f(olah):\n    return olah\n"}, "olah")
    assert s and "parameter" in s


def test_nama_yang_dikirim_sebagai_kata_kunci_ditolak(tmp_path):
    """`f(olah=...)`: the name belongs to the callee (same rule as in Layer A)."""
    s = _sebab(tmp_path, {"a.py": "def olah():\n    return 1\n",
                          "b.py": "def g(**k):\n    return k\n\ng(olah=1)\n"}, "olah")
    assert s and "kata kunci" in s


def test_nama_di_dalam_string_ditolak(tmp_path):
    """Strings are NOT renamed, so `getattr(m, "olah")` and `tambal("olah")`
    would point to a missing name.

    This fails at pytest collection time, not at run time.
    """
    s = _sebab(tmp_path, {"a.py": "def olah():\n    return 1\n",
                          "b.py": 'import a\n\nf = getattr(a, "olah")\n'}, "olah")
    assert s and "string" in s


def test_sasaran_yang_sudah_dipakai_ditolak(tmp_path):
    """If `process` already exists in the repo, renaming `olah` to `process`
    makes two different things share one name.
    """
    s = _sebab(tmp_path, {"a.py": "def olah():\n    return 1\n",
                          "b.py": "def f():\n    process = 1\n    return process\n"},
               "olah")
    assert s and "sudah dipakai" in s


def test_dua_nama_satu_sasaran_ditolak_keduanya(tmp_path):
    """`periksa` and `cek` both map to `check`. BOTH are dropped, not one:
    choosing one would merge two different things.
    """
    ganti = _peta(tmp_path, {"a.py": "def periksa():\n    return 1\n",
                             "b.py": "def cek():\n    return 2\n"})
    assert "periksa" not in ganti and "cek" not in ganti


# --------------------------------------------------------------- word order

def test_kepala_kata_benda_ditolak(tmp_path):
    """Indonesian is head-first, English head-last.

        backup_terbaru -> backup_latest    should be: latest_backup

    The tool does not reorder words, and guessing the order is worse than not
    translating at all.
    """
    s = _sebab(tmp_path, {"a.py": "def backup_terbaru():\n    return 1\n"},
               "backup_terbaru")
    assert s and "kepala kata benda" in s


def test_tiga_kata_ditolak_walau_kepalanya_kata_kerja(tmp_path):
    """Only a verb plus exactly ONE word is allowed.

    Requiring just a leading verb fixes only the FIRST word's position; later
    words keep Indonesian order:

        simpan_sesi_sftp -> save_session_sftp   should be save_sftp_session
    """
    s = _sebab(tmp_path, {"a.py": "def simpan_sesi_sftp():\n    return 1\n"},
               "simpan_sesi_sftp")
    assert s and "kepala kata benda" in s


def test_nama_uji_ikut_tersaring(tmp_path):
    """`test_*` and `uji_*` names are SENTENCES, not verb phrases.
    `test_berkas_benar_lolos` would become `test_file_correct_passed` instead
    of `test_correct_file_passes`.
    """
    ganti = _peta(tmp_path, {"a.py": "def uji_daftar_berkas():\n    return 1\n"})
    assert "uji_daftar_berkas" not in ganti


# -------------------------------------------------------------------- abort

def test_komentar_dan_string_tidak_berubah(tmp_path):
    """The same name inside comments and strings is TEXT PEOPLE READ, which is
    outside this tool's scope (user-facing text stays Indonesian).
    """
    akar = _repo(tmp_path, {
        "a.py": ('def baca_sandi():\n'
                 '    # baca_sandi dipanggil poller\n'
                 '    return "baca_sandi selesai"\n')})
    tp.jalankan(akar=akar, tulis=True, glos=GLOS, akar_dok=str(tmp_path / "kosong"))
    isi = io.open(os.path.join(akar, "a.py"), encoding="utf-8").read()
    assert "def read_password():" in isi
    assert "# baca_sandi dipanggil poller" in isi
    assert '"baca_sandi selesai"' in isi


def test_satu_berkas_gagal_membatalkan_semuanya(tmp_path):
    """A repo with HALF its functions renamed does not run at all. Skipping
    failed files is worse than doing nothing.
    """
    akar = _repo(tmp_path, {"a.py": "def baca_sandi():\n    return 1\n"})
    asli = io.open(os.path.join(akar, "a.py"), encoding="utf-8").read()

    # Force one file to fail the check after the rename map is computed.
    urai_asli = tp.ast.parse

    def urai_pincang(src, *a, **k):
        if "read_password" in src:
            raise SyntaxError("dipaksa gagal")
        return urai_asli(src, *a, **k)

    tp.ast.parse = urai_pincang
    try:
        h = tp.jalankan(akar=akar, tulis=True, glos=GLOS,
                        akar_dok=str(tmp_path / "kosong"))
    finally:
        tp.ast.parse = urai_asli

    assert h["gagal"], "seharusnya melapor gagal"
    assert h["berkas"] == 0
    assert io.open(os.path.join(akar, "a.py"), encoding="utf-8").read() == asli


# --------------------------------------------------------------------- docs

def test_dokumen_ikut_diperbarui(tmp_path):
    """Docs pointing at functions that no longer exist mislead more than
    mixed-language docs.
    """
    akar = tmp_path / "kode"
    dok = tmp_path / "dok"
    akar.mkdir(); dok.mkdir()
    (akar / "a.py").write_text("def baca_sandi():\n    return 1\n", encoding="utf-8")
    (dok / "x.md").write_text("Fungsi `baca_sandi()` dipanggil poller.\n", encoding="utf-8")
    tp.jalankan(akar=str(akar), tulis=True, glos=GLOS, akar_dok=str(dok))
    assert "read_password" in (dok / "x.md").read_text(encoding="utf-8")


def test_dokumen_hanya_nama_bergaris_bawah(tmp_path):
    """`baris` and `jam` appear in hundreds of Markdown files as ordinary
    Indonesian words, not function references, and text matching cannot tell
    them apart. One-word names are therefore never touched in docs, though they
    are still renamed in Python.
    """
    akar = tmp_path / "kode"
    dok = tmp_path / "dok"
    akar.mkdir(); dok.mkdir()
    (akar / "a.py").write_text("def olah():\n    return 1\n", encoding="utf-8")
    (dok / "x.md").write_text("Data itu diolah, lalu olah lagi besok.\n",
                              encoding="utf-8")
    tp.jalankan(akar=str(akar), tulis=True, glos=GLOS, akar_dok=str(dok))
    assert (dok / "x.md").read_text(encoding="utf-8") == \
        "Data itu diolah, lalu olah lagi besok.\n"


# ------------------------------------------------------ against the real repo

def test_repo_sungguhan_tidak_menghasilkan_kegagalan():
    """Dry run against the real repo. Any file that fails the check must show up
    here, not later in pytest.
    """
    h = tp.jalankan(akar=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    tulis=False)
    assert h["gagal"] == []

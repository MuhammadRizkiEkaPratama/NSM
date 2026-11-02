"""Guards for the migration harness itself.

`SUDAH_PINDAH` decides which files the wrapper STOPS running. One wrong entry
makes a test file vanish from the report with no error, the costliest failure
shape in this project. A checker never proven to find problems only gives
false confidence, so the harness has its own guards.
"""
import os

import pytest
from conftest import BACKEND, SUDAH_PINDAH, berkas_uji_di_disk, muat_manifest

pytestmark = pytest.mark.murni

TESTS = os.path.join(BACKEND, "tests")


def test_setiap_yang_didaftar_pindah_punya_pengganti_nyata():
    """Every name in `SUDAH_PINDAH` must have a real replacement file; otherwise
    adding a name stops a test file forever while the report stays green.
    """
    missing = [(old, baru) for old, baru in SUDAH_PINDAH.items()
              if not os.path.exists(os.path.join(TESTS, baru))]
    assert not missing, (
        "berkas ini didaftarkan sudah pindah, tetapi penggantinya TIDAK ADA "
        "di tests/ -- artinya ujinya berhenti dijalankan tanpa ada yang "
        "menggantikan: %r" % missing)


def test_setiap_yang_didaftar_pindah_masih_ada_asalnya_atau_sudah_bersih():
    """If the source file still exists it must still be in the manifest. During the
    transition `jalankan_ci.py` runs the source files; one that is on disk but
    out of the manifest would be run by no runner.
    """
    m = muat_manifest() or {}
    recorded = set()
    for k in ("murni", "butuh_lab", "merah_saat_diukur", "tidak_terukur",
              "dikecualikan"):
        recorded |= set(m.get(k) or [])

    at_disk = set(berkas_uji_di_disk())
    yatim = [n for n in SUDAH_PINDAH
             if n in at_disk and n not in recorded]
    assert not yatim, (
        "berkas ini sudah dilewati pytest (SUDAH_PINDAH) DAN tidak ada di "
        "ci_manifest.json, jadi tidak dijalankan runner mana pun: %r" % yatim)


def test_tidak_ada_berkas_uji_yang_lolos_dari_kedua_runner():
    """Every `uji_*.py` on disk must be run by exactly one path. This counts rather
    than assumes.
    """
    m = muat_manifest() or {}
    recorded = set()
    for k in ("murni", "butuh_lab", "merah_saat_diukur", "tidak_terukur",
              "dikecualikan"):
        recorded |= set(m.get(k) or [])

    tak_terjangkau = [n for n in berkas_uji_di_disk()
                      if n not in recorded and n not in SUDAH_PINDAH]
    assert not tak_terjangkau, (
        "berkas uji ini tidak ada di ci_manifest.json DAN belum dipindahkan "
        "ke pytest asli -- tidak ada yang menjalankannya: %r" % tak_terjangkau)

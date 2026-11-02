"""Bridge: each legacy `uji_*.py` file becomes one pytest test.

Layer 1 of the migration (see `conftest.py` for why there are two layers).
It runs each file as a subprocess and turns its exit code into a pytest
verdict, without rewriting any test file.

What this provides
------------------
  * one standard entry point: `pytest`
  * markers: `-m murni`, `-m butuh_lab`, `-m mengubah_perangkat`
  * parallel runs: `pytest -n auto` (pytest-xdist), safe because each file
    is still its own subprocess
  * one report, with the output of failing files printed

What it does not provide
------------------------
Each file is still ONE pytest test. `uji_report_service.py` holds 78 checks,
but pytest sees a single pass or fail. Per-check results require rewriting
the file as native pytest (layer 2).
"""
import pytest
from conftest import run_file


def test_berkas_uji_warisan(berkas_warisan, request):
    """Run one legacy test file; exit code 0 means pass."""
    if "manifest_basi" in request.node.keywords:
        pytest.fail(
            "'%s' ada di disk tetapi TIDAK ada di satu pun keranjang "
            "ci_manifest.json.\n\n"
            "Ini bukan hal sepele. Pada 23 Agustus 2026 ada 15 berkas uji "
            "dalam keadaan ini, dan CI tetap melaporkan '61 hijau, 0 MERAH' "
            "-- benar tentang yang dijalankan, menyesatkan tentang yang "
            "diperiksa.\n\n"
            "Perbaiki dengan:\n"
            "    venv\\Scripts\\python.exe ci_klasifikasi.py --berkas %s"
            % (berkas_warisan, berkas_warisan))

    passed, output = run_file(berkas_warisan)
    if not passed:
        # Print the output in full, not summarized: real defects have been spotted
        # from numbers inside passing output.
        pytest.fail("%s GAGAL\n\n%s" % (berkas_warisan, output), pytrace=False)

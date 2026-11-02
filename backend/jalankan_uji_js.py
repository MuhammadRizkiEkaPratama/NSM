"""Shared runner for the JavaScript tests under `frontend/`.

`jalankan_semua_uji.py` only collects `uji_*.py` in `backend/`, so each JS test file
under `frontend/src/test/js/` gets a thin `uji_*_js.py` wrapper here.

The name deliberately does not start with `uji_`, so CI does not collect this
helper as a test.

Node missing = SKIPPED, not passed. Reporting a pass for something never checked
is a false green (same rule as `uji_pulih_backup.py`).
"""
import os
import shutil
import subprocess

DIR = os.path.dirname(os.path.abspath(__file__))


def jalankan(nama_berkas, sebutan):
    """Run one JS test file and return a CI-style exit code.

    `sebutan` is used in the "DILEWATI" message so the CI output says which part was
    not checked.
    """
    test = os.path.normpath(os.path.join(
        DIR, "..", "frontend", "src", "test", "js", nama_berkas))

    if not os.path.exists(test):
        print("  [GAGAL] berkas ujinya sendiri tidak ada: %s" % test)
        return 1

    node = shutil.which("node")
    if not node:
        print("  [LEWAT] `node` tidak ada di PATH -- uji JavaScript halaman")
        print("          %s tidak bisa dijalankan. DILEWATI, bukan" % sebutan)
        print("          dianggap lolos.")
        return 0

    hasil = subprocess.run([node, test], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300)
    print(hasil.stdout.rstrip())
    if hasil.stderr.strip():
        print(hasil.stderr.rstrip())
    return hasil.returncode

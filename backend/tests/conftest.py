"""pytest harness for NSM.

Many legacy `uji_*.py` files run their tests at module level, so importing
them during pytest collection would execute them (network, database, even
real devices) and collect almost no tests.

Two layers:
1. Each legacy `uji_*.py` is wrapped as one pytest test that runs it as a
   subprocess, exactly like `jalankan_ci.py`: same process isolation, same
   exit-code verdict, same per-file timeout. Markers come from `ci_manifest.json`.
2. Files rewritten as real pytest live in `tests/` as `test_*.py` and are
   registered in `SUDAH_PINDAH` so the wrapper stops running them (nothing runs twice).

Process isolation must stay until a file is truly rewritten: running many
files in one process lets patches leak between files (patches that apply once
for all, modules already imported, leaked global state), and the failures are
silent: tests stay green while no longer testing what they claim.
"""
import json
import os
import subprocess
import sys

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

MANIFEST = os.path.join(BACKEND, "ci_manifest.json")

# Legacy files already rewritten as real pytest (layer 2).
#
# The wrapper stops running these because the replacement exists in `tests/`.
# The list is explicit rather than guessed from file names, so a file can never
# stop running without its replacement existing. The original `uji_*.py` files
# stay until the old runner is retired, so each file runs exactly once per runner.
#
# Value: legacy file name -> replacement file name in `tests/`.
SUDAH_PINDAH = {
    "uji_akar.py": "test_akar.py",
    "uji_kualitas_sambungan.py": "test_kualitas_sambungan.py",
    "uji_ambang_diamati.py": "test_ambang_diamati.py",
    "uji_layanan_ringkas.py": "test_layanan_ringkas.py",
    "uji_kestabilan.py": "test_kestabilan.py",
    "uji_sumberdaya.py": "test_sumberdaya.py",
    "uji_flow.py": "test_flow.py",
    "uji_notifikasi_tangga.py": "test_notifikasi_tangga.py",
    "uji_akseslog.py": "test_akseslog.py",
    "uji_bukti_layanan.py": "test_bukti_layanan.py",
    "uji_perintah_ip_sesi.py": "test_perintah_ip_sesi.py",
    "uji_identitas_sumber.py": "test_identitas_sumber.py",
}


def pytest_addoption(parser):
    parser.addoption(
        "--lab", action="store_true", default=False,
        help="ikut jalankan uji yang butuh lab hidup (VM, router, LDAP)")
    parser.addoption(
        "--ubah-perangkat", action="store_true", default=False,
        help="ikut jalankan uji yang MENGUBAH perangkat sungguhan")


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
def muat_manifest():
    if not os.path.exists(MANIFEST):
        return None
    with open(MANIFEST, encoding="utf-8") as f:
        return json.load(f)


def berkas_uji_di_disk():
    return sorted(f for f in os.listdir(BACKEND)
                  if f.startswith("uji_") and f.endswith(".py"))


def penanda_untuk(nama, m):
    """Translate manifest buckets into pytest markers.

    The classification in `ci_manifest.json` was expensive to measure (about 40
    minutes per full run) and records which tests need the live lab and which
    change devices; guessing again from file names would lose that.
    """
    if nama in set(m.get("dikecualikan") or []):
        return "mengubah_perangkat"
    if nama in set(m.get("butuh_lab") or []):
        return "butuh_lab"
    if nama in set(m.get("murni") or []):
        return "murni"
    return None


# ---------------------------------------------------------------------------
# Parametrisasi
# ---------------------------------------------------------------------------
def pytest_generate_tests(metafunc):
    if "berkas_warisan" not in metafunc.fixturenames:
        return

    m = muat_manifest()
    if m is None:
        pytest.skip("ci_manifest.json tidak ada; jalankan ci_klasifikasi.py")

    kasus = []
    for nama in berkas_uji_di_disk():
        if nama in SUDAH_PINDAH:
            continue
        tanda = penanda_untuk(nama, m)
        marker = []
        if tanda:
            marker.append(getattr(pytest.mark, tanda))
        else:
            # Files on disk that are in no bucket are not skipped silently: they are
            # marked as failures so a stale manifest is noticed.
            marker.append(pytest.mark.manifest_basi)
        kasus.append(pytest.param(nama, marks=marker, id=nama[:-3]))

    metafunc.parametrize("berkas_warisan", kasus)


def pytest_collection_modifyitems(config, items):
    bypass_lab = not config.getoption("--lab")
    bypass_change = not config.getoption("--ubah-perangkat")
    for item in items:
        if bypass_lab and "butuh_lab" in item.keywords:
            item.add_marker(pytest.mark.skip(
                reason="butuh lab hidup; jalankan dengan --lab"))
        if bypass_change and "mengubah_perangkat" in item.keywords:
            item.add_marker(pytest.mark.skip(
                reason="MENGUBAH perangkat sungguhan; jalankan dengan --ubah-perangkat"))


def run_file(nama):
    """Run one `uji_*.py` as a subprocess. Returns (passed, output).

    The invocation deliberately matches `jalankan_ci.jalankan_satu`, including:
    `-X utf8` forces UTF-8 output from the child, and `errors="replace"` keeps
    reading intact if stray bytes remain. Without them one bad byte (for example
    0x97 from `mysqldump` or `net.exe`) kills the subprocess reader thread
    silently: `stdout` becomes `None` and the report says "RED" with no explanation.
    """
    import jalankan_ci

    limit = jalankan_ci.batas_untuk(nama)
    try:
        h = subprocess.run(
            [sys.executable, "-X", "utf8", nama],
            cwd=BACKEND, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=limit)
        return h.returncode == 0, (h.stdout or "") + (h.stderr or "")
    except subprocess.TimeoutExpired as e:
        output = (e.stdout or "") + (e.stderr or "")
        if isinstance(output, bytes):
            output = output.decode("utf-8", "replace")
        return False, output + "\n[pytest] kehabisan waktu %d detik" % limit

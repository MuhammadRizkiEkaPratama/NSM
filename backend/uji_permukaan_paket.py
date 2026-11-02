"""Test: the SURFACE of `report_service` and `poller` is unchanged after splitting.

`report_service.py` (6,046 lines) became a 12-module package and `poller.py`
(3,159 lines) became a scheduler plus `nsm/pemantau/` (10 modules). What must be
preserved is the DOOR, not the file layout: every name that used to be callable
must stay callable with the exact same signature. A name lost in the split raises
no error until the path using it runs, and some paths run only monthly or during
incidents. Underscore-prefixed names are included, since tests use them
(`rs._cache.clear()` in `uji_report_service.py`).

`report_service_permukaan.json` was recorded from the package after the split and
compared with the pre-split file. Only two differences were found, neither a defect:

  * modules and model classes that used to leak into the surface (`json`, `os`,
    `re`, `config`, ...) no longer do; no file used them via `report_service.`;
  * `ALAMAT_NSM` is a `set` whose `repr` order differs between processes, so
    sets are recorded sorted.

Pure test: touches no database, network, or device.

Run: py uji_permukaan_report_service.py
"""
import inspect
import json
import os
import sys

import report_service as rs

DIR = os.path.dirname(os.path.abspath(__file__))
ACUAN = os.path.join(DIR, "report_service_permukaan.json")
PENJADWAL = os.path.join(DIR, "poller_permukaan.json")


def gambarkan(o):
    if inspect.isfunction(o):
        return "fungsi" + str(inspect.signature(o))
    if inspect.ismodule(o):
        return "modul:" + o.__name__
    if isinstance(o, (set, frozenset)):
        return "himpunan:" + repr(sorted(o))[:300]
    if inspect.isclass(o):
        # Names only, not `repr`: a class `repr` contains its module name, which
        # legitimately moves when a file is split.
        return "kelas:" + o.__name__
    if isinstance(o, (str, int, float, bool, type(None), list, dict, tuple)):
        return "nilai:" + repr(o)[:300]
    # Other objects are recorded by TYPE only, not content. `SessionLocal`'s `repr`
    # contains the whole connection URL, which would put the database host, user, and
    # name into `report_service_permukaan.json`, a Git-tracked file; it would also
    # make the test depend on the local `.env`. If `SessionLocal` disappears or stops
    # being a sessionmaker, the test still turns red.
    return "jenis:" + type(o).__name__


# Names whose VALUE comes from `.env`, so only their TYPE is recorded. Recording
# values would put installation-specific network addresses into a Git-tracked file
# and make the test green on one machine only. If the name disappears or changes
# from set/map to something else, the test still turns red.
DARI_KONFIGURASI = {"ALAMAT_NSM", "LOKASI_ACL_ROUTER"}


def _bandingkan(modul, berkas_acuan, judul):
    reference = json.load(open(berkas_acuan, encoding="utf-8"))
    current = {n: ("jenis:" + type(getattr(modul, n)).__name__
                if n in DARI_KONFIGURASI else gambarkan(getattr(modul, n)))
            for n in dir(modul) if not n.startswith("__")}

    missing = sorted(set(reference) - set(current))
    assert not missing, (f"{len(missing)} nama HILANG dari {judul}: "
                        f"{missing[:8]} -- ada yang tercecer saat memecah paket")

    diff = sorted(n for n in reference if n in current and reference[n] != current[n])
    assert not diff, (f"{len(diff)} nama {judul} berubah bentuk: "
                      + "; ".join(f"{n}: {reference[n]} -> {current[n]}" for n in diff[:3]))
    print(f"  {judul}: {len(reference)} nama ada semua, tanda tangan sama")


def uji_permukaan_report_service():
    _bandingkan(rs, ACUAN, "report_service")


def uji_permukaan_poller():
    """The four syslog state names are intentionally no longer in `poller.`. Their
    functions REBIND them (`global`); a name re-imported into `poller` would stop
    following the rebinding and become a stale copy.
    """
    import poller
    _bandingkan(poller, PENJADWAL, "poller")


def uji_tidak_melingkar():
    """`_inti` must not import any `bidang` module. This rule is what lets the split
    load at all: if one `bidang` needs another, the shared code moves down into `_inti`.
    """
    core = open(os.path.join(DIR, "report_service", "_inti.py"),
                encoding="utf-8").read()
    bidang = [b[:-3] for b in os.listdir(os.path.join(DIR,
                                                      "report_service"))
              if b.endswith(".py") and b not in ("__init__.py", "_inti.py")]
    melanggar = [b for b in bidang
                 if f"from .{b} import" in core or f"from . import {b}" in core]
    assert not melanggar, f"_inti bergantung pada bidang: {melanggar}"
    print(f"  _inti bebas dari {len(bidang)} bidang: tidak ada lingkaran impor")


def uji_semua_bidang_terekspor():
    """Every `bidang` module must be wired into `__init__`. A module that exists but is
    not exported is dead code that looks alive.
    """
    init = open(os.path.join(DIR, "report_service",
                             "__init__.py"), encoding="utf-8").read()
    file = [b[:-3] for b in os.listdir(os.path.join(DIR,
                                                      "report_service"))
              if b.endswith(".py") and b != "__init__.py"]
    lupa = [b for b in file if f"from .{b} import" not in init]
    assert not lupa, f"modul tidak diekspor `__init__`: {lupa}"
    print(f"  {len(file)} modul bidang: semuanya diekspor")


if __name__ == "__main__":
    gagal = 0
    for uji in [uji_permukaan_report_service, uji_permukaan_poller,
                uji_tidak_melingkar, uji_semua_bidang_terekspor]:
        print(f"{uji.__name__} ...")
        try:
            uji()
        except AssertionError as e:
            gagal += 1
            print(f"  GAGAL: {e}")
    print("LOLOS" if not gagal else f"{gagal} uji gagal")
    sys.exit(1 if gagal else 0)

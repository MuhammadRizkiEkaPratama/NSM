"""Test helper: patch a name in the module that ACTUALLY defines it.

`poller` and `report_service` now only forward: the code lives in
`nsm/pemantau/*` and `report_service/*` and is re-imported so that
`poller.periksa_device(...)` still works. Reading through the forwarder is
fine; patching is not, and the difference is silent:

    poller.cek_port_terbuka = tiruan       # has no effect

`periksa_device` lives in `nsm.pemantau.dasar` and looks up `cek_port_terbuka`
in its own module namespace, so setting it on `poller` only replaces a copy
nobody reads. The test does not fail; it PASSES while running the real
function, touching the real network. `uji_tambal_sampai.py` makes this
failure loud.

Usage:
    asli = tambal("cek_port_terbuka", tiruan)
    ...
    tambal("cek_port_terbuka", asli)

`tambal` sets the name in EVERY module that has it, including modules added
later, so nobody has to remember to update a module list when a function moves.
"""
import importlib
import pkgutil

PAKET = ["nsm.pemantau", "report_service"]
MODUL_AKAR = ["poller"]


def _modul():
    hasil = []
    for nama in MODUL_AKAR:
        try:
            hasil.append(importlib.import_module(nama))
        except ImportError:
            pass
    for package in PAKET:
        try:
            p = importlib.import_module(package)
        except ImportError:
            continue
        hasil.append(p)
        for info in pkgutil.iter_modules(p.__path__):
            hasil.append(importlib.import_module(f"{package}.{info.name}"))
    return hasil


def patch(nama, nilai):
    """Set `nama` in every module that has it; returns the original value.
    The original comes from the FIRST module that has it, which is enough: the
    same name in several modules always comes from one import.
    """
    original, found = None, False
    for m in _modul():
        if hasattr(m, nama):
            if not found:
                original, found = getattr(m, nama), True
            setattr(m, nama, nilai)
    if not found:
        raise AttributeError(
            f"tidak ada modul pemantau/laporan yang punya nama {nama!r} -- "
            "salah ketik, atau namanya sudah berpindah")
    return original


def modul_pemilik(nama):
    return sorted(m.__name__ for m in _modul() if hasattr(m, nama))

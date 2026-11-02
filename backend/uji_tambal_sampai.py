"""Checks that no test file patches a name that is only forwarded.
`poller` and `report_service` now only forward; the code lives in `nsm/pemantau/*` and `report_service/*`. Patching `poller.cek_port_terbuka` replaces an unused copy, so a test can pass while running the real function against the real network. Use `bantu_tambal.tambal(nama, nilai)`, which patches every module that owns the name (`cek_port_terbuka` exists in both `nsm.pemantau.dasar` and `nsm.pemantau.layanan`).
Pure test: only reads other test files.
Run: py uji_tambal_sampai.py
"""
import ast
import glob
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))

# Forwarding module names whose code has moved; patching through them has no effect.
MENERUSKAN = {"poller", "report_service", "rs"}

LEWATI = {"uji_tambal_sampai.py"}


def penambalan_meleset(jalur):
    tree = ast.parse(open(jalur, encoding="utf-8").read(), jalur)
    temuan = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Assign):
            continue
        for t in n.targets:
            if (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                    and t.value.id in MENERUSKAN):
                temuan.append((n.lineno, f"{t.value.id}.{t.attr}"))
    return temuan


def uji_tidak_ada_penambalan_meleset():
    temuan = []
    checked = 0
    for jalur in sorted(glob.glob(os.path.join(DIR, "uji_*.py"))):
        if os.path.basename(jalur) in LEWATI:
            continue
        checked += 1
        for lineno, nama in penambalan_meleset(jalur):
            temuan.append(f"{os.path.basename(jalur)}:{lineno} {nama} = ...")
    assert not temuan, (
        f"{len(temuan)} penambalan tidak akan sampai ke fungsinya: {temuan[:6]}"
        " -- pakai `from bantu_tambal import tambal` lalu "
        "`tambal(\"nama\", nilai)`")
    print(f"  {checked} berkas uji: tidak ada penambalan yang meleset")


def uji_tambal_benar_benar_sampai():
    """`tambal()` must replace the name in every module that owns it (for example `cek_port_terbuka` in both monitor modules)."""
    import bantu_tambal

    owner = bantu_tambal.modul_pemilik("cek_port_terbuka")
    assert len(owner) >= 2, f"harusnya dimiliki >1 modul, dapat {owner}"

    marker = object()
    original = bantu_tambal.patch("cek_port_terbuka", marker)
    try:
        import importlib
        not_yet = [m for m in owner
                 if getattr(importlib.import_module(m), "cek_port_terbuka") is not marker]
        assert not not_yet, f"modul ini tidak ikut tertambal: {not_yet}"
    finally:
        bantu_tambal.patch("cek_port_terbuka", original)

    back = [m for m in owner
               if getattr(__import__(m, fromlist=["x"]), "cek_port_terbuka") is not original]
    assert not back, f"pemulihan tidak lengkap: {back}"
    print(f"  tambal() sampai ke {len(owner)} modul, dan pulih lagi")


if __name__ == "__main__":
    gagal = 0
    for uji in [uji_tambal_benar_benar_sampai, uji_tidak_ada_penambalan_meleset]:
        print(f"{uji.__name__} ...")
        try:
            uji()
        except AssertionError as e:
            gagal += 1
            print(f"  GAGAL: {e}")
    print("LOLOS" if not gagal else f"{gagal} uji gagal")
    sys.exit(1 if gagal else 0)

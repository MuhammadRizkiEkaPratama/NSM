"""Test: the list of served ROUTES does not change during the architecture move.

Moving 74 routes into several `APIRouter`s can silently change an address: a
`prefix="/report"` applied twice gives `/report/report/summary`, a forgotten route
disappears, a `@router.get` written as `@router.post` changes the method. None of
this crashes Python; the Java pages fail later with a misleading message.

`rute_terdaftar.json` is the list of 74 routes from BEFORE the move, generated from
a copy of `main.py`. A failure here does not mean the list should be updated; first
ask whether the change was intended. Update the reference only together with a
deliberate API change (which also touches Java).

Run: py uji_daftar_rute.py
"""
import json
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
ACUAN = os.path.join(DIR, "rute_terdaftar.json")
PENYELESAI = os.path.join(DIR, "rute_penyelesai.json")


def _penyelesai(rute):
    """(path, method, function name) for a route node, including nested ones."""
    if hasattr(rute, "path") and getattr(rute, "endpoint", None) is not None:
        return [(rute.path, m.lower(), rute.endpoint.__name__)
                for m in sorted(rute.methods or [])]
    child = getattr(rute, "original_router", None) or rute
    hasil = []
    for r in getattr(child, "routes", []):
        hasil += _penyelesai(r)
    return hasil


def sekarang():
    """Addresses actually served, read from the OpenAPI schema.

    `app.routes` is not used: this FastAPI version does not copy child routes into the
    parent list on `include_router`, so the list would depend on FastAPI internals.
    The OpenAPI schema is FastAPI's own answer to "what do you serve", and what Java reads via `/docs`.
    """
    import main
    skema = main.app.openapi()["paths"]
    return sorted([jalur, sorted(m.lower() for m in metode)]
                  for jalur, metode in skema.items())


def uji_daftar_rute_sama():
    reference = [[j, sorted(m)] for j, m in json.load(open(ACUAN, encoding="utf-8"))]
    current = sekarang()

    missing = [r for r in reference if r not in current]
    baru = [r for r in current if r not in reference]

    assert not missing, f"{len(missing)} rute HILANG: {missing[:5]}"
    assert not baru, (f"{len(baru)} rute BARU muncul: {baru[:5]}. "
                      "Kalau memang disengaja, perbarui rute_terdaftar.json "
                      "bersama perubahan di sisi Java.")
    print(f"  {len(current)} rute: alamat dan metode sama persis dengan acuan")


def _semua_jalur(rute):
    """All (path, method) pairs under a route node, including nested ones."""
    if hasattr(rute, "path"):
        return [(rute.path, m) for m in sorted(getattr(rute, "methods", []) or [])]
    child = getattr(rute, "original_router", None) or rute
    hasil = []
    for r in getattr(child, "routes", []):
        hasil += _semua_jalur(r)
    return hasil


def uji_tidak_ada_rute_ganda():
    """Routes registered twice: the first wins, the second silently dies.

    Typical when moving routes: the old version is not yet removed while the new one is
    installed, so the code actually serving is not the one being read.
    """
    import main
    datar = []
    for r in main.app.routes:
        datar += _semua_jalur(r)
    bertumpuk = sorted({j for j in datar if datar.count(j) > 1})
    assert not bertumpuk, f"rute terdaftar lebih dari sekali: {bertumpuk[:5]}"
    print("  tidak ada rute yang terdaftar dua kali")


def uji_nama_fungsi_penyelesai_sama():
    """The same address must be answered by the same FUNCTION.

    An address list is not enough: two routes can have right addresses with handlers
    swapped (e.g. a block moved to the wrong router), and the page still gets 200.
    """
    # The reference stores one row per route with its method list; here it is expanded to one entry per (address, method) so FastAPI's default GET+HEAD routes do not read as "missing".
    reference = {(j, m): n
             for j, daftar, n in json.load(open(PENYELESAI, encoding="utf-8"))
             for m in daftar}
    import main
    current = {}
    for r in main.app.routes:
        for jalur, metode, nama in _penyelesai(r):
            current[(jalur, metode)] = nama
    tertukar = [(k, reference[k], current[k]) for k in reference
                if k in current and reference[k] != current[k]]
    assert not tertukar, f"{len(tertukar)} rute dijawab fungsi lain: {tertukar[:5]}"
    missing = [k for k in reference if k not in current]
    assert not missing, f"{len(missing)} rute tidak ditemukan lagi: {missing[:5]}"
    print(f"  {len(reference)} rute: masih dijawab fungsi yang sama")


def uji_alamat_harfiah_tidak_tertelan_parameter():
    """A literal address must not be swallowed by its parameterized sibling.

    `/konfig/kepatuhan` and `/konfig/{snapshot_id}` match the same request; FastAPI uses
    the FIRST registered, so registration order decides, and moving routes between files
    changes it easily. If `{snapshot_id}` wins, the page gets 422 instead of 404.

    This test actually CALLS the address, because only real matching answers "who wins".
    """
    import asyncio

    import main
    from uji_middleware_tenant_rute_baru import _panggil

    harfiah = ["/konfig/kepatuhan", "/sot/katalog", "/devices/bandwidth-terkini",
               "/traffic/berkas", "/traffic/anomali", "/services/ringkas",
               "/backup/status", "/pagar/status", "/pagar/riwayat",
               "/prakiraan/anggaran", "/report/slo", "/syslog/ringkas"]
    tertelan = []
    for jalur in harfiah:
        code, _ = asyncio.run(_panggil(main.app, jalur))
        if code in (404, 422):
            tertelan.append((jalur, code))
    assert not tertelan, ("alamat harfiah ditelan rute berparameter "
                          f"(atau hilang): {tertelan}")
    print(f"  {len(harfiah)} alamat harfiah: menang atas saudara berparameternya")


def uji_semua_rute_baca_benar_terlayani():
    """Call EVERY GET route without required parameters and demand 200.

    Regression: when `report_service` was split into a package, the per-module import
    counter read only the first line of MULTI-LINE imports, so
    `report_service/identitas.py` lost `OrangLdap` and `/ldap/direktori` died with
    `NameError`. Unit tests and the route list stayed green; it only shows when the
    code actually RUNS. So this test checks only "can each route run to completion".

    Parameterized routes (`/devices/{id}/...`) are skipped (they need existing ids).
    `/backup/isi` is skipped too: it requires a `nama` query, so its 422 is correct.

    NEEDS THE LAB: reads the real database. About 85 seconds.
    """
    import asyncio

    import main
    from uji_middleware_tenant_rute_baru import _panggil

    skema = main.app.openapi()["paths"]
    bypass = {"/backup/isi"}
    jalur = []
    for j, metode in sorted(skema.items()):
        if "get" not in metode or "{" in j or j in bypass:
            continue
        required = [p for p in metode["get"].get("parameters", []) if p.get("required")]
        if not required:
            jalur.append(j)

    bad = []
    for j in jalur:
        try:
            code, body = asyncio.run(_panggil(main.app, j))
            if code != 200:
                bad.append(f"{j} -> {code} {body[:80]}")
        except Exception as e:
            bad.append(f"{j} -> {type(e).__name__}: {e}")
    assert not bad, f"{len(bad)} rute tidak terlayani: {bad[:5]}"
    print(f"  {len(jalur)} rute GET tanpa parameter wajib: semuanya 200")


if __name__ == "__main__":
    gagal = 0
    for uji in [uji_daftar_rute_sama, uji_tidak_ada_rute_ganda,
                uji_nama_fungsi_penyelesai_sama,
                uji_alamat_harfiah_tidak_tertelan_parameter,
                uji_semua_rute_baca_benar_terlayani]:
        print(f"{uji.__name__} ...")
        try:
            uji()
        except AssertionError as e:
            gagal += 1
            print(f"  GAGAL: {e}")
    print("LOLOS" if not gagal else f"{gagal} uji gagal")
    sys.exit(1 if gagal else 0)

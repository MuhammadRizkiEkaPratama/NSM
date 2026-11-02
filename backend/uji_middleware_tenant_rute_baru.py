"""Test: the tenant filter STILL applies to routes mounted through `APIRouter`.

Before moving any route from `main.py` to `APIRouter`, we must know whether the
tenant filter (`@aplikasi.middleware("http")`) also covers routes added via
`include_router`. If not, the page would still render with plausible numbers
while tenant A sees tenant B's data, with no error anywhere.

Today the filter does nothing until a tenant context is set, so the defect
would only show up later, far from its cause.

Run WITHOUT `httpx`: `TestClient` needs it, and a test this important must not
depend on a dev library. The ASGI app is called directly, as uvicorn would,
minus the socket.

Pure test for the tenant part: no devices, no DB writes.

Run: py uji_middleware_tenant_rute_baru.py
"""
import asyncio
import json
import sys

from fastapi import APIRouter

import main
import tenancy
from nsm.antarmuka.http.rakit import buat_aplikasi

KEPALA = main.NAMA_KEPALA_TENANT


async def _panggil(aplikasi, jalur, kepala=None):
    """Panggil aplikasi ASGI langsung. Kembalikan (kode, badan)."""
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": jalur, "raw_path": jalur.encode(), "query_string": b"",
        "root_path": "", "client": ("127.0.0.1", 51234),
        "server": ("127.0.0.1", 8000),
        "headers": [(k.lower().encode(), str(v).encode())
                    for k, v in (kepala or {}).items()],
    }
    chunk, state = [], {}

    async def terima():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def kirim(pesan):
        if pesan["type"] == "http.response.start":
            state["kode"] = pesan["status"]
        elif pesan["type"] == "http.response.body":
            chunk.append(pesan.get("body", b""))

    await aplikasi(scope, terima, kirim)
    return state.get("kode"), b"".join(chunk)


def _rakit_seperti_aplikasi():
    """Assemble the app through the SAME entry point as the primary lab instance.

    `buat_aplikasi()` installs its own tenant filter and `main.py` only calls it.
    Calling `main._pasang_middleware_tenant(aplikasi)` here would add a second
    filter on top; the test would still pass, which is why it is not done.
    """
    aplikasi = buat_aplikasi()

    intip = APIRouter()

    @intip.get("/_uji/tenant")
    def lihat_tenant():
        return {"tenant": tenancy.sekarang()}

    aplikasi.include_router(intip)
    return aplikasi


def uji_kepala_sampai_ke_rute_router():
    aplikasi = _rakit_seperti_aplikasi()
    kode, body = asyncio.run(_panggil(aplikasi, "/_uji/tenant", {KEPALA: "42"}))
    assert kode == 200, f"kode {kode}"
    content = json.loads(body)
    assert content["tenant"] == 42, \
        f"konteks tenant TIDAK sampai ke rute APIRouter: {content['tenant']!r}"
    print("  kepala X-NSM-Tenant sampai ke rute APIRouter: ya")


def uji_tanpa_kepala_tetap_lihat_semua():
    """No header = no context = see everything. This is the behavior used by the
    platform admin and the CLI and must not change.
    """
    aplikasi = _rakit_seperti_aplikasi()
    kode, body = asyncio.run(_panggil(aplikasi, "/_uji/tenant"))
    assert kode == 200, f"kode {kode}"
    assert json.loads(body)["tenant"] is None, "tanpa kepala seharusnya tanpa konteks"
    print("  tanpa kepala: tetap tanpa konteks (lihat semua)")


def uji_kepala_ngawur_diabaikan_bukan_ditolak():
    """A nonsensical header is IGNORED, not rejected, so a config typo does not take the page down."""
    aplikasi = _rakit_seperti_aplikasi()
    kode, body = asyncio.run(_panggil(aplikasi, "/_uji/tenant", {KEPALA: "bukan-angka"}))
    assert kode == 200, f"kepala ngawur menjatuhkan permintaan: kode {kode}"
    assert json.loads(body)["tenant"] is None
    print("  kepala ngawur: diabaikan, permintaan tetap dilayani")


def uji_konteks_tidak_bocor_antar_permintaan():
    """A tenant request must not leave its context for the next request; such a leak
    would let tenant A see tenant B's data without any error.
    """
    aplikasi = _rakit_seperti_aplikasi()
    asyncio.run(_panggil(aplikasi, "/_uji/tenant", {KEPALA: "7"}))
    kode, body = asyncio.run(_panggil(aplikasi, "/_uji/tenant"))
    assert json.loads(body)["tenant"] is None, "konteks tenant BOCOR ke permintaan berikutnya"
    assert tenancy.sekarang() is None, "konteks tenant tertinggal di proses"
    print("  konteks tidak bocor ke permintaan berikutnya")


def uji_rute_nyata_terlayani():
    """Real routes (not only the probe route) are served through this assembly."""
    aplikasi = _rakit_seperti_aplikasi()
    kode, _ = asyncio.run(_panggil(aplikasi, "/devices", {KEPALA: "1"}))
    assert kode == 200, f"/devices lewat rakitan baru: kode {kode}"
    print("  /devices lewat rakitan baru: 200")


if __name__ == "__main__":
    gagal = 0
    for uji in [uji_kepala_sampai_ke_rute_router,
                uji_tanpa_kepala_tetap_lihat_semua,
                uji_kepala_ngawur_diabaikan_bukan_ditolak,
                uji_konteks_tidak_bocor_antar_permintaan,
                uji_rute_nyata_terlayani]:
        print(f"{uji.__name__} ...")
        try:
            uji()
        except AssertionError as e:
            gagal += 1
            print(f"  GAGAL: {e}")
    print("LOLOS" if not gagal else f"{gagal} uji gagal")
    sys.exit(1 if gagal else 0)

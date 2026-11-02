"""FastAPI application factory: the ONLY place the app is assembled.

A factory instead of a module-level `app` so tests can assemble different setups (no tenant
middleware, fake stores) without patching globals. `main.py` and the tests both build the app
through `buat_aplikasi()`; two separate assembly paths would let tests cover an app nobody serves.

Order matters:
1. `tenancy.pasang()` runs at import, before any request is served; a filter installed later
   leaves a gap at the start.
2. The tenant filter is installed before routers are registered.
3. Router order matches `main.py`: FastAPI uses the FIRST matching route, so
   `/konfig/kepatuhan` must precede `/konfig/{snapshot_id}`. `uji_daftar_rute.py` checks that
   every colliding address still reaches the right function.
"""
from fastapi import FastAPI

import tenancy
from nsm.antarmuka.http.rute import (
    backup,
    dasbor,
    device,
    drift,
    firewall,
    identitas,
    insiden,
    konfig,
    laporan,
    layanan,
    pagar,
    penemuan,
    perintah,
    sot,
    syslog,
    tenant,
    trafik,
    wawasan,
)

# Install the tenant filter BEFORE any request is served. Without a tenant context it does
# nothing, so this does not change behavior for installs that do not use tenants.
tenancy.pasang()

NAMA_KEPALA_TENANT = "X-NSM-Tenant"

# Order preserved from `main.py`; see "Order matters" in the module docstring.
RUTER = (
    dasbor.router, device.router, laporan.router, insiden.router,
    layanan.router, trafik.router, firewall.router, konfig.router,
    perintah.router, sot.router, drift.router, pagar.router, wawasan.router,
    syslog.router, identitas.router, backup.router, tenant.router,
    penemuan.router,
)


def pasang_middleware_tenant(aplikasi):
    """Set the tenant context from the `X-NSM-Tenant` header on each request.

    Spring Boot sends it, from the `tenant_id` of the logged-in account, never from user input.
    Python listens only on `127.0.0.1` (uvicorn bound to localhost), so only a process on the
    same machine can send it. This is the same trust boundary as `/internal/notifikasi-device`:
    if port 8000 were ever exposed to the network, the header would become a claim anyone could
    forge, so opening that port is not a minor operational decision.

    No header = no context = sees everything (platform admin and CLI behavior).
    """

    @aplikasi.middleware("http")
    async def _tenant(request, call_next):       # noqa: ANN001
        raw = request.headers.get(NAMA_KEPALA_TENANT)
        tid = None
        if raw:
            try:
                tid = int(raw)
            except ValueError:
                # An invalid header is IGNORED rather than rejected (meaning "see all", safe on this localhost
                # path); rejecting would take pages down over a config typo.
                tid = None
        if tid is None:
            return await call_next(request)
        with tenancy.dengan_tenant(tid):
            return await call_next(request)

    return _tenant


def buat_aplikasi(judul="NSM API", dengan_tenant=True):
    """Assemble one complete FastAPI application.

    `dengan_tenant=False` exists for tests that must verify behavior WITHOUT the filter; it is on
    by default so forgetting the argument never drops the filter.
    """
    aplikasi = FastAPI(title=judul)
    if dengan_tenant:
        pasang_middleware_tenant(aplikasi)
    for router in RUTER:
        aplikasi.include_router(router)
    return aplikasi

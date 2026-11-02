r"""Multi-tenancy: tenant filtering enforced at the ORM layer, not left to callers.

Cross-tenant leaks fail silently: a query that forgets to filter raises no
error, it returns another tenant's data. With hundreds of queries spread over
`report_service.py`, `poller.py`, `kesehatan.py`, `laporan_excel.py` and other
modules, relying on every caller to add `.where(tenant_id == ...)` will
eventually fail.

This module installs a filter on the ORM via `do_orm_execute` +
`with_loader_criteria`, so every SELECT on a tenant-scoped entity is filtered
without changing callers. Callers only set the context; if they forget, the
default is no tenant, which means seeing everything (legacy behavior) rather
than leaking into a specific tenant.

    dengan_tenant(3)   -> only tenant 3's rows
    (no context)       -> everything (legacy behavior, for poller and CLI)
    lintas_tenant()    -> explicit, greppable cross-tenant exception

Limits: the filter only applies to ORM queries. It does NOT cover:

  * `db.execute(text("SELECT ..."))` (raw SQL);
  * `mysqldump` and other external tools;
  * aggregates written directly as SQL strings.

Those paths remain the caller's responsibility. `uji_kebocoran.py` scans
page-serving modules for raw SQL so such gaps show up as findings.
"""
import contextlib
import contextvars

from sqlalchemy import event, select
from sqlalchemy.orm import Session, with_loader_criteria

import models

# Tenant in effect for this thread/task. `None` = see everything.
#
# `ContextVar`, not a global: uvicorn serves concurrent requests, and a global
# would let tenant A's request use tenant B's context.
_tenant = contextvars.ContextVar("nsm_tenant_id", default=None)

# Marker that a query intentionally crosses tenants.
_lintas = contextvars.ContextVar("nsm_lintas_tenant", default=False)


# ---------------------------------------------------------------------------
# Filtered entities and how each links to a tenant
# ---------------------------------------------------------------------------
#
# `Device` holds `tenant_id` directly. The rest link via `device_id` and are
# filtered with a subquery on `devices`.
#
# Why not add `tenant_id` to every table: it would be faster, but it creates a
# second source of truth; moving a device to another tenant would mean
# rewriting all child rows. One source of truth, paid for with one subquery.
LEWAT_DEVICE = (
    models.StatusLog,
    models.DeviceEvent,
    models.BandwidthSample,
    models.SumberDaya,
    models.KonfigSnapshot,
    models.SyslogPesan,
    models.InsidenGejala,
    models.BaselinePerilaku,
    models.UsulanAgen,
    models.PagarTindakan,
    models.StatusRollupJam,
    models.Service,
)

# `Insiden` is filtered via `akar_device_id`, not `device_id`.
LEWAT_AKAR = (models.Insiden,)


# Holds `tenant_id` directly like `Device`, for a different reason: a
# `PerangkatDitemukan` is a scan-discovered address with no device yet.
LANGSUNG = (models.PerangkatDitemukan,)


def _kriteria(kelas, tenant_id):
    """Extra criteria for one class. None if the class is not tenant-scoped."""
    if kelas is models.Device:
        return models.Device.tenant_id == tenant_id
    if kelas in LANGSUNG:
        return kelas.tenant_id == tenant_id
    if kelas in LEWAT_DEVICE:
        return kelas.device_id.in_(
            select(models.Device.id).where(models.Device.tenant_id == tenant_id))
    if kelas in LEWAT_AKAR:
        return kelas.akar_device_id.in_(
            select(models.Device.id).where(models.Device.tenant_id == tenant_id))
    return None


SEMUA_KELAS = (models.Device,) + LANGSUNG + LEWAT_DEVICE + LEWAT_AKAR


def sekarang():
    """Current tenant. None = see everything."""
    return _tenant.get()


@contextlib.contextmanager
def dengan_tenant(tenant_id):
    """Run this block as a specific tenant.

    Restored in `finally` even if the block raises; a context leaking out of a
    failed block would make the next request see the wrong data.
    """
    token = _tenant.set(tenant_id)
    try:
        yield
    finally:
        _tenant.reset(token)


@contextlib.contextmanager
def lintas_tenant():
    """Deliberately see all tenants. Used by the poller, backups, and platform pages.

    An explicit block rather than a default, so every cross-tenant site can be
    found with one text search:

        grep -rn "lintas_tenant" backend/
    """
    token = _lintas.set(True)
    try:
        yield
    finally:
        _lintas.reset(token)


def pasang():
    """Install the filter on every SQLAlchemy Session in this process.

    Idempotent: calling it twice does not install two filters.
    """
    if getattr(pasang, "_terpasang", False):
        return False

    @event.listens_for(Session, "do_orm_execute")
    def _saring(state):                          # noqa: ANN001
        # SELECT only. Writes are deliberately not filtered: writing to another tenant
        # is rarer and more visible than reading, and silently filtering writes would
        # drop rows without errors.
        if not state.is_select:
            return
        if _lintas.get():
            return
        # Per-query opt-out for callers that need cross-tenant access in one place.
        if state.execution_options.get("lintas_tenant", False):
            return
        t = _tenant.get()
        if t is None:
            return
        for kelas in SEMUA_KELAS:
            condition = _kriteria(kelas, t)
            if condition is not None:
                state.statement = state.statement.options(
                    with_loader_criteria(kelas, condition, include_aliases=True))

    pasang._terpasang = True
    return True


def tenant_device(db, device_id):
    """Owning tenant of a device. None if the device does not exist.

    Used by upper-layer guards (`boleh_device`) that must decide before touching
    data, e.g. when an id comes from the URL.
    """
    with lintas_tenant():
        d = db.get(models.Device, device_id)
    return d.tenant_id if d else None


def boleh_device(db, device_id, tenant_id=None):
    """May this tenant access that device?

    Needed despite the ORM filter: the filter returns zero rows for another
    tenant's device, which reads as "no data" rather than "not yours". For
    per-device detail pages that is the difference between a proper 404 and a
    confusing empty page.
    """
    t = tenant_id if tenant_id is not None else _tenant.get()
    if t is None:
        return True  # no context = see everything
    return tenant_device(db, device_id) == t


def kuota_terpakai(db, tenant_id):
    """How many devices this tenant uses, and its quota.

    The quota keeps one tenant from adding unlimited devices and exhausting
    shared resources.
    """
    with lintas_tenant():
        t = db.get(models.Tenant, tenant_id)
        n = len(db.execute(select(models.Device.id).where(
            models.Device.tenant_id == tenant_id)).scalars().all())
    return {"tenant_id": tenant_id, "nama": t.nama if t else None,
            "device": n, "kuota_device": t.kuota_device if t else None,
            "penuh": bool(t and t.kuota_device and n >= t.kuota_device)}

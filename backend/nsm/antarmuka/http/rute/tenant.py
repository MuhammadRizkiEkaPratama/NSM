"""Tenant routes."""
from fastapi import APIRouter, Depends

import tenancy
from nsm.antarmuka.http import wiring

router = APIRouter(tags=["tenant"])


@router.get("/tenant")
def tenant_daftar(db=Depends(wiring.beri_sesi)):
    """List tenants with their quota usage.

    Read-only and intentionally cross-tenant: only `admin_platform` may use this
    page, enforced by Spring Security on the Java side (`/admin/**` -> hasRole).
    Filtering per tenant would stop the platform admin from ever seeing other
    tenants, which defeats the purpose.

    No endpoint here creates or deletes tenants. Adding a tenant decides who can
    see what; that belongs in a deliberate migration (`migrate_tenant.py`), not a
    single HTTP request.
    """
    from sqlalchemy import select as _select

    import models as _m
    with tenancy.lintas_tenant():
        hasil = []
        for t in db.execute(_select(_m.Tenant)
                            .order_by(_m.Tenant.nama)).scalars().all():
            k = tenancy.kuota_terpakai(db, t.id)
            hasil.append({
                "id": t.id, "nama": t.nama, "kontak": t.kontak,
                "aktif": bool(t.aktif),
                "kuota_device": t.kuota_device,
                "device": k["device"], "penuh": k["penuh"],
                "dibuat": t.dibuat.isoformat() if t.dibuat else None,
                "catatan": t.catatan,
            })
        # Devices with no owner yet are reported as such. That is a valid state,
        # and hiding it would mean nobody ever learns that some devices are
        # invisible to every tenant.
        without = db.execute(_select(_m.Device.id, _m.Device.name).where(
            _m.Device.tenant_id.is_(None))).all()
    return {"tenant": hasil,
            "tanpa_tenant": [{"id": i, "nama": n} for i, n in without]}

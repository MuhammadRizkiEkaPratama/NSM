"""Device configuration routes: snapshots, compliance, and diffs.
All READ-ONLY: no endpoint sends anything to a device, and any addition must require explicit
approval per change.
"""
from fastapi import APIRouter, Depends

import report_service
from nsm.antarmuka.http import wiring

router = APIRouter(tags=["konfig"])


@router.get("/konfig")
def konfig_daftar(device_id: int = None, db=Depends(wiring.beri_sesi)):
    """Config snapshot history. One row = one real change."""
    return report_service.konfig_daftar(db, device_id)


@router.get("/konfig/kepatuhan")
def konfig_kepatuhan(device_id: int = None, db=Depends(wiring.beri_sesi)):
    """Compliance findings on each device's latest snapshot.
    Registered BEFORE `/konfig/{snapshot_id}` on purpose: FastAPI matches in registration order,
    and otherwise "kepatuhan" would be captured as an invalid `snapshot_id`.
    """
    return report_service.konfig_kepatuhan(db, device_id)


@router.get("/konfig/{snapshot_id}")
def konfig_isi(snapshot_id: int, db=Depends(wiring.beri_sesi)):
    """Content of one config snapshot, masked since it was stored."""
    return report_service.konfig_isi(db, snapshot_id)


@router.get("/konfig/{snapshot_id}/beda")
def konfig_beda(snapshot_id: int, db=Depends(wiring.beri_sesi)):
    """What changed in this snapshot compared to the previous one."""
    return report_service.konfig_beda(db, snapshot_id)


@router.get("/konfig/{snapshot_id}/belum-disimpan")
def konfig_belum_disimpan(snapshot_id: int, db=Depends(wiring.beri_sesi)):
    """Which lines would be LOST if this device restarted."""
    return report_service.konfig_belum_disimpan(db, snapshot_id)

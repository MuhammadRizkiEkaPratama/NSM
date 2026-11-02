"""Automation guard routes: kill-switch status and action history.
READ-ONLY. Nothing executes `pagar_otomasi.putuskan()` from the web on purpose: it ALWAYS
writes an audit row and counts toward rate limits, so a "just look" call would pollute the
audit trail with decisions that never became real actions.
"""
from fastapi import APIRouter, Depends

import pagar_otomasi as _pagar
from nsm.antarmuka.http import wiring

router = APIRouter(tags=["pagar"])


@router.get("/pagar/status")
def pagar_status():
    """Guard settings in effect: allowlist, rate limits, working hours, freeze windows."""
    return _pagar.status_pagar()


@router.get("/pagar/riwayat")
def pagar_riwayat(device_id: int = None, limit: int = 100, db=Depends(wiring.beri_sesi)):
    """Guard decision history, newest first."""
    return _pagar.riwayat(db, device_id=device_id, batas=limit)

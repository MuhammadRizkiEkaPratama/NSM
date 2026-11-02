"""Drift routes: difference between intent and actual state.
Compares intent (stage 1) with the latest config snapshot (`konfig_snapshots`). ZERO device
contact; see drift/__init__.py and docs/design/CLOSED-LOOP-AUTOMATION.md.
"""
from fastapi import APIRouter, Depends

from drift import service as _drift
from nsm.antarmuka.http import wiring
from nsm.antarmuka.http.balasan import balas_ditolak as _balas_ditolak

# `sot.katalog.Ditolak` is used here too: a legitimate SoT refusal is answered with 409, not 500.
from sot import katalog as _sot_katalog

router = APIRouter(tags=["drift"])


@router.get("/drift")
def drift_ringkasan(db=Depends(wiring.beri_sesi)):
    """One row per device: aligned, drifted, or unsupported."""
    return _drift.ringkasan(db)


@router.get("/drift/{device_id}")
def drift_bandingkan(device_id: int, db=Depends(wiring.beri_sesi)):
    """Full drift detection result for one device."""
    try:
        return _drift.bandingkan(db, device_id)
    except _sot_katalog.Ditolak as e:
        return _balas_ditolak(e)

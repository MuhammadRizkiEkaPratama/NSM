"""SoT (configuration source of truth) routes: catalog, values, and history.

Zero device contact. Every endpoint reads/writes only NSM's own database
(`intent_*`) and calls the pure renderer (`sot/render.py`); none opens a
network connection. See docs/design/CLOSED-LOOP-AUTOMATION.md.

`sot.katalog.Ditolak` returns 409, the same pattern as
`kirim_perintah.Ditolak`: not a server error, the request was valid and
the answer is "invalid" or "incomplete".
"""
from fastapi import APIRouter, Body, Depends

from nsm.antarmuka.http import wiring
from nsm.antarmuka.http.balasan import balas_ditolak as _balas_ditolak
from sot import katalog as _sot_katalog
from sot import service as _sot

router = APIRouter(tags=["sot"])


@router.get("/sot/katalog")
def sot_katalog(platform: str = None):
    """Intent key catalog, in full or for one platform.

    The web page builds its forms from this: each key's title, shape, example,
    and rationale come from here instead of being repeated in the Java template.
    """
    if platform:
        return {"platform": platform,
               "kunci": _sot_katalog.untuk_platform(platform)}
    return {"platform_didukung": _sot_katalog.platform_didukung(),
           "kunci": _sot_katalog.KUNCI}


@router.get("/sot")
def sot_ringkasan(db=Depends(wiring.beri_sesi)):
    """One row per device whose platform has a Source of Truth catalog."""
    return _sot.ringkasan(db)


@router.get("/sot/{device_id}")
def sot_ambil(device_id: int, db=Depends(wiring.beri_sesi)):
    """All intent for one device: values, interfaces, VLANs, routes, completeness."""
    try:
        return _sot.ambil(db, device_id)
    except _sot_katalog.Ditolak as e:
        return _balas_ditolak(e)


@router.post("/sot/{device_id}/nilai")
def sot_simpan_nilai(device_id: int, isi: dict = Body(...), db=Depends(wiring.beri_sesi)):
    """Save single-key intent values. Partial updates allowed; see sot/service.py."""
    try:
        hasil = _sot.simpan_nilai(db, device_id, isi.get("nilai") or {},
                                  oleh=isi.get("oleh"))
        return {"ok": True, **hasil}
    except _sot_katalog.Ditolak as e:
        db.rollback()
        return _balas_ditolak(e)


@router.post("/sot/{device_id}/interface")
def sot_simpan_interface(device_id: int, isi: dict = Body(...), db=Depends(wiring.beri_sesi)):
    """Reconcile ALL intended interfaces of this device against the submitted list."""
    try:
        hasil = _sot.simpan_interface(db, device_id, isi.get("interface") or [],
                                      oleh=isi.get("oleh"))
        return {"ok": True, **hasil}
    except _sot_katalog.Ditolak as e:
        db.rollback()
        return _balas_ditolak(e)


@router.post("/sot/{device_id}/vlan")
def sot_simpan_vlan(device_id: int, isi: dict = Body(...), db=Depends(wiring.beri_sesi)):
    """Reconcile ALL intended VLANs of this device against the submitted list."""
    try:
        hasil = _sot.simpan_vlan(db, device_id, isi.get("vlan") or [],
                                 oleh=isi.get("oleh"))
        return {"ok": True, **hasil}
    except _sot_katalog.Ditolak as e:
        db.rollback()
        return _balas_ditolak(e)


@router.post("/sot/{device_id}/rute")
def sot_simpan_rute(device_id: int, isi: dict = Body(...), db=Depends(wiring.beri_sesi)):
    """Reconcile ALL intended static routes of this device against the submitted list."""
    try:
        hasil = _sot.simpan_rute(db, device_id, isi.get("rute") or [],
                                 oleh=isi.get("oleh"))
        return {"ok": True, **hasil}
    except _sot_katalog.Ditolak as e:
        db.rollback()
        return _balas_ditolak(e)


@router.get("/sot/{device_id}/render")
def sot_render(device_id: int, db=Depends(wiring.beri_sesi)):
    """Render stored intent into intended config text.

    Does NOT touch any device (see sot/render.py). Returns 409 if the intent is
    incomplete, listing the required keys that are still empty.
    """
    try:
        return _sot.render_intent(db, device_id)
    except _sot_katalog.Ditolak as e:
        return _balas_ditolak(e)


@router.get("/sot/{device_id}/riwayat")
def sot_riwayat(device_id: int, limit: int = 100, db=Depends(wiring.beri_sesi)):
    """Intent change history for this device, newest first."""
    try:
        return _sot.riwayat(db, device_id, batas=limit)
    except _sot_katalog.Ditolak as e:
        return _balas_ditolak(e)

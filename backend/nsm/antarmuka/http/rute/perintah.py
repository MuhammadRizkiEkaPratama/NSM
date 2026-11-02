"""Command routes: catalog, preview, send, decide, save.

The catalog and preview endpoints never send anything to a device. Preview
uses POST because it takes a request body, not because it changes any state.

The send path exposes `kirim_perintah.py`, which handles permissions, the
`reload in N` safety net, before/after snapshots, rollback, and `write memory`.

`sungguhan` must be sent explicitly. It defaults to False on all three
endpoints, as in the module: a forgotten argument results in nothing
happening, not in a router changing silently.
"""
import json

from fastapi import APIRouter, Body, Depends, Response

import report_service
from nsm.antarmuka.http import wiring

router = APIRouter(tags=["perintah"])


@router.get("/devices/{device_id}/perintah")
def perintah_katalog(device_id: int, db=Depends(wiring.beri_sesi)):
    """List the commands available for this device."""
    return report_service.perintah_katalog(db, device_id)


@router.post("/devices/{device_id}/perintah/pratinjau")
def perintah_pratinjau(device_id: int, isi: dict, db=Depends(wiring.beri_sesi)):
    """Build the command and show what WOULD be sent. Does not send."""
    return report_service.perintah_pratinjau(
        db, device_id, isi.get("perintah_id"), isi.get("nilai") or {})


@router.post("/devices/{device_id}/perintah/kirim")
def perintah_kirim(device_id: int, isi: dict, db=Depends(wiring.beri_sesi)):
    """Send one config change with the safety net in place.

    The module runs this order, which must not be changed from here:
    check permission -> snapshot before -> arm `reload in N` -> send ->
    confirm the device still responds -> disarm -> snapshot after.

    The change is NOT permanent yet. A reboot still reverts it, by design:
    as long as that holds, any mistake still has a way back.
    """
    import kirim_perintah
    try:
        return kirim_perintah.kirim(
            db, device_id,
            isi.get("perintah_id"), isi.get("nilai") or {},
            oleh=isi.get("oleh"),
            sungguhan=bool(isi.get("sungguhan")))
    except kirim_perintah.Ditolak as e:
        # A refusal is not a server error: the request was valid and the answer
        # is "not allowed". 409 lets the Java side tell it apart from a failure
        # and show the reason to the operator as is.
        return Response(content=json.dumps({"ok": False, "ditolak": str(e)}),
                        media_type="application/json", status_code=409)


@router.post("/devices/{device_id}/perintah/putuskan")
def perintah_putuskan(device_id: int, isi: dict, db=Depends(wiring.beri_sesi)):
    """Keep or roll back the change just sent.

    "Roll back" does NOT send inverse commands; it reboots the device, which
    restores the untouched startup-config. Inverse commands are only correct
    if the prior state is known exactly, which cannot be guaranteed right
    after something went wrong.
    """
    import kirim_perintah
    try:
        return kirim_perintah.putuskan(
            db, device_id, isi.get("tindakan"),
            sungguhan=bool(isi.get("sungguhan")))
    except kirim_perintah.Ditolak as e:
        return Response(content=json.dumps({"ok": False, "ditolak": str(e)}),
                        media_type="application/json", status_code=409)


@router.post("/devices/{device_id}/perintah/simpan")
def perintah_simpan(device_id: int, isi: dict = Body(default={}), db=Depends(wiring.beri_sesi)):
    """`write memory`: make the change survive a reboot.

    Standalone; never called automatically by `kirim()`. Until a change is
    saved, a reboot still reverts it, and saving automatically would remove
    that way back without anyone asking for it.
    """
    import kirim_perintah
    try:
        return kirim_perintah.simpan_permanen(
            db, device_id, sungguhan=bool((isi or {}).get("sungguhan")))
    except kirim_perintah.Ditolak as e:
        return Response(content=json.dumps({"ok": False, "ditolak": str(e)}),
                        media_type="application/json", status_code=409)

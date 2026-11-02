"""Device discovery routes (docs/design/DEVICE-AGNOSTIC.md).

    POST /penemuan/pindai        scan, store findings
    GET  /penemuan               list awaiting a decision
    POST /penemuan/{id}/setujui  -> becomes a device, NOT ACTIVE yet
    POST /penemuan/{id}/abaikan  -> a decision that persists

No endpoint creates a device straight from scan results (see `penemuan.py`).
Scanning is POST even though it changes no device: GET can be repeated by a reload button or
browser cache, and a network scan that a reload can trigger will run more often than anyone asked.
"""
from fastapi import APIRouter, Body, Depends, HTTPException

import penemuan
import tenancy
from nsm.antarmuka.http import wiring

router = APIRouter(tags=["penemuan"])


def _baris(b):
    return {
        "id": b.id,
        "ip_address": b.ip_address,
        "pertama_terlihat": b.pertama_terlihat.isoformat() if b.pertama_terlihat else None,
        "terakhir_terlihat": b.terakhir_terlihat.isoformat() if b.terakhir_terlihat else None,
        "rtt_ms": b.rtt_ms,
        "port_terbuka": [int(x) for x in (b.port_terbuka or "").split(",") if x],
        "sysobjectid": b.sysobjectid,
        "platform": b.platform,
        # Human-readable platform name AND evidence level. A device matching a `dokumentasi`-tier
        # definition is recognized but that recognition was never tested on real hardware; the person
        # approving it should know.
        "keterangan_platform": (
            penemuan.dialek_perangkat.ambil(b.platform).keterangan
            if b.platform else ""),
        "teruji": (penemuan.dialek_perangkat.ambil(b.platform).teruji
                   if b.platform else None),
        "catatan": b.catatan,
        "status": b.status,
        "device_id": b.device_id,
    }


@router.post("/penemuan/pindai")
def penemuan_pindai(
    jaringan: str = Body(..., embed=True),
    izinkan_publik: bool = Body(False, embed=True),
    db=Depends(wiring.beri_sesi),
):
    """Scan one network and store the results as OFFERS.
    SNMP is deliberately NOT requested through this endpoint: SNMPv3 credentials sent over HTTP
    for one-time use would show up in request logs and browser history. Findings from here have
    an empty platform, which is not a failure: ping, TCP and services are vendor-neutral; only
    config reading and the write path are missing. Fill SNMP on the device page after approval.
    """
    try:
        temuan = penemuan.pindai(jaringan, izinkan_publik=izinkan_publik)
    except penemuan.PindaiDitolak as e:
        # 400, not 500: the request is refused, NSM is not broken. Messages are written for humans in `penemuan.py`.
        raise HTTPException(status_code=400, detail=str(e)) from e

    summarize = penemuan.simpan(db, temuan, tenant_id=tenancy.sekarang())
    summarize["jaringan"] = jaringan
    summarize["temuan"] = [t.sebagai_dict() for t in temuan]
    return summarize


@router.get("/penemuan")
def penemuan_daftar(status: str = "baru", db=Depends(wiring.beri_sesi)):
    """Findings awaiting a decision. `status=semua` for all."""
    if status not in penemuan.STATUS and status != "semua":
        raise HTTPException(
            status_code=400,
            detail="status harus salah satu dari %s, atau `semua`"
                   % ", ".join(penemuan.STATUS))
    line = penemuan.daftar(db, status=None if status == "semua" else status,
                            tenant_id=tenancy.sekarang())
    return {"status": status, "jumlah": len(line),
            "temuan": [_baris(b) for b in line]}


@router.post("/penemuan/{temuan_id}/setujui")
def penemuan_setujui(
    temuan_id: int,
    nama: str = Body(..., embed=True),
    device_type: str = Body("server", embed=True),
    platform: str = Body(None, embed=True),
    db=Depends(wiring.beri_sesi),
):
    """Turn a finding into a device, created NOT ACTIVE.
    Approving means "yes, this is our device", which is different from "start monitoring now";
    enabling is one more step on the device page, where credentials and thresholds are filled in.
    """
    try:
        d = penemuan.setujui(db, temuan_id, nama=nama,
                             device_type=device_type, platform=platform)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"device_id": d.id, "nama": d.name, "ip_address": d.ip_address,
            "platform": d.platform, "aktif": d.aktif,
            "catatan": "Device dibuat dalam keadaan BELUM AKTIF. Isi "
                       "kredensial dan ambangnya di halaman device, lalu "
                       "aktifkan."}


@router.post("/penemuan/{temuan_id}/abaikan")
def penemuan_abaikan(temuan_id: int, db=Depends(wiring.beri_sesi)):
    """Mark as not our device. The decision PERSISTS; otherwise every scan would offer the rejected
    address again.
    """
    try:
        b = penemuan.abaikan(db, temuan_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _baris(b)

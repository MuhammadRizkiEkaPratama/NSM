"""Syslog routes: summary, dashboard, and raw messages."""
from fastapi import APIRouter, Depends

import syslog_service
from nsm.antarmuka.http import wiring

router = APIRouter(tags=["syslog"])


@router.get("/syslog/ringkas")
def syslog_ringkas(jam: int = 24, db=Depends(wiring.beri_sesi)):
    """Syslog stream summary for the page."""
    return syslog_service.ringkas(db, jam=jam)


@router.get("/syslog/dasbor")
def syslog_dasbor(jam: int = 24, db=Depends(wiring.beri_sesi)):
    """Everything the Syslog page needs in a single request."""
    return syslog_service.dasbor(db, jam=jam)


@router.get("/syslog/pesan")
def syslog_pesan(jam: int = 24, device_id: int = None, tag: str = None,
                 penting: int = 0, cari: str = None,
                 halaman: int = 1, per_halaman: int = 5, db=Depends(wiring.beri_sesi)):
    """Paginated, filterable list of syslog messages."""
    return syslog_service.daftar(
        db, jam=jam, device_id=device_id, tag=tag,
        hanya_penting=bool(penting), cari=cari,
        halaman=halaman, per_halaman=per_halaman)

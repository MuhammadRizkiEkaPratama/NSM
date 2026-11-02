"""Report routes. All read-only and never touch devices; calculation lives in report_service.py,
here we only open and close the DB session. Accepted periods: 1h, 24h, 7d, 30d (default 24h).
"""
from fastapi import APIRouter, Depends, Response

import laporan_excel
import laporan_word
import slo
from nsm.antarmuka.http import wiring
from nsm.antarmuka.http.media import DOCX, XLSX
from nsm.aplikasi.kasus.lihat_laporan import (
    LihatKetersediaan,
    LihatRingkasan,
    LihatSparkline,
)

router = APIRouter(prefix="/report", tags=["laporan"])


@router.get("/summary")
def ringkasan(period: str = "24h", db=Depends(wiring.beri_sesi)):
    """Figures for the 4 main cards plus secondary cards (MTTR, top offender, etc.)."""
    return LihatRingkasan(wiring.beri_laporan(db)).jalankan(period)


@router.get("/availability")
def ketersediaan(period: str = "24h", db=Depends(wiring.beri_sesi)):
    """Per-device availability and current status. Fills the main table of the Report page."""
    return LihatKetersediaan(wiring.beri_laporan(db)).jalankan(period)


@router.get("/sparkline")
def sparkline(period: str = "24h", kotak: int = 40, db=Depends(wiring.beri_sesi)):
    """Up/down pattern of each device. A separate endpoint because it scans `status_logs` and is far
    costlier than the rest of the page; the page fetches it rarely.
    """
    return LihatSparkline(wiring.beri_laporan(db)).jalankan(period, kotak)


@router.get("/slo")
def report_slo(period: str = "30d", db=Depends(wiring.beri_sesi)):
    """SLO and error budget per device.
    The default window is 30 days, NOT 24 h: an error budget only means something over a window
    long enough to contain several outages.
    """
    return slo.semua(db, period)


@router.get("/export")
def report_export(period: str = "24h", oleh: str = "",
                  db=Depends(wiring.beri_sesi)):
    """Availability report as a formatted Excel file."""
    isi = laporan_excel.create_report(db, period, oleh)
    return Response(content=isi, media_type=XLSX, headers={
        "X-Nama-Berkas": laporan_excel.nama_berkas("laporan-availability"),
    })


@router.get("/export-word")
def report_export_word(period: str = "24h", oleh: str = "",
                  db=Depends(wiring.beri_sesi)):
    """Brief availability report as a Word (.docx) file."""
    isi = laporan_word.buat_laporan_word(db, period, oleh)
    return Response(content=isi, media_type=DOCX, headers={
        "X-Nama-Berkas": laporan_word.nama_berkas("laporan-availability"),
    })

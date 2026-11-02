"""Dashboard routes: charts, summary, topology, diagnosis, health."""
from fastapi import APIRouter, Depends

import dasbor_grafik
import kesehatan
import report_service
from nsm.antarmuka.http import wiring

router = APIRouter(tags=["dasbor"])


@router.get("/dasbor/grafik")
def dasbor_grafik_semua(jam: int = 24, db=Depends(wiring.beri_sesi)):
    """The three Dashboard charts beside the topology map, in ONE request so the panels cannot
    end up half filled with no way to tell failure from empty.
    """
    return dasbor_grafik.semua(db, jam=jam)


@router.get("/dashboard/ringkas")
def dashboard_ringkas(db=Depends(wiring.beri_sesi)):
    """Dashboard summary strip: devices, services, incidents, network rate.
    One request for the whole strip because the dashboard refreshes every five seconds. READ-ONLY
    and cheap: no period-based availability calculation (see `report_service.ringkas_dashboard()`).
    """
    return report_service.ringkas_dashboard(db)


@router.get("/topologi")
def topologi(db=Depends(wiring.beri_sesi)):
    """Device relationship map for the Dashboard topology map.
    READ-ONLY and cheap, since the Java `TopologiBroadcaster` calls it repeatedly: only a snapshot
    of `flow_koneksi` from the last few minutes. Java forwards the JSON as is to open WebSocket
    sessions and never inspects it, so a shape change here needs no Java change.
    """
    return report_service.topologi(db)


@router.get("/diagnosis")
def diagnosis(db=Depends(wiring.beri_sesi)):
    """What is broken, who is affected, and the first step, in ONE request so the page never shows
    half a diagnosis.
    """
    return report_service.diagnosis(db)


@router.get("/kesehatan")
def kesehatan_sistem(db=Depends(wiring.beri_sesi)):
    """State of NSM itself: each poller job, the database, and backups.
    Scored here in Python; Java adds only MySQL and mail-server reachability, which it alone can see.
    """
    return kesehatan.ringkasan(db)

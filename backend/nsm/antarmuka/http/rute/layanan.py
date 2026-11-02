"""Service routes: availability of services on top of devices."""
from fastapi import APIRouter, Depends

import report_service
from nsm.antarmuka.http import wiring

router = APIRouter(tags=["layanan"])


@router.get("/services")
def list_services(period: str = "24h", db=Depends(wiring.beri_sesi)):
    """All monitored services with their state and availability.
    Answers "the server is up but HTTP is not": ping is under /devices, services are here.
    """
    return report_service.layanan_semua(db, period)


@router.get("/services/ringkas")
def services_ringkas(db=Depends(wiring.beri_sesi)):
    """CURRENT state of each service, grouped by device.
    A light path for the dashboard device cards. It takes no period parameter on purpose: it
    answers "which services are up now", and offering a period would invite paying for the
    availability calculation on a 5-second refresh.
    Registered before the parameterized routes as a habit: if a plain `/services/{id}` is ever
    added first, FastAPI would swallow "ringkas" as a `service_id`.
    """
    return report_service.ringkas_layanan_per_device(db)


@router.get("/devices/{device_id}/services")
def device_services(device_id: int, period: str = "24h", db=Depends(wiring.beri_sesi)):
    """Services of one device, for the device history page."""
    return report_service.layanan_device(db, device_id, period)


@router.get("/services/{service_id}/history")
def service_history(service_id: int, period: str = "24h", limit: int = 100, db=Depends(wiring.beri_sesi)):
    """Outage history of one service, with evidence, advice and diagnosis."""
    return report_service.riwayat_layanan(db, service_id, period, limit)

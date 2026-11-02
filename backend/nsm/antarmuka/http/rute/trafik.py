"""Traffic routes: per device, files, conversations, and anomalies."""
from fastapi import APIRouter, Depends

import report_service
from nsm.antarmuka.http import wiring

router = APIRouter(tags=["trafik"])


@router.get("/devices/{device_id}/traffic")
def device_traffic(device_id: int, period: str = "24h", db=Depends(wiring.beri_sesi)):
    """Who pulled what from this web server, and how much.

    Answers what /devices/{id}/bandwidth cannot: interface counters know how
    many bytes passed, but not who the peer was.
    """
    return report_service.traffic_device(db, device_id, period)


@router.get("/traffic/berkas")
def traffic_berkas(period: str = "24h", db=Depends(wiring.beri_sesi)):
    """Who transferred which files over SFTP, and how much.

    The only source on the Traffic page that names PEOPLE rather than IP
    addresses. Addresses change hands; LDAP names do not.
    """
    return report_service.berkas_transfer(db, period)


@router.get("/traffic")
def traffic_semua(period: str = "24h", db=Depends(wiring.beri_sesi)):
    """Ranking of the addresses pulling the most data, across all devices."""
    return report_service.traffic_semua(db, period)


@router.get("/traffic/anomali")
def traffic_anomali(period: str = "7d", db=Depends(wiring.beri_sesi)):
    """Traffic anomaly findings with their comparison figures.

    Every finding MUST carry its baseline ("203 MB in one hour, usual 0.3 MB"),
    not just "traffic spike". A label without numbers gets ignored after the
    second time.

    If the baseline cannot be computed yet, say so plainly instead of covering
    it with a number invented from too little data.
    """
    return report_service.anomali_lalu_lintas(db, period)

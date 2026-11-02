"""Identity routes: device identity verdicts and the people directory."""
from fastapi import APIRouter, Depends

import identitas
import report_service
from models import Device
from nsm.antarmuka.http import wiring

router = APIRouter(tags=["identitas"])


@router.get("/identitas")
def identitas_semua(db=Depends(wiring.beri_sesi)):
    """Identity verdict of each device with its stored markers.
    READ-ONLY on what was already collected; collection is the poller's `identitas` job, since a
    refreshed page would otherwise open SSH to every device on each view.
    """
    hasil = []
    for d in db.query(Device).order_by(Device.id).all():
        allowed, vonis, why = identitas.boleh_ditulisi(db, d.id)
        hasil.append({
            "device_id": d.id,
            "device": d.name,
            "ip_address": d.ip_address,
            "platform": d.platform,
            "aktif": d.aktif,
            "vonis": vonis,
            "boleh_ditulisi": allowed,
            "alasan": why,
            "diperiksa": d.identitas_diperiksa.isoformat()
                         if d.identitas_diperiksa else None,
            "penanda": identitas.penanda_tersimpan(db, d.id),
        })
    return {"perangkat": hasil}


@router.get("/ldap/direktori")
def ldap_direktori(db=Depends(wiring.beri_sesi)):
    """Copy of the LDAP directory: who, which role, which groups.
    Read from `orang_ldap` (synced periodically by the poller, see `OrangLdap` in models.py);
    never connects to LDAP directly, so it still answers when `.101` is down, with the age shown
    in `usia_menit`.
    """
    return report_service.direktori_ldap(db)

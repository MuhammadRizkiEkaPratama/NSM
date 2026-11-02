"""Incident routes: list, detail, and latest incident."""
from fastapi import APIRouter, Depends

import korelasi
import report_service
from nsm.antarmuka.http import wiring

router = APIRouter(tags=["insiden"])


@router.get("/insiden")
def daftar_insiden(jam: int = 24, db=Depends(wiring.beri_sesi)):
    """Correlated incidents: one outage, not one symptom. Unlike `/report/insiden-terakhir` (latest
    raw events), these are events already merged by root according to the dependency graph.
    """
    return korelasi.ringkas(db, jam=jam)


@router.get("/insiden/{insiden_id}")
def rinci_insiden(insiden_id: int, db=Depends(wiring.beri_sesi)):
    """One complete incident with all its symptoms, in time order."""
    from sqlalchemy import select

    import models as m
    ins = db.get(m.Insiden, insiden_id)
    if ins is None:
        return {"ada": False, "alasan": "insiden id=%s tidak ada" % insiden_id}
    akar = db.get(m.Device, ins.akar_device_id) if ins.akar_device_id else None
    gejala = db.execute(select(m.InsidenGejala).where(
        m.InsidenGejala.insiden_id == ins.id
    ).order_by(m.InsidenGejala.waktu)).scalars().all()
    return {
        "ada": True, "id": ins.id, "status": ins.status,
        "mulai": ins.mulai.isoformat() if ins.mulai else None,
        "selesai": ins.selesai.isoformat() if ins.selesai else None,
        "akar": akar.name if akar else None,
        "akar_pasti": ins.akar_pasti, "keparahan": ins.keparahan,
        "ringkas": ins.ringkas, "mttr_detik": ins.mttr_detik,
        "jumlah_gejala": ins.jumlah_gejala,
        "akar_id": ins.akar_device_id,
        "notif_terkirim": bool(ins.notif_terkirim),
        "gejala": [{
            "jenis": g.jenis,
            "device_id": g.device_id,
            "device": (db.get(m.Device, g.device_id).name
                       if g.device_id else None),
            "adalah_akar": (g.device_id is not None
                            and g.device_id == ins.akar_device_id),
            "waktu": g.waktu.isoformat() if g.waktu else None,
            "waktu_terakhir": (g.waktu_terakhir.isoformat()
                               if g.waktu_terakhir else None),
            # When the symptom RECOVERED, as opposed to `waktu_terakhir` (last seen still broken); see
            # `models.InsidenGejala.pulih_pada`. The page uses it to draw a correct timeline.
            "pulih_pada": (g.pulih_pada.isoformat()
                           if g.pulih_pada else None),
            "jumlah": g.jumlah, "pulih": g.pulih, "detail": g.detail,
        } for g in gejala],
    }


@router.get("/report/insiden-terakhir")
def report_insiden_terakhir(db=Depends(wiring.beri_sesi)):
    """Latest outage with its cause, evidence chain and suggested action.
    Separate from /report/summary so the incident card can carry long diagnoses (hundreds of
    lines) without weighing down the 10-second page refresh.
    """
    return {"insiden": report_service.insiden_terakhir_lengkap(db)}

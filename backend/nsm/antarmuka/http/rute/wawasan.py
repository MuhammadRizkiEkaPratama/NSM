"""Insight routes: baseline, log patterns, forecasts, and the SOC agent."""
from fastapi import APIRouter, Depends

from nsm.antarmuka.http import wiring

router = APIRouter(tags=["wawasan"])


@router.get("/baseline")
def baseline_ringkas(ambang: float = 3.0, db=Depends(wiring.beri_sesi)):
    """Which devices are deviating from their own normal RIGHT NOW.

    Unlike `/anomali`, which uses a FIXED threshold (same for every device, all
    week), this compares against each device's own habit at that hour.
    """
    import baseline
    return baseline.ringkas(db, ambang=ambang)


@router.get("/baseline/{device_id}")
def baseline_device(device_id: int, db=Depends(wiring.beri_sesi)):
    """One device's normal for this hour, with an explanatory sentence."""
    import baseline
    return baseline.nilai_sekarang(db, device_id)


@router.get("/pola-log")
def pola_log_ringkas(jam: int = 24, db=Depends(wiring.beri_sesi)):
    """Log message patterns, split into NEW and most frequent.

    Deliberately not merged into one sorted list: they answer opposite
    questions (rarest vs most common), and one sort order can answer only one.
    """
    import pola_log
    return pola_log.ringkas(db, jam=max(1, min(jam, 720)))


@router.get("/prakiraan")
def prakiraan_semua(db=Depends(wiring.beri_sesi)):
    """Bandwidth saturation and latency trends.

    The error budget is deliberately NOT here. It calls
    `report_service.hitung_device()`, which touches many tables: measured at
    8.5 s for 11 devices, while the two parts of this endpoint finish in 3.7 s.

    Combining them would make the page wait for the slowest part before showing
    anything. Kept separate, the page draws trends first and fills in the budget
    later; see `/prakiraan/anggaran`.
    """
    import prakiraan
    return prakiraan.semua(db, dengan_anggaran=False)


@router.get("/prakiraan/anggaran")
def prakiraan_anggaran(db=Depends(wiring.beri_sesi)):
    """Error budget burn rate per device.

    Separate from `/prakiraan` because it is much more expensive; see the note there.
    """
    from sqlalchemy import select as _select

    import models as _m
    import prakiraan
    hasil = []
    for d in db.execute(_select(_m.Device).where(
            _m.Device.aktif == True)).scalars().all():   # noqa: E712
        try:
            a = prakiraan.anggaran_device(db, d)
            if a.get("vonis") != prakiraan.TIDAK_CUKUP:
                hasil.append(a)
        except Exception as e:                           # noqa: BLE001
            # One device that fails to compute must not discard
            # the ten that succeeded.
            hasil.append({"device_id": d.id, "nama": d.name,
                          "vonis": prakiraan.TIDAK_CUKUP,
                          "alasan": "gagal dihitung: %s" % str(e)[:120]})

    def urut(x):
        v = x.get("hari_menuju_habis")
        return v if v is not None else 1e9

    hasil.sort(key=urut)
    return {"anggaran": hasil}


@router.get("/agen-soc")
def agen_soc_ringkas(jam: int = 24, db=Depends(wiring.beri_sesi)):
    """What the agent proposed, and what the guard said.

    Read-only. No endpoint runs the agent or flips its switch: enabling a
    component that proposes actions on network devices is a decision for
    someone at the machine, via `.env`, not a single HTTP request.
    """
    import agen_soc
    return agen_soc.ringkas(db, jam=max(1, min(jam, 720)))

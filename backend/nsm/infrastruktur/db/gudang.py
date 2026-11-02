"""SQLAlchemy implementation of the `GudangDevice`/`GudangDenyut` contracts.

The only place in the new layers that knows the `devices` and `status_logs`
tables exist. Everything above speaks `RujukanDevice` and `Denyut`, so
changing storage (or adding a cache) stops at this file instead of spreading
to callers.

`terakhir_semua()` is the single-query form of the per-device `StatusLog`
lookup (1 + N queries per page). Query order can change row order, which is
visible on screen, so `uji_arsitektur_baru.py` compares both forms on real
data.
"""
from sqlalchemy import desc, func

from models import Device, StatusLog
from nsm.domain.model import Denyut, RujukanDevice


def _ke_rujukan(d):
    return RujukanDevice(
        id=d.id, nama=d.name, ip=d.ip_address, tipe=d.device_type,
        platform=d.platform, lokasi=d.location,
        aktif=d.aktif != 0, penting=d.penting == 1,
        jeda_alasan=d.jeda_alasan, jeda_sejak=d.jeda_sejak, jeda_oleh=d.jeda_oleh,
    )


def _ke_denyut(log):
    if log is None:
        return None
    return Denyut(device_id=log.device_id, waktu=log.timestamp,
                  terjangkau=log.is_reachable, rtt_ms=log.response_time_ms,
                  sumber=getattr(log, "sumber", None))


class GudangDeviceSql:
    def __init__(self, db):
        self._db = db

    def semua(self):
        return [_ke_rujukan(d) for d in self._db.query(Device).all()]

    def ambil(self, device_id):
        d = self._db.query(Device).filter(Device.id == device_id).first()
        return _ke_rujukan(d) if d else None


class GudangDenyutSql:
    def __init__(self, db):
        self._db = db

    def terakhir(self, device_id):
        log = (self._db.query(StatusLog)
               .filter(StatusLog.device_id == device_id)
               .order_by(desc(StatusLog.timestamp)).first())
        return _ke_denyut(log)

    def terakhir_semua(self):
        """Latest heartbeat of EVERY device in one query, not one per device."""
        latest = (self._db.query(StatusLog.device_id,
                                  func.max(StatusLog.timestamp).label("t"))
                   .group_by(StatusLog.device_id).subquery())
        line = (self._db.query(StatusLog)
                 .join(latest, (StatusLog.device_id == latest.c.device_id)
                       & (StatusLog.timestamp == latest.c.t)).all())
        return {l.device_id: _ke_denyut(l) for l in line}

    def rentang(self, device_id, mulai, selesai):
        line = (self._db.query(StatusLog)
                 .filter(StatusLog.device_id == device_id,
                         StatusLog.timestamp >= mulai,
                         StatusLog.timestamp <= selesai)
                 .order_by(StatusLog.timestamp).all())
        return [_ke_denyut(l) for l in line]

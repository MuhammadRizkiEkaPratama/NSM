# -*- coding: utf-8 -*-
"""Three charts for the Dashboard, next to the Topology Map.

The dashboard already shows alert cards, summary numbers, the topology map and a
network-rate chart. These three charts cover what that page could not answer:

1. Hourly availability. The rest of the dashboard describes NOW ("10 of 11
   answering"); it cannot show how last night went, so a device that flapped
   twenty times overnight looks as healthy as one that never dropped.

2. Device-sent syslog messages per hour. A message spike often precedes an
   outage.

3. Disk and memory capacity. The alert cards report one device at a time; the
   chart shows WHICH device is closest to its threshold relative to the others,
   which decides what to work on first.

One request for all three charts, like `syslog_service.dasbor`: separate
requests risk some panels filling and others not, and a viewer cannot tell a
failed panel from an empty one.
"""
from datetime import datetime, timedelta

from sqlalchemy import func, select

import models


def _dialek(db):
    return db.get_bind().dialect.name


def _kolom_jam(db, kolom):
    """Round to the hour in the DATABASE, with the right function per dialect.

    MySQL uses DATE_FORMAT, SQLite only has strftime. The primary lab instance runs
    MySQL and the tests run SQLite, so supporting only one breaks the other (see
    `syslog_service.deret_jam`).
    """
    if _dialek(db) == "sqlite":
        return func.strftime("%Y-%m-%d %H:00", kolom)
    return func.date_format(kolom, "%Y-%m-%d %H:00")


def ketersediaan_jam(db, jam=24):
    """Percent of samples that ANSWERED, per hour, across all devices.

    Computed from `status_rollup_jam` (already hourly) rather than `status_logs`
    (over a million rows): the dashboard is opened most when the network is in
    trouble, so it must not be slow then.

    PAUSED devices are excluded. They are intentionally unmonitored, and counting
    them would pull the line down because of a human decision, not a fault.
    """
    limit = datetime.now() - timedelta(hours=jam)
    paused = select(models.Device.id).where(models.Device.jeda_sejak.isnot(None))

    kolom = _kolom_jam(db, models.StatusRollupJam.jam)
    line = db.execute(
        select(kolom.label("j"),
               func.sum(models.StatusRollupJam.sampel).label("sampel"),
               func.sum(models.StatusRollupJam.sampel_naik).label("naik"),
               func.count(func.distinct(models.StatusRollupJam.device_id)).label("n_device"))
        .where(models.StatusRollupJam.jam >= limit,
               models.StatusRollupJam.device_id.notin_(paused))
        .group_by(kolom).order_by(kolom)).all()

    hasil = []
    for j, sampel, naik, n_device in line:
        sampel = int(sampel or 0)
        naik = int(naik or 0)
        hasil.append({
            "jam": j,
            "sampel": sampel,
            "naik": naik,
            # Percent rounded to two decimals, not to an integer: 99.95% vs 100% is the
            # difference between "briefly dropped" and "never dropped".
            "persen": round(naik * 100.0 / sampel, 2) if sampel else None,
            "device": int(n_device or 0),
        })
    return hasil


def pesan_jam(db, jam=24):
    """Syslog message count per hour, split into severe and normal.

    Uses `syslog_service.deret_jam` so the definition of "severe" stays in ONE place
    and cannot drift from the Syslog page.
    """
    import syslog_service
    return syslog_service.deret_jam(db, jam=jam)


def kapasitas_kini(db):
    """LATEST resource measurement per device.

    Not an average: the question is "how full is it NOW", and a weekly average
    hides a disk that just spiked.
    """
    sub = (select(models.SumberDaya.device_id,
                  func.max(models.SumberDaya.waktu).label("t"))
           .group_by(models.SumberDaya.device_id).subquery())

    line = db.execute(
        select(models.SumberDaya, models.Device.name)
        .join(sub, (models.SumberDaya.device_id == sub.c.device_id) &
                   (models.SumberDaya.waktu == sub.c.t))
        .join(models.Device, models.Device.id == models.SumberDaya.device_id)
        .order_by(models.SumberDaya.disk_persen.desc())).all()

    hasil = []
    for s, nama in line:
        hasil.append({
            "device_id": s.device_id,
            "nama": nama,
            "disk_persen": round(s.disk_persen, 1) if s.disk_persen is not None else None,
            "mem_persen": round(s.mem_persen, 1) if s.mem_persen is not None else None,
            "load_per_inti": round(s.load_per_inti, 2) if s.load_per_inti is not None else None,
            "inti": s.inti,
            "waktu": s.waktu.isoformat(sep=" ", timespec="seconds") if s.waktu else None,
            "sumber": s.sumber,
        })
    return hasil


# Threshold used for the charts' red line. Named once here so the three places do
# not drift apart.
AMBANG_DISK = 90
AMBANG_MEM = 90


def semua(db, jam=24):
    """All three charts in one request."""
    return {
        "jam": jam,
        "ketersediaan": ketersediaan_jam(db, jam=jam),
        "pesan": pesan_jam(db, jam=jam),
        "kapasitas": kapasitas_kini(db),
        "ambang_disk": AMBANG_DISK,
        "ambang_mem": AMBANG_MEM,
    }


__all__ = ["ketersediaan_jam", "pesan_jam", "kapasitas_kini", "semua",
           "AMBANG_DISK", "AMBANG_MEM"]

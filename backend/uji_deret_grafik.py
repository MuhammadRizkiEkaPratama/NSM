"""Test `deret_per_jam()`: the series drawn as charts in the Excel report.

A chart carries its own numbers, so any number appearing twice in a document must
match. An earlier attempt computed availability from the share of successful ping
samples, giving 96.805% against 96.528% on the history card for the same data: the
poller's sampling density varies (720 samples in one hour, 55 in another), so
"average per sample" differs from "average per time".

So test 1 matters most: the series TOTAL must equal what `hitung_device` reports.

Tests:
  1. Series total == card availability (main invariant).
  2. Unmonitored time is not counted as down: a fully paused time unit is None, not 0.
  3. An outage crossing an hour boundary is split across both hours.
  4. The unit follows the period length (minute / hour / day).
  5. The series starts at `dipantau_sejak`, not at the period start.
  6. availability never leaves 0..100.

Run: py uji_deret_grafik.py
"""
import sys
from datetime import datetime, timedelta

lolos = 0
gagal = 0


def cek(nama, dapat, harap):
    global lolos, gagal
    if dapat == harap:
        lolos += 1
        print(f"  LOLOS  {nama}: {dapat}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama}: dapat {dapat!r}, harusnya {harap!r}")


def cek_dekat(nama, dapat, harap, toleransi=0.01):
    global lolos, gagal
    if dapat is not None and abs(dapat - harap) <= toleransi:
        lolos += 1
        print(f"  LOLOS  {nama}: {dapat}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama}: dapat {dapat!r}, harusnya ~{harap!r}")


def uji():
    print("=" * 74)
    print("deret_per_jam(): deret untuk grafik laporan Excel")
    print("=" * 74)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import database

    mesin = create_engine("sqlite://")
    original_engine, original_session = database.engine, database.SessionLocal
    database.engine = mesin
    database.SessionLocal = sessionmaker(bind=mesin)

    import models
    models.Base.metadata.create_all(mesin)
    db = database.SessionLocal()
    import jeda
    import report_service as rs
    jeda.lupakan_cache()

    # Setup: one device monitored for 6 full hours without gaps, with one 30-minute outage CROSSING an hour boundary (02:45 - 03:15).
    t0 = datetime(2026, 7, 1, 0, 0, 0)
    end = t0 + timedelta(hours=6)

    db.add(models.Device(id=1, name="Server Uji", ip_address="10.0.0.1",
                         device_type="server", platform="linux", aktif=1))

    # status_logs every 30 seconds so nothing reads as a gap.
    t = t0
    while t <= end:
        mati = (t0 + timedelta(hours=2, minutes=45)) <= t < (t0 + timedelta(hours=3, minutes=15))
        db.add(models.StatusLog(device_id=1, timestamp=t,
                                is_reachable=not mati,
                                response_time_ms=None if mati else 2.0))
        t += timedelta(seconds=30)

    db.add(models.DeviceEvent(device_id=1, event_type="UP", timestamp=t0))
    db.add(models.DeviceEvent(device_id=1, event_type="DOWN",
                              timestamp=t0 + timedelta(hours=2, minutes=45),
                              category="tidak_ada_respons"))
    db.add(models.DeviceEvent(device_id=1, event_type="UP",
                              timestamp=t0 + timedelta(hours=3, minutes=15),
                              duration_sec=1800))
    db.commit()

    d = rs.deret_per_jam(db, 1, t0, end)
    titik = d["titik"]

    print("\n1. Satuan dan jumlah titik")
    cek("satuan untuk 6 jam", d["satuan"], "jam")
    cek("jumlah titik", len(titik), 6)
    cek("titik pertama mulai dari dipantau_sejak", titik[0]["kotak"], "01/07 00:00")

    print("\n2. Gangguan yang melintasi batas jam dibagi ke dua jam")
    # 02:45-03:00 = 900 seconds in hour 3; 03:00-03:15 = 900 seconds in hour 4.
    cek_dekat("jam 02.00 down (detik)", titik[2]["down_detik"], 900, 1)
    cek_dekat("jam 03.00 down (detik)", titik[3]["down_detik"], 900, 1)
    cek_dekat("jam 02.00 availability", titik[2]["availability"], 75.0, 0.01)
    cek_dekat("jam 03.00 availability", titik[3]["availability"], 75.0, 0.01)
    cek("jam 01.00 tanpa gangguan", titik[1]["availability"], 100.0)

    print("\n3. INVARIANT: total deret == availability kartu")
    # The real guard: if the basis is changed back to sample proportion, this test fails first.
    diamati = sum(x["diamati_detik"] for x in titik)
    down = sum(x["down_detik"] for x in titik)
    dari_deret = round((diamati - down) * 100.0 / diamati, 3)
    dev = db.query(models.Device).get(1)
    kartu = rs.hitung_device(db, dev, t0, end)
    cek_dekat("availability deret == kartu", dari_deret,
              kartu["availability"], 0.01)
    cek_dekat("total down deret == kartu", down,
              kartu["total_down_detik"], 2)

    print("\n4. Batas nilai tidak pernah dilanggar")
    at_outer = [x["kotak"] for x in titik
               if x["availability"] is not None
               and not (0.0 <= x["availability"] <= 100.0)]
    cek("tidak ada availability di luar 0..100", at_outer, [])
    negatif = [x["kotak"] for x in titik if x["down_detik"] < 0]
    cek("tidak ada down negatif", negatif, [])
    more = [x["kotak"] for x in titik if x["down_detik"] > x["diamati_detik"] + 0.5]
    cek("down tidak pernah melebihi waktu diamati", more, [])

    print("\n5. Latency hanya dari ping yang berhasil")
    cek("jam sehat punya latency", titik[1]["latency_ms"], 2.0)
    cek("jam gangguan tetap punya latency dari sampel yang hidup",
        titik[2]["latency_ms"], 2.0)

    # Second setup: a full one-hour monitoring GAP (04:00). The poller was down, so there are no status_logs in that hour.
    print("\n6. Jam yang tidak terpantau bukan jam yang mati")
    jeda.lupakan_cache()
    db.query(models.StatusLog).filter(
        models.StatusLog.timestamp >= t0 + timedelta(hours=4),
        models.StatusLog.timestamp < t0 + timedelta(hours=5)).delete()
    db.commit()
    jeda.lupakan_cache()

    d2 = rs.deret_per_jam(db, 1, t0, end)
    hour4 = [x for x in d2["titik"] if x["kotak"] == "01/07 04:00"]
    cek("jam berlubang tetap muncul di deret", len(hour4), 1)
    if hour4:
        cek("availability jam berlubang = None (bukan 0)",
            hour4[0]["availability"], None)
        cek_dekat("waktu diamati jam berlubang ~ 0", hour4[0]["diamati_detik"], 0, 60)

    # The card must not drop because of that gap either.
    kartu2 = rs.hitung_device(db, dev, t0, end)
    diamati2 = sum(x["diamati_detik"] for x in d2["titik"])
    down2 = sum(x["down_detik"] for x in d2["titik"])
    dari_deret2 = round((diamati2 - down2) * 100.0 / diamati2, 3)
    cek_dekat("deret masih cocok dengan kartu setelah ada lubang",
              dari_deret2, kartu2["availability"], 0.01)

    print("\n7. Satuan mengikuti panjang periode")
    d_minute = rs.deret_per_jam(db, 1, t0, t0 + timedelta(hours=1))
    cek("periode 1 jam -> per menit", d_minute["satuan"], "menit")
    cek("periode 1 jam -> 60 titik", len(d_minute["titik"]), 60)
    d_day = rs.deret_per_jam(db, 1, t0 - timedelta(days=20), end)
    cek("periode 20 hari -> per hari", d_day["satuan"], "hari")

    print("\n8. Device yang belum pernah dipantau tidak menghasilkan deret palsu")
    db.add(models.Device(id=2, name="Belum pernah", ip_address="10.0.0.2",
                         device_type="server", aktif=1))
    db.commit()
    d3 = rs.deret_per_jam(db, 2, t0, end)
    cek("deret device tanpa event kosong", d3["titik"], [])

    db.close()
    database.engine, database.SessionLocal = original_engine, original_session


if __name__ == "__main__":
    uji()
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

"""Test: availability is not published from an observation window that is too short.

Regression: a device paused while DOWN had only 26 s observed out of 24 h, yet
NSM published `availability = 0.188 %`, indistinguishable from a device that was
down all day. The old condition `jendela > 0` let any observation through.

Guards:
1. Observation below the threshold -> `availability` None, `cukup_diamati` False.
2. Observation above the threshold -> the number is published as usual.
3. The overall average is not dragged by the withheld number.
4. A withheld device still carries how long it was observed, so the page can explain.

Run: py uji_ambang_diamati.py
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


def cek_benar(nama, syarat, keterangan=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print(f"  LOLOS  {nama}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama} {keterangan}")


def uji():
    print("=" * 74)
    print("Availability tidak terbit dari pengamatan yang terlalu pendek")
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

    try:
        finish = datetime.now()
        start = finish - timedelta(hours=24)

        def device(id_, nama):
            d = models.Device(id=id_, name=nama, ip_address=f"10.9.9.{id_}",
                              device_type="router", platform="linux", aktif=1)
            db.add(d)
            return d

        # Device 1: paused while DOWN, modeled on the WiFi gateway. Pings stopped 23 hours ago while DOWN.
        d1 = device(1, "Dijeda selagi DOWN")
        halt = finish - timedelta(hours=23)
        db.add(models.DeviceEvent(device_id=1, event_type="DOWN",
                                  category="dead", timestamp=halt - timedelta(seconds=30)))
        # A few ping rows just before it stopped, then silence.
        for i in range(6):
            db.add(models.StatusLog(device_id=1, timestamp=halt - timedelta(seconds=30 - i * 5),
                                    is_reachable=False, response_time_ms=None, sumber="icmp"))

        # --- Device 2: dipantau penuh, sehat -------------------------------
        d2 = device(2, "Dipantau penuh")
        db.add(models.DeviceEvent(device_id=2, event_type="UP",
                                  category="baseline", timestamp=start))
        # Row spacing must be tighter than `jeda.ambang_detik()` (60 s), otherwise each gap
        # reads as a monitoring hole and a healthy device is held back by the threshold.
        t = start
        while t < finish:
            db.add(models.StatusLog(device_id=2, timestamp=t,
                                    is_reachable=True, response_time_ms=1.0, sumber="icmp"))
            t += timedelta(seconds=30)

        db.commit()

        hasil = {x["name"]: x for x in rs.availability_semua(db, "24h")["devices"]}

        print("\n-- 1. pengamatan terlalu pendek: angkanya DITAHAN --")
        a = hasil["Dijeda selagi DOWN"]
        cek("availability tidak diterbitkan", a["availability"], None)
        cek("ditandai tidak cukup diamati", a["cukup_diamati"], False)
        cek_benar("diamati jauh di bawah ambang",
                  a["durasi_diamati_detik"] < rs.MIN_DIAMATI_DETIK,
                  f"(diamati {a['durasi_diamati_detik']} dtk, "
                  f"ambang {rs.MIN_DIAMATI_DETIK})")

        print("\n-- 2. keterangannya tetap ada, supaya halaman bisa menjelaskan --")
        cek_benar("durasi_diamati_teks terisi",
                  bool(a["durasi_diamati_teks"]) and a["durasi_diamati_teks"] != "-",
                  f"(isi: {a['durasi_diamati_teks']!r})")
        cek_benar("tak_terpantau_teks terisi",
                  bool(a["tak_terpantau_teks"]),
                  f"(isi: {a['tak_terpantau_teks']!r})")

        print("\n-- 3. PENJAGA ARAH SEBALIKNYA: device sehat TIDAK ikut ditahan --")
        b = hasil["Dipantau penuh"]
        cek("ditandai cukup diamati", b["cukup_diamati"], True)
        cek_benar("availability tetap terbit", b["availability"] is not None,
                  "(ambangnya menelan device yang seharusnya terukur)")
        cek_benar("dan nilainya masuk akal",
                  b["availability"] is not None and b["availability"] > 99,
                  f"(dapat {b['availability']})")

        print("\n-- 4. rata-rata keseluruhan tidak terseret angka yang ditahan --")
        r = rs.ringkasan(db, "24h")
        cek_benar("rata-rata dihitung hanya dari yang terbit",
                  r["availability_rata"] is not None and r["availability_rata"] > 99,
                  f"(dapat {r['availability_rata']}; kalau 0,x berarti angka "
                  f"yang ditahan ikut terhitung)")

        print("\n-- 5. ambangnya diumumkan, bukan angka rahasia di dalam kode --")
        cek("min_diamati_detik ikut dikirim ke halaman",
            a["min_diamati_detik"], rs.MIN_DIAMATI_DETIK)

    finally:
        db.close()
        jeda.lupakan_cache()
        database.engine, database.SessionLocal = original_engine, original_session


if __name__ == "__main__":
    uji()
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

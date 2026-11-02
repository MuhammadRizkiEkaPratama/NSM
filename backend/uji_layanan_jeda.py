"""Test that SERVICE availability also excludes unmonitored time.

The earlier fix (time when NSM was not monitoring does not count as downtime)
only reached `hitung_device()`; `_hitung_layanan()` still used the old formula,
so one product gave two meanings to "availability" with the same display.

Uses an in-memory database with hand-computable cases plus a cross-check on
real data. Proven:

1. A service DOWN while the poller was off is not counted dead for that period.
2. A HEALTHY service while the poller was off no longer gets an inflated denominator.
3. Cases without any gap are unchanged (regression guard).
4. `layanan_semua()` returns `diamati` and `periode_penuh`, so the Services page
   does not promise "7 days" while silently computing over 19 hours.

Run: py uji_layanan_jeda.py
"""
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

lolos = 0
gagal = 0


def cek(nama, dapat, harap, toleransi=0.6):
    global lolos, gagal
    if isinstance(harap, (int, float)) and not isinstance(harap, bool) \
            and isinstance(dapat, (int, float)) and not isinstance(dapat, bool):
        ok = abs(dapat - harap) <= toleransi
    else:
        ok = dapat == harap
    if ok:
        lolos += 1
        print(f"  LOLOS  {nama}: {dapat}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama}: dapat {dapat}, harusnya {harap}")


def uji_buatan():
    print("=" * 74)
    print("BAGIAN 1: kasus buatan (jawaban benarnya dihitung tangan)")
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

    t0 = datetime(2026, 7, 1, 0, 0, 0)

    def device(id_, nama):
        db.add(models.Device(id=id_, name=nama, ip_address=f"10.0.0.{id_}",
                             device_type="server", platform="linux", aktif=1))

    def layanan(id_, did, nama, port=80):
        db.add(models.Service(id=id_, device_id=did, nama=nama, jenis="tcp",
                              port=port, aktif=1))

    def ping(did, dari, sampai, langkah=5):
        """status_logs of the DEVICE: the only 'being monitored' trace dense enough to find observation gaps."""
        t = dari
        while t <= sampai:
            db.add(models.StatusLog(device_id=did, timestamp=t,
                                    is_reachable=True, response_time_ms=1.0))
            t += timedelta(seconds=langkah)

    def ev(sid, did, tipe, waktu, kategori=None):
        db.add(models.ServiceEvent(service_id=sid, device_id=did,
                                   event_type=tipe, timestamp=waktu,
                                   kategori=kategori, detail="uji"))

    # Case A: service DOWN, then the poller is off for 13 hours.
    # Device monitored 0:00-1:00, stopped, resumed 14:00-15:00. Service DOWN at
    # 0:59:00, UP again at 14:00. The old formula gives 13.2% availability; the
    # correct one counts only 60 s of outage in 2 h observed: 99.167%.
    device(1, "Device A")
    layanan(1, 1, "Web A")
    ping(1, t0, t0 + timedelta(hours=1))
    ping(1, t0 + timedelta(hours=14), t0 + timedelta(hours=15))
    ev(1, 1, "UP", t0, "baseline")
    ev(1, 1, "DOWN", t0 + timedelta(minutes=59), "koneksi_ditolak")
    ev(1, 1, "UP", t0 + timedelta(hours=14), "pulih")

    device(2, "Device B")
    layanan(2, 2, "Web B")
    ping(2, t0, t0 + timedelta(hours=15))
    ev(2, 2, "UP", t0, "baseline")
    ev(2, 2, "DOWN", t0 + timedelta(hours=1), "koneksi_ditolak")
    ev(2, 2, "UP", t0 + timedelta(hours=1, minutes=5), "pulih")

    # Case C: poller off while the service is HEALTHY. Availability stays 100%, but the
    # observation length must report 2 h, not 15 h.
    device(3, "Device C")
    layanan(3, 3, "Web C")
    ping(3, t0, t0 + timedelta(hours=1))
    ping(3, t0 + timedelta(hours=14), t0 + timedelta(hours=15))
    ev(3, 3, "UP", t0, "baseline")

    db.commit()

    now = t0 + timedelta(hours=15)
    start = now - timedelta(hours=24)

    def hitung(sid):
        s = db.query(models.Service).get(sid)
        d = db.query(models.Device).get(s.device_id)
        return rs._hitung_layanan(db, s, d, start, now)

    print("\nKasus A: layanan DOWN selagi poller mati 13 jam")
    a = hitung(1)
    cek("total down yang diamati (detik)", a["total_down_detik"], 60)
    cek("angka mentah cara lama tetap tersimpan",
        a["total_down_mentah_detik"], 46860, toleransi=60)
    cek("lama diamati (detik)", a["diamati_detik"], 7200, toleransi=60)
    cek("availability (%)", a["availability"], 99.167, toleransi=0.2)
    cek("tak terpantau dilaporkan (detik)",
        a["tak_terpantau_detik"] > 46000, True)

    print("\nKasus B: gangguan biasa tanpa jeda (regresi, tidak boleh berubah)")
    b = hitung(2)
    cek("total down (detik)", b["total_down_detik"], 300)
    cek("tidak ada waktu tak terpantau", b["tak_terpantau_detik"], 0)
    cek("lama diamati (detik)", b["diamati_detik"], 54000, toleransi=60)
    cek("availability (%)", b["availability"], 99.444, toleransi=0.05)

    print("\nKasus C: poller mati selagi layanan sehat")
    c = hitung(3)
    cek("tidak ada gangguan", c["insiden"], 0)
    cek("availability tetap penuh (%)", c["availability"], 100.0)
    cek("lama diamati mengaku 2 jam (detik)",
        c["diamati_detik"], 7200, toleransi=60)
    cek("penyebut TIDAK menggelembung jadi 15 jam",
        c["diamati_detik"] < 54000 * 0.5, True)

    print("\nJ7: layanan_semua mengirim bahan untuk mengaku jendelanya pendek")
    semua = rs.layanan_semua(db, "24h")
    per_service = [x["diamati_detik"] for x in semua["layanan"]
                   if x.get("diamati_detik") is not None]
    cek("periode_penuh ada dan bernilai False", semua["periode_penuh"], False)
    cek("diamati_detik memakai jendela TERPENDEK",
        semua["diamati_detik"], min(per_service), toleransi=0)
    cek("diamati_maks_detik menyimpan yang terpanjang",
        semua["diamati_maks_detik"], max(per_service), toleransi=0)
    cek("periode_teks terisi", semua["periode_teks"], "24 jam")

    print("\nPenjaga: jeda dipakai dari DEVICE pemilik, bukan dari layanan")
    # Service D has no events in the middle, but its device has an observation gap.
    # If gaps were found from the (sparse) service trail, this one would be missed.
    device(4, "Device D")
    layanan(4, 4, "Web D")
    ping(4, t0, t0 + timedelta(hours=1))
    ping(4, t0 + timedelta(hours=14), t0 + timedelta(hours=15))
    ev(4, 4, "UP", t0, "baseline")
    db.commit()
    jeda.lupakan_cache()
    d4 = hitung(4)
    cek("lubang device terbaca dari sisi layanan",
        d4["tak_terpantau_detik"] > 46000, True)

    db.close()
    database.engine, database.SessionLocal = original_engine, original_session


def uji_nyata():
    print()
    print("=" * 74)
    print("BAGIAN 2: data nyata dari salinan nsm.db")
    print("=" * 74)

    origin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nsm.db")
    if not os.path.exists(origin):
        print("  nsm.db tidak ada, bagian ini dilewati.")
        return

    folder = tempfile.mkdtemp(prefix="nsm-uji-layanan-")
    copy_of = os.path.join(folder, "salinan.db")
    source = sqlite3.connect(f"file:{origin}?mode=ro", uri=True)
    destination = sqlite3.connect(copy_of)
    source.backup(destination)
    destination.close()
    source.close()

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import database
    mesin = create_engine(f"sqlite:///{copy_of.replace(os.sep, '/')}")
    database.engine = mesin
    database.SessionLocal = sessionmaker(bind=mesin)

    import models
    import jeda
    import report_service as rs
    jeda.lupakan_cache()
    db = database.SessionLocal()

    line = (db.query(models.Service, models.Device)
             .join(models.Device, models.Device.id == models.Service.device_id)
             .order_by(models.Service.id).all())
    if not line:
        print("  Belum ada layanan terdaftar, bagian ini dilewati.")
        db.close()
        mesin.dispose()
        shutil.rmtree(folder, ignore_errors=True)
        return

    now = db.query(models.StatusLog.timestamp).order_by(
        models.StatusLog.timestamp.desc()).first()[0]
    if isinstance(now, str):
        now = datetime.fromisoformat(now)
    start = now - timedelta(days=7)

    print(f"\n  Jendela uji: 7 hari sampai {now:%d %b %H:%M}\n")
    print(f"  {'Layanan':<24}{'avail lama':>12}{'avail baru':>12}"
          f"{'diamati':>14}{'tak dipantau':>14}")
    print("  " + "-" * 76)

    for s, d in line:
        content = rs._hitung_layanan(db, s, d, start, now)
        if content is None:
            continue
        observed_old = content["diamati_detik"] + content["tak_terpantau_detik"]
        down_old = content["total_down_mentah_detik"]
        av_old = (max(0.0, observed_old - down_old) / observed_old * 100
                   if observed_old > 0 else 0.0)
        av_new = content["availability"]
        print(f"  {s.nama[:23]:<24}{av_old:>11.3f}%"
              f"{(av_new if av_new is not None else 0):>11.3f}%"
              f"{content['diamati_teks']:>14}{content['tak_terpantau_teks'] or '-':>14}")

    print()
    # Cross-check: service availability must not be computed over a longer window
    # than its owning device's window.
    worst = 0.0
    for s, d in line:
        content = rs._hitung_layanan(db, s, d, start, now)
        dev = rs.hitung_device(db, d, start, now)
        if content is None or dev["durasi_diamati_detik"] is None:
            continue
        kelebihan = content["diamati_detik"] - dev["durasi_diamati_detik"]
        worst = max(worst, kelebihan)
        print(f"  {s.nama[:23]:<24} layanan {content['diamati_teks']:>16}"
              f"   device {dev['durasi_diamati_teks']:>16}")

    print()
    cek("tidak ada layanan yang mengaku diamati lebih lama dari device-nya",
        worst <= 60, True)

    db.close()
    mesin.dispose()
    shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    uji_buatan()
    uji_nyata()
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

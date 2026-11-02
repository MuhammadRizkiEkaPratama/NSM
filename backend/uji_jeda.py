"""Test the fix "unmonitored time is not counted as down time".

1. SYNTHETIC tests: in-memory database with cases whose answers are known,
   including the case that used to be wrong.
2. REAL DATA tests: read from a copy of `nsm.db` (read-only), proving the fix hits the target on real data.

Run: py uji_jeda.py
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
    if isinstance(harap, (int, float)) and isinstance(dapat, (int, float)):
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

    mesin = create_engine("sqlite://")  # purely in memory
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
        d = models.Device(id=id_, name=nama, ip_address=f"10.0.0.{id_}",
                          device_type="server", platform="linux", aktif=1)
        db.add(d)
        return d

    def ping(did, dari, sampai, langkah=5, hidup=True):
        """Fill status_logs densely every `langkah` seconds; this is the proof of 'monitored'."""
        t = dari
        while t <= sampai:
            db.add(models.StatusLog(device_id=did, timestamp=t,
                                    is_reachable=hidup, response_time_ms=1.0))
            t += timedelta(seconds=langkah)

    def event(did, tipe, waktu, kategori=None):
        db.add(models.DeviceEvent(device_id=did, event_type=tipe,
                                  timestamp=waktu, category=kategori,
                                  detail="uji"))

    # Case A: exactly the WiFi gateway case. Monitored 0:00-1:00. DOWN at 0:59:00.
    # Monitoring stopped at 1:00:00 (device paused), resumed 13 hours later at 14:00 and
    # the device was UP.
    #
    # Old way: outage = 0:59 -> 14:00 = 46,860 s. Correct: only 0:59:00 -> 1:00:00 = 60 s was observed.
    device(1, "Kasus A dijeda saat DOWN")
    ping(1, t0, t0 + timedelta(hours=1))
    event(1, "UP", t0, "baseline")
    event(1, "DOWN", t0 + timedelta(minutes=59), "dead")
    ping(1, t0 + timedelta(hours=14), t0 + timedelta(hours=15))
    event(1, "UP", t0 + timedelta(hours=14), "recovered")

    # Case B: ordinary outage, no pause. Regression guard: the fix must not change numbers that were already right.
    device(2, "Kasus B gangguan biasa")
    ping(2, t0, t0 + timedelta(hours=15))
    event(2, "UP", t0, "baseline")
    event(2, "DOWN", t0 + timedelta(hours=1), "dead")
    event(2, "UP", t0 + timedelta(hours=1, minutes=5), "recovered")

    # Case C: poller down while the device was healthy. No outage at all, but 13 hours
    # unobserved. Availability must stay 100% and the observation time must admit only 2 hours.
    device(3, "Kasus C jeda saat sehat")
    ping(3, t0, t0 + timedelta(hours=1))
    event(3, "UP", t0, "baseline")
    ping(3, t0 + timedelta(hours=14), t0 + timedelta(hours=15))

    db.commit()

    now = t0 + timedelta(hours=15)
    start = now - timedelta(hours=24)

    print("\nKasus A: device dijeda selagi DOWN")
    d1 = db.query(models.Device).get(1)
    a = rs.hitung_device(db, d1, start, now)
    down_a, _ = rs.selang_down(db, 1, start, now)
    cek("lama gangguan yang diamati (detik)", round(down_a[0]["durasi_detik"]), 60)
    cek("bagian yang tidak terpantau (detik)",
        round(down_a[0]["jeda_detik"]), 46800, toleransi=60)
    cek("angka mentah cara lama masih tersimpan",
        round(down_a[0]["durasi_mentah_detik"]), 46860, toleransi=60)
    cek("total down (detik)", a["total_down_detik"], 60)
    # Observed 2 hours (0:00-1:00 and 14:00-15:00) = 7,200 s, down 60 s.
    cek("lama diamati (detik)", a["durasi_diamati_detik"], 7200, toleransi=60)
    cek("availability (%)", a["availability"], 99.167, toleransi=0.2)
    cek("tak terpantau dilaporkan", a["tak_terpantau_detik"] > 46000, True)

    print("\nKasus B: gangguan biasa (regresi, tidak boleh berubah)")
    d2 = db.query(models.Device).get(2)
    b = rs.hitung_device(db, d2, start, now)
    down_b, _ = rs.selang_down(db, 2, start, now)
    cek("lama gangguan (detik)", round(down_b[0]["durasi_detik"]), 300)
    cek("tidak ada jeda", round(down_b[0]["jeda_detik"]), 0)
    cek("total down (detik)", b["total_down_detik"], 300)
    cek("lama diamati (detik)", b["durasi_diamati_detik"], 54000, toleransi=60)
    cek("availability (%)", b["availability"], 99.444, toleransi=0.05)

    print("\nKasus C: poller mati selagi device sehat")
    d3 = db.query(models.Device).get(3)
    c = rs.hitung_device(db, d3, start, now)
    cek("tidak ada gangguan", c["insiden"], 0)
    cek("availability tetap penuh (%)", c["availability"], 100.0)
    cek("lama diamati mengaku 2 jam (detik)",
        c["durasi_diamati_detik"], 7200, toleransi=60)
    cek("periode 24 jam ditandai belum penuh",
        c["durasi_diamati_detik"] < 86400 * 0.99, True)

    print("\nPenjaga: jeda pendek (12 detik) TIDAK boleh dianggap putus")
    # The poller sometimes skips a round; if a jump that short counted, every device would have hundreds of false gaps.
    device(4, "Kasus D lompatan pendek")
    ping(4, t0, t0 + timedelta(hours=1))
    ping(4, t0 + timedelta(hours=1, seconds=12), t0 + timedelta(hours=15))
    event(4, "UP", t0, "baseline")
    db.commit()
    jeda.lupakan_cache()
    # The 24-hour window starts 9 hours BEFORE this device's first ping row, so one
    # legitimate gap exists at the front. What is checked is that the 12-second jump in the middle is not counted.
    list_d = jeda.find_gaps(db, 4, start, now)
    di_tengah = [(a, b) for a, b in list_d if a >= t0]
    cek("lompatan 12 detik di tengah diabaikan", len(di_tengah), 0)
    cek("jeda depan (sebelum device punya data) tetap terlihat",
        len(list_d), 1)

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

    # Copied with the SQLite backup API, not a file copy, so WAL contents not yet in the main file are included (same reason as in database.py).
    folder = tempfile.mkdtemp(prefix="nsm-uji-")
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

    now = db.query(models.StatusLog.timestamp).order_by(
        models.StatusLog.timestamp.desc()).first()[0]
    if isinstance(now, str):
        now = datetime.fromisoformat(now)
    start = now - timedelta(days=7)

    print(f"\n  Jendela uji: 7 hari sampai {now:%d %b %H:%M}\n")
    print(f"  {'Device':<22}{'avail lama':>12}{'avail baru':>12}"
          f"{'down lama':>12}{'down baru':>12}")
    print("  " + "-" * 70)

    changed = 0
    for d in db.query(models.Device).order_by(models.Device.id).all():
        pause_list = jeda.find_gaps(db, d.id, start, now)
        down, monitored = rs.selang_down(db, d.id, start, now, pause_list)
        if monitored is None:
            continue
        effective = max(start, monitored)
        window_old = (now - effective).total_seconds()
        down_old = sum(round(x["durasi_mentah_detik"]) for x in down)
        down_new = sum(round(x["durasi_detik"]) for x in down)
        tak = jeda.detik_tak_terpantau(pause_list, effective, now)
        window_new = window_old - tak

        av_old = (max(0.0, window_old - down_old) / window_old * 100
                   if window_old > 0 else 0)
        av_new = (max(0.0, window_new - down_new) / window_new * 100
                   if window_new > 0 else 0)
        if abs(av_new - av_old) > 0.01:
            changed += 1
        print(f"  {d.name:<22}{av_old:>11.3f}%{av_new:>11.3f}%"
              f"{down_old:>11}s{down_new:>11}s")

    print()
    # Cross-check: event-based availability should be close to the successful-ping percentage.
    #
    # The comparison must start at the device's first event (`dipantau_sejak`), not the
    # period start: `device_events` is newer than `status_logs`, and comparing different
    # ranges produces a spurious 5% gap.
    print(f"  {'Device':<22}{'dari event':>12}{'dari ping':>12}{'selisih':>10}")
    print("  " + "-" * 60)
    from sqlalchemy import text as _teks
    worst = 0.0
    for d in db.query(models.Device).order_by(models.Device.id).all():
        summarize = rs.hitung_device(db, d, start, now)
        if summarize["availability"] is None or not summarize.get("dipantau_sejak"):
            continue
        effective = max(start, datetime.fromisoformat(summarize["dipantau_sejak"]))
        n, ok = db.execute(
            _teks("SELECT COUNT(*), SUM(is_reachable) FROM status_logs "
                  "WHERE device_id=:d AND timestamp>=:m"),
            {"d": d.id, "m": effective}).one()
        n, ok = n or 0, ok or 0
        if not n:
            continue
        from_ping = ok / n * 100
        selisih = abs(summarize["availability"] - from_ping)
        worst = max(worst, selisih)
        mark = "  <-- masih jauh" if selisih > 1.5 else ""
        print(f"  {d.name:<22}{summarize['availability']:>11.3f}%"
              f"{from_ping:>11.3f}%{selisih:>9.2f}%{mark}")

    print()
    # Threshold 1.5%: the anti-flapping threshold (2 consecutive failures) makes the event version slightly more optimistic, so zero is not the right target.
    cek("selisih terburuk event vs ping turun di bawah 1,5%",
        worst < 1.5, True)

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

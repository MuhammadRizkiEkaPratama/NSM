"""Part B: recompute `device_events` with the new DOWN threshold.

Full plan and the four pitfalls (B1-B4): docs/design/NETWORK-STATUS.md, Part B.

Why this exists: the DOWN detection threshold was raised from 2 to 5 consecutive
failures (`config.get_down_threshold()`) because the old threshold produced
hundreds of "outages" a day, almost all false (mostly a single lost ping, caused
by emulated Dynamips routers delaying ICMP replies when the host CPU was busy).
The new threshold applies to NEW events since the restart. OLD `device_events`
were still computed with the 2x threshold, so period reports spanning that range
mix both thresholds until this script is run.

Four pitfalls handled (do not simplify):

    B1  Time gaps while the poller was down: a gap between status_logs rows
        greater than 3x the ping interval breaks the consecutive-failure count,
        so two separate failures are not read as "consecutive" just because the
        rows between them were never recorded.
    B2  The `ping_blocked` category (ICMP blocked, TCP alive) is read DIRECTLY
        from the `status_logs.sumber` column, which stored it when the row was
        written. No need to re-guess with a new TCP probe: the final verdict is
        already recorded as `is_reachable`.
    B3  `baseline` rows (marker of first monitoring) are NOT recomputed; they
        are copied as is from the old `device_events` per device.
    B4  status_logs older than the device's old baseline are NOT touched. That
        is the period before the device was monitored for events, and counting
        it would invent events nobody ever observed.

Flow: 1) require a fresh backup (< 1 hour); 2) copy the old device_events to the
table `device_events_sebelum_ambang5` ONCE (never overwritten, so the FIRST copy
stays the reference if the script is run repeatedly); 3) recompute in memory;
4) show a before/after summary; 5) ask for EXPLICIT confirmation before swapping
anything.

Idempotent: running twice on the same data gives identical device_events (old
baseline + the same recomputed result).

Run (INTERACTIVE, asks before swapping anything):

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\python.exe hitung_ulang_insiden.py
"""
import glob
import os
import sys

from sqlalchemy import func, inspect, text

import config
import database
from models import Device, DeviceEvent, StatusLog

NAMA_SALINAN = "device_events_sebelum_ambang5"
JEDA_MAKS_KELIPATAN = 3  # see B1 in the docstring


def _backup_terbaru_umur_jam():
    """Age (hours) of the NEWEST backup. None if there is no backup at all."""
    folder = config.get_backup_dir()
    file = (glob.glob(os.path.join(folder, "*.zip"))
             + glob.glob(os.path.join(folder, "*.zip.enc")))
    if not file:
        return None
    import datetime
    latest = max(file, key=os.path.getmtime)
    age = datetime.datetime.now() - datetime.datetime.fromtimestamp(
        os.path.getmtime(latest))
    return age.total_seconds() / 3600.0


def hitung_ulang_device(db, device_id, baris, batas):
    """Replay ONE device. `baris` = its status_logs (this device_id only, timestamp >=
    old baseline, ascending). Returns a list of dicts ready to become new
    `DeviceEvent` rows, NOT including the baseline (see B3: the caller copies it
    as is).
    """
    import jeda

    event = []
    fail_consecutive = 0
    previous = None
    time_past = None
    time_event_past = None
    interval = config.get_interval()

    for b in baris:
        # B1: time gap, the poller was down. Do not carry the consecutive-failure count
        # across the gap as if both sides were close together.
        if time_past is not None:
            distance = (b.timestamp - time_past).total_seconds()
            if distance > JEDA_MAKS_KELIPATAN * interval:
                fail_consecutive = 0
        time_past = b.timestamp

        if b.is_reachable:
            fail_consecutive = 0
        else:
            fail_consecutive += 1

        if previous is None:
            # First row AFTER the old baseline: continue the status the baseline already
            # recorded, NOT a new baseline (B3/B4).
            previous = "UP" if b.is_reachable else "DOWN"
            time_event_past = b.timestamp
            continue

        baru = None
        # UP -> DOWN, only after consecutive failures reach the threshold. B2: the
        # category is ALWAYS "dead" here, since a row whose port answered (sumber="tcp")
        # never has is_reachable=False.
        if previous == "UP" and not b.is_reachable and fail_consecutive >= batas:
            baru = {
                "event_type": "DOWN", "category": "dead",
                "last_rtt_ms": None,
                "detail": ("Ping tidak dibalas dan tidak ada port TCP yang "
                          "menjawab -> device kemungkinan MATI atau "
                          "terputus dari jaringan. (dihitung ulang, ambang "
                          "%dx)" % batas),
            }
            previous = "DOWN"
        # DOWN -> UP: recovery is recorded immediately without a threshold; the category
        # depends on HOW the device proved alive again (B2).
        elif previous == "DOWN" and b.is_reachable:
            if b.sumber == "tcp":
                kategori = "ping_blocked"
                detail = ("Device terjangkau lagi lewat TCP, TETAPI ping-nya "
                          "tetap tidak dibalas. Mesinnya hidup; yang "
                          "kemungkinan besar diblokir ICMP-nya, bukan "
                          "mesinnya yang mati. (dihitung ulang)")
            else:
                kategori = "recovered"
                detail = "Device kembali membalas ping. (dihitung ulang)"
            baru = {"event_type": "UP", "category": kategori,
                   "last_rtt_ms": b.response_time_ms, "detail": detail}
            previous = "UP"

        if baru is not None:
            baru["timestamp"] = b.timestamp
            duration = (b.timestamp - time_event_past).total_seconds()
            if duration >= 0:
                tak_terpantau = jeda.tak_terpantau_antara(
                    db, device_id, time_event_past, b.timestamp)
                duration = max(0.0, duration - tak_terpantau)
            else:
                duration = None
            baru["duration_sec"] = duration
            event.append(baru)
            time_event_past = b.timestamp

    return event


def main():
    print("=" * 74)
    print("BAGIAN B: hitung ulang device_events dengan ambang DOWN baru")
    print("=" * 74)

    # 1. A fresh backup is REQUIRED.
    age = _backup_terbaru_umur_jam()
    if age is None:
        print("\nBERHENTI: tidak ada backup sama sekali di %s."
              % config.get_backup_dir())
        print("Jalankan backup_nsm.py dulu, baru ulangi skrip ini.")
        return 1
    if age > 1.0:
        print("\nBERHENTI: backup terbaru berumur %.1f jam (>1 jam)." % age)
        print("Jalankan backup_nsm.py dulu, baru ulangi skrip ini.")
        return 1
    print("\nBackup terbaru berumur %.1f jam -- OK, lanjut." % age)

    insp = inspect(database.engine)

    # 2. Copy the OLD device_events, ONLY if the copy does not exist yet.
    if insp.has_table(NAMA_SALINAN):
        print("\nTabel salinan '%s' sudah ada -- TIDAK disalin ulang "
              "(salinan PERTAMA yang harus tetap jadi acuan pembanding, "
              "bukan yang terbaru)." % NAMA_SALINAN)
    else:
        with database.engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE %s AS SELECT * FROM device_events" % NAMA_SALINAN))
        print("\nTabel salinan '%s' dibuat dari device_events saat ini."
              % NAMA_SALINAN)

    db = database.SessionLocal()
    try:
        batas = config.get_down_threshold()
        print("\nAmbang DOWN yang dipakai: %d gagal beruntun (%d detik)."
              % (batas, batas * config.get_interval()))

        devices = db.query(Device).order_by(Device.name).all()
        total_old = db.query(func.count(DeviceEvent.id)).scalar()

        plan = {}  # device_id -> (old_baseline, [new_event, ...])
        for d in devices:
            baseline_old = (db.query(DeviceEvent)
                             .filter(DeviceEvent.device_id == d.id)
                             .order_by(DeviceEvent.timestamp, DeviceEvent.id)
                             .first())
            if baseline_old is None:
                continue

            baris = (db.query(StatusLog)
                     .filter(StatusLog.device_id == d.id,
                             StatusLog.timestamp >= baseline_old.timestamp)
                     .order_by(StatusLog.timestamp, StatusLog.id).all())
            event_new = hitung_ulang_device(db, d.id, baris, batas)
            plan[d.id] = (baseline_old, event_new)

        # 3. Before/after SUMMARY per device.
        print("\n%-32s %8s %8s" % ("Device", "Lama", "Baru*"))
        print("-" * 52)
        total_new = 0
        for d in devices:
            if d.id not in plan:
                continue
            _, event_new = plan[d.id]
            old_n = (db.query(func.count(DeviceEvent.id))
                     .filter(DeviceEvent.device_id == d.id).scalar())
            new_n = 1 + len(event_new)
            total_new += new_n
            mark = "  <-" if new_n < old_n else ""
            print("%-32s %8d %8d%s" % (d.name, old_n, new_n, mark))
        print("-" * 52)
        print("%-32s %8d %8d" % ("TOTAL", total_old, total_new))
        print("(*termasuk 1 baris baseline yang disalin apa adanya per device)")

        if total_old:
            fall = 100.0 * (total_old - total_new) / total_old
            print("\nPengurangan jumlah event: %.1f%%" % fall)

        # 4. Ask for explicit confirmation before swapping anything.
        print("\nSalinan lama SUDAH aman di tabel '%s' -- bisa dibandingkan "
              "atau dikembalikan kapan pun." % NAMA_SALINAN)
        answer = input("\nTukar device_events dengan hasil hitung ulang ini? "
                      "(ketik 'ya' untuk lanjut): ").strip().lower()
        if answer != "ya":
            print("\nDibatalkan. device_events TIDAK disentuh.")
            return 0

        # 5. Swap: delete the OLD events per device (EXCEPT the baseline itself, copied
        #    as is -- B3) and write the NEW events.
        for d in devices:
            if d.id not in plan:
                continue
            baseline_old, event_new = plan[d.id]
            (db.query(DeviceEvent)
             .filter(DeviceEvent.device_id == d.id,
                     DeviceEvent.id != baseline_old.id)
             .delete())
            for e in event_new:
                db.add(DeviceEvent(device_id=d.id, **e))
        db.commit()
        print("\nSelesai. device_events sudah dihitung ulang dengan ambang "
              "%dx." % batas)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

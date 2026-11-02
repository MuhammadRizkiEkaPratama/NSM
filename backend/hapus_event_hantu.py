"""Find (and, when asked, delete) outages that were never actually observed.

What a "ghost event" is: an outage is stored as a DOWN row and an UP row in
`device_events`, and the time between them is read as the outage duration. If
NSM stops watching in between (poller stopped or device paused) while an outage
is open, that span includes time nobody observed. Example: a device paused
while DOWN and resumed 13 hours later produced a "13-hour outage" of which only
25 seconds was ever seen.

Deleting is optional. `jeda.py` already cuts unmonitored time out of every
calculation (availability, MTTR, incidents, Excel/Word/PDF exports) without
deleting any row. DOWN/UP rows are the raw record that a ping failed; once
deleted they cannot be restored, so think twice.

What this script deletes: only DOWN+UP pairs with NO failed ping inside their
span, i.e. outages with no evidence at all. Outages with evidence, even 25
seconds, are left alone: the unobserved part is already cut from calculations,
and the observed part really happened.

Rows are deleted in pairs. Deleting only the UP row would leave the device DOWN
forever in the transition record and drop its availability to zero.

Usage:
    py hapus_event_hantu.py            list only, changes nothing
    py hapus_event_hantu.py --hapus    actually delete

Stop the poller and uvicorn before `--hapus`, as with migrations.
"""
import sys
from datetime import datetime, timedelta

from sqlalchemy import text

import jeda
from database import SessionLocal
from models import Device, DeviceEvent, StatusLog
from report_service import format_durasi


def build_outage(db, d):
    """(DOWN event, UP event) pairs for each outage of this device.

    The UP event is None for an outage still in progress; those are never deleted.
    """
    ev = (db.query(DeviceEvent)
          .filter(DeviceEvent.device_id == d.id)
          .order_by(DeviceEvent.timestamp, DeviceEvent.id).all())
    hasil = []
    pending = None
    for e in ev:
        if e.event_type == "DOWN" and pending is None:
            pending = e
        elif e.event_type == "UP" and pending is not None:
            hasil.append((pending, e))
            pending = None
    if pending is not None:
        hasil.append((pending, None))
    return hasil


def ping_gagal_di_dalam(db, device_id, mulai, selesai):
    """Number of failed pings inside the outage span.

    This is the evidence: zero means no observation supports the outage.
    """
    return db.execute(
        text("SELECT COUNT(*) FROM status_logs "
             "WHERE device_id=:d AND timestamp>=:a AND timestamp<=:b "
             "AND is_reachable=0"),
        {"d": device_id, "a": mulai, "b": selesai}).scalar() or 0


def poller_masih_jalan(db):
    """True if a new ping row appeared within the last 20 seconds."""
    last = db.execute(
        text("SELECT MAX(timestamp) FROM status_logs")).scalar()
    if not last:
        return False
    if isinstance(last, str):
        last = datetime.fromisoformat(last)
    return (datetime.now() - last) < timedelta(seconds=20)


def main():
    hapus = "--hapus" in sys.argv
    db = SessionLocal()
    try:
        if hapus and poller_masih_jalan(db):
            print("BERHENTI. Poller masih menulis ke nsm.db (ada baris ping")
            print("kurang dari 20 detik lalu). Matikan poller dan uvicorn")
            print("lebih dulu, lalu jalankan ulang perintah ini.")
            return 1

        print("=" * 74)
        print("GANGGUAN YANG TIDAK PUNYA SATU PUN PING GAGAL SEBAGAI BUKTI")
        print("=" * 74)

        discard = []
        checked = 0
        for d in db.query(Device).order_by(Device.id).all():
            for fall, rise in build_outage(db, d):
                checked += 1
                if rise is None:
                    continue  # still in progress, leave alone
                bukti = ping_gagal_di_dalam(db, d.id, fall.timestamp,
                                            rise.timestamp)
                raw = (rise.timestamp - fall.timestamp).total_seconds()
                tak = jeda.tak_terpantau_antara(db, d.id, fall.timestamp,
                                                rise.timestamp)
                observed = max(0.0, raw - tak)
                if bukti == 0:
                    discard.append((d, fall, rise, raw, tak))
                    print(f"\n  {d.name}  (event {fall.id} + {rise.id})")
                    print(f"    {fall.timestamp:%d %b %H:%M:%S}"
                          f" -> {rise.timestamp:%d %b %H:%M:%S}")
                    print(f"    tercatat  : {format_durasi(round(raw))}")
                    print(f"    diamati   : {format_durasi(round(observed))}")
                    print(f"    ping gagal: {bukti}  <-- tanpa bukti")

        print()
        print("-" * 74)
        print(f"  {checked} gangguan diperiksa, {len(discard)} tanpa bukti.")

        if not discard:
            print("  Tidak ada yang perlu dihapus.")
            print()
            print("  Catatan: gangguan yang durasinya sempat menggelembung")
            print("  karena poller mati atau device dijeda TIDAK muncul di")
            print("  daftar ini selama masih ada ping gagal yang mendukungnya.")
            print("  Angkanya sudah dibereskan tanpa menghapus apa pun, lewat")
            print("  pemotongan waktu tak terpantau di jeda.py.")
            return 0

        if not hapus:
            print()
            print("  Tidak ada yang diubah. Tambahkan --hapus untuk benar-benar")
            print("  menghapus pasangan baris di atas.")
            return 0

        for d, fall, rise, _, _ in discard:
            db.delete(fall)
            db.delete(rise)
        db.commit()
        print(f"  {len(discard) * 2} baris device_events dihapus.")
        print("  Nyalakan lagi poller dan uvicorn.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

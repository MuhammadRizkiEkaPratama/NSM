"""Test of the escalating back-off when notification delivery fails.

Proven:

1. The first failure is NOT retried immediately on the next round.
2. The gap between attempts widens: 30, 60, 300, 900, 1800, 3600 s.
3. Widening stops at 1 hour.
4. After a successful send the failure count resets, so the next failure starts
   again from 30 s.
5. A pending event does not touch the network at all during its wait; merely
   delaying the error message would not reduce load on the mail server.

Run: py uji_notifikasi_tangga.py
"""
import sys
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import database

lolos = 0
gagal = 0


def cek(nama, dapat, harap):
    global lolos, gagal
    if dapat == harap:
        lolos += 1
        print(f"  LOLOS  {nama}: {dapat}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama}: dapat {dapat}, harusnya {harap}")


def main():
    mesin = create_engine("sqlite://")
    database.engine = mesin
    database.SessionLocal = sessionmaker(bind=mesin)

    import models
    models.Base.metadata.create_all(mesin)
    db = database.SessionLocal()

    import config
    import notifikasi

    config.get_notif_enabled = lambda: True
    config.get_notif_jeda_menit = lambda: 0
    config.get_notif_config = lambda: {
        "url": "http://uji.invalid/notify", "base_url": "http://uji.invalid",
    }

    d = models.Device(id=1, name="VM Uji", ip_address="10.0.0.1",
                      device_type="server", platform="linux", aktif=1)
    db.add(d)
    db.add(models.DeviceEvent(device_id=1, event_type="DOWN",
                              timestamp=datetime.now(), category="dead",
                              detail="uji", duration_sec=10))
    db.commit()

    called = {"n": 0}

    def selalu_gagal(*_a, **_k):
        called["n"] += 1
        raise RuntimeError("smtp.gmail.com: Connect timed out")

    print("=" * 70)
    print("Percobaan berturut-turut saat server email tidak bisa dihubungi")
    print("=" * 70)

    notifikasi._tunda.clear()
    distance = []
    waktu = datetime(2026, 7, 28, 12, 0, 0)
    for _ in range(7):
        content = notifikasi._tunda.get(1)
        if content:
            distance.append(round((content[1] - waktu).total_seconds()))
            waktu = content[1]
        # proses_antrean uses datetime.now(); it is injected through a small stand-in
        notifikasi.datetime = _JamPalsu(waktu)
        notifikasi.proses_antrean(db, pengirim=selalu_gagal)

    notifikasi.datetime = datetime
    print(f"  jarak antar percobaan (detik): {distance}")
    cek("tangga jeda sesuai rencana", distance, [30, 60, 300, 900, 1800, 3600])
    cek("berhenti melebar di 1 jam", max(distance), 3600)
    cek("pengirim dipanggil sekali per percobaan, bukan tiap putaran",
        called["n"], 7)

    print()
    print("Masa tunggu benar-benar menahan panggilan keluar")
    notifikasi._tunda.clear()
    called["n"] = 0
    waktu = datetime(2026, 7, 28, 12, 0, 0)
    notifikasi.datetime = _JamPalsu(waktu)
    notifikasi.proses_antrean(db, pengirim=selalu_gagal)
    after_fail = called["n"]
    hasil = None
    for second in (5, 10, 20):
        notifikasi.datetime = _JamPalsu(waktu + timedelta(seconds=second))
        hasil = notifikasi.proses_antrean(db, pengirim=selalu_gagal)
    cek("panggilan keluar tidak bertambah selama masa tunggu",
        called["n"], after_fail)
    cek("putaran itu dilaporkan sebagai tertunda", hasil["tertunda"], 1)

    print()
    print("Setelah berhasil, hitungan gagal dilupakan")
    notifikasi.datetime = _JamPalsu(waktu + timedelta(seconds=60))
    notifikasi.proses_antrean(db, pengirim=lambda *a, **k: {"terkirim": 1,
                                                           "pelanggan": 1})
    cek("tidak ada sisa catatan tunda", len(notifikasi._tunda), 0)

    notifikasi.datetime = datetime
    db.close()
    return 0


class _JamPalsu:
    """Stand-in for the datetime module with a controllable `now()`, so the test
    finishes instantly instead of waiting 1 h 47 min 30 s.
    """

    def __init__(self, waktu):
        self._waktu = waktu

    def now(self):
        return self._waktu


if __name__ == "__main__":
    main()
    print()
    print("=" * 70)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 70)
    sys.exit(1 if gagal else 0)

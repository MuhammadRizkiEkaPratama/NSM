"""Test: a silent ping does not mean the machine is dead.

A real host did not answer ping 82 times out of 82 while its port 22 answered 12
of 14 times in 21 to 53 ms. NSM still declared it DOWN and counted the time
against availability, even though it already ran the port check and categorized
the event `ping_blocked` ("device probably ALIVE, ICMP blocked").

Guarded, number 2 being the most important since it guards the opposite direction:

1. Ping fails + port answers -> device stays **UP**, `sumber="tcp"`.
2. Ping fails + port does NOT answer -> device stays **DOWN**. The fix must not
   make a truly dead device look alive.
3. A single lost ping (below threshold) triggers no port check at all, otherwise
   every network blip would cost a one-second port check per device.
4. Ping succeeds -> `sumber="icmp"`, and no port check runs.
5. The check result expires: a device reachable by TCP that then truly dies must
   be noticed once the validity ends.
6. Recovery over TCP is recorded with category `ping_blocked`, not "recovered"
   with "back to answering ping", which would be false for a device that never answers ping.

Run: py uji_ping_diblokir.py
"""
import sys
from datetime import datetime, timedelta

# `poller` and `report_service` now only forward; the logic lives in
# `nsm/pemantau/*` and `report_service/*`. Setting `poller.nama = fake` has no
# effect, so `tambal()` patches the module that actually owns the name. See
# `bantu_tambal.py`.
from bantu_tambal import patch

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
    print("Ping diam bukan berarti mesinnya mati")
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

    import poller

    # The port check is replaced by a fake. Tested is the poller's decision on its
    # result and how often it bothers to ask, not TCP connectivity.
    original_check_port = poller.cek_port_terbuka
    panggilan = {"n": 0}
    jawaban = {"ports": [22]}

    def cek_port_tiruan(ip, ports, timeout=1.0):
        panggilan["n"] += 1
        return list(jawaban["ports"])

    patch("cek_port_terbuka", cek_port_tiruan)

    try:
        d = models.Device(id=1, name="VM Uji", ip_address="192.168.56.101",
                          device_type="server", platform="linux", aktif=1)
        db.add(d)
        db.commit()

        limit = poller.get_down_threshold()
        print(f"\n(ambang DOWN = {limit} gagal beruntun)")

        def bersihkan():
            poller.gagal_beruntun.clear()
            poller.tcp_terjangkau_sampai.clear()
            poller.tcp_periksa_lagi_pada.clear()
            panggilan["n"] = 0

        # ------------------------------------------------------------------
        print("\n-- 1. ping berhasil: sumber icmp, port tidak pernah dicek --")
        bersihkan()
        alive, rtt = poller.periksa_device(db, d, hasil_ping=(True, 1.5))
        db.commit()
        line = db.query(models.StatusLog).order_by(models.StatusLog.id.desc()).first()
        cek("device UP", alive, True)
        cek("sumber", line.sumber, "icmp")
        cek("pemeriksaan port tidak dijalankan", panggilan["n"], 0)

        # ------------------------------------------------------------------
        print("\n-- 2. satu ping hilang, belum mencapai ambang: port tidak dicek --")
        bersihkan()
        poller.periksa_device(db, d, hasil_ping=(False, None))
        db.commit()
        cek_benar("port belum dicek karena ambang belum tercapai",
                  panggilan["n"] == 0,
                  f"(dipanggil {panggilan['n']} kali)")

        # ------------------------------------------------------------------
        print("\n-- 3. ping diam terus + port MENJAWAB: tetap UP, sumber tcp --")
        bersihkan()
        jawaban["ports"] = [22]
        for _ in range(limit):
            alive, rtt = poller.periksa_device(db, d, hasil_ping=(False, None))
            db.commit()
        line = db.query(models.StatusLog).order_by(models.StatusLog.id.desc()).first()
        cek("device tetap dianggap UP", alive, True)
        cek("sumber", line.sumber, "tcp")
        cek("is_reachable ikut True", bool(line.is_reachable), True)
        cek("waktu jawab kosong (tidak ada RTT ICMP)", line.response_time_ms, None)
        cek_benar("tidak ada event DOWN yang ditulis",
                  db.query(models.DeviceEvent)
                    .filter(models.DeviceEvent.event_type == "DOWN").count() == 0,
                  "(device yang portnya menjawab tidak boleh dicatat mati)")

        # ------------------------------------------------------------------
        print("\n-- 4. pemeriksaan tidak diulang tiap putaran (hemat) --")
        n_before = panggilan["n"]
        for _ in range(5):
            poller.periksa_device(db, d, hasil_ping=(False, None))
            db.commit()
        cek("lima putaran tambahan, pemeriksaan port bertambah",
            panggilan["n"] - n_before, 0)

        # ------------------------------------------------------------------
        print("\n-- 5. PENJAGA ARAH SEBALIKNYA: port diam juga -> tetap DOWN --")
        bersihkan()
        db.query(models.DeviceEvent).delete()
        db.query(models.StatusLog).delete()
        db.commit()
        jawaban["ports"] = []
        poller.periksa_device(db, d, hasil_ping=(True, 1.0))   # baseline UP
        db.commit()
        for _ in range(limit):
            alive, rtt = poller.periksa_device(db, d, hasil_ping=(False, None))
            db.commit()
        line = db.query(models.StatusLog).order_by(models.StatusLog.id.desc()).first()
        cek("device yang benar-benar mati tetap DOWN", alive, False)
        cek("sumber tetap icmp", line.sumber, "icmp")
        ev = (db.query(models.DeviceEvent)
              .filter(models.DeviceEvent.event_type == "DOWN").first())
        cek_benar("event DOWN tertulis", ev is not None)
        if ev:
            cek("kategorinya 'dead'", ev.category, "dead")

        # ------------------------------------------------------------------
        print("\n-- 6. pemulihan lewat TCP dicatat sebagai ping_blocked --")
        poller.tcp_periksa_lagi_pada.clear()
        poller.tcp_terjangkau_sampai.clear()
        jawaban["ports"] = [22]
        alive, rtt = poller.periksa_device(db, d, hasil_ping=(False, None))
        db.commit()
        cek("device kembali dianggap UP", alive, True)
        ev = (db.query(models.DeviceEvent)
              .filter(models.DeviceEvent.event_type == "UP")
              .order_by(models.DeviceEvent.id.desc()).first())
        cek_benar("event UP tertulis", ev is not None)
        if ev:
            cek("kategorinya ping_blocked, bukan recovered", ev.category, "ping_blocked")
            cek_benar("detailnya TIDAK mengaku device membalas ping",
                      "kembali membalas ping" not in (ev.detail or ""),
                      f"(detail: {ev.detail})")
            cek_benar("detailnya menyebut ICMP diblokir",
                      "ICMP" in (ev.detail or ""),
                      f"(detail: {ev.detail})")

        # ------------------------------------------------------------------
        print("\n-- 7. masa berlaku habis: device yang lalu mati ketahuan lagi --")
        # Validity forced to expire, as if JEDA_PROBE_TCP seconds had passed.
        poller.tcp_terjangkau_sampai[d.id] = 0
        poller.tcp_periksa_lagi_pada[d.id] = 0
        jawaban["ports"] = []
        alive, rtt = poller.periksa_device(db, d, hasil_ping=(False, None))
        db.commit()
        cek("setelah masa berlaku habis dan port diam, device jadi DOWN",
            alive, False)
        ev = (db.query(models.DeviceEvent)
              .order_by(models.DeviceEvent.id.desc()).first())
        cek("event terakhir DOWN", ev.event_type, "DOWN")
        cek("kategorinya dead", ev.category, "dead")

    finally:
        patch("cek_port_terbuka", original_check_port)
        poller.gagal_beruntun.clear()
        poller.tcp_terjangkau_sampai.clear()
        poller.tcp_periksa_lagi_pada.clear()
        db.close()
        database.engine, database.SessionLocal = original_engine, original_session


if __name__ == "__main__":
    uji()
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

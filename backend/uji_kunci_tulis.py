"""Prove or refute the suspected cause of the poller skipping ping rounds.

Hypothesis: each poller job uses one session opened at the start and committed
only at the END, after all devices are processed, with slow network work in
between (SSH, SNMP, access-log reads). Under SQLAlchemy, a new row followed by
another query triggers autoflush, which turns the SQLite transaction into a
write and holds the write lock until commit. A ping job needing to write six
rows then waits up to `busy_timeout=15000` ms, and the poller reports
`poll_all skipped: maximum number of running instances reached`.

Two tests run on a temporary database, not `nsm.db`:

1. Current pattern: one session adds a row, queries (autoflush), does 3 s of
   "network work", then commits. A second session tries to write midway and
   its wait is measured.
2. Fixed pattern: same, but committing after each device.

If the hypothesis holds, test 1 blocks for about 3 s and test 2 for almost none.

Run: py uji_kunci_tulis.py
"""
import os
import sys
import tempfile
import threading
import time

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

# `poller` and `report_service` now only forward; the logic lives in
# `nsm/pemantau/*` and `report_service/*`. Setting `poller.nama = fake` has no
# effect, so `tambal()` patches the module that actually owns the name. See
# `bantu_tambal.py`.
from bantu_tambal import patch

lolos = 0
gagal = 0

KERJA_JARINGAN_DETIK = 3.0


def cek(nama, ok, ket=""):
    global lolos, gagal
    if ok:
        lolos += 1
        print(f"  LOLOS  {nama} {ket}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama} {ket}")


def buat_mesin(jalur):
    mesin = create_engine(f"sqlite:///{jalur}", connect_args={"timeout": 15})

    @event.listens_for(mesin, "connect")
    def _atur(sambungan, _c):
        k = sambungan.cursor()
        k.execute("PRAGMA journal_mode=WAL")
        k.execute("PRAGMA busy_timeout=15000")
        k.execute("PRAGMA synchronous=NORMAL")
        k.close()

    return mesin


JUMLAH_DEVICE = 3


def jalankan(jalur, commit_tiap_device):
    """Return how many seconds the second writer was held waiting for its turn."""
    mesin = buat_mesin(jalur)
    session = sessionmaker(bind=mesin)

    with mesin.connect() as s:
        s.exec_driver_sql("CREATE TABLE IF NOT EXISTS sampel "
                          "(id INTEGER PRIMARY KEY, nilai INTEGER)")
        s.exec_driver_sql("CREATE TABLE IF NOT EXISTS ping "
                          "(id INTEGER PRIMARY KEY, nilai INTEGER)")
        s.commit()

    mulai_pengumpul = threading.Event()
    held = {}

    def pengumpul():
        """Imitate poll_bandwidth, with the same ORDER as the real code: per device, network
        work comes first, then the write. So the write lock opened at device 1 is held
        through the network work of the later devices until the final commit.
        """
        db = session()
        try:
            for i in range(JUMLAH_DEVICE):
                if i == 1:
                    mulai_pengumpul.set()
                time.sleep(KERJA_JARINGAN_DETIK / JUMLAH_DEVICE)   # SSH / SNMP
                db.execute(text("INSERT INTO sampel(nilai) VALUES(:v)"), {"v": i})
                db.execute(text("SELECT COUNT(*) FROM sampel")).scalar()
                if commit_tiap_device:
                    db.commit()
            db.commit()
        finally:
            db.close()

    def penulis_ping():
        """Imitate poll_all: six small rows that should finish instantly."""
        mulai_pengumpul.wait()
        time.sleep(KERJA_JARINGAN_DETIK / JUMLAH_DEVICE * 0.5)
        db = session()
        t0 = time.perf_counter()
        try:
            for i in range(6):
                db.execute(text("INSERT INTO ping(nilai) VALUES(:v)"), {"v": i})
            db.commit()
            held["detik"] = time.perf_counter() - t0
        except Exception as e:
            held["detik"] = time.perf_counter() - t0
            held["galat"] = str(e)
        finally:
            db.close()

    a = threading.Thread(target=pengumpul)
    b = threading.Thread(target=penulis_ping)
    a.start(); b.start()
    a.join(); b.join()
    mesin.dispose()
    return held


def uji_periksa_device_sungguhan(folder):
    """Test against the real `periksa_device()`, not an imitation.

    While `cek_port_terbuka()` tries three TCP ports (up to three seconds), can
    another process still write to the database? Before the order in
    `periksa_device()` was changed, it could not: the status_logs row was added
    first, the next query triggered autoflush, and the write lock was held
    throughout the port attempts.
    """
    jalur = os.path.join(folder, "periksa.db")
    mesin = buat_mesin(jalur)
    session = sessionmaker(bind=mesin)

    import database
    database.engine = mesin
    database.SessionLocal = session
    import models
    models.Base.metadata.create_all(mesin)

    import poller
    import connectors.icmp as icmp

    db = session()
    d = models.Device(id=1, name="Device Uji", ip_address="192.0.2.1",
                      device_type="server", platform="linux", aktif=1)
    db.add(d)
    db.add(models.DeviceEvent(device_id=1, event_type="UP",
                              timestamp=__import__("datetime").datetime.now(),
                              category="baseline", detail="uji"))
    db.commit()

    icmp.IcmpConnector.check_reachable = lambda self: (False, None)
    poller.IcmpConnector.check_reachable = lambda self: (False, None)

    held = {}

    def port_lambat(ip, ports, timeout=1.0):
        """Replaces cek_port_terbuka: imitates its duration, then measures."""
        db2 = session()
        t0 = time.perf_counter()
        try:
            db2.execute(text("INSERT INTO status_logs"
                             "(device_id,timestamp,is_reachable,response_time_ms)"
                             " VALUES(1,'2026-01-01 00:00:00',1,1.0)"))
            db2.commit()
            held["detik"] = time.perf_counter() - t0
        except Exception as e:
            held["detik"] = time.perf_counter() - t0
            held["galat"] = str(e)
        finally:
            db2.close()
        time.sleep(1.0)
        return []

    patch("cek_port_terbuka", port_lambat)

    # The port check runs only after consecutive failures reach the DOWN threshold
    # (`gagal_beruntun[d.id] >= batas`), so the call count is read from the current
    # threshold rather than hard-coded; a fixed number silently goes stale.
    limit = poller.get_down_threshold()
    for _ in range(limit):
        poller.periksa_device(db, d)
        db.commit()
    db.close()
    mesin.dispose()
    if "detik" not in held:
        held["detik"] = float("nan")
        held["galat"] = (
            "cek_port_terbuka tidak pernah terpanggil sesudah %d kali gagal "
            "beruntun -- ambang DOWN atau syarat perlu_probe_tcp() mungkin "
            "berubah lagi" % limit)
    return held


def main():
    folder = tempfile.mkdtemp(prefix="nsm-kunci-")
    print("=" * 74)
    print("Berapa lama job ping tertahan menunggu job pengumpul selesai?")
    print("=" * 74)
    print(f"  Kerja jaringan yang ditiru: {KERJA_JARINGAN_DETIK:.1f} detik")
    print()

    a = jalankan(os.path.join(folder, "sekarang.db"), commit_tiap_device=False)
    print(f"  POLA SEKARANG   (commit sekali di akhir) : "
          f"ping tertahan {a['detik']:.2f} detik" +
          (f"  GALAT: {a['galat']}" if "galat" in a else ""))

    b = jalankan(os.path.join(folder, "perbaikan.db"), commit_tiap_device=True)
    print(f"  POLA PERBAIKAN  (commit tiap device)     : "
          f"ping tertahan {b['detik']:.2f} detik" +
          (f"  GALAT: {b['galat']}" if "galat" in b else ""))
    print()

    # The threshold is derived from the simulated network work: if the lock is held
    # throughout, the wait must approach half of the remaining work.
    cek("pola sekarang MEMANG menahan job ping",
        a["detik"] > KERJA_JARINGAN_DETIK * 0.4,
        f"({a['detik']:.2f} dtk, jauh di atas nol)")
    cek("commit tiap device menghilangkan penantian itu",
        b["detik"] < 0.5, f"({b['detik']:.2f} dtk)")
    cek("perbaikannya berarti, bukan selisih derau",
        a["detik"] > b["detik"] * 5,
        f"({a['detik']:.2f} dtk vs {b['detik']:.2f} dtk)")

    print()
    print("=" * 74)
    print("Uji pada periksa_device() yang ASLI, saat sedang mencoba port TCP")
    print("=" * 74)
    c = uji_periksa_device_sungguhan(folder)
    print(f"  penulis lain tertahan {c['detik']:.2f} detik" +
          (f"  GALAT: {c['galat']}" if "galat" in c else ""))
    print()
    cek("basis data tetap bisa ditulis selagi port sedang dicoba",
        "galat" not in c and c["detik"] < 0.5, f"({c['detik']:.2f} dtk)")

    for f in os.listdir(folder):
        try:
            os.remove(os.path.join(folder, f))
        except OSError:
            pass
    try:
        os.rmdir(folder)
    except OSError:
        pass


if __name__ == "__main__":
    main()
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

"""Test of batched ping checks: must be faster AND still correct.

Fast is easy; fast without changing the meaning of the data is the hard part, so
this tests correctness more than speed:

1. `ping_banyak()` returns a result per address, duplicates not doubled.
2. `periksa_device()` given a batch result writes the SAME `status_logs` row as
   when it pings itself.
3. Devices with platform "lokal" are not batched (read via psutil locally).
4. PAUSED devices are still not checked at all.
5. If the batch ping fails entirely, the round does NOT die.
6. `cek_port_terbuka()` still returns ports in the requested order, not the
   order they answered.

Numbers 5 and 6 are the easiest to break unnoticed.

Run: py uji_ping_paralel.py
"""
import sys
import time
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


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print(f"  LOLOS  {nama}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama} {ket}")


def uji():
    print("=" * 74)
    print("Pemeriksaan ping borongan")
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
    from connectors.icmp import ping_banyak
    from connectors.tcp import cek_port_terbuka

    # --- 1. ping_banyak: bentuk hasilnya -------------------------------
    print("\n1. ping_banyak mengembalikan hasil untuk tiap alamat")
    down = ["192.168.56.200", "192.168.56.201", "192.168.56.202"]
    peta = ping_banyak(down)
    cek("jumlah hasil sama dengan jumlah alamat", len(peta), 3)
    benar("semua alamat ada di hasil",
          all(ip in peta for ip in down),
          f"-> yang ada: {list(peta)}")
    benar("alamat yang tidak ada mesinnya dilaporkan mati",
          all(peta[ip][0] is False for ip in down),
          f"-> {peta}")

    print("\n   alamat kembar tidak digandakan")
    peta2 = ping_banyak(["192.168.56.200", "192.168.56.200", "192.168.56.201"])
    cek("dua alamat unik dari tiga masukan", len(peta2), 2)

    cek("daftar kosong dijawab peta kosong", ping_banyak([]), {})

    # 2. batch result == single-ping result
    print("\n2. periksa_device dengan hasil borongan menulis hal yang sama")
    d1 = models.Device(id=1, name="Uji borongan", ip_address="192.168.56.203",
                       device_type="server", platform="linux", aktif=1)
    d2 = models.Device(id=2, name="Uji satuan", ip_address="192.168.56.204",
                       device_type="server", platform="linux", aktif=1)
    db.add_all([d1, d2])
    db.commit()

    alive1, rtt1 = poller.periksa_device(db, d1, hasil_ping=(False, None))
    db.commit()
    alive2, rtt2 = poller.periksa_device(db, d2)
    db.commit()

    cek("keduanya menyimpulkan DOWN", (alive1, alive2), (False, False))
    b1 = db.query(models.StatusLog).filter(models.StatusLog.device_id == 1).all()
    b2 = db.query(models.StatusLog).filter(models.StatusLog.device_id == 2).all()
    cek("sama-sama menulis satu baris status_logs", (len(b1), len(b2)), (1, 1))
    cek("isi kolom is_reachable sama",
        (b1[0].is_reachable, b2[0].is_reachable), (False, False))

    e1 = db.query(models.DeviceEvent).filter(models.DeviceEvent.device_id == 1).all()
    e2 = db.query(models.DeviceEvent).filter(models.DeviceEvent.device_id == 2).all()
    cek("sama-sama menulis satu baris baseline", (len(e1), len(e2)), (1, 1))
    cek("kategori baseline sama", (e1[0].category, e2[0].category),
        ("baseline", "baseline"))

    # 3. local device is not batched
    print("\n3. device lokal dibaca lewat mesin ini, bukan lewat jaringan")
    called = {"borongan": None}
    original_ping_many = poller.ping_banyak

    def rekam(daftar):
        called["borongan"] = list(daftar)
        return original_ping_many(daftar)

    patch("ping_banyak", rekam)
    db.add(models.Device(id=3, name="Mesin ini", ip_address="127.0.0.1",
                         device_type="pc", platform="lokal", aktif=1))
    db.add(models.Device(id=4, name="Sedang dijeda", ip_address="192.168.56.205",
                         device_type="server", platform="linux", aktif=0))
    db.commit()

    poller.poll_all()
    patch("ping_banyak", original_ping_many)

    diborongkan = called["borongan"] or []
    benar("alamat device lokal TIDAK ikut diborongkan",
          "127.0.0.1" not in diborongkan, f"-> {diborongkan}")
    benar("alamat device yang dijeda TIDAK ikut diborongkan",
          "192.168.56.205" not in diborongkan, f"-> {diborongkan}")
    benar("device jauh yang aktif ikut diborongkan",
          "192.168.56.203" in diborongkan and "192.168.56.204" in diborongkan,
          f"-> {diborongkan}")

    # 4. paused device produces no row
    print("\n4. device yang dijeda tidak meninggalkan jejak")
    cek("tidak ada status_logs untuk device dijeda",
        db.query(models.StatusLog).filter(
            models.StatusLog.device_id == 4).count(), 0)
    cek("tidak ada device_events untuk device dijeda",
        db.query(models.DeviceEvent).filter(
            models.DeviceEvent.device_id == 4).count(), 0)

    # 5. a failed batch ping does not stop the round
    print("\n5. ping borongan gagal seluruhnya, putaran tidak ikut mati")

    def selalu_meledak(daftar):
        raise OSError("soket ICMP ditolak sistem (disengaja, ini uji)")

    before = db.query(models.StatusLog).count()
    patch("ping_banyak", selalu_meledak)
    try:
        poller.poll_all()
        not_raises = True
    except Exception as e:
        not_raises = False
        print(f"       melempar: {e}")
    finally:
        patch("ping_banyak", original_ping_many)

    benar("poll_all tidak melempar walau ping borongan gagal", not_raises)
    after = db.query(models.StatusLog).count()
    benar("device tetap diperiksa lewat jalur satuan",
          after > before,
          f"-> baris bertambah {after - before}, harusnya lebih dari 0")

    # 6. port order is unchanged
    print("\n6. cek_port_terbuka mengembalikan urutan yang diminta")
    # All ports on a dead address are closed, so the result is an empty list; the shape is tested, not the content.
    cek("alamat mati -> tidak ada port terbuka",
        cek_port_terbuka("192.168.56.206", [22, 80, 443]), [])
    cek("daftar port kosong -> hasil kosong",
        cek_port_terbuka("192.168.56.206", []), [])

    import connectors.tcp as tcp
    original_tcp = tcp.TcpConnector

    class TcpPalsu:
        def __init__(self, ip_address, port=22, timeout=1.0):
            self.port = port

        def check_reachable(self):
            # The larger port deliberately answers slowest, so a result order that follows the
            # fastest responder would fail the test.
            time.sleep(0.05 if self.port == 443 else 0.01)
            return True, 1.0

    tcp.TcpConnector = TcpPalsu
    try:
        hasil = tcp.cek_port_terbuka("10.0.0.1", [443, 22, 80])
    finally:
        tcp.TcpConnector = original_tcp
    cek("urutan mengikuti daftar yang diminta, bukan siapa tercepat",
        hasil, [443, 22, 80])

    db.close()
    database.engine, database.SessionLocal = original_engine, original_session



# =============================================================================
print()
print("=" * 74)
print("SETELAN PING TIDAK BOLEH KEMBALI KE SATU PAKET")
print("   Regresi nyata 22 Agustus 2026: `count=1, timeout=1` membuat")
print("   Lokasi B hidup-mati-hidup-mati sepanjang hari untuk perangkat")
print("   yang tidak pernah benar-benar mati.")
print("=" * 74)

from connectors import icmp as _icmp  # noqa: E402

benar("mengirim LEBIH DARI SATU paket per pemeriksaan "
      "(SmokePing menolak kurang dari 3)",
      _icmp.COUNT >= 3, "-> COUNT=%r" % _icmp.COUNT)
benar("batas waktu cukup untuk jalur berlatensi tinggi "
      "(p99 LDAP terukur 844 ms)",
      _icmp.TIMEOUT >= 2, "-> TIMEOUT=%r" % _icmp.TIMEOUT)
benar("jeda antar-paket ada dan singkat -- tiga paket sekaligus bisa "
      "terbaca seperti lonjakan, tiga paket berjarak 1 detik terlalu lambat",
      0 < getattr(_icmp, "INTERVAL", 0) <= 0.5,
      "-> INTERVAL=%r" % getattr(_icmp, "INTERVAL", None))

# Single and batch checks MUST use the same settings; two definitions of "down" in
# one product is a defect found long after the numbers are used (see the comment
# at the top of `connectors/icmp.py`).
import inspect  # noqa: E402

sumber = inspect.getsource(_icmp)
for setelan in ("count=COUNT", "timeout=TIMEOUT", "interval=INTERVAL"):
    benar("`%s` dipakai di KEDUA jalur (satuan dan borongan)" % setelan,
          sumber.count(setelan) >= 2,
          "-> ditemukan %d kali" % sumber.count(setelan))

if __name__ == "__main__":
    uji()
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

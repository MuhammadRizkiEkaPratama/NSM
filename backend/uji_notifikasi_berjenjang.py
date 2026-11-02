"""Test of `notifikasi_berjenjang.py`: the evaluation logic of the THREE rules,
with an in-memory SQLite database (no MySQL, no real email).

In-memory SQLite is used instead of mocks because the module queries
`status_logs`/`device_events` with raw SQL (COUNT, SUM CASE WHEN); mocked results
would make the test "already know the answer".

When the "down" email actually goes out: the evaluation window always looks back
15 minutes from now, so if a device starts going down exactly at a round, the
window at round 4 (minute 15) still touches a little healthy time before it.
The email therefore goes out at round 5 (minute 20), an honest consequence of
requiring continuous down time, not a bug. See `3. ROUNDS 4-5` below.

Run: py uji_notifikasi_berjenjang.py
"""
import os
import sys
from datetime import datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

lolos = 0
gagal_n = 0


def benar(nama, syarat, ket=""):
    global lolos, gagal_n
    if syarat:
        lolos += 1
        print("  LOLOS  %s" % nama)
    else:
        gagal_n += 1
        print("  GAGAL  %s %s" % (nama, ket))


# Throwaway SQLite database, schema EXACTLY as in models.py
import models  # noqa: E402 -- perlu sys.path di atas dulu
import config  # noqa: E402
import notifikasi_berjenjang as nb  # noqa: E402

engine = create_engine("sqlite:///:memory:")
models.Base.metadata.create_all(engine)
Sesi = sessionmaker(bind=engine)
db = Sesi()

T0 = datetime(2026, 8, 20, 0, 0, 0)


def menit(n):
    return T0 + timedelta(minutes=n)


def buat_device(id_, nama):
    db.execute(text(
        "INSERT INTO devices (id, name, ip_address, device_type, username, "
        "password, location, aktif) VALUES (:id, :nama, '10.0.0.%s', 'linux', "
        "'x', 'x', 'Lab', 1)" % id_
    ), {"id": id_, "nama": nama})


def isi_ping(device_id, dari_menit, sampai_menit, ok):
    """Fill one ping EVERY MINUTE (not every 10 s); test data is scaled down and
    `sampel_min` is reduced in each test accordingly.
    """
    for m in range(dari_menit, sampai_menit + 1):
        db.execute(text(
            "INSERT INTO status_logs (device_id, timestamp, is_reachable) "
            "VALUES (:did, :t, :ok)"
        ), {"did": device_id, "t": menit(m), "ok": 1 if ok else 0})


def add_event(device_id, m, jenis):
    db.execute(text(
        "INSERT INTO device_events (device_id, event_type, timestamp) "
        "VALUES (:did, :jenis, :t)"
    ), {"did": device_id, "jenis": jenis, "t": menit(m)})


db.commit()

# ---------------------------------------------------------------------------
print("1. SAMPEL KURANG (§6.3): poller mati TIDAK boleh terbaca 'semua mati'")

buat_device(1, "Uji Sampel Kurang")
db.commit()
isi_ping(1, 0, 1, ok=False)
db.commit()

status = nb._down_terus_penuh(db, 1, menit(15), menit=15, sampel_min=30)
benar("sampel kurang dari ambang -> None (dilewati, BUKAN dianggap mati)",
      status is None, "-> %r" % status)

# ---------------------------------------------------------------------------
print("\n2. DOWN TERUS PENUH vs ADA YANG PULIH (fungsi inti, jendela eksplisit)")

buat_device(2, "Uji Down Penuh")
db.commit()
isi_ping(2, 0, 15, ok=False)
db.commit()
status2 = nb._down_terus_penuh(db, 2, menit(15), menit=15, sampel_min=10)
benar("down terus 16 baris tanpa satu pun berhasil -> True",
      status2 is True, "-> %r" % status2)

buat_device(3, "Uji Ada Pulih")
db.commit()
isi_ping(3, 0, 6, ok=False)
isi_ping(3, 7, 7, ok=True)
isi_ping(3, 8, 15, ok=False)
db.commit()
status3 = nb._down_terus_penuh(db, 3, menit(15), menit=15, sampel_min=10)
benar("SATU ping berhasil di tengah jendela -> False (hangus, bukan mati)",
      status3 is False, "-> %r" % status3)

# ---------------------------------------------------------------------------
print("\n3. PUTARAN 4 vs 5 -- kapan email 'mati' BENAR-BENAR keluar")
print("   (lihat docstring berkas ini: kontinu = putaran ke-5, bukan ke-4)")

# Monkeypatch config so `nilai_semua()` uses test parameters: 5/3 as by default,
# but a smaller `sampel_min` since test data has 1 row/minute instead of 6.
asli = {
    "menit": config.get_notif_putaran_menit,
    "butuh": config.get_notif_putaran_butuh,
    "sampel": config.get_notif_sampel_min,
    "flap": config.get_notif_flap_ambang,
    "tenang": config.get_notif_flap_tenang_jam,
}
config.get_notif_putaran_menit = lambda: 5
config.get_notif_putaran_butuh = lambda: 3
config.get_notif_sampel_min = lambda: 10
config.get_notif_flap_ambang = lambda: 999
config.get_notif_flap_tenang_jam = lambda: 6

try:
    # Devices 2 and 3 from part 2 are deactivated because `nilai_semua()` evaluates ALL active devices.
    db.execute(text("UPDATE devices SET aktif = 0 WHERE id IN (2, 3)"))

    buat_device(4, "File Server")
    buat_device(5, "Data Server")  # down STARTS at minute 5, never recovers (here)
    db.commit()
    isi_ping(4, 0, 9, ok=False)
    isi_ping(4, 10, 40, ok=True)
    isi_ping(5, -10, 4, ok=True)
    isi_ping(5, 5, 24, ok=False)
    db.commit()

    hasil_t15 = nb.nilai_semua(db, sekarang=menit(15))
    mati_t15 = {d.name for d in hasil_t15["mati"]}
    benar("putaran ke-4 (menit 15): File Server TIDAK pernah masuk 'mati'",
          "File Server" not in mati_t15, "-> %r" % mati_t15)
    benar("putaran ke-4 (menit 15): Data Server BELUM masuk 'mati' "
          "(baru down 10 menit, jendela masih menyentuh saat ia sehat)",
          "Data Server" not in mati_t15, "-> %r" % mati_t15)

    hasil_t20 = nb.nilai_semua(db, sekarang=menit(20))
    mati_t20 = {d.name for d in hasil_t20["mati"]}
    benar("putaran ke-5 (menit 20): Data Server SEKARANG masuk 'mati' "
          "(down genap 15 menit penuh, jendela [5,20] semuanya gagal)",
          "Data Server" in mati_t20, "-> %r" % mati_t20)
    benar("putaran ke-5 (menit 20): File Server TETAP tidak pernah 'mati'",
          "File Server" not in mati_t20, "-> %r" % mati_t20)

    # Simulate sending via `proses()`, then test RECOVERY
    dikirim_ids = []
    def pengirim_tiruan(cfg, subjek, isi, ids):
        dikirim_ids.append((subjek, list(ids)))
        return {"terkirim": 1}

    ringkasan = nb.proses(db, pengirim=pengirim_tiruan, sekarang=menit(20))
    benar("proses() mengirim TEPAT 1 email 'mati' (bukan 1 per device)",
          ringkasan["mati"] == 1 and len(dikirim_ids) == 1,
          "-> ringkasan=%r dikirim=%r" % (ringkasan, dikirim_ids))

    d5 = db.query(models.Device).filter(models.Device.id == 5).first()
    benar("notif_mati_dikirim tercatat untuk Data Server setelah dikirim",
          d5.notif_mati_dikirim is not None)

    # Now the Data Server recovers at minute 25.
    isi_ping(5, 25, 40, ok=True)
    db.commit()
    dikirim_ids.clear()
    ringkasan2 = nb.proses(db, pengirim=pengirim_tiruan, sekarang=menit(40))
    benar("Data Server yang PERNAH dikirimi mati -> dapat email PULIH",
          ringkasan2["pulih"] == 1, "-> %r" % ringkasan2)
    d5b = db.query(models.Device).filter(models.Device.id == 5).first()
    benar("notif_mati_dikirim dikosongkan lagi setelah PULIH dikirim",
          d5b.notif_mati_dikirim is None)

    semua_subjek = " ".join(subjek for subjek, _ids in dikirim_ids)
    benar("File Server (tidak pernah dikirimi mati) TIDAK pernah dikirimi "
          "pulih juga", "File Server" not in semua_subjek,
          "-> %r" % semua_subjek)
finally:
    config.get_notif_putaran_menit = asli["menit"]
    config.get_notif_putaran_butuh = asli["butuh"]
    config.get_notif_sampel_min = asli["sampel"]
    config.get_notif_flap_ambang = asli["flap"]
    config.get_notif_flap_tenang_jam = asli["tenang"]

# ---------------------------------------------------------------------------
print("\n4. FLAP (§4.5): device kedip-kedip -- tidak pernah 15 menit penuh, "
      "tapi jelas bermasalah")

buat_device(6, "Kedip Cepat")
db.commit()
# Never down for a full 15 minutes (so the 'down' rule never applies), but DOWN
# events in `device_events` recur every 5 minutes THROUGHOUT the test range, so
# the flap threshold is still met at later points. This makes the quiet-period
# test exercise only the QUIET GATE.
for m in range(1, 500, 5):
    add_event(6, m, "DOWN")
db.commit()

jumlah = nb._hitung_down_1jam(db, 6, menit(60))
benar("12 kejadian DOWN dalam 1 jam terhitung benar", jumlah == 12,
      "-> %d" % jumlah)

asli2 = config.get_notif_flap_ambang, config.get_notif_flap_tenang_jam
config.get_notif_flap_ambang = lambda: 10
config.get_notif_flap_tenang_jam = lambda: 6
try:
    hasil_flap = nb.nilai_semua(db, sekarang=menit(60))
    nama_flap = {d.name for d in hasil_flap["flap"]}
    benar(">=10 kejadian/jam -> masuk daftar 'flap'",
          "Kedip Cepat" in nama_flap, "-> %r" % nama_flap)

    d6 = db.query(models.Device).filter(models.Device.id == 6).first()
    d6.notif_flap_dikirim = menit(60)
    db.commit()
    hasil_flap2 = nb.nilai_semua(db, sekarang=menit(90))
    nama_flap2 = {d.name for d in hasil_flap2["flap"]}
    benar("sudah pernah dikirim, BELUM tenang 6 jam -> tidak diulang",
          "Kedip Cepat" not in nama_flap2, "-> %r" % nama_flap2)

    hasil_flap3 = nb.nilai_semua(db, sekarang=menit(60 + 6 * 60 + 1))
    nama_flap3 = {d.name for d in hasil_flap3["flap"]}
    benar("sudah tenang > 6 jam -> boleh diperingatkan lagi",
          "Kedip Cepat" in nama_flap3, "-> %r" % nama_flap3)
finally:
    config.get_notif_flap_ambang, config.get_notif_flap_tenang_jam = asli2

# ---------------------------------------------------------------------------
print("\n5. SUSUN PESAN: satu email berisi semua device (bukan satu per device)")

cfg = {"base_url": "http://localhost:8080"}
d4 = db.query(models.Device).filter(models.Device.id == 4).first()
d5c = db.query(models.Device).filter(models.Device.id == 5).first()
subjek, isi = nb.susun_pesan_gabungan("mati", [d4, d5c], cfg, sekarang=menit(20), db=db)
benar("subjek email gabungan menyebut JUMLAH device, bukan satu nama",
      "2 device" in subjek, "-> %r" % subjek)
benar("isi email memuat NAMA KEDUA device",
      "File Server" in isi and "Data Server" in isi)

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal_n))
print("=" * 74)

db.close()
sys.exit(1 if gagal_n else 0)

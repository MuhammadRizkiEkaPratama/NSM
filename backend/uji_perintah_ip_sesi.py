"""Test: the SSH command client IP is inherited across poller rounds within the SAME
session, read from a previously stored row rather than guessed.

The `USER_START` line (SSH session IP) appears only ONCE per session, at the
start. `perintahlog.gabung()` sees only lines within one log chunk, so once
USER_START falls out of the read window, later events of the same session lose
the address even though it was stored on an earlier row.

The fix in `poller.simpan_traffic_device()`: before saving a row without
`ip_klien`, look for an already-stored IP for the same session (device_id +
session). This is structural, not a guess: auditd session numbers (`ses=`) keep
increasing and are not reused quickly, so "one session = one IP".

Run: py uji_perintah_ip_sesi.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

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


import poller
import models


def siapkan():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    file = os.path.join(tempfile.mkdtemp(prefix="uji_ipsesi_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    d = models.Device(name="Server Berkas Uji", ip_address="192.168.56.105",
                      device_type="server", platform="linux", aktif=True)
    db.add(d)
    db.commit()
    return db, d


def bacaan_perintah(jalur, kejadian, posisi_baru=100):
    return {"log": [], "sftp": [], "smb": [], "flow": [],
            "perintah": [{"jalur": jalur, "service_id": 1, "galat": None,
                          "kejadian": kejadian, "posisi_baru": posisi_baru}]}


MULAI = datetime(2026, 8, 19, 16, 20, 0)


# ---------------------------------------------------------------------------
print("1. PUTARAN PERTAMA: IP diketahui (USER_START ada di potongan ini)")

db, d = siapkan()
k1 = [
    {"waktu": MULAI, "pengguna": "arif", "perintah": "whoami",
     "argumen": "whoami", "berhasil": 1, "ip_klien": "192.168.56.1",
     "sesi": "2610"},
    {"waktu": MULAI + timedelta(seconds=5), "pengguna": "arif",
     "perintah": "ls", "argumen": "ls -la /srv/sharing", "berhasil": 1,
     "ip_klien": "192.168.56.1", "sesi": "2610"},
]
poller.simpan_traffic_device(db, d, bacaan_perintah("audit.log", k1, 100))
db.commit()

baris1 = (db.query(models.PerintahPengguna)
         .order_by(models.PerintahPengguna.waktu).all())
benar("dua baris tersimpan", len(baris1) == 2, "-> %d" % len(baris1))
benar("keduanya bawa IP (USER_START ada di potongan ini)",
      all(b.ip_klien == "192.168.56.1" for b in baris1),
      "-> %r" % [b.ip_klien for b in baris1])

# ---------------------------------------------------------------------------
print("\n2. PUTARAN KEDUA: sesi SAMA, USER_START sudah lewat jendela baca")
print("   (persis kasus nyata -- gabung() TIDAK melihat USER_START lagi,")
print("    ip_klien kosong dari perintahlog, TAPI sesinya sama)")

k2 = [
    {"waktu": MULAI + timedelta(minutes=1), "pengguna": "arif",
     "perintah": "cp", "argumen": "cp jadwal.xlsx video/", "berhasil": 1,
     "ip_klien": None, "sesi": "2610"},
    {"waktu": MULAI + timedelta(minutes=1, seconds=30), "pengguna": "arif",
     "perintah": "rm", "argumen": "rm jadwal.xlsx", "berhasil": 1,
     "ip_klien": None, "sesi": "2610"},
]
poller.simpan_traffic_device(db, d, bacaan_perintah("audit.log", k2, 200))
db.commit()

baris2 = (db.query(models.PerintahPengguna)
         .filter(models.PerintahPengguna.perintah.in_(("cp", "rm")))
         .all())
benar("dua baris putaran kedua tersimpan", len(baris2) == 2, "-> %d" % len(baris2))
benar("KEDUANYA berhasil diwarisi IP dari sesi yang sama (bukan kosong lagi)",
      all(b.ip_klien == "192.168.56.1" for b in baris2),
      "-> %r" % [(b.perintah, b.ip_klien) for b in baris2])

# ---------------------------------------------------------------------------
print("\n3. SESI LAIN yang IP-nya BELUM PERNAH tercatat tetap kosong")
print("   (jangan menebak -- kalau memang belum pernah diketahui, biarkan")
print("    kosong, bukan mengarang alamat)")

db2, d2 = siapkan()
k3 = [{"waktu": MULAI, "pengguna": "dewi", "perintah": "ls",
      "argumen": "ls", "berhasil": 1, "ip_klien": None, "sesi": "9999"}]
poller.simpan_traffic_device(db2, d2, bacaan_perintah("audit.log", k3, 50))
db2.commit()
baris3 = db2.query(models.PerintahPengguna).all()
benar("sesi yang tidak pernah punya IP tercatat TETAP None, bukan ditebak",
      len(baris3) == 1 and baris3[0].ip_klien is None,
      "-> %r" % [b.ip_klien for b in baris3])

# ---------------------------------------------------------------------------
print("\n4. DEVICE LAIN dengan nomor SESI KEBETULAN SAMA tidak ikut tertukar")
print("   (nomor `ses=` auditd itu per-mesin, bukan global)")

db3, d3a = siapkan()
d3b = models.Device(name="Server Lain", ip_address="192.168.56.199",
                    device_type="server", platform="linux", aktif=True)
db3.add(d3b)
db3.commit()

# Device A, sesi 500, IP dikenal.
poller.simpan_traffic_device(db3, d3a, bacaan_perintah(
    "a.log", [{"waktu": MULAI, "pengguna": "x", "perintah": "whoami",
              "argumen": "whoami", "berhasil": 1,
              "ip_klien": "10.0.0.5", "sesi": "500"}], 10))
db3.commit()

poller.simpan_traffic_device(db3, d3b, bacaan_perintah(
    "b.log", [{"waktu": MULAI, "pengguna": "y", "perintah": "whoami",
              "argumen": "whoami", "berhasil": 1,
              "ip_klien": None, "sesi": "500"}], 10))
db3.commit()

baris_b = (db3.query(models.PerintahPengguna)
          .filter(models.PerintahPengguna.device_id == d3b.id).all())
benar("device B TIDAK mewarisi IP milik device A walau nomor sesi kebetulan sama",
      len(baris_b) == 1 and baris_b[0].ip_klien is None,
      "-> %r" % [b.ip_klien for b in baris_b])

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal_n))
print("=" * 74)
sys.exit(1 if gagal_n else 0)

"""Test: each HTTP service has its own access log instead of one global path.

A single configured access-log path is correct while a machine serves one web
app and silently wrong once it serves two (Apache on :80 and Spring Boot on
:8080 on `.103`). Nothing on screen would say that a service is not being read.

Checked, number 2 being the most decisive:

  1. two web services on one machine produce TWO log paths
  2. the read-position marker is SEPARATE per file
  3. a service without `log_akses` keeps using the default path
  4. the same file is not read twice
  5. paused and non-HTTP services are excluded
  6. one failing log does not take down the others on the same machine

A shared marker would let progress in file A read as progress in file B and
skip unread lines silently.

Runs on a TEMPORARY database; touches no device.
"""
import os
import sys
import tempfile

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

lolos = 0
gagal = 0


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print("  LOLOS  %s" % nama)
    else:
        gagal += 1
        print("  GAGAL  %s %s" % (nama, ket))


def sama(nama, dapat, harap):
    benar(nama, dapat == harap, "-> dapat %r, harusnya %r" % (dapat, harap))


def siapkan():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    file = os.path.join(tempfile.mkdtemp(prefix="uji_logsvc_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    web = models.Device(name="Web Server", ip_address="192.168.56.103",
                        device_type="server", platform="linux", aktif=True,
                        username="nsmro", ssh_key_path="/x/k")
    dbserver = models.Device(name="DB Server", ip_address="192.168.56.101",
                             device_type="server", platform="linux", aktif=True,
                             username="nsmro", ssh_key_path="/x/k")
    db.add_all([web, dbserver])
    db.commit()

    db.add_all([
        models.Service(device_id=web.id, nama="Web Server BSP", jenis="http",
                       port=80, aktif=1,
                       log_akses="/var/log/apache2/access.log"),
        models.Service(device_id=web.id, nama="E-Canteen v2", jenis="http",
                       port=8080, aktif=1,
                       log_akses="/opt/ecanteen/logs/access.log"),
        models.Service(device_id=web.id, nama="SSH", jenis="tcp",
                       port=22, aktif=1),
        models.Service(device_id=web.id, nama="Web lama", jenis="http",
                       port=8081, aktif=0,
                       log_akses="/var/log/lama/access.log"),
        models.Service(device_id=dbserver.id, nama="phpMyAdmin", jenis="http",
                       port=80, aktif=1),
    ])
    db.commit()
    return db, web, dbserver


import poller

db, web, dbserver = siapkan()
BAWAAN = poller.get_access_log_path()

# ---------------------------------------------------------------------------
print("\n1. DUA LAYANAN WEB DI SATU MESIN = DUA JALUR LOG")
print("   (regresi utamanya: dulu hanya satu yang pernah dibaca, dan tidak")
print("    ada apa pun di layar yang menyatakan yang satunya dilewati)")

pasangan = poller.jalur_log_web(db, web.id)
jalur = [j for j, _sid in pasangan]
sama("dua jalur ditemukan", len(jalur), 2)
benar("log Apache ikut", "/var/log/apache2/access.log" in jalur, "-> %r" % jalur)
benar("log E-Canteen ikut", "/opt/ecanteen/logs/access.log" in jalur,
      "-> %r" % jalur)

# Each path names its owning service; otherwise rows from two web apps on one
# machine cannot be told apart.
peta = dict(pasangan)
benar("log Apache menyebut layanan pemiliknya",
      peta["/var/log/apache2/access.log"] is not None, "-> %r" % pasangan)
benar("log E-Canteen menyebut layanan pemiliknya",
      peta["/opt/ecanteen/logs/access.log"] is not None, "-> %r" % pasangan)
benar("keduanya layanan yang BERBEDA",
      peta["/var/log/apache2/access.log"] != peta["/opt/ecanteen/logs/access.log"])

# ---------------------------------------------------------------------------
print("\n2. LAYANAN YANG TIDAK PUNYA LOG TIDAK IKUT")

benar("layanan non-HTTP (SSH) tidak menyumbang jalur",
      not any("22" in j for j in jalur))
benar("layanan yang DIJEDA tidak ikut",
      "/var/log/lama/access.log" not in jalur, "-> %r" % jalur)

# ---------------------------------------------------------------------------
print("\n3. LAYANAN LAMA TANPA log_akses TETAP MEMAKAI JALUR BAWAAN")
print("   (migrasi yang mengubah perilaku layanan yang tidak disebut-sebut")
print("    adalah cara tercepat membuat orang takut menjalankan migrasi)")

jalur_db = poller.jalur_log_web(db, dbserver.id)
sama("satu jalur", len(jalur_db), 1)
sama("dan itu jalur bawaan dari config", jalur_db[0][0], BAWAAN)
# The default path can be shared, so NSM does not know its owner; None is honest here.
sama("layanan pemiliknya None, bukan ditebak", jalur_db[0][1], None)

# ---------------------------------------------------------------------------
print("\n4. BERKAS YANG SAMA TIDAK DIBACA DUA KALI")
print("   (kalau dibaca dua kali, tiap permintaan web tercatat ganda dan")
print("    seluruh angka di halaman jadi dua kali lipat)")

import models
db.add(models.Service(device_id=web.id, nama="Web kembar", jenis="http",
                      port=8082, aktif=1,
                      log_akses="/var/log/apache2/access.log"))
db.commit()
jalur2 = [j for j, _s in poller.jalur_log_web(db, web.id)]
sama("tetap dua jalur, bukan tiga", len(jalur2), 2)
sama("tidak ada duplikat", len(jalur2), len(set(jalur2)))

# ---------------------------------------------------------------------------
print("\n5. DEVICE TANPA LAYANAN WEB MENGHASILKAN DAFTAR KOSONG")
print("   (daftar kosong itulah yang menggantikan punya_layanan_web();")
print("    dua fungsi untuk satu keputusan pasti menyimpang diam-diam)")

polos = models.Device(name="Router", ip_address="10.0.0.1",
                      device_type="router", platform="cisco_ios", aktif=True)
db.add(polos)
db.commit()
sama("daftarnya kosong", poller.jalur_log_web(db, polos.id), [])

# ---------------------------------------------------------------------------
print("\n6. PENANDA POSISI BACA TERPISAH PER BERKAS")
print("   (satu penanda untuk dua berkas membuat maju di berkas A terbaca")
print("    sebagai maju di berkas B — baris yang belum pernah dibaca")
print("    dilewati tanpa satu pun galat)")

p1 = poller.posisi_log(db, web.id, "/var/log/apache2/access.log")
p2 = poller.posisi_log(db, web.id, "/opt/ecanteen/logs/access.log")
db.commit()
benar("dua baris penanda yang berbeda", p1.id != p2.id)

p1.posisi = 99999
db.commit()
p2_lagi = poller.posisi_log(db, web.id, "/opt/ecanteen/logs/access.log")
sama("maju di log Apache TIDAK memajukan log E-Canteen", p2_lagi.posisi, 0)

# ---------------------------------------------------------------------------
print("\n7. SATU LOG GAGAL TIDAK MENJATUHKAN LOG LAIN")
print("   (berkas E-Canteen bisa belum ada sementara log Apache sudah berisi")
print("    ribuan baris; menghentikan keduanya berarti menukar sebagian data")
print("    dengan tidak ada data sama sekali)")

bacaan = {"log": [
    {"jalur": "/var/log/apache2/access.log", "service_id": 1, "galat": None,
     "entri": [{"waktu": None, "ip_klien": "192.168.1.5", "metode": "GET",
                "path": "/a.png", "protokol": "HTTP/1.1", "status": 200,
                "byte_kirim": 100.0, "byte_terima": None, "rujukan": "-",
                "user_agent": "x", "dari_nsm": 0}],
     "posisi_baru": 500, "diputar": False},
    {"jalur": "/opt/ecanteen/logs/access.log", "service_id": 2,
     "galat": "No such file or directory", "entri": [],
     "posisi_baru": 0, "diputar": False},
], "flow": []}

n_akses, n_flow, log_gagal, _n_transfer = poller.simpan_traffic_device(
    db, web, bacaan)
db.commit()
sama("baris dari log yang BERHASIL tetap tersimpan", n_akses, 1)

tersimpan = db.query(models.AksesWeb).order_by(models.AksesWeb.id.desc()).first()
sama("baris menyebut layanan asalnya", tersimpan.service_id, 1)
sama("dan device-nya tetap benar", tersimpan.device_id, web.id)
sama("log yang gagal dilaporkan, bukan didiamkan", len(log_gagal), 1)
benar("laporannya menyebut jalur mana yang gagal",
      log_gagal[0][0] == "/opt/ecanteen/logs/access.log",
      "-> %r" % (log_gagal,))

# The position marker of a FAILED log must not advance, or its lines would be
# skipped forever once the file appears.
p_gagal = poller.posisi_log(db, web.id, "/opt/ecanteen/logs/access.log")
sama("posisi log yang gagal TIDAK dimajukan", p_gagal.posisi, 0)
p_ok = poller.posisi_log(db, web.id, "/var/log/apache2/access.log")
sama("posisi log yang berhasil dimajukan", p_ok.posisi, 500)

# ---------------------------------------------------------------------------
print("\n8. BERKAS TIDAK ADA DIBEDAKAN DARI BERKAS KOSONG")
print("   (keduanya menghasilkan nol baris baru, tetapi yang satu keadaan")
print("    normal dan yang satunya SALAH PASANG. Menyamakannya membuat log")
print("    yang tidak pernah ada dilaporkan sebagai pembacaan yang sukses —")
print("    ketahuan saat log E-Canteen didaftarkan sebelum Tomcat disuruh")
print("    menulisnya)")

from connectors import akseslog

perintah = akseslog.perintah_baca("/opt/ecanteen/logs/access.log", 0)
benar("perintahnya menandai berkas hilang dengan -1, bukan 0",
      "echo -1" in perintah, "-> %r" % perintah[:80])

for nama, keluaran, pos, harap_ada, harap_baris in [
        ("berkas TIDAK ADA",       "-1\n", 100, False, 0),
        ("berkas ada tapi kosong", "0\n",    0, True,  0),
        ("berkas ada dan berisi",
         '120\n1.2.3.4 - - [09/Aug/2026:01:00:00 +0000] "GET /a HTTP/1.1" 200 10 "-" "x"\n',
         0, True, 1),
        ("berkas diputar",         "5\n",  999, True,  0),
]:
    baris, _pos, _putar, ada = akseslog.baca_potongan(keluaran, pos)
    benar("%-22s -> ada=%s" % (nama, harap_ada), ada is harap_ada,
          "-> dapat ada=%r" % ada)
    sama("%-22s -> %d baris" % (nama, harap_baris), len(baris), harap_baris)

_b, pos_baru, _p, _a = akseslog.baca_potongan("-1\n", 4321)
sama("posisi berkas yang tidak ada dibiarkan apa adanya", pos_baru, 4321)

db.close()

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

"""Test the file list on the Traffic page: "what was downloaded".

The Traffic page used to stop at "192.168.56.1 pulled 203.18 MB", raising the
question "which file?" without answering it. The data existed (file names in
`akses_web`) but was buried in the per-device history page.

Guards:
  1. the global endpoint really sends the file list (main regression)
  2. ordered by total bytes, not request count
  3. average per request separates one huge fetch from thousands of small ones
  4. NSM's own requests are named, not silently dropped
  5. the period really filters

Number 3 matters most: `/hello.php` (monitoring heartbeat) had 7,989 requests but
~3 MB, while `/uji-50mb.bin` had 4 requests and 200 MB.

Runs on a TEMPORARY database. Does not touch nsm.db.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

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

    file = os.path.join(tempfile.mkdtemp(prefix="uji_berkas_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    d = models.Device(name="Web Server", ip_address="192.168.56.103",
                      device_type="server", platform="linux", aktif=True)
    db.add(d)
    db.commit()

    current = datetime.now()

    def catat(path, byte, kapan, klien="192.168.56.1", nsm=0, status=200):
        db.add(models.AksesWeb(
            device_id=d.id, waktu=kapan, ip_klien=klien, metode="GET",
            path=path, protokol="HTTP/1.1", status=status,
            byte_kirim=float(byte), dari_nsm=nsm))

    # One LARGE file, fetched four times. Total 200 MB.
    for i in range(4):
        catat("/uji-50mb.bin", 52_429_109, current - timedelta(hours=2, minutes=i))

    # SMALL file fetched a thousand times by NSM itself. Total ~0.4 MB: 250x the requests, 500x less data.
    for i in range(1000):
        catat("/hello.php", 418, current - timedelta(minutes=i % 600), nsm=1)

    # One ordinary image file.
    catat("/icons/ubuntu-logo.png", 3607, current - timedelta(hours=3))

    # OLD file, outside the 24-hour period.
    catat("/arsip-lama.zip", 900_000_000, current - timedelta(days=20))

    db.commit()
    return db, d


import report_service as rs

db, d = siapkan()

# ---------------------------------------------------------------------------
print("\n1. DAFTAR BERKAS BENAR-BENAR DIKIRIM")
print("   (ini regresi utamanya: endpoint globalnya dulu TIDAK mengirim")
print("    satu nama berkas pun, sehingga halamannya tidak mungkin")
print("    menampilkannya walau datanya lengkap di basis data)")

hasil = rs.traffic_semua(db, "24h")
benar("kunci `path` ada di jawaban", "path" in hasil,
      "-> kunci yang ada: %s" % sorted(hasil.keys()))
benar("isinya tidak kosong", bool(hasil.get("path")))
benar("jumlah berkas disebut", hasil.get("berkas_terlihat") == len(hasil["path"]),
      "-> %r vs %r" % (hasil.get("berkas_terlihat"), len(hasil.get("path") or [])))

nama = [p["path"] for p in hasil["path"]]
benar("berkas besar ikut terdaftar", "/uji-50mb.bin" in nama, "-> %r" % nama)
benar("berkas kecil ikut terdaftar", "/hello.php" in nama)
benar("gambar ikut terdaftar", "/icons/ubuntu-logo.png" in nama)

# ---------------------------------------------------------------------------
print("\n2. DIURUTKAN MENURUT TOTAL BYTE, BUKAN JUMLAH PERMINTAAN")
print("   (yang paling sering diminta belum tentu yang paling banyak")
print("    memindahkan data — di lab ini justru kebalikannya)")

sama("berkas terbesar ada di urutan pertama", nama[0], "/uji-50mb.bin")
byte_urut = [p["byte"] for p in hasil["path"]]
benar("urutannya menurun", byte_urut == sorted(byte_urut, reverse=True),
      "-> %r" % byte_urut)

p_besar = next(p for p in hasil["path"] if p["path"] == "/uji-50mb.bin")
p_kecil = next(p for p in hasil["path"] if p["path"] == "/hello.php")
benar("berkas kecil punya JAUH lebih banyak permintaan",
      p_kecil["permintaan"] > p_besar["permintaan"] * 100,
      "-> %d vs %d" % (p_kecil["permintaan"], p_besar["permintaan"]))
benar("tetapi berkas besar memindahkan jauh lebih banyak data",
      p_besar["byte"] > p_kecil["byte"] * 100,
      "-> %.0f vs %.0f" % (p_besar["byte"], p_kecil["byte"]))

# ---------------------------------------------------------------------------
print("\n3. RATA-RATA PER PERMINTAAN MEMBEDAKAN KEDUANYA")

benar("rata-rata disediakan", p_besar.get("rata_teks") is not None)
benar("rata-rata berkas besar terbaca MB", "MB" in (p_besar["rata_teks"] or ""),
      "-> %r" % p_besar["rata_teks"])
benar("rata-rata berkas kecil terbaca byte, bukan MB",
      "MB" not in (p_kecil["rata_teks"] or ""),
      "-> %r" % p_kecil["rata_teks"])

# ---------------------------------------------------------------------------
print("\n4. PERMINTAAN NSM SENDIRI DISEBUT, BUKAN DIBUANG DIAM-DIAM")
print("   (denyut pemantauan yang tidak diberi keterangan akan terbaca")
print("    sebagai berkas yang sangat populer)")

sama("hello.php ditandai berasal dari NSM", p_kecil["dari_nsm"], 1000)
sama("berkas sungguhan tidak ditandai NSM", p_besar["dari_nsm"], 0)
benar("barisnya TIDAK dibuang dari daftar", p_kecil["permintaan"] == 1000,
      "-> membuangnya membuat totalnya tidak pernah cocok")

# ---------------------------------------------------------------------------
print("\n5. PERIODE BENAR-BENAR MENYARING")

benar("berkas berumur 20 hari TIDAK ikut di periode 24 jam",
      "/arsip-lama.zip" not in nama, "-> %r" % nama)

luas = rs.traffic_semua(db, "30d")
nama_luas = [p["path"] for p in luas["path"]]
benar("dan IKUT di periode 30 hari", "/arsip-lama.zip" in nama_luas,
      "-> %r" % nama_luas)
sama("di periode luas ia jadi yang terbesar", nama_luas[0], "/arsip-lama.zip")

# ---------------------------------------------------------------------------
print("\n6. TIDAK ADA DATA BUKAN KEADAAN GALAT")

db2, _d2 = siapkan()
db2.query(__import__("models").AksesWeb).delete()
db2.commit()
kosong = rs.traffic_semua(db2, "24h")
benar("tetap mengirim kunci `path`", "path" in kosong)
sama("isinya daftar kosong, bukan None", kosong["path"], [])
sama("jumlah berkasnya nol", kosong["berkas_terlihat"], 0)

db.close()
db2.close()

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

"""Tests for the five functions feeding the Syslog page: `deret_jam`, `per_device`, `per_tag`, `daftar`, `dasbor`.
Deliberately covered:
  1. Hour rounding must work on both SQLite and MySQL (not only MySQL's `DATE_FORMAT`).
  2. Unknown senders (`device_id` NULL) must not be dropped; they must appear with their address.
  3. Pagination must be right at the edges: a partial last page, a page past the end, and `total` shrinking when filtered.
Run: py uji_syslog_halaman.py
"""
import os
import tempfile
from datetime import datetime, timedelta

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


import models                       # noqa: E402
import syslog_service as ss         # noqa: E402


def siapkan():
    """Temporary database with messages shaped like the real lab. The distribution is deliberately uneven (one tag dominates), since flat data would let a wrongly sorting function pass."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    file = os.path.join(tempfile.mkdtemp(prefix="uji_syslog_hal_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    r1 = models.Device(name="Router Lokasi A", ip_address="192.168.56.60",
                       device_type="router", platform="cisco_ios", aktif=True)
    r2 = models.Device(name="Router Lokasi B", ip_address="192.168.20.1",
                       device_type="router", platform="cisco_ios", aktif=True)
    db.add_all([r1, r2])
    db.commit()

    sekarang = datetime.now()

    def tambah(menit_lalu, device, alamat, sev, tag, pesan):
        db.add(models.SyslogPesan(
            waktu=sekarang - timedelta(minutes=menit_lalu),
            device_id=(device.id if device else None),
            alamat=alamat, facility=23, severity=sev, tag=tag, pesan=pesan,
            sidik_templat="sidik-" + (tag or "kosong")))

    for i in range(20):
        tambah(10 + i * 7, r1, "192.168.56.60", 4, "%CDP-4-DUPLEX_MISMATCH",
               "duplex mismatch discovered on FastEthernet0/%d" % (i % 3))
    for i in range(3):
        tambah(20 + i * 5, r2, "192.168.20.1", 2, "%LINK-3-UPDOWN",
               "Interface FastEthernet1/1, changed state to down")
    for i in range(2):
        tambah(30 + i, None, "10.9.9.9", 5, "%SYS-5-CONFIG_I",
               "Configured from console by vty0 (10.9.9.9)")
    tambah(60 * 30, r1, "192.168.56.60", 6, "%SYS-6-LOGGINGHOST_STARTSTOP",
           "Logging to host 192.168.56.156 started")
    db.commit()
    return db, r1, r2


db, r1, r2 = siapkan()

# =============================================================================
print("=" * 74)
print("1. MEMBULATKAN KE JAM JALAN DI SQLITE, BUKAN CUMA MYSQL")
print("=" * 74)

deret = ss.deret_jam(db, jam=72)
benar("deret_jam berjalan di SQLite tanpa melempar", isinstance(deret, list))
benar("deret_jam menghasilkan titik", len(deret) > 0, "-> %d titik" % len(deret))
benar("tiap titik punya jam, semua, penting",
      all(set(t) == {"jam", "semua", "penting"} for t in deret))
benar("jumlah 'penting' tidak pernah melebihi 'semua'",
      all(t["penting"] <= t["semua"] for t in deret))
benar("titik terurut menaik menurut jam",
      [t["jam"] for t in deret] == sorted(t["jam"] for t in deret))

total_deret = sum(t["semua"] for t in deret)
benar("jumlah seluruh titik sama dengan total pesan dalam jendela",
      total_deret == ss.ringkas(db, jam=72)["total"],
      "-> deret %d vs ringkas %d" % (total_deret, ss.ringkas(db, jam=72)["total"]))

# =============================================================================
print()
print("=" * 74)
print("2. PENGIRIM TAK DIKENAL TIDAK BOLEH HILANG")
print("=" * 74)

kirim = ss.per_device(db, jam=72)
tak_dikenal = [k for k in kirim if not k["dikenal"]]
benar("pengirim tak dikenal MUNCUL di daftar", len(tak_dikenal) == 1,
      "-> %d baris" % len(tak_dikenal))
if tak_dikenal:
    benar("alamatnya ikut disebut", tak_dikenal[0]["alamat"] == "10.9.9.9",
          "-> %r" % tak_dikenal[0]["alamat"])
    benar("namanya menyatakan ia tak dikenal",
          "tak dikenal" in tak_dikenal[0]["nama"].lower(),
          "-> %r" % tak_dikenal[0]["nama"])

benar("pengirim diurutkan dari yang paling banyak bicara",
      kirim[0]["jumlah"] >= kirim[-1]["jumlah"],
      "-> %d lalu %d" % (kirim[0]["jumlah"], kirim[-1]["jumlah"]))
benar("perangkat dikenal memakai NAMANYA, bukan alamatnya",
      any(k["nama"] == "Router Lokasi A" for k in kirim))
benar("severity terparah dilaporkan sebagai ANGKA TERKECIL (RFC 3164)",
      min(k["terparah"] for k in kirim if k["dikenal"]) == 2,
      "-> %r" % [k["terparah"] for k in kirim])

# =============================================================================
print()
print("=" * 74)
print("3. PENGELOMPOKAN TAG MENEMUKAN YANG MENDOMINASI")
print("=" * 74)

tag = ss.per_tag(db, jam=72)
benar("tag terbanyak ada di urutan pertama",
      tag[0]["tag"] == "%CDP-4-DUPLEX_MISMATCH", "-> %r" % tag[0]["tag"])
benar("persennya dihitung, bukan dibiarkan kosong", tag[0]["persen"] > 50,
      "-> %r%%" % tag[0]["persen"])
benar("seluruh persen berjumlah sekitar 100",
      99.0 <= sum(t["persen"] for t in tag) <= 101.0,
      "-> %r" % sum(t["persen"] for t in tag))
benar("nama keparahan diterjemahkan, bukan angka telanjang",
      isinstance(tag[0]["terparah_nama"], str) and tag[0]["terparah_nama"] != "",
      "-> %r" % tag[0]["terparah_nama"])

# =============================================================================
print()
print("=" * 74)
print("4. PAGINASI BENAR DI TEPINYA, BUKAN CUMA DI TENGAH")
print("=" * 74)

h1 = ss.daftar(db, jam=72, per_halaman=5, halaman=1)
benar("halaman pertama berisi tepat 5 baris", len(h1["pesan"]) == 5,
      "-> %d" % len(h1["pesan"]))
benar("total menghitung SELURUH baris, bukan yang di halaman ini",
      h1["total"] == 26, "-> %d" % h1["total"])
benar("jumlah halaman dibulatkan ke atas",
      h1["jumlah_halaman"] == 6, "-> %d" % h1["jumlah_halaman"])
benar("pesan terurut dari yang TERBARU",
      h1["pesan"][0]["waktu"] >= h1["pesan"][-1]["waktu"])

terakhir = ss.daftar(db, jam=72, per_halaman=5, halaman=6)
benar("halaman terakhir berisi sisanya, bukan 5",
      len(terakhir["pesan"]) == 1, "-> %d" % len(terakhir["pesan"]))

lewat = ss.daftar(db, jam=72, per_halaman=5, halaman=99)
benar("halaman melewati batas mengembalikan kosong, BUKAN melempar",
      lewat["pesan"] == [] and lewat["total"] == 26)

nol = ss.daftar(db, jam=72, per_halaman=5, halaman=0)
benar("halaman 0 diperlakukan sebagai halaman 1, bukan offset negatif",
      nol["halaman"] == 1 and len(nol["pesan"]) == 5,
      "-> halaman %r" % nol["halaman"])

# =============================================================================
print()
print("=" * 74)
print("5. PENYARING BENAR-BENAR MENYARING, DAN TOTALNYA IKUT MENGECIL")
print("=" * 74)

f_tag = ss.daftar(db, jam=72, tag="%LINK-3-UPDOWN", per_halaman=50)
benar("saring tag menyisakan hanya tag itu",
      all(p["tag"] == "%LINK-3-UPDOWN" for p in f_tag["pesan"]))
benar("total ikut mengecil saat disaring, bukan tetap 26",
      f_tag["total"] == 3, "-> %d" % f_tag["total"])

f_dev = ss.daftar(db, jam=72, device_id=r2.id, per_halaman=50)
benar("saring perangkat menyisakan hanya perangkat itu",
      all(p["device_id"] == r2.id for p in f_dev["pesan"]) and f_dev["total"] == 3,
      "-> %d baris" % f_dev["total"])

f_penting = ss.daftar(db, jam=72, hanya_penting=True, per_halaman=50)
benar("saring 'hanya gawat' membuang yang di bawah ambang",
      all(p["penting"] for p in f_penting["pesan"]),
      "-> %d baris" % f_penting["total"])

f_cari = ss.daftar(db, jam=72, cari="changed state", per_halaman=50)
benar("cari isi menemukan yang mengandung katanya",
      f_cari["total"] == 3, "-> %d" % f_cari["total"])

f_kosong = ss.daftar(db, jam=72, cari="tidak-akan-pernah-ada-xyz", per_halaman=50)
benar("cari yang tidak cocok mengembalikan kosong, bukan seluruh tabel",
      f_kosong["total"] == 0 and f_kosong["pesan"] == [])

# =============================================================================
print()
print("=" * 74)
print("6. BATAS WAKTU BENAR-BENAR MEMBATASI")
print("=" * 74)

sempit = ss.daftar(db, jam=1, per_halaman=50)
benar("jendela 1 jam membuang pesan yang lebih tua",
      sempit["total"] < 26, "-> %d dari 26" % sempit["total"])
benar("pesan berumur 30 jam tidak ikut di jendela 1 jam",
      not any("LOGGINGHOST" in p["tag"] for p in sempit["pesan"]))

lebar = ss.daftar(db, jam=72, per_halaman=50)
benar("jendela 72 jam memuat yang berumur 30 jam",
      any("LOGGINGHOST" in p["tag"] for p in lebar["pesan"]))

# =============================================================================
print()
print("=" * 74)
print("7. DASBOR MEMBUNGKUS SEMUANYA DALAM SATU PANGGILAN")
print("=" * 74)

d = ss.dasbor(db, jam=72)
for kunci in ("total", "penting", "deret", "per_device", "per_tag",
              "templat_teratas", "ambang_penting"):
    benar("dasbor memuat '%s'" % kunci, kunci in d)
benar("dasbor konsisten dengan ringkas untuk jendela yang sama",
      d["total"] == ss.ringkas(db, jam=72)["total"])

# =============================================================================
print()
print("=" * 74)
print("%d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
raise SystemExit(1 if gagal else 0)

"""Test `kapasitas.py`: the "disk full in how many days" forecast.

A forecast is where it is easiest to lie confidently, so what is guarded is the
honesty of its limits, not exact numbers:
  * too little data -> answer "not enough yet", do NOT fit a line to three points;
  * noisy trend -> the number may appear but MUST carry the verdict `tidak_yakin`;
  * far horizon -> "more than a year", not "1,482 days".

Uses temporary SQLite + data planted at KNOWN rates so answers can be computed by hand.

Run: py uji_kapasitas.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

lolos = 0
gagal = 0


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print(f"  LOLOS  {nama}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama} {ket}")


def cek(nama, dapat, harap):
    global lolos, gagal
    if dapat == harap:
        lolos += 1
        print(f"  LOLOS  {nama}: {dapat!r}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama}: dapat {dapat!r}, harusnya {harap!r}")


import models  # noqa: E402
import kapasitas  # noqa: E402

T0 = datetime(2026, 8, 1, 0, 0, 0)


def siapkan_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    file = os.path.join(tempfile.mkdtemp(prefix="uji_kap_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def buat_device(db, nama="Server Uji", ip="10.0.0.1"):
    d = models.Device(name=nama, ip_address=ip, device_type="server",
                      platform="linux", aktif=1)
    db.add(d)
    db.commit()
    return d


def tanam(db, device_id, mulai, jam, awal_persen, naik_per_hari,
          tiap_menit=5, derau=0.0):
    """Plant disk samples at a KNOWN rate.

    `derau` (noise) adds a fixed-pattern wobble (not random) so results are identical on every run.
    """
    n = int(jam * 60 / tiap_menit)
    for i in range(n):
        t = mulai + timedelta(minutes=i * tiap_menit)
        hari = (t - mulai).total_seconds() / 86400.0
        value = awal_persen + naik_per_hari * hari
        if derau:
            value += derau * (1 if i % 2 == 0 else -1)
        db.add(models.SumberDaya(device_id=device_id, waktu=t,
                                 disk_persen=round(value, 2),
                                 mem_persen=40.0, load_per_inti=0.5,
                                 inti=2, sumber="uji"))
    db.commit()


# =============================================================================
print("=" * 74)
print("1. LAJU YANG DIKETAHUI HARUS TERBACA KEMBALI")
print("   Ditanam 2%/hari selama 5 hari mulai dari 50%. Kalau modul ini")
print("   tidak bisa menemukan angka yang kita sendiri yang menaruhnya,")
print("   sisanya tidak perlu diuji.")
print("=" * 74)

db = siapkan_db()
d = buat_device(db)
tanam(db, d.id, T0, jam=24 * 5, awal_persen=50.0, naik_per_hari=2.0)
sekarang = T0 + timedelta(days=5)

r = kapasitas.prakiraan_device(db, d.id, sekarang=sekarang, jendela_hari=7)
print("   -> %r" % {k: r[k] for k in ("vonis", "disk_persen", "laju_per_hari",
                                      "r2", "hari_menuju_penuh")})
cek("vonisnya cukup data", r["vonis"], kapasitas.CUKUP)
benar("laju terbaca ~2%/hari", abs(r["laju_per_hari"] - 2.0) < 0.05,
      "-> %r" % r["laju_per_hari"])
benar("garis lurus sempurna -> R^2 mendekati 1",
      r["r2"] >= 0.99, "-> %r" % r["r2"])

# 5 days x 2% = up 10 -> now ~60%. Remaining to 100% = 40 -> 20 days.
benar("hari menuju penuh ~20 (dihitung tangan: sisa 40%% / 2%% per hari)",
      abs(r["hari_menuju_penuh"] - 20) <= 1.0,
      "-> %r (disk sekarang %r)" % (r["hari_menuju_penuh"], r["disk_persen"]))
benar("hari menuju WASPADA (90%) lebih cepat daripada menuju penuh",
      r["hari_menuju_waspada"] < r["hari_menuju_penuh"],
      "-> waspada %r, penuh %r" % (r["hari_menuju_waspada"],
                                   r["hari_menuju_penuh"]))
benar("kalimatnya menyebut angka, bukan cuma kata sifat",
      "%" in r["alasan"] and "hari" in r["alasan"], "-> %r" % r["alasan"])


# =============================================================================
print()
print("=" * 74)
print("2. DATA TERLALU SEDIKIT -> MENOLAK MERAMAL")
print("   Ini invarian terpenting berkas ini. Modul yang tetap menjawab")
print("   angka dari tiga titik akan terlihat lebih pintar dan lebih")
print("   berguna -- sampai orang mengambil keputusan dari angka itu.")
print("=" * 74)

db = siapkan_db()
d = buat_device(db)
tanam(db, d.id, T0, jam=1, awal_persen=50.0, naik_per_hari=2.0)   # 12 sampel
r = kapasitas.prakiraan_device(db, d.id, sekarang=T0 + timedelta(hours=1))
print("   -> sampel=%s vonis=%s" % (r["sampel"], r["vonis"]))
cek("sampel di bawah batas -> tidak_cukup_data", r["vonis"],
    kapasitas.TIDAK_CUKUP)
benar("dan TIDAK mengarang angka prakiraan",
      r["hari_menuju_penuh"] is None, "-> %r" % r["hari_menuju_penuh"])
benar("alasannya menyebut BERAPA sampel yang ada, bukan cuma 'kurang'",
      str(r["sampel"]) in r["alasan"], "-> %r" % r["alasan"])

# MANY samples but a short span: still refused. A hundred samples in ten minutes say nothing about the DAILY trend.
db = siapkan_db()
d = buat_device(db)
tanam(db, d.id, T0, jam=2, awal_persen=50.0, naik_per_hari=2.0, tiap_menit=1)
r = kapasitas.prakiraan_device(db, d.id, sekarang=T0 + timedelta(hours=2))
print("   -> sampel=%s rentang pendek, vonis=%s" % (r["sampel"], r["vonis"]))
benar("sampel banyak TAPI rentang pendek -> tetap ditolak",
      r["vonis"] == kapasitas.TIDAK_CUKUP and r["sampel"] >= kapasitas.MIN_SAMPEL,
      "-> sampel %s vonis %s" % (r["sampel"], r["vonis"]))
benar("alasannya menyebut rentang waktunya, bukan jumlah sampelnya",
      "jam" in r["alasan"], "-> %r" % r["alasan"])


# =============================================================================
print()
print("=" * 74)
print("3. DATAR DAN MENURUN DILAPORKAN APA ADANYA")
print("   Disk yang menyusut adalah fakta yang berguna. Halaman yang cuma")
print("   bisa menakuti tidak bisa memberi tahu.")
print("=" * 74)

db = siapkan_db()
d = buat_device(db)
tanam(db, d.id, T0, jam=24 * 5, awal_persen=42.0, naik_per_hari=0.0)
r = kapasitas.prakiraan_device(db, d.id, sekarang=T0 + timedelta(days=5))
cek("disk datar -> vonis stabil", r["vonis"], kapasitas.STABIL)
benar("dan tidak menjanjikan tanggal penuh",
      r["hari_menuju_penuh"] is None)

db = siapkan_db()
d = buat_device(db)
tanam(db, d.id, T0, jam=24 * 5, awal_persen=80.0, naik_per_hari=-1.5)
r = kapasitas.prakiraan_device(db, d.id, sekarang=T0 + timedelta(days=5))
cek("disk menyusut -> vonis menurun", r["vonis"], kapasitas.MENURUN)
benar("alasannya menyebut penurunannya sebagai INFORMASI, bukan diam saja",
      "MENURUN" in r["alasan"], "-> %r" % r["alasan"])


# =============================================================================
print()
print("=" * 74)
print("4. TREN BERISIK DITANDAI BERISIK")
print("   Angkanya boleh keluar -- yang tidak boleh adalah keluar tanpa")
print("   memberi tahu bahwa ia kasar.")
print("=" * 74)

db = siapkan_db()
d = buat_device(db)
# A small increase buried in large wobble: the line exists, but the points scatter far from it.
tanam(db, d.id, T0, jam=24 * 5, awal_persen=50.0, naik_per_hari=0.30,
      derau=9.0)
r = kapasitas.prakiraan_device(db, d.id, sekarang=T0 + timedelta(days=5))
print("   -> R^2=%s vonis=%s" % (r.get("r2"), r["vonis"]))
benar("R^2 rendah -> vonis tidak_yakin, bukan cukup",
      r["vonis"] == kapasitas.TIDAK_YAKIN, "-> %s (R2 %s)" % (r["vonis"], r.get("r2")))
benar("angkanya TETAP diberikan (berisik bukan berarti disembunyikan)",
      r["hari_menuju_penuh"] is not None)
benar("kalimatnya memperingatkan pembaca supaya tidak memakainya sbg tanggal",
      "kasar" in r["alasan"] or "isyarat" in r["alasan"],
      "-> %r" % r["alasan"])


# =============================================================================
print()
print("=" * 74)
print("5. HORIZON JAUH TIDAK DIBERI KETEPATAN PALSU")
print("=" * 74)

db = siapkan_db()
d = buat_device(db)
tanam(db, d.id, T0, jam=24 * 5, awal_persen=10.0, naik_per_hari=0.06)
r = kapasitas.prakiraan_device(db, d.id, sekarang=T0 + timedelta(days=5))
print("   -> laju=%s penuh=%s lewat_horizon=%s"
      % (r.get("laju_per_hari"), r.get("hari_menuju_penuh"),
         r.get("lewat_horizon")))
benar("naik sangat pelan -> tidak menyebut angka hari",
      r.get("hari_menuju_penuh") is None,
      "-> %r" % r.get("hari_menuju_penuh"))
benar("ditandai lewat horizon, bukan diam-diam None",
      r.get("lewat_horizon") is True, "-> %r" % r.get("lewat_horizon"))
benar("kalimatnya menyebut 'setahun' supaya pembaca tahu artinya",
      "setahun" in r["alasan"], "-> %r" % r["alasan"])


# =============================================================================
print()
print("=" * 74)
print("6. DAFTAR SEMUA PERANGKAT: YANG PALING MENDESAK DI ATAS")
print("=" * 74)

db = siapkan_db()
pelan = buat_device(db, "Pelan", "10.0.0.1")
cepat = buat_device(db, "Cepat", "10.0.0.2")
sepi = buat_device(db, "Tanpa data", "10.0.0.3")
tanam(db, pelan.id, T0, jam=24 * 5, awal_persen=20.0, naik_per_hari=0.5)
tanam(db, cepat.id, T0, jam=24 * 5, awal_persen=80.0, naik_per_hari=3.0)

daftar = kapasitas.prakiraan_semua(db, sekarang=T0 + timedelta(days=5))
print("   -> %r" % [(x["nama"], x["vonis"], x.get("hari_menuju_penuh"))
                    for x in daftar])
cek("perangkat tanpa data sama sekali TIDAK ikut", len(daftar), 2)
cek("yang paling cepat penuh ada di urutan pertama", daftar[0]["nama"], "Cepat")
benar("dan keduanya punya prakiraan",
      all(x["hari_menuju_penuh"] is not None for x in daftar))


if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

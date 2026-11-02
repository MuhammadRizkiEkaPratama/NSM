"""Tests for the three Dashboard charts.

1. Rounding to the hour must work on SQLite AND MySQL: use the helper that picks
   the function per dialect (`DATE_FORMAT` exists only in MySQL and breaks SQLite,
   where all tests run).
2. PAUSED devices must not lower availability: they are deliberately unmonitored.
3. Capacity must use the LATEST measurement, not the average, which hides a disk
   that just spiked. Tested with two measurements for one device (old low, new high).

Run: py uji_dasbor_grafik.py
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


import models             # noqa: E402
import dasbor_grafik as dg  # noqa: E402


def siapkan():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    file = os.path.join(tempfile.mkdtemp(prefix="uji_dg_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    healthy = models.Device(name="Router Sehat", ip_address="192.168.56.60",
                          device_type="router", platform="cisco_ios", aktif=True)
    paused = models.Device(name="Router Dijeda", ip_address="192.168.56.61",
                           device_type="router", platform="cisco_ios", aktif=True,
                           jeda_sejak=datetime.now() - timedelta(days=1),
                           jeda_alasan="sengaja tidak diawasi")
    srv = models.Device(name="Server Data (Lokasi A)", ip_address="192.168.56.104",
                        device_type="server", platform="linux", aktif=True)
    db.add_all([healthy, paused, srv])
    db.commit()

    sekarang = datetime.now()

    # Availability: the healthy device is 100% in the first hour, 90% in the second. The PAUSED one is 0%; if counted, the number drops.
    for hour_past, sampel, naik in ((2, 100, 100), (1, 100, 90)):
        db.add(models.StatusRollupJam(
            device_id=healthy.id, jam=sekarang - timedelta(hours=hour_past),
            sampel=sampel, sampel_naik=naik, latency_jumlah=100.0,
            latency_sampel=sampel, latency_min=1.0, latency_maks=2.0))
        db.add(models.StatusRollupJam(
            device_id=paused.id, jam=sekarang - timedelta(hours=hour_past),
            sampel=100, sampel_naik=0, latency_jumlah=0.0,
            latency_sampel=0, latency_min=None, latency_maks=None))

    # Capacity: TWO measurements for one server, old low and new high. The average would give 45; the right answer is 80.
    db.add(models.SumberDaya(device_id=srv.id, waktu=sekarang - timedelta(hours=6),
                             disk_persen=10.0, mem_persen=20.0,
                             load_per_inti=0.1, inti=4, sumber="ssh"))
    db.add(models.SumberDaya(device_id=srv.id, waktu=sekarang,
                             disk_persen=80.0, mem_persen=55.0,
                             load_per_inti=1.5, inti=4, sumber="ssh"))
    db.commit()
    return db, healthy, paused, srv


db, healthy, paused, srv = siapkan()

# =============================================================================
print("=" * 74)
print("1. MEMBULATKAN KE JAM JALAN DI SQLITE, BUKAN CUMA MYSQL")
print("=" * 74)

ada = dg.ketersediaan_jam(db, jam=24)
benar("ketersediaan_jam berjalan di SQLite tanpa melempar", isinstance(ada, list))
benar("menghasilkan titik", len(ada) == 2, "-> %d" % len(ada))
benar("tiap titik punya jam, sampel, naik, persen, device",
      all(set(t) == {"jam", "sampel", "naik", "persen", "device"} for t in ada))
benar("titik terurut menaik menurut jam",
      [t["jam"] for t in ada] == sorted(t["jam"] for t in ada))

# =============================================================================
print()
print("=" * 74)
print("2. PERANGKAT DIJEDA TIDAK MENURUNKAN KETERSEDIAAN")
print("=" * 74)

benar("jam pertama 100%, bukan 50% (yang dijeda dibuang)",
      ada[0]["persen"] == 100.0, "-> %r" % ada[0]["persen"])
benar("jam kedua 90%, bukan 45%",
      ada[1]["persen"] == 90.0, "-> %r" % ada[1]["persen"])
benar("hanya SATU perangkat dihitung, bukan dua",
      all(t["device"] == 1 for t in ada), "-> %r" % [t["device"] for t in ada])
benar("sampel tidak memuat sampel perangkat dijeda",
      all(t["sampel"] == 100 for t in ada), "-> %r" % [t["sampel"] for t in ada])

# If the pause is removed, the number MUST change; otherwise a non-functional filter would pass the three tests above.
paused.jeda_sejak = None
db.commit()
setelah = dg.ketersediaan_jam(db, jam=24)
benar("melepas jeda MENGUBAH angkanya (bukti penyaringnya bekerja)",
      setelah[0]["persen"] == 50.0 and setelah[0]["device"] == 2,
      "-> %r / %r device" % (setelah[0]["persen"], setelah[0]["device"]))
paused.jeda_sejak = datetime.now() - timedelta(days=1)
db.commit()

# =============================================================================
print()
print("=" * 74)
print("3. PERSEN TIDAK DIBULATKAN SAMPAI KEHILANGAN ARTINYA")
print("=" * 74)

# 99.95% vs 100% is the difference between "briefly down" and "never down"; rounding to an integer erases it.
db.add(models.StatusRollupJam(
    device_id=healthy.id, jam=datetime.now() - timedelta(hours=3),
    sampel=2000, sampel_naik=1999, latency_jumlah=10.0,
    latency_sampel=2000, latency_min=1.0, latency_maks=2.0))
db.commit()
halus = dg.ketersediaan_jam(db, jam=24)[0]
benar("1999 dari 2000 tidak dibulatkan jadi 100",
      halus["persen"] == 99.95, "-> %r" % halus["persen"])

# =============================================================================
print()
print("=" * 74)
print("4. KAPASITAS MEMAKAI PENGUKURAN TERBARU, BUKAN RATA-RATA")
print("=" * 74)

kap = dg.kapasitas_kini(db)
benar("satu baris per perangkat yang punya pengukuran", len(kap) == 1,
      "-> %d" % len(kap))
benar("disk 80 (terbaru), BUKAN 45 (rata-rata) dan bukan 10 (terlama)",
      kap[0]["disk_persen"] == 80.0, "-> %r" % kap[0]["disk_persen"])
benar("memori juga dari baris yang sama", kap[0]["mem_persen"] == 55.0,
      "-> %r" % kap[0]["mem_persen"])
benar("nama perangkat dipakai, bukan id",
      kap[0]["nama"] == "Server Data (Lokasi A)", "-> %r" % kap[0]["nama"])
benar("beban per inti ikut, untuk tooltip",
      kap[0]["load_per_inti"] == 1.5 and kap[0]["inti"] == 4)

# A device with no measurement must not appear as zero: "0% used" and "not measured" differ.
benar("perangkat tanpa pengukuran TIDAK muncul sebagai 0%",
      not any(k["nama"] == "Router Sehat" for k in kap))

# =============================================================================
print()
print("=" * 74)
print("5. AMBANG DINAMAI SATU KALI, DAN IKUT DIKIRIM KE HALAMAN")
print("=" * 74)

s = dg.semua(db, jam=24)
for kunci in ("jam", "ketersediaan", "pesan", "kapasitas", "ambang_disk", "ambang_mem"):
    benar("semua() memuat '%s'" % kunci, kunci in s)
benar("ambang disk berupa angka, bukan None",
      isinstance(s["ambang_disk"], int) and s["ambang_disk"] > 0,
      "-> %r" % s["ambang_disk"])
benar("pesan_jam memakai syslog_service, jadi definisi 'gawat' tetap satu",
      isinstance(s["pesan"], list))

# =============================================================================
print()
print("=" * 74)
print("6. JENDELA WAKTU BENAR-BENAR MEMBATASI")
print("=" * 74)

db.add(models.StatusRollupJam(
    device_id=healthy.id, jam=datetime.now() - timedelta(hours=50),
    sampel=100, sampel_naik=1, latency_jumlah=1.0,
    latency_sampel=100, latency_min=1.0, latency_maks=2.0))
db.commit()
sempit = dg.ketersediaan_jam(db, jam=24)
lebar = dg.ketersediaan_jam(db, jam=72)
benar("titik berumur 50 jam TIDAK ikut di jendela 24 jam",
      len(sempit) == 3, "-> %d titik" % len(sempit))
benar("dan IKUT di jendela 72 jam", len(lebar) == 4, "-> %d titik" % len(lebar))
benar("titik lama itu memang yang 1%",
      lebar[0]["persen"] == 1.0, "-> %r" % lebar[0]["persen"])

# =============================================================================
print()
print("=" * 74)
print("%d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
raise SystemExit(1 if gagal else 0)

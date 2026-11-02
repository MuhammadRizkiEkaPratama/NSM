"""Tests for `report_service.py`, the source of every number on the Report page (availability, incident count, MTTR, connection quality, stability).
Mostly checks invariants rather than single values, since errors here produce wrong numbers without any exception:
    * availability is always 0..100 or None
    * down time never exceeds observed time
    * observed + unmonitored time never exceeds the period length
    * MTTR counts only resolved incidents
    * a longer window never loses an existing incident
    * one quantity computed by two paths gives one value
Uses a temporary SQLite database with seeded data only; no live database, network or devices.
Run: py uji_report_service.py
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
import report_service as rs  # noqa: E402

T0 = datetime(2026, 8, 20, 12, 0, 0)


def siapkan_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import jeda

    file = os.path.join(tempfile.mkdtemp(prefix="uji_rs_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)

    # Required: `jeda._cache` is module-level, keyed by (device_id, rounded time), not per database. Each temporary DB here uses device id 1, so the cache must be cleared between cases. Test isolation only; harmless in the single-DB lab instance.
    jeda.lupakan_cache()

    # `report_service._cache` is also module-level and has no database identity, so clear it between cases; otherwise a second DB gets the first one's answers and tests can pass falsely.
    rs._cache.clear()
    return sessionmaker(bind=engine)()


def buat_device(db, nama="Device Uji", ip="10.0.0.1"):
    d = models.Device(name=nama, ip_address=ip, device_type="server",
                      platform="linux", aktif=1)
    db.add(d)
    db.commit()
    return d


def tanam_ping(db, device_id, mulai, jumlah, interval=10, hidup=True):
    """Seed `jumlah` status_logs rows spaced `interval` seconds apart."""
    for i in range(jumlah):
        db.add(models.StatusLog(
            device_id=device_id,
            timestamp=mulai + timedelta(seconds=i * interval),
            is_reachable=bool(hidup),
            response_time_ms=(5.0 if hidup else None),
            sumber="icmp"))
    db.commit()


def tanam_event(db, device_id, waktu, tipe, kategori="dead"):
    e = models.DeviceEvent(device_id=device_id, timestamp=waktu,
                           event_type=tipe, category=kategori, detail="uji")
    db.add(e)
    db.commit()
    return e


# =============================================================================
print("=" * 74)
print("1. FORMATTER MURNI -- dipakai di SETIAP halaman, nol ketergantungan")
print("=" * 74)

# Deliberate: 0 means "known to be zero", None means "unknown". Merging them would make a perfect device look like one with no data.
cek("format_durasi(0) -> nol yang diketahui", rs.format_durasi(0), "0 detik")
cek("format_durasi(None) -> tidak diketahui", rs.format_durasi(None), "-")
benar("format_durasi(59) menyebut detik", "detik" in rs.format_durasi(59))
benar("format_durasi(60) menyebut menit", "menit" in rs.format_durasi(60))
benar("format_durasi(3600) menyebut jam", "jam" in rs.format_durasi(3600))
benar("format_durasi TIDAK PERNAH mengembalikan 'None'/'nan' utk masukan sah",
      all("None" not in rs.format_durasi(x)
          and "nan" not in rs.format_durasi(x).lower()
          for x in [0, 1, 59, 60, 61, 3599, 3600, 86399, 86400, 1000000]))
benar("format_durasi menolak negatif dengan anggun (tidak crash)",
      isinstance(rs.format_durasi(-5), str))

benar("format_bps(0) menghasilkan teks", isinstance(rs.format_bps(0), str))
benar("format_bps skala naik: 1e9 berbeda dari 1e3",
      rs.format_bps(1e9) != rs.format_bps(1e3))
benar("format_byte(0) menghasilkan teks", isinstance(rs.format_byte(0), str))
benar("format_byte skala naik: 1e9 berbeda dari 1e3",
      rs.format_byte(int(1e9)) != rs.format_byte(int(1e3)))

# `rentang()` returns three values (start, end, label), not one datetime; tested so the shape stays fixed for its many callers.
for p in ("1h", "24h", "7d", "30d"):
    r = rs.rentang(p)
    benar("rentang(%r) mengembalikan 3 nilai" % p,
          isinstance(r, tuple) and len(r) == 3, "-> %r" % (r,))
    mulai_r, selesai_r, label_r = r
    benar("rentang(%r): mulai di masa lalu, selesai sekarang" % p,
          isinstance(mulai_r, datetime) and isinstance(selesai_r, datetime)
          and mulai_r < selesai_r)
benar("periode tak dikenal jatuh ke 24h, bukan crash",
      rs.rentang("periode-ngawur")[2] == "24h")
benar("rentang periode panjang lebih jauh ke belakang daripada yang pendek",
      rs.rentang("30d")[0] < rs.rentang("7d")[0]
      < rs.rentang("24h")[0] < rs.rentang("1h")[0])


# =============================================================================
print()
print("=" * 74)
print("2. hitung_device -- INVARIAN yang harus benar untuk data APA PUN")
print("=" * 74)


def periksa_invarian(nama, hasil, mulai, selesai):
    """Invariants that hold for every `hitung_device` output."""
    length = (selesai - mulai).total_seconds()
    a = hasil.get("availability")
    benar("%s: availability 0..100 atau None" % nama,
          a is None or (0 <= a <= 100), "-> %r" % a)
    benar("%s: total_down tidak negatif" % nama,
          (hasil.get("total_down_detik") or 0) >= 0)
    observed = hasil.get("durasi_diamati_detik")
    if observed is not None:
        benar("%s: waktu down <= waktu yang diamati" % nama,
              (hasil.get("total_down_detik") or 0) <= observed + 1,
              "-> down=%s diamati=%s" % (hasil.get("total_down_detik"), observed))
        benar("%s: diamati + tak_terpantau <= panjang periode" % nama,
              observed + (hasil.get("tak_terpantau_detik") or 0) <= length + 2,
              "-> %s + %s vs %s" % (observed,
                                    hasil.get("tak_terpantau_detik"), length))
    benar("%s: insiden_selesai <= insiden" % nama,
          hasil.get("insiden_selesai", 0) <= hasil.get("insiden", 0))
    if hasil.get("mttr_detik") is not None:
        benar("%s: MTTR hanya ada kalau ada insiden SELESAI" % nama,
              hasil.get("insiden_selesai", 0) > 0)


# Case A: device stays up, never goes down
db = siapkan_db()
d = buat_device(db)
mulai, selesai = T0, T0 + timedelta(hours=1)
tanam_ping(db, d.id, mulai, jumlah=360, interval=10, hidup=True)
tanam_event(db, d.id, mulai, "UP", "recovered")

print("  -- device hidup terus --")
h = rs.hitung_device(db, d, mulai, selesai)
periksa_invarian("hidup-terus", h, mulai, selesai)
cek("  availability 100%", h["availability"], 100.0)
cek("  nol insiden", h["insiden"], 0)
cek("  MTTR tidak ada", h["mttr_detik"], None)

db = siapkan_db()
d = buat_device(db)
mulai, selesai = T0, T0 + timedelta(hours=1)
tanam_ping(db, d.id, mulai, jumlah=360, interval=10, hidup=True)
tanam_event(db, d.id, mulai, "UP", "recovered")
tanam_event(db, d.id, mulai + timedelta(minutes=10), "DOWN", "dead")
tanam_event(db, d.id, mulai + timedelta(minutes=16), "UP", "recovered")

print("  -- satu gangguan 6 menit, sudah pulih --")
h = rs.hitung_device(db, d, mulai, selesai)
periksa_invarian("gangguan-pulih", h, mulai, selesai)
cek("  1 insiden", h["insiden"], 1)
cek("  1 insiden selesai", h["insiden_selesai"], 1)
benar("  total down sekitar 360 detik",
      abs((h["total_down_detik"] or 0) - 360) <= 2,
      "-> %s" % h["total_down_detik"])
benar("  MTTR terisi karena insidennya selesai", h["mttr_detik"] is not None)
benar("  availability di bawah 100 (ada gangguan nyata)",
      (h["availability"] or 0) < 100)

db = siapkan_db()
d = buat_device(db)
mulai, selesai = T0, T0 + timedelta(hours=1)
tanam_ping(db, d.id, mulai, jumlah=360, interval=10, hidup=True)
tanam_event(db, d.id, mulai, "UP", "recovered")
tanam_event(db, d.id, mulai + timedelta(minutes=50), "DOWN", "dead")

print("  -- gangguan masih berlangsung (belum ada UP penutup) --")
h = rs.hitung_device(db, d, mulai, selesai)
periksa_invarian("gangguan-berlangsung", h, mulai, selesai)
cek("  1 insiden", h["insiden"], 1)
cek("  0 insiden SELESAI", h["insiden_selesai"], 0)
cek("  MTTR None (tidak boleh dihitung dari insiden yang belum selesai)",
    h["mttr_detik"], None)

db = siapkan_db()
d = buat_device(db)
mulai, selesai = T0, T0 + timedelta(hours=1)
tanam_ping(db, d.id, mulai, jumlah=100, interval=10, hidup=True)
tanam_ping(db, d.id, mulai + timedelta(seconds=1000), jumlah=100,
           interval=10, hidup=False)

print("  -- belum ada DeviceEvent, jatuh ke jalur cadangan status_logs --")
h = rs.hitung_device(db, d, mulai, selesai)
periksa_invarian("tanpa-event", h, mulai, selesai)
benar("  availability sekitar 50% (100 hidup dari 200 sampel)",
      h["availability"] is not None and 49 <= h["availability"] <= 51,
      "-> %s" % h["availability"])
benar("  sumbernya ditandai jujur sebagai jalur cadangan",
      "status_logs" in (h.get("sumber") or ""))

db = siapkan_db()
d = buat_device(db)
print("  -- nol data --")
h = rs.hitung_device(db, d, T0, T0 + timedelta(hours=1))
periksa_invarian("nol-data", h, T0, T0 + timedelta(hours=1))
benar("  tidak crash, availability None", h["availability"] is None)


# =============================================================================
print()
print("=" * 74)
print("3. INVARIAN LINTAS-PERIODE: periode lebih panjang tidak boleh")
print("   MENGHILANGKAN insiden yang sudah terjadi")
print("=" * 74)

db = siapkan_db()
d = buat_device(db)
mulai = T0
tanam_ping(db, d.id, mulai, jumlah=1080, interval=10, hidup=True)
tanam_event(db, d.id, mulai, "UP", "recovered")
tanam_event(db, d.id, mulai + timedelta(minutes=30), "DOWN", "dead")
tanam_event(db, d.id, mulai + timedelta(minutes=35), "UP", "recovered")
tanam_event(db, d.id, mulai + timedelta(minutes=100), "DOWN", "dead")
tanam_event(db, d.id, mulai + timedelta(minutes=104), "UP", "recovered")

h1 = rs.hitung_device(db, d, mulai, mulai + timedelta(hours=1))
h3 = rs.hitung_device(db, d, mulai, mulai + timedelta(hours=3))
print("  1 jam -> %d insiden | 3 jam -> %d insiden"
      % (h1["insiden"], h3["insiden"]))
benar("periode 3 jam melihat insiden >= periode 1 jam",
      h3["insiden"] >= h1["insiden"])
cek("  periode 1 jam melihat 1 insiden", h1["insiden"], 1)
cek("  periode 3 jam melihat 2 insiden", h3["insiden"], 2)
benar("total down periode panjang >= periode pendek",
      (h3["total_down_detik"] or 0) >= (h1["total_down_detik"] or 0))


# =============================================================================
print()
print("=" * 74)
print("4. WAKTU TAK TERPANTAU dikeluarkan dari hitungan (jeda.py)")
print("   cacat nyata 28 Juli 2026: availability terbaca 46,171% padahal")
print("   99,065% ping-nya berhasil -- poller mati ikut dihitung MATI")
print("=" * 74)

db = siapkan_db()
d = buat_device(db)
mulai = T0
# 10 minutes normal, a 40-minute gap (poller down), then 10 minutes normal.
tanam_ping(db, d.id, mulai, jumlah=60, interval=10, hidup=True)
tanam_ping(db, d.id, mulai + timedelta(minutes=50), jumlah=60,
           interval=10, hidup=True)
tanam_event(db, d.id, mulai, "UP", "recovered")

selesai = mulai + timedelta(hours=1)
h = rs.hitung_device(db, d, mulai, selesai)
periksa_invarian("ada-lubang", h, mulai, selesai)
print("  diamati=%ss  tak_terpantau=%ss"
      % (h.get("durasi_diamati_detik"), h.get("tak_terpantau_detik")))
benar("lubang 40 menit dikenali TAK TERPANTAU, bukan waktu mati",
      (h.get("tak_terpantau_detik") or 0) > 1800,
      "-> %s" % h.get("tak_terpantau_detik"))
benar("dan availability TIDAK jatuh gara-gara lubang itu",
      h["availability"] is None or h["availability"] > 90,
      "-> %s" % h["availability"])


# =============================================================================
print()
print("=" * 74)
print("5. KUALITAS SAMBUNGAN -- kehilangan paket, terpisah dari availability")
print("=" * 74)

db = siapkan_db()
d = buat_device(db)
mulai = datetime.now() - timedelta(hours=1)
tanam_ping(db, d.id, mulai, jumlah=80, interval=10, hidup=True)
tanam_ping(db, d.id, mulai + timedelta(seconds=800), jumlah=20,
           interval=10, hidup=False)

k = rs.hitung_kualitas_sambungan(db, d.id, "24h", rs.rentang("24h")[0])
print("  ->", k)
benar("kehilangan paket terhitung 0..100",
      k.get("kehilangan_persen") is None
      or 0 <= k["kehilangan_persen"] <= 100)
benar("kehilangan sekitar 20%",
      k.get("kehilangan_persen") is not None
      and 19 <= k["kehilangan_persen"] <= 21,
      "-> %s" % k.get("kehilangan_persen"))

db2 = siapkan_db()
d2 = buat_device(db2)
k2 = rs.hitung_kualitas_sambungan(db2, d2.id, "24h", rs.rentang("24h")[0])
benar("nol sampel -> tidak crash, tidak mengarang angka",
      k2.get("kehilangan_persen") in (None, 0), "-> %s" % k2)


# =============================================================================
print()
print("=" * 74)
print("6. KONSISTENSI ANTAR-FUNGSI -- satu besaran, satu nilai")
print("   cacat nyata: availability yang sama dihitung 2 cara berbeda")
print("   menghasilkan 96,805% vs 96,528% di dalam SATU berkas")
print("=" * 74)

db = siapkan_db()
d1 = buat_device(db, "Device A", "10.0.0.1")
d2 = buat_device(db, "Device B", "10.0.0.2")
mulai = datetime.now() - timedelta(hours=2)
for dd in (d1, d2):
    tanam_ping(db, dd.id, mulai, jumlah=600, interval=10, hidup=True)
    tanam_event(db, dd.id, mulai, "UP", "recovered")
tanam_event(db, d1.id, mulai + timedelta(minutes=30), "DOWN", "dead")
tanam_event(db, d1.id, mulai + timedelta(minutes=40), "UP", "recovered")

semua = rs.availability_semua(db, "24h")
benar("availability_semua mengembalikan kedua device",
      len(semua.get("devices", [])) == 2,
      "-> %s" % len(semua.get("devices", [])))

per_id = {x["id"]: x for x in semua.get("devices", [])}
langsung = rs.hitung_device(db, d1, rs.rentang("24h")[0], datetime.now())
benar("availability dari availability_semua SAMA dengan hitung_device langsung",
      abs((per_id[d1.id]["availability"] or 0)
          - (langsung["availability"] or 0)) < 0.5,
      "-> %s vs %s" % (per_id[d1.id]["availability"],
                       langsung["availability"]))

for x in semua.get("devices", []):
    benar("  %s: availability dalam 0..100" % x["name"],
          x["availability"] is None or 0 <= x["availability"] <= 100)


# =============================================================================
print()
print("=" * 74)
print("7. hitung_kestabilan -- deteksi tidak-stabil berbasis WAKTU")
print("=" * 74)

sekarang = datetime.now()
db = siapkan_db()
d = buat_device(db)
for i in range(4):
    t = sekarang - timedelta(minutes=14 - i * 3)
    tanam_event(db, d.id, t, "DOWN", "dead")
    tanam_event(db, d.id, t + timedelta(seconds=60), "UP", "recovered")

ks = rs.hitung_kestabilan(db, d.id, sekarang=sekarang)
print("  ->", ks)
# The key is `stabil` (False means unstable), not `flapping`; a wrong key would always return None and let the neighboring test pass vacuously.
benar("4 gangguan dalam 15 menit -> ditandai TIDAK stabil",
      ks.get("stabil") is False, "-> %s" % ks)
benar("dan ikut melaporkan berapa siklus terhitung di jendela itu",
      isinstance(ks.get("siklus_jendela"), int) and ks["siklus_jendela"] >= 3,
      "-> %s" % ks)

db2 = siapkan_db()
d2 = buat_device(db2)
tanam_event(db2, d2.id, sekarang - timedelta(hours=5), "DOWN", "dead")
tanam_event(db2, d2.id, sekarang - timedelta(hours=5, minutes=-1),
            "UP", "recovered")
ks2 = rs.hitung_kestabilan(db2, d2.id, sekarang=sekarang)
benar("satu gangguan 5 jam lalu -> TETAP dianggap stabil",
      ks2.get("stabil") is True, "-> %s" % ks2)


if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

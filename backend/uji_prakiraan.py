"""Tests for the bandwidth, latency and error-budget forecasts.
A forecast must refuse to answer when data is insufficient, and must answer when data is enough; each section tests both.
Pure test: temporary SQLite, no network.
Run: py uji_prakiraan.py
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
        print("  LOLOS  %s" % nama)
    else:
        gagal += 1
        print("  GAGAL  %s %s" % (nama, ket))


def cek(nama, dapat, harap):
    global lolos, gagal
    if dapat == harap:
        lolos += 1
        print("  LOLOS  %s: %r" % (nama, dapat))
    else:
        gagal += 1
        print("  GAGAL  %s: dapat %r, harusnya %r" % (nama, dapat, harap))


import kapasitas as K  # noqa: E402
import models  # noqa: E402
import prakiraan as P  # noqa: E402

SEKARANG = datetime(2026, 8, 23, 12, 0, 0)


def siapkan_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    file = os.path.join(tempfile.mkdtemp(prefix="uji_prakiraan_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    d = models.Device(name="Router Lokasi A", ip_address="192.168.56.60",
                      device_type="router", platform="cisco_ios", aktif=True)
    db.add(d)
    db.commit()
    return db, d


print("=" * 74)
print("Uji PAKET C3 -- prakiraan yang diperluas")
print("=" * 74)

# ===========================================================================
print("\n1. BANDWIDTH: data tipis -> MENOLAK meramal")
db, dev = siapkan_db()
for i in range(10):
    db.add(models.BandwidthSample(
        device_id=dev.id, iface="Fa0/0",
        timestamp=SEKARANG - timedelta(hours=i),
        in_bps=1e6, out_bps=5e5, source="snmp"))
db.commit()
h = P.bandwidth_device(db, dev.id, sekarang=SEKARANG)
cek("10 sampel -> tidak cukup", h["vonis"], K.TIDAK_CUKUP)
cek("dan tidak menerbitkan angka", h["hari_menuju_penuh"], None)
benar("alasannya menyebut angkanya", "10 sampel" in h["alasan"],
      "-> %r" % h["alasan"])

# ===========================================================================
print("\n2. BANDWIDTH: tren naik yang jelas -> MENJAWAB (pasangannya)")
db2, dev2 = siapkan_db()
# 14 days, 6 samples per day; the daily peak rises 2 Mbit/s per day.
for hari in range(14):
    puncak = 10e6 + hari * 2e6
    for j in range(6):
        db2.add(models.BandwidthSample(
            device_id=dev2.id, iface="Fa0/0",
            timestamp=SEKARANG - timedelta(days=13 - hari, hours=j * 3),
            in_bps=puncak * (0.4 if j else 1.0),
            out_bps=1e5, source="snmp"))
db2.commit()

h2 = P.bandwidth_device(db2, dev2.id, sekarang=SEKARANG)
cek("tanpa kapasitas -> vonis kapasitas_tak_diketahui", h2["vonis"],
    P.KAPASITAS_TAK_DIKETAHUI)
cek("dan hari menuju penuh tetap None", h2["hari_menuju_penuh"], None)
benar("tetapi lajunya TETAP terukur",
      h2["laju_bps_per_hari"] is not None and h2["laju_bps_per_hari"] > 1e6,
      "-> %r" % h2["laju_bps_per_hari"])
benar("alasannya menjelaskan kenapa tidak bisa dijawab",
      "kapasitas" in h2["alasan"].lower(), "-> %r" % h2["alasan"])
print("       %s" % h2["alasan"])

h3 = P.bandwidth_device(db2, dev2.id, kapasitas_bps=100e6, sekarang=SEKARANG)
cek("dengan kapasitas -> vonis cukup", h3["vonis"], K.CUKUP)
benar("puncaknya sekitar 36% dari 100 Mbit/s",
      30 < h3["pakai_persen"] < 42, "-> %r" % h3["pakai_persen"])
benar("penuh dalam puluhan hari, bukan None",
      h3["hari_menuju_penuh"] is not None and 20 < h3["hari_menuju_penuh"] < 60,
      "-> %r" % h3["hari_menuju_penuh"])
print("       %s" % h3["alasan"])

# ===========================================================================
print("\n3. BANDWIDTH: yang MENURUN dilaporkan apa adanya, bukan disembunyikan")
db3, dev3 = siapkan_db()
for hari in range(14):
    puncak = 40e6 - hari * 2e6
    for j in range(6):
        db3.add(models.BandwidthSample(
            device_id=dev3.id, iface="Fa0/0",
            timestamp=SEKARANG - timedelta(days=13 - hari, hours=j * 3),
            in_bps=puncak, out_bps=1e5, source="snmp"))
db3.commit()
h4 = P.bandwidth_device(db3, dev3.id, kapasitas_bps=100e6, sekarang=SEKARANG)
cek("tren turun -> vonis menurun", h4["vonis"], K.MENURUN)
benar("dan tidak mengarang kejenuhan", h4.get("hari_menuju_penuh") is None,
      "-> %r" % h4.get("hari_menuju_penuh"))

# ===========================================================================
print("\n4. LATENCY: nama kolom rollup benar-benar dipakai")
# The forecast must not silently report "not enough data" because of a misspelled column name (`latency_sampel`).
db4, dev4 = siapkan_db()
for jam in range(24 * 20):
    ms = 100.0 + jam * 0.05                      # naik perlahan
    db4.add(models.StatusRollupJam(
        device_id=dev4.id, jam=SEKARANG - timedelta(hours=24 * 20 - jam),
        sampel=720, sampel_naik=720,
        latency_jumlah=ms * 720, latency_sampel=720,
        latency_min=ms - 5, latency_maks=ms + 5))
db4.commit()

h5 = P.latency_device(db4, dev4.id, sekarang=SEKARANG)
benar("BUKAN 'tidak cukup data' -- kolomnya terbaca",
      h5["vonis"] != K.TIDAK_CUKUP,
      "-> %r; kalau ini 'tidak_cukup_data', nama kolom rollup salah lagi"
      % h5["vonis"])
benar("latency sekarang sekitar 124 ms",
      h5["latency_kini_ms"] is not None and 118 < h5["latency_kini_ms"] < 130,
      "-> %r" % h5["latency_kini_ms"])
benar("lajunya positif dan masuk akal (% per minggu)",
      h5["laju_persen_per_minggu"] is not None
      and 3 < h5["laju_persen_per_minggu"] < 12,
      "-> %r" % h5["laju_persen_per_minggu"])
print("       %s" % h5["alasan"])

# ===========================================================================
print("\n5. LATENCY: yang DATAR tidak dilaporkan sebagai tren")
db5, dev5 = siapkan_db()
for jam in range(24 * 20):
    db5.add(models.StatusRollupJam(
        device_id=dev5.id, jam=SEKARANG - timedelta(hours=24 * 20 - jam),
        sampel=720, sampel_naik=720,
        latency_jumlah=100.0 * 720, latency_sampel=720,
        latency_min=95, latency_maks=105))
db5.commit()
h6 = P.latency_device(db5, dev5.id, sekarang=SEKARANG)
benar("laju mendekati nol",
      abs(h6.get("laju_persen_per_minggu") or 0.0) < 1.0,
      "-> %r" % h6.get("laju_persen_per_minggu"))
benar("kalimatnya mengatakan datar", "datar" in h6["alasan"].lower(),
      "-> %r" % h6["alasan"])

# ===========================================================================
print("\n6. LATENCY: rollup TANPA sampel dilewati, tidak dibagi nol")
db6, dev6 = siapkan_db()
for jam in range(24 * 20):
    db6.add(models.StatusRollupJam(
        device_id=dev6.id, jam=SEKARANG - timedelta(hours=24 * 20 - jam),
        sampel=0, sampel_naik=0, latency_jumlah=None, latency_sampel=0))
db6.commit()
h7 = P.latency_device(db6, dev6.id, sekarang=SEKARANG)
cek("seluruh jam kosong -> tidak cukup", h7["vonis"], K.TIDAK_CUKUP)
cek("dan latency sekarang None, bukan 0", h7["latency_kini_ms"], None)

# ===========================================================================
print("\n7. HORIZON dibatasi: tidak ada '1.482 hari'")
hari, teks = P._horizon(2000.0)
cek("di atas setahun -> hari None", hari, None)
cek("dan disebut 'lebih dari setahun'", teks, "lebih dari setahun")
hari2, teks2 = P._horizon(12.0)
cek("di dalam jangkauan -> angkanya diberikan", hari2, 12.0)
cek("dengan teks yang wajar", teks2, "12 hari")

# ===========================================================================
print("\n8. Laju bandwidth ditulis dalam satuan yang bisa dibaca")
cek("juta bit", P._laju_teks(2.5e6), "naik 2.50 Mbit/s per hari")
cek("ribu bit", P._laju_teks(1500.0), "naik 1.5 kbit/s per hari")
cek("menurun disebut menurun", P._laju_teks(-2.5e6),
    "turun 2.50 Mbit/s per hari")
cek("tidak terukur", P._laju_teks(None), "tidak terukur")

# ===========================================================================
print("\n9. Ringkasan `semua` tidak jatuh pada basis data yang miskin data")
db7, dev7 = siapkan_db()
r = P.semua(db7, sekarang=SEKARANG)
benar("mengembalikan ketiga bagian",
      all(k in r for k in ("bandwidth", "latency", "anggaran")),
      "-> %r" % sorted(r))
benar("dan tidak melempar walau datanya kosong", True)

# ===========================================================================
print("\n10. VONIS dan KALIMAT tidak boleh saling membantah")
# If the rate (percent) is None the verdict must not be `cukup`: the page and the SOC agent rely only on that number.
db10, dev10 = siapkan_db()
for jam in range(24 * 20):
    db10.add(models.StatusRollupJam(
        device_id=dev10.id, jam=SEKARANG - timedelta(hours=24 * 20 - jam),
        sampel=720, sampel_naik=720,
        latency_jumlah=0.0, latency_sampel=720,
        latency_min=0.0, latency_maks=0.0))
db10.commit()
h10 = P.latency_device(db10, dev10.id, sekarang=SEKARANG)
benar("laju persen memang tidak bisa dihitung",
      h10.get("laju_persen_per_minggu") is None,
      "-> %r" % h10.get("laju_persen_per_minggu"))
# Must be exactly `tidak_cukup_data`, not merely "not cukup" (`tidak_yakin` must not pass).
cek("vonisnya tidak_cukup_data, bukan tidak_yakin", h10["vonis"],
    K.TIDAK_CUKUP)
benar("dan kalimatnya cocok dengan vonisnya",
      "belum bisa diukur" in h10["alasan"] or "belum" in h10["alasan"],
      "-> %r" % h10["alasan"])

h10b = P.latency_device(db4, dev4.id, sekarang=SEKARANG)
benar("data yang lajunya terukur tetap boleh bervonis cukup/tidak_yakin",
      h10b["laju_persen_per_minggu"] is not None,
      "-> %r" % h10b.get("laju_persen_per_minggu"))

print()
print("=" * 74)
print("%d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

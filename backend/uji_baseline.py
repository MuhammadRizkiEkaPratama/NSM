"""Tests for the per-device, hour-of-week behavior baseline.

A module computing "deviation from habit" fails without raising: it yields
confidently wrong numbers. So section 2 compares the formula against
`river.stats.EWMean` (a widely used third-party library) rather than numbers
computed by hand. River is used only here, not in the app: it pulls in numpy +
scipy (+102.7 MB RSS). If river is not installed, that section is SKIPPED with a
message, not counted as passed.

Pure test: temporary SQLite, no network.

Run: py uji_baseline.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

lolos = 0
gagal = 0
dilewati = 0


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


def dekat(nama, dapat, harap, toleransi=1e-9):
    global lolos, gagal
    if dapat is not None and abs(dapat - harap) <= toleransi:
        lolos += 1
        print("  LOLOS  %s: %.10g (harap %.10g)" % (nama, dapat, harap))
    else:
        gagal += 1
        print("  GAGAL  %s: dapat %r, harusnya %.10g +- %g"
              % (nama, dapat, harap, toleransi))


import baseline as B  # noqa: E402
import models  # noqa: E402

SENIN = datetime(2026, 8, 17, 0, 0, 0)      # 17 Agustus 2026 = Senin


def siapkan_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    file = os.path.join(tempfile.mkdtemp(prefix="uji_baseline_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    d = models.Device(name="LDAP", ip_address="192.168.20.101",
                      device_type="server", platform="linux", aktif=True)
    db.add(d)
    db.commit()
    return db, d


print("=" * 74)
print("Uji PAKET C1 -- baseline perilaku")
print("=" * 74)

# ===========================================================================
print("\n1. SLOT jam-dalam-minggu dihitung benar")
cek("Senin 00.00 -> slot 0", B.slot_dari(SENIN), 0)
cek("Senin 13.00 -> slot 13", B.slot_dari(SENIN + timedelta(hours=13)), 13)
cek("Selasa 00.00 -> slot 24", B.slot_dari(SENIN + timedelta(days=1)), 24)
cek("Sabtu 20.00 -> slot 140",
    B.slot_dari(SENIN + timedelta(days=5, hours=20)), 5 * 24 + 20)
cek("Minggu 23.00 -> slot 167",
    B.slot_dari(SENIN + timedelta(days=6, hours=23)), 167)

# The explanatory sentence must name the correct day.
cek("slot 140 disebut 'Sabtu pukul 20.00'", B.sebut_slot(140),
    "Sabtu pukul 20.00")
cek("slot 0 disebut 'Senin pukul 00.00'", B.sebut_slot(0), "Senin pukul 00.00")

# ===========================================================================
print("\n2. RUMUS EWMA dibandingkan dengan RIVER, bukan dengan diri sendiri")
DERET = [40, 41, 39, 42, 38, 40, 44, 37, 41, 40, 43, 39, 40, 42, 41, 38,
         40, 39, 41, 40, 45, 36, 40, 41, 39, 42, 40, 38, 41, 40]

ewma = ewmd = None
n = 0
for x in DERET:
    ewma, ewmd, n = B.lipat(ewma, ewmd, n, float(x))
cek("cacah sampel", n, len(DERET))

try:
    from river import stats
    # River's `fading_factor` is the weight of the NEW sample, not the decay of old
    # values. With ff=ALPHA, River gives 10 / 10.5 / 11.475 for [10, 20, 30], matching
    # this module and the hand formula m <- a*x + (1-a)*m. Passing `1 - ALPHA` gives a
    # mean that almost entirely follows the last sample.
    r = stats.EWMean(fading_factor=B.ALPHA)
    for x in DERET:
        r.update(float(x))
    dekat("EWMA kami sama dengan river.stats.EWMean", ewma, r.get(), 1e-9)
    print("       kami %.10f | river %.10f" % (ewma, r.get()))

    # Counterpart: prove this comparison can actually FAIL.
    salah = stats.EWMean(fading_factor=1.0 - B.ALPHA)
    for x in DERET:
        salah.update(float(x))
    benar("dan perbandingannya BISA gagal (bobot keliru -> angka berbeda)",
          abs(ewma - salah.get()) > 1e-6,
          "-> keduanya sama; berarti perbandingan di atas tidak membuktikan apa-apa")
except ImportError:
    dilewati += 1
    print("  [LEWAT] river tidak terpasang di lingkungan ini. Perbandingan")
    print("          rumus DILEWATI, bukan dianggap lolos.")
    print("          Pasang dengan: venv\\Scripts\\pip install river")

# Hand calculation for the first two samples, a second check independent of any library.
e2, d2, n2 = B.lipat(None, None, 0, 100.0)
cek("sampel pertama jadi nilai awal apa adanya", (e2, d2, n2), (100.0, 0.0, 1))
e3, d3, n3 = B.lipat(100.0, 0.0, 1, 200.0)
dekat("EWMA sesudah sampel kedua", e3, 0.05 * 200 + 0.95 * 100, 1e-12)
dekat("simpangan sesudah sampel kedua", d3, 0.05 * 100.0, 1e-12)

# ===========================================================================
print("\n3. KONSTANTA pengubah ke sigma: 1,2533 (mean AD), BUKAN 1,4826")
# For a normal distribution, E|X-mu| = sigma*sqrt(2/pi), so sigma = mean deviation * 1.2533.
# Using 1.4826 (for MEDIAN absolute deviation) would overstate sigma by 18%.
import math  # noqa: E402
dekat("KE_SIGMA = 1/sqrt(2/pi)", B.KE_SIGMA, 1.0 / math.sqrt(2.0 / math.pi),
      0.0005)
benar("dan BUKAN 1,4826", abs(B.KE_SIGMA - 1.4826) > 0.2,
      "-> %r" % B.KE_SIGMA)

# ===========================================================================
print("\n4. MENOLAK MENILAI selama buktinya masih tipis")
cek("n di bawah ambang -> None", B.sigma(999.0, 40.0, 2.0, 5), None)
cek("n = MIN_SAMPEL-1 -> masih None",
    B.sigma(999.0, 40.0, 2.0, B.MIN_SAMPEL - 1), None)
benar("n = MIN_SAMPEL -> sudah menilai",
      B.sigma(999.0, 40.0, 2.0, B.MIN_SAMPEL) is not None)
# None is distinct from 0.0: zero means "exactly as usual", None means "habit not known yet".
s_normal = B.sigma(40.0, 40.0, 2.0, 100)
dekat("nilai persis seperti biasanya -> sigma 0", s_normal, 0.0, 1e-9)
benar("dan itu BUKAN None", s_normal is not None)

# ===========================================================================
print("\n5. Contoh dari dokumen rencana: 40 ms jadi 260 ms")
# Simpangan rata-rata 4 ms -> simpangan baku ~5,01 ms -> (260-40)/5,01 = 43,9
s = B.sigma(260.0, 40.0, 4.0, 200, metrik="latency")
benar("terbaca sangat menyimpang", s is not None and s > 20, "-> %r" % s)
kal = B.kalimat("LDAP", "latency", 140, 260.0, 40.0, s)
print("       %s" % kal)
benar("kalimatnya menyebut kebiasaan, jam, nilai sekarang, dan simpangan",
      all(k in kal for k in ("LDAP", "40.0", "Sabtu pukul 20.00", "260.0",
                             "simpangan")),
      "-> %r" % kal)

# ===========================================================================
print("\n6. LANTAI simpangan: device sangat stabil tidak melapor 50 sigma")
# LAN web server: always 0.4 ms with near-zero deviation. Without a floor, one 0.9 ms
# sample gives a huge sigma and alarms fire for half a millisecond.
s_stabil = B.sigma(0.9, 0.4, 0.0001, 500, metrik="latency")
benar("simpangan 0,5 ms pada device 0,4 ms TIDAK dianggap gawat",
      s_stabil is not None and s_stabil < 3.0, "-> %r" % s_stabil)

# Counterpart: the floor must not blind the module. The same device 500x slower MUST read as critical.
s_parah = B.sigma(200.0, 0.4, 0.0001, 500, metrik="latency")
benar("tetapi 200 ms pada device 0,4 ms TETAP terbaca gawat",
      s_parah is not None and s_parah >= 10.0, "-> %r" % s_parah)

# ===========================================================================
print("\n7. Skor dipotong -- ketepatan palsu tidak menambah informasi")
s_gila = B.sigma(1e9, 40.0, 1.0, 500)
cek("sigma dipotong di batas atas", s_gila, B.SIGMA_MAKS)

# ===========================================================================
print("\n8. Melipat dari status_logs: tidak ada baris yang terhitung dua kali")
db, dev = siapkan_db()
# 30 samples in the same slot (Monday 09:00).
for i in range(30):
    db.add(models.StatusLog(device_id=dev.id,
                            timestamp=SENIN + timedelta(hours=9, seconds=i * 10),
                            is_reachable=True,
                            response_time_ms=40.0 + (i % 5) - 2))
# FAILED ping, which must not be folded in: `response_time_ms` is empty.
for i in range(5):
    db.add(models.StatusLog(device_id=dev.id,
                            timestamp=SENIN + timedelta(hours=9, minutes=10, seconds=i),
                            is_reachable=False, response_time_ms=None))
db.commit()

h1 = B.perbarui_latency(db)
cek("30 sampel berhasil dibaca (yang gagal dilewati)", h1["dibaca"], 30)
cek("satu slot tersentuh", h1["slot_disentuh"], 1)

b = db.query(models.BaselinePerilaku).one()
cek("slotnya Senin 09.00", b.slot, 9)
cek("cacahnya 30", b.n, 30)

# A SECOND round must fold nothing again; otherwise the deviation shrinks toward zero and every normal value reads as a big anomaly.
ewma_sebelum, ewmd_sebelum, n_sebelum = b.ewma, b.ewmd, b.n
h2 = B.perbarui_latency(db)
cek("putaran kedua tidak membaca apa pun", h2["dibaca"], 0)
db.refresh(b)
cek("cacahnya tidak berubah", b.n, n_sebelum)
dekat("dan kebiasaannya tidak bergeser", b.ewma, ewma_sebelum, 1e-12)

# ===========================================================================
print("\n9. Slot BERBEDA belajar sendiri-sendiri")
# This is why hour-of-week slots exist: LDAP on Saturday night may behave differently from Monday morning.
for i in range(30):
    db.add(models.StatusLog(
        device_id=dev.id,
        timestamp=SENIN + timedelta(days=5, hours=20, seconds=i * 10),
        is_reachable=True, response_time_ms=250.0 + (i % 3)))
db.commit()
B.perbarui_latency(db)

semua = {x.slot: x for x in db.query(models.BaselinePerilaku).all()}
cek("dua slot terpisah", sorted(semua), [9, 140])
benar("Senin pagi tetap sekitar 40 ms", 35 < semua[9].ewma < 45,
      "-> %r" % semua[9].ewma)
benar("Sabtu malam sekitar 250 ms", 240 < semua[140].ewma < 260,
      "-> %r" % semua[140].ewma)

s_sabtu = B.sigma(250.0, semua[140].ewma, semua[140].ewmd, semua[140].n)
s_senin = B.sigma(250.0, semua[9].ewma, semua[9].ewmd, semua[9].n)
benar("250 ms pada Sabtu malam = wajar", s_sabtu is not None and s_sabtu < 3,
      "-> %r" % s_sabtu)
benar("250 ms pada Senin pagi = sangat aneh",
      s_senin is not None and s_senin > 10, "-> %r" % s_senin)
print("       Sabtu %.2f sigma | Senin %.2f sigma" % (s_sabtu, s_senin))

# ===========================================================================
print("\n10. `nilai_sekarang` menyatakan 'belum bisa dinilai', tidak menyamarkan")
db2, dev2 = siapkan_db()
h = B.nilai_sekarang(db2, dev2.id)
cek("tanpa sampel sama sekali -> tidak layak", h["layak"], False)
benar("alasannya disebutkan", bool(h.get("alasan")), "-> %r" % h)
cek("dan sigmanya None, bukan 0", h["sigma"], None)

h3 = B.nilai_sekarang(db, dev.id,
                      waktu=SENIN + timedelta(days=5, hours=20), nilai=250.0)
cek("dengan baseline terisi -> layak dinilai", h3["layak"], True)
benar("dan membawa kalimatnya", "biasanya" in h3.get("kalimat", ""),
      "-> %r" % h3.get("kalimat"))

# ===========================================================================
print("\n11. Cakupan dilaporkan sebagai pecahan, bukan 'aktif/tidak'")
c = B.cakupan(db)
cek("dua slot terisi", c["slot_terisi"], 2)
cek("keduanya sudah layak", c["slot_layak"], 2)
cek("dari 168 slot yang mungkin per device", c["slot_mungkin"], 168)
benar("dan menyebut ambang sampelnya", c["min_sampel"] == B.MIN_SAMPEL)

# ===========================================================================
print("\n12. JENDELA BELAJAR: riwayat lama TIDAK dipakai, dan itu soal KEBENARAN")
# Regression from a real instance: a baseline learned from sample history before
# the topology changed (LDAP moved behind a WAN link) reported a 50-sigma alarm
# (0.8 ms "usual" vs 196.5 ms now). Only data inside the window may count.
db12, dev12 = siapkan_db()
KINI = SENIN + timedelta(days=30)  # well after the "old" data

# Times are computed FORWARD from one point, not backward from `KINI`: going backward
# crossed midnight and put the 40 samples into two hour slots, some below MIN_SAMPEL.
LAMA_MULAI = KINI - timedelta(days=40)
BARU_MULAI = KINI - timedelta(days=2)

# OLD data (40 days ago, OUTSIDE the window): fast device, 1 ms.
for i in range(40):
    db12.add(models.StatusLog(
        device_id=dev12.id, timestamp=LAMA_MULAI + timedelta(seconds=i * 10),
        is_reachable=True, response_time_ms=1.0))
# NEW data (2 days ago, INSIDE the window): slow device, 200 ms.
for i in range(40):
    db12.add(models.StatusLog(
        device_id=dev12.id, timestamp=BARU_MULAI + timedelta(seconds=i * 10),
        is_reachable=True, response_time_ms=200.0 + (i % 3)))
db12.commit()

h12 = B.perbarui_latency(db12, sekarang=KINI)
cek("hanya 40 sampel BARU yang dilipat, 40 yang lama dilompati",
    h12["dibaca"], 40)

b12 = db12.query(models.BaselinePerilaku).all()
cek("satu slot terbentuk", len(b12), 1)
benar("dan kebiasaannya sekitar 200 ms, BUKAN 1 ms",
      b12 and 190 < b12[0].ewma < 210,
      "-> %r; kalau ~1 ms, riwayat lama masih ikut dipelajari"
      % (b12[0].ewma if b12 else None))

s12 = B.sigma(200.0, b12[0].ewma, b12[0].ewmd, b12[0].n)
benar("200 ms terbaca WAJAR, bukan 50 sigma", s12 is not None and s12 < 3.0,
      "-> %r" % s12)

# ===========================================================================
print("\n13. 'Sedang mengejar' DINYATAKAN, bukan disembunyikan")
db13, dev13 = siapkan_db()
# Many new rows not yet folded in.
for i in range(B.AMBANG_MENGEJAR_BARIS + 500):
    db13.add(models.StatusLog(
        device_id=dev13.id, timestamp=SENIN + timedelta(seconds=i),
        is_reachable=True, response_time_ms=40.0))
db13.commit()

k13 = B.mengejar(db13)
benar("dinyatakan sedang mengejar", k13["mengejar"] is True, "-> %r" % k13)
benar("dan menyebut berapa baris tertinggal",
      k13["tertinggal"] > B.AMBANG_MENGEJAR_BARIS, "-> %r" % k13["tertinggal"])

r13 = B.ringkas(db13)
benar("ringkasan membawa penanda mengejar", r13["mengejar"] is True)
benar("dan kalimat peringatannya", bool(r13.get("catatan")),
      "-> %r" % r13.get("catatan"))
print("       %s" % r13.get("catatan"))

# Counterpart: after catching up, the flag MUST turn off.
for _ in range(10):
    if B.perbarui_latency(db13, sekarang=SENIN + timedelta(hours=2))["dibaca"] == 0:
        break
k13b = B.mengejar(db13)
benar("sesudah terkejar, penandanya MATI", k13b["mengejar"] is False,
      "-> tertinggal %r" % k13b["tertinggal"])
r13b = B.ringkas(db13)
cek("dan catatannya hilang", r13b.get("catatan"), None)

print()
print("=" * 74)
print("%d lolos, %d gagal, %d bagian dilewati" % (lolos, gagal, dilewati))
print("=" * 74)
sys.exit(1 if gagal else 0)

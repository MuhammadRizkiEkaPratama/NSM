"""Test of incident correlation.

Correlation can look successful while being wrong, since "fewer rows" always
looks like progress. There are two opposite failure modes:

  1. Merging too much: unrelated faults are fused into one incident.
  2. Merging too little: symptoms with a single root stay separate.

The tests check BOTH directions, not just that the count went down. Symptoms on
several devices with the SAME root must become ONE incident, while faults with
different roots must stay separate, even in the same second.

Pure test: temporary SQLite, no network.

Run: py uji_korelasi.py
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


import korelasi as K  # noqa: E402
import models  # noqa: E402


def siapkan_db():
    """Small topology: R1 -> R2 -> SW-B -> LDAP, plus a standalone WEB."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    file = os.path.join(tempfile.mkdtemp(prefix="uji_korelasi_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    # NSM itself must exist, with platform 'lokal'. `ketergantungan.titik_pandang()`
    # uses the `lokal` device as the root of every traversal; without it the whole
    # graph answers `tidak_bisa_dipastikan` and nothing gets merged (safe degradation).
    nama = ["NSM", "R1", "R2", "SW-B", "LDAP", "WEB"]
    dev = {}
    for i, n in enumerate(nama, start=1):
        d = models.Device(name=n, ip_address="192.168.9.%d" % i,
                          device_type="router" if n != "NSM" else "server",
                          platform="lokal" if n == "NSM" else "cisco_ios",
                          aktif=True)
        db.add(d)
        dev[n] = d
    db.commit()

    # Kabel: NSM-R1, R1-R2, R2-SW-B, SW-B-LDAP, R1-WEB
    for a, b in (("NSM", "R1"), ("R1", "R2"), ("R2", "SW-B"),
                 ("SW-B", "LDAP"), ("R1", "WEB")):
        db.add(models.DeviceLink(device_a_id=dev[a].id, device_b_id=dev[b].id))
    db.commit()
    return db, dev


SEKARANG = datetime(2026, 8, 23, 10, 0, 0)


def matikan(db, dev, nama, waktu=None):
    db.add(models.DeviceEvent(device_id=dev[nama].id, event_type="DOWN",
                              timestamp=waktu or SEKARANG))
    db.commit()


def hidupkan(db, dev, nama, waktu=None):
    db.add(models.DeviceEvent(device_id=dev[nama].id, event_type="UP",
                              timestamp=waktu or SEKARANG))
    db.commit()


# =============================================================================
print("=" * 74)
print("1. SATU AKAR -> SATU INSIDEN, walau gejalanya di banyak perangkat")
print("   Ini seluruh alasan Paket B ada.")
print("=" * 74)

db, dev = siapkan_db()
for n in ("R2", "SW-B", "LDAP"):
    matikan(db, dev, n)

h = K.proses(db, sekarang=SEKARANG)
print("   ->", h)
semua = db.query(models.Insiden).all()
benar("3 perangkat mati -> 1 insiden, bukan 3", len(semua) == 1,
      "-> %d insiden" % len(semua))
if semua:
    i = semua[0]
    akar = db.get(models.Device, i.akar_device_id)
    benar("akarnya R2 (yang paling hulu di antara yang mati)",
          akar is not None and akar.name == "R2",
          "-> %r" % (akar.name if akar else None))
    benar("ketiga gejala tercatat di insiden yang sama",
          i.jumlah_gejala == 3, "-> %r" % i.jumlah_gejala)
    benar("ringkasannya menyebut perangkat lain ikut terdampak",
          "terdampak" in (i.ringkas or ""), "-> %r" % i.ringkas)


# =============================================================================
print()
print("=" * 74)
print("2. AKAR BERBEDA -> TETAP TERPISAH, walau di detik yang sama")
print("   Ini arah gagal yang paling berbahaya: menggabung terlalu banyak")
print("   membuat angkanya TERLIHAT lebih bagus sambil menghasilkan insiden")
print("   yang menceritakan dua cerita sekaligus.")
print("=" * 74)

db2, dev2 = siapkan_db()
matikan(db2, dev2, "R2")      # cabang kiri
matikan(db2, dev2, "WEB")
K.proses(db2, sekarang=SEKARANG)
semua2 = db2.query(models.Insiden).all()
akar2 = sorted((db2.get(models.Device, i.akar_device_id).name) for i in semua2)
print("   -> %d insiden, akar: %s" % (len(semua2), akar2))
benar("dua gangguan tak berhubungan -> DUA insiden", len(semua2) == 2,
      "-> %d" % len(semua2))
benar("akarnya R2 dan WEB, masing-masing sendiri",
      akar2 == ["R2", "WEB"], "-> %r" % akar2)


# =============================================================================
print()
print("=" * 74)
print("3. DEDUPLIKASI: gejala berulang menaikkan hitungan, bukan baris")
print("   Satu perangkat yang berkedip seratus kali tidak boleh menghasilkan")
print("   seratus baris yang menceritakan hal yang sama.")
print("=" * 74)

db3, dev3 = siapkan_db()
matikan(db3, dev3, "R2")
for k in range(5):
    K.proses(db3, sekarang=SEKARANG + timedelta(seconds=k * 10))
semua3 = db3.query(models.Insiden).all()
gejala3 = db3.query(models.InsidenGejala).all()
benar("5 putaran korelasi -> tetap 1 insiden", len(semua3) == 1,
      "-> %d" % len(semua3))
benar("...dan tetap 1 baris gejala", len(gejala3) == 1,
      "-> %d" % len(gejala3))
if gejala3:
    benar("hitungannya yang naik (5x)", gejala3[0].jumlah == 5,
          "-> %r" % gejala3[0].jumlah)


# =============================================================================
print()
print("=" * 74)
print("4. INSIDEN DITUTUP saat semua gejala pulih -- TAPI TIDAK SEKETIKA")
print("   Perangkat yang berkedip (pulih lalu mati lagi) harus tetap SATU")
print("   insiden. Menutup seketika membuat korelasi MEMPERBANYAK baris,")
print("   kebalikan dari gunanya.")
print("=" * 74)

db4, dev4 = siapkan_db()
matikan(db4, dev4, "R2")
K.proses(db4, sekarang=SEKARANG)
hidupkan(db4, dev4, "R2", SEKARANG + timedelta(seconds=30))

K.proses(db4, sekarang=SEKARANG + timedelta(seconds=40))
i4 = db4.query(models.Insiden).first()
benar("baru pulih 30 detik -> insiden MASIH terbuka",
      i4.status == "terbuka", "-> %r" % i4.status)

K.proses(db4, sekarang=SEKARANG + timedelta(seconds=K.JEDA_TUTUP_DETIK + 60))
db4.refresh(i4)
benar("sesudah jeda tutup lewat -> insiden PULIH", i4.status == "pulih",
      "-> %r" % i4.status)
benar("MTTR terisi", i4.mttr_detik is not None and i4.mttr_detik >= 0,
      "-> %r" % i4.mttr_detik)

# MTTR must be a correct number, not merely populated. Finish time is derived
# from when the device recovered as seen by a correlation round, not from the last
# time a symptom was seen broken; the two coincide with `mulai` for faults that
# recover before the next round. Here the device recovers at +30 s and the round
# that sees it runs at +40 s, so the correct MTTR is 40 s, not 0.
benar("MTTR = 40 dtk (saat pulihnya TERLIHAT), bukan 0",
      i4.mttr_detik == 40,
      "-> %r; 0 berarti waktu selesai lagi-lagi diambil dari "
      "`waktu_terakhir`, bukan dari waktu pulih" % i4.mttr_detik)

g4 = db4.query(models.InsidenGejala).all()
benar("waktu pulih gejala benar-benar dicatat",
      all(g.pulih_pada is not None for g in g4),
      "-> %r" % [g.pulih_pada for g in g4])
benar("dan waktu selesai insiden = waktu pulih gejalanya",
      i4.selesai == max(g.pulih_pada for g in g4),
      "-> selesai %r vs pulih %r"
      % (i4.selesai, [g.pulih_pada for g in g4]))


# =============================================================================
print()
print("=" * 74)
print("4b. GEJALA YANG KAMBUH MELUPAKAN WAKTU PULIHNYA")
print("   Kalau tidak, perangkat yang mati lagi akan ditutup memakai waktu")
print("   pulih LAMA yang sudah lewat -- sehingga jeda anti-berkedip 300")
print("   detik langsung terlewati dan insidennya ditutup justru saat ia")
print("   sedang kambuh.")
print("=" * 74)

db4b, dev4b = siapkan_db()
matikan(db4b, dev4b, "R2")
K.proses(db4b, sekarang=SEKARANG)

hidupkan(db4b, dev4b, "R2", SEKARANG + timedelta(seconds=30))
K.proses(db4b, sekarang=SEKARANG + timedelta(seconds=40))
g4b = db4b.query(models.InsidenGejala).first()
benar("waktu pulih tercatat lebih dulu", g4b.pulih_pada is not None)

matikan(db4b, dev4b, "R2", SEKARANG + timedelta(seconds=200))
K.proses(db4b, sekarang=SEKARANG + timedelta(seconds=200))
db4b.refresh(g4b)
benar("gejala yang kambuh melupakan waktu pulihnya",
      g4b.pulih_pada is None, "-> %r" % g4b.pulih_pada)

K.proses(db4b, sekarang=SEKARANG + timedelta(seconds=400))
i4b = db4b.query(models.Insiden).first()
benar("insiden yang sedang kambuh TIDAK ditutup",
      i4b.status == "terbuka", "-> %r" % i4b.status)


# =============================================================================
print()
print("=" * 74)
print("5. BERKEDIP TETAP SATU INSIDEN")
print("=" * 74)

db5, dev5 = siapkan_db()
matikan(db5, dev5, "R2")
K.proses(db5, sekarang=SEKARANG)
hidupkan(db5, dev5, "R2", SEKARANG + timedelta(seconds=20))
K.proses(db5, sekarang=SEKARANG + timedelta(seconds=25))
matikan(db5, dev5, "R2", SEKARANG + timedelta(seconds=60))
K.proses(db5, sekarang=SEKARANG + timedelta(seconds=65))
semua5 = db5.query(models.Insiden).all()
benar("mati -> pulih -> mati lagi dalam 1 menit = SATU insiden",
      len(semua5) == 1, "-> %d insiden" % len(semua5))


# =============================================================================
print()
print("=" * 74)
print("6. KEPARAHAN = YANG TERTINGGI, bukan rata-rata")
print("   Satu gejala gawat membuat seluruh insiden gawat. Merata-ratakan")
print("   akan menyembunyikan hal terburuk di balik hal-hal yang biasa.")
print("=" * 74)

db6, dev6 = siapkan_db()
K.record_symptom(db6, "syslog", 1, dev6["R2"].id, SEKARANG, "pesan biasa",
               keparahan="info", akar_id=dev6["R2"].id, sekarang=SEKARANG)
K.record_symptom(db6, "device", 2, dev6["R2"].id, SEKARANG, "device mati",
               keparahan="bahaya", akar_id=dev6["R2"].id, sekarang=SEKARANG)
i6 = db6.query(models.Insiden).first()
benar("info + bahaya -> insiden BAHAYA", i6.keparahan == "bahaya",
      "-> %r" % i6.keparahan)
benar("keduanya di insiden yang sama", i6.jumlah_gejala == 2,
      "-> %r" % i6.jumlah_gejala)


# =============================================================================
print()
print("=" * 74)
print("7. RINGKASAN UNTUK HALAMAN")
print("=" * 74)

r = K.ringkas(db, jam=24)
benar("insiden terbuka ikut dilaporkan", len(r["terbuka"]) >= 1,
      "-> %r" % len(r["terbuka"]))
if r["terbuka"]:
    t = r["terbuka"][0]
    benar("membawa nama akar, bukan cuma id", t["akar"] == "R2",
          "-> %r" % t["akar"])
    benar("membawa kalimat ringkas yang bisa dibaca orang",
          bool(t["ringkas"]), "-> %r" % t["ringkas"])


if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

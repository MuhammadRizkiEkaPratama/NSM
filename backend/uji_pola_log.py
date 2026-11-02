"""Test of log pattern mining with Drain3.

Two ways this module can fail, both silently:

1. Merging distinct patterns. `%LINK-3-UPDOWN` and `%LINEPROTO-5-UPDOWN` share
   many words ("changed state to"); too loose a similarity threshold turns them
   into one pattern and two events with different actions read as one.
2. Declaring EVERYTHING new on every restart. If the Drain3 tree is not rebuilt
   from stored templates, every poller restart reports all patterns as "never
   seen", turning the most valuable signal into noise.

Both are tested explicitly because neither produces an error.

Pure test: temporary SQLite, no network. Skipped if drain3 is not installed.

Run: py uji_pola_log.py
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


import models  # noqa: E402
import pola_log as P  # noqa: E402

# The time anchor moves. It used to be a fixed timestamp, but
# `pola_log.ringkas(db, jam=24)` computes history age against the REAL
# `datetime.now()`, so section 8 passed on the day it was written and stayed red
# once the 24-hour window passed. The anchor is 30 minutes in the past, not bare
# `datetime.now()`: the largest forward offset in this file is `SEKARANG +
# timedelta(seconds=500)`, so an anchor at "now" would put some messages in the
# future and the window would silently drop them. `microsecond=0` keeps timestamp
# comparison stable.
SEKARANG = datetime.now().replace(microsecond=0) - timedelta(minutes=30)


def siapkan_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    file = os.path.join(tempfile.mkdtemp(prefix="uji_polalog_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    dev = {}
    for i, n in enumerate(["R1", "R2"], start=1):
        d = models.Device(name=n, ip_address="192.168.56.%d" % (60 + i),
                          device_type="router", platform="cisco_ios",
                          aktif=True)
        db.add(d)
        dev[n] = d
    db.commit()
    return db, dev


def kirim(db, dev, pesan, severity=5, waktu=None, tag=None):
    db.add(models.SyslogPesan(
        waktu=waktu or SEKARANG, device_id=dev.id if dev else None,
        alamat=dev.ip_address if dev else "10.0.0.9", facility=23,
        severity=severity, tag=tag or pesan.split(":")[0][:60], pesan=pesan,
        sidik_templat="x", jadi_event=None))
    db.commit()


print("=" * 74)
print("Uji PAKET C2 -- penambangan pola log (Drain3)")
print("=" * 74)

print("\n0. Pustakanya benar-benar ada")
if not P.tersedia():
    print("  [LEWAT] drain3 tidak terpasang di lingkungan ini.")
    print("          Uji DILEWATI, bukan dianggap lolos.")
    print("          Pasang dengan: venv\\Scripts\\pip install drain3")
    print()
    print("=" * 74)
    print("0 lolos, 0 gagal (seluruh berkas dilewati)")
    print("=" * 74)
    sys.exit(0)
benar("drain3 terpasang", True)

db0, _dev0 = siapkan_db()
h0 = P.tambang(db0)
cek("basis data kosong -> nol dibaca", h0["dibaca"], 0)
cek("dan dinyatakan berjalan", h0["jalan"], True)

# ===========================================================================
print("\n1. Ratusan pesan -> segelintir pola")
db, dev = siapkan_db()
for i in range(120):
    kirim(db, dev["R1"],
          "%%LINK-3-UPDOWN: Interface FastEthernet0/%d, changed state to down"
          % (i % 12), severity=3,
          waktu=SEKARANG + timedelta(seconds=i))
for i in range(60):
    kirim(db, dev["R2"],
          "%%SYS-5-CONFIG_I: Configured from console by vty%d (192.168.56.%d)"
          % (i % 4, i % 200), severity=5,
          waktu=SEKARANG + timedelta(seconds=200 + i))

h = P.tambang(db)
cek("180 pesan dibaca", h["dibaca"], 180)
templat = db.query(models.LogTemplat).all()
print("       templat yang ditemukan:")
for t in templat:
    print("         x%-5d sev=%s  %s" % (t.jumlah, t.severity_min,
                                         (t.templat or "")[:64]))
benar("dilipat jadi sedikit pola, bukan 180", 1 <= len(templat) <= 6,
      "-> %d templat" % len(templat))
cek("seluruh pesan terhitung", sum(t.jumlah for t in templat), 180)

# ===========================================================================
print("\n2. CARA GAGAL #1: pola yang BERBEDA tidak boleh dilebur")
db2, dev2 = siapkan_db()
# Two Cisco tags sharing many words; merging them would read "interface down" and
# "line protocol down" as one event.
for i in range(30):
    kirim(db2, dev2["R1"],
          "%%LINK-3-UPDOWN: Interface FastEthernet0/%d, changed state to down" % i,
          severity=3, waktu=SEKARANG + timedelta(seconds=i))
for i in range(30):
    kirim(db2, dev2["R1"],
          "%%LINEPROTO-5-UPDOWN: Line protocol on Interface Fa0/%d, changed "
          "state to down" % i, severity=5,
          waktu=SEKARANG + timedelta(seconds=100 + i))
P.tambang(db2)
t2 = db2.query(models.LogTemplat).all()
for t in t2:
    print("         x%-5d %s" % (t.jumlah, (t.templat or "")[:66]))
benar("%LINK dan %LINEPROTO tetap DUA pola", len(t2) >= 2,
      "-> %d pola; keduanya dilebur" % len(t2))
benar("dan salah satunya memuat LINEPROTO",
      any("LINEPROTO" in (t.templat or "") for t in t2))
benar("severity terparah yang disimpan, bukan yang terakhir",
      any(t.severity_min == 3 for t in t2),
      "-> %r" % [t.severity_min for t in t2])

# ===========================================================================
print("\n3. CARA GAGAL #2: restart tidak boleh menyatakan semuanya BARU")
db3, dev3 = siapkan_db()
for i in range(20):
    kirim(db3, dev3["R1"],
          "%%LINK-3-UPDOWN: Interface Fa0/%d, changed state to down" % i,
          severity=3, waktu=SEKARANG + timedelta(seconds=i))
h3a = P.tambang(db3)
benar("putaran pertama menemukan pola baru", len(h3a["pola_baru"]) >= 1,
      "-> %r" % h3a["pola_baru"])

# A NEW message with the SAME pattern after a "restart" (the miner is rebuilt on every `tambang` call).
for i in range(20):
    kirim(db3, dev3["R2"],
          "%%LINK-3-UPDOWN: Interface Fa0/%d, changed state to down" % (i + 40),
          severity=3, waktu=SEKARANG + timedelta(seconds=300 + i))
h3b = P.tambang(db3)
cek("putaran kedua membaca 20 pesan", h3b["dibaca"], 20)
cek("dan TIDAK menyatakan satu pun pola baru", len(h3b["pola_baru"]), 0)

# ===========================================================================
print("\n4. Pola yang BENAR-BENAR baru tetap ketahuan (pasangannya)")
kirim(db3, dev3["R1"],
      "%SEC-6-IPACCESSLOGP: list 101 denied tcp 10.0.0.5(1234) -> 10.0.0.9(22)",
      severity=6, waktu=SEKARANG + timedelta(seconds=500))
h3c = P.tambang(db3)
cek("pesan berbentuk baru dibaca", h3c["dibaca"], 1)
benar("dan DILAPORKAN sebagai pola baru", len(h3c["pola_baru"]) == 1,
      "-> %r" % h3c["pola_baru"])
if h3c["pola_baru"]:
    benar("laporannya menyebut isinya",
          "IPACCESSLOGP" in h3c["pola_baru"][0]["templat"],
          "-> %r" % h3c["pola_baru"][0])

# ===========================================================================
print("\n5. Penanda posisi: pesan yang sama tidak ditambang dua kali")
sebelum = {t.templat: t.jumlah for t in db3.query(models.LogTemplat).all()}
h3d = P.tambang(db3)
cek("tidak ada yang dibaca lagi", h3d["dibaca"], 0)
sesudah = {t.templat: t.jumlah for t in db3.query(models.LogTemplat).all()}
cek("cacah tiap pola tidak berubah", sesudah, sebelum)

# ===========================================================================
print("\n6. Pesan KOSONG dan pengirim TAK DIKENAL tidak menjatuhkan apa pun")
db6, dev6 = siapkan_db()
kirim(db6, None, "%SYS-5-RESTART: System restarted", severity=5)
db6.add(models.SyslogPesan(waktu=SEKARANG, device_id=None, alamat="10.0.0.9",
                           facility=23, severity=6, tag=None, pesan="   ",
                           sidik_templat="k", jadi_event=None))
db6.commit()
h6 = P.tambang(db6)
cek("kedua baris dibaca tanpa jatuh", h6["dibaca"], 2)
benar("pesan kosong tidak jadi templat",
      all((t.templat or "").strip() for t in db6.query(models.LogTemplat).all()))

# ===========================================================================
print("\n7. Ringkasan memisahkan 'baru' dari 'tersering'")
r = P.ringkas(db3, jam=24)
benar("melaporkan pustakanya tersedia", r["tersedia"] is True)
benar("punya daftar baru", isinstance(r["baru"], list))
benar("punya daftar tersering", isinstance(r["tersering"], list))
benar("tersering benar-benar terurut menurun",
      all(r["tersering"][i]["jumlah"] >= r["tersering"][i + 1]["jumlah"]
          for i in range(len(r["tersering"]) - 1)),
      "-> %r" % [t["jumlah"] for t in r["tersering"]])
benar("total pesan = jumlah seluruh pola",
      r["total_pesan"] == sum(t.jumlah for t in db3.query(models.LogTemplat).all()))
print("       %d pesan terlipat jadi %d pola"
      % (r["total_pesan"], r["total_templat"]))

benar("pelipatannya nyata (pesan jauh lebih banyak daripada pola)",
      r["total_pesan"] > r["total_templat"] * 3,
      "-> %d pesan, %d pola" % (r["total_pesan"], r["total_templat"]))

# ===========================================================================
print("\n8. 'POLA BARU' yang tidak berarti apa-apa HARUS mengatakannya")
# A pattern seen 897 times is not news. The whole `syslog_pesan` history was only
# 8.3 hours old, so EVERY pattern had its first occurrence inside the 24-hour
# window. Calling those "new" trains people to ignore the most valuable part of
# this stream, so a too-young history must say so.
db8, dev8 = siapkan_db()
for i in range(200):
    kirim(db8, dev8["R1"],
          "%%LINK-3-UPDOWN: Interface Fa0/%d, changed state to down" % i,
          severity=3, waktu=SEKARANG - timedelta(minutes=120 - i // 2))
kirim(db8, dev8["R2"],
      "%SEC-6-IPACCESSLOGP: list 101 denied tcp 10.0.0.5 -> 10.0.0.9",
      severity=6, waktu=SEKARANG - timedelta(minutes=5))
P.tambang(db8)

r8 = P.ringkas(db8, jam=24)
benar("riwayat yang lebih muda dari jendela DINYATAKAN",
      r8["riwayat_muda"] is True, "-> %r jam" % r8["riwayat_jam"])
benar("dan ada kalimat peringatannya", bool(r8["catatan"]),
      "-> %r" % r8["catatan"])
benar("kalimatnya menyebut umur riwayatnya",
      "jam" in (r8["catatan"] or ""), "-> %r" % r8["catatan"])
print("       %s" % (r8["catatan"] or "")[:120])

# ORDER: rarest first. A pattern seen once deserves a human look far more than one
# seen two hundred times, even if both were first seen today.
jumlah = [t["jumlah"] for t in r8["baru"]]
print("       urutan jumlah di kolom BARU: %r" % jumlah)
benar("pola paling jarang muncul PALING ATAS",
      jumlah == sorted(jumlah), "-> %r" % jumlah)
benar("dan pola yang sudah ratusan kali TIDAK di atas",
      not jumlah or jumlah[0] < 10, "-> %r" % jumlah[:3])

# ===========================================================================
print("\n9. PASANGANNYA: riwayat yang cukup panjang TIDAK diberi peringatan")
db9, dev9 = siapkan_db()
kirim(db9, dev9["R1"], "%SYS-5-CONFIG_I: Configured from console by vty0",
      severity=5, waktu=SEKARANG - timedelta(days=9))
kirim(db9, dev9["R1"], "%SYS-5-CONFIG_I: Configured from console by vty1",
      severity=5, waktu=SEKARANG - timedelta(minutes=3))
P.tambang(db9)
r9 = P.ringkas(db9, jam=24)
benar("riwayat 9 hari > jendela 24 jam -> tidak diperingatkan",
      r9["riwayat_muda"] is False, "-> %r jam" % r9["riwayat_jam"])
cek("dan catatannya kosong", r9["catatan"], None)

print()
print("=" * 74)
print("%d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

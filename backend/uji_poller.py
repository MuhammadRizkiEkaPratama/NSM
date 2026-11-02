"""Test of `poller.py`, which previously had no direct tests.

`poller.py` calls every Stage 4-7 remediator and is the only place that decides
when a device is officially declared DOWN, a decision that directly determines
whether automation restarts a router.

Most guarded: the CONSECUTIVE-FAILURE THRESHOLD. `DOWN_THRESHOLD` (default 5) is
all that separates "one lost ping" from "router rebooted automatically". Sections
5 and 6 lock it from both sides: the poller (no DOWN event before the threshold)
and the remediator (no candidate before the threshold).

Nothing here touches the network: `periksa_device()` takes `hasil_ping` and
`hasil_port`, so all check results are injected.

Run: py uji_poller.py
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


# GUARD: this file must not touch anything outside itself. Earlier, the
# `uji_pemulih_*.py` tests really called the notification endpoint on nsm-app; no
# email went out only because the endpoint accepts localhost only (403). That was
# luck, not design. Installed at the top, before any import that might use it.
import notifikasi_berjenjang as _nb  # noqa: E402

_nb.eskalasi_segera = lambda *a, **k: None

import models  # noqa: E402
import poller  # noqa: E402
import config  # noqa: E402

AMBANG = config.get_down_threshold()


def siapkan_db():
    """Clean SQLite DB plus ALL module-level state reset.

    `poller` keeps four module-level dicts (`gagal_beruntun`, `tcp_terjangkau_sampai`,
    `tcp_periksa_lagi_pada`, `gagal_layanan`) keyed by device_id/service_id, not per
    database. Each temporary DB creates a device with id=1, so without a reset the
    failure counts of an earlier case would leak into the next one. Same trap as
    `jeda._cache` and `report_service._cache`; safe in the primary instance (one
    process, one database) and dangerous only in tests.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import jeda

    poller.gagal_beruntun.clear()
    poller.tcp_terjangkau_sampai.clear()
    poller.tcp_periksa_lagi_pada.clear()
    poller.gagal_layanan.clear()
    jeda.lupakan_cache()

    file = os.path.join(tempfile.mkdtemp(prefix="uji_poller_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def buat_device(db, nama="R-uji", ip="10.9.9.9", platform="cisco_ios"):
    d = models.Device(name=nama, ip_address=ip, device_type="router",
                      platform=platform, aktif=1)
    db.add(d)
    db.commit()
    return d


def peristiwa(db, device_id):
    from sqlalchemy import select, desc
    return db.execute(
        select(models.DeviceEvent).where(models.DeviceEvent.device_id == device_id)
        .order_by(desc(models.DeviceEvent.timestamp), desc(models.DeviceEvent.id))
    ).scalars().all()


# =============================================================================
print("=" * 74)
print("1. beruntun_berikutnya -- penghitung gagal beruntun")
print("   Dihitung, BUKAN dibaca apa adanya: memakai gagal_beruntun[id]")
print("   langsung berarti memakai angka yang tertinggal satu putaran, dan")
print("   device yang BARU SAJA mencapai ambang akan selalu terlewat.")
print("=" * 74)

db = siapkan_db()
d = buat_device(db)

cek("belum pernah gagal, lalu gagal -> 1",
    poller.beruntun_berikutnya(d.id, False), 1)
cek("device yang menjawab -> selalu 0",
    poller.beruntun_berikutnya(d.id, True), 0)

poller.gagal_beruntun[d.id] = 3
cek("sudah 3 gagal, gagal lagi -> 4",
    poller.beruntun_berikutnya(d.id, False), 4)
cek("sudah 3 gagal, lalu MENJAWAB -> 0 (bukan 3)",
    poller.beruntun_berikutnya(d.id, True), 0)

benar("memanggilnya TIDAK mengubah hitungan yang tersimpan "
      "(ia menghitung, bukan menaikkan)",
      poller.gagal_beruntun[d.id] == 3,
      "-> %r" % poller.gagal_beruntun.get(d.id))


# =============================================================================
print()
print("=" * 74)
print("2. perlu_probe_tcp -- kapan port benar-benar dicoba")
print("   Aturan ini ditulis SEKALI karena dibaca dua kali (poll_all dan")
print("   periksa_device). Dua salinan aturan yang sama akan menyimpang.")
print("=" * 74)

db = siapkan_db()
d = buat_device(db)
lokal = buat_device(db, "NSM sendiri", "127.0.0.1", platform="lokal")
t0 = datetime(2026, 8, 22, 10, 0, 0)

benar("device MENJAWAB -> port tidak perlu dicoba",
      poller.perlu_probe_tcp(d, True, 0, t0) is False)
benar("platform 'lokal' -> tidak pernah dicoba lewat TCP",
      poller.perlu_probe_tcp(lokal, False, 99, t0) is False)

benar("SATU ping gagal -> port TIDAK dicoba (ini penjaga utamanya)",
      poller.perlu_probe_tcp(d, False, 1, t0) is False)
benar("gagal beruntun tepat DI BAWAH ambang -> masih tidak dicoba",
      poller.perlu_probe_tcp(d, False, AMBANG - 1, t0) is False)
benar("gagal beruntun MENCAPAI ambang -> baru dicoba",
      poller.perlu_probe_tcp(d, False, AMBANG, t0) is True,
      "-> ambang=%s" % AMBANG)

poller.tcp_terjangkau_sampai[d.id] = (t0 + timedelta(seconds=30)).timestamp()
benar("hasil sebelumnya masih berlaku -> tidak dicoba lagi",
      poller.perlu_probe_tcp(d, False, AMBANG, t0) is False)
poller.tcp_terjangkau_sampai.clear()

poller.tcp_periksa_lagi_pada[d.id] = (t0 + timedelta(seconds=30)).timestamp()
benar("belum waktunya diperiksa lagi -> tidak dicoba",
      poller.perlu_probe_tcp(d, False, AMBANG, t0) is False)
benar("sesudah waktunya lewat -> dicoba lagi",
      poller.perlu_probe_tcp(d, False, AMBANG,
                             t0 + timedelta(seconds=31)) is True)


# =============================================================================
print()
print("=" * 74)
print("3. status_terakhir -- peristiwa terakhir, urut waktu LALU id")
print("=" * 74)

db = siapkan_db()
d = buat_device(db)
benar("device tanpa peristiwa -> None",
      poller.status_terakhir(db, d.id) is None)

for i, tipe in enumerate(["UP", "DOWN", "UP"]):
    db.add(models.DeviceEvent(device_id=d.id, event_type=tipe,
                              timestamp=t0 + timedelta(minutes=i),
                              category="uji", detail="uji"))
db.commit()
cek("mengambil yang paling baru", poller.status_terakhir(db, d.id).event_type, "UP")

# Two events with the EXACT same timestamp: the id decides. Two rounds can fall in
# the same second, and without a defined order the next transition could be
# compared with the wrong event.
sama = t0 + timedelta(minutes=10)
db.add(models.DeviceEvent(device_id=d.id, event_type="DOWN", timestamp=sama,
                          category="uji", detail="lebih dulu"))
db.commit()
db.add(models.DeviceEvent(device_id=d.id, event_type="UP", timestamp=sama,
                          category="uji", detail="lebih belakang"))
db.commit()
cek("stempel waktu SAMA -> id lebih besar yang menang",
    poller.status_terakhir(db, d.id).detail, "lebih belakang")


# =============================================================================
print()
print("=" * 74)
print("4. tulis_event -- durasi memotong waktu TIDAK TERPANTAU")
print("   cacat nyata: menutup laptop semalam menghasilkan 'pulih setelah")
print("   DOWN 46.508 detik' untuk gangguan yang cuma 25 detik terlihat.")
print("=" * 74)

db = siapkan_db()
d = buat_device(db)

durasi = poller.tulis_event(db, d.id, "UP", "baseline", "awal", None, None, t0)
db.commit()
benar("peristiwa PERTAMA (tidak ada sebelumnya) -> durasi None, bukan 0",
      durasi is None, "-> %r" % durasi)

sebelum = models.DeviceEvent(device_id=d.id, event_type="UP",
                             timestamp=t0, category="uji", detail="uji")
db.add(sebelum)
db.commit()


def tanam_pantauan(db, device_id, mulai, jumlah, interval=10):
    """`status_logs` rows are the evidence that NSM was monitoring at that time. They
    must be planted: without any ping row in the range, `jeda` correctly treats the
    whole range as unmonitored and a 300 s duration is cut to 0.
    """
    for i in range(jumlah):
        db.add(models.StatusLog(
            device_id=device_id, timestamp=mulai + timedelta(seconds=i * interval),
            is_reachable=True, response_time_ms=5.0, sumber="icmp"))
    db.commit()


# Kasus A: dipantau TERUS selama 300 detik -> durasi utuh.
tanam_pantauan(db, d.id, t0, 31)
durasi = poller.tulis_event(db, d.id, "DOWN", "dead", "mati", None,
                            sebelum, t0 + timedelta(seconds=300))
db.commit()
cek("dipantau terus -> durasi apa adanya", durasi, 300.0)

# Case B: a monitoring GAP in the middle -> the gap is cut. Without cutting, closing
# a laptop overnight would report a "12 hour outage" for a 25-second one.
db2 = siapkan_db()
d2 = buat_device(db2, "R-lubang", "10.9.9.8")
sebelum2 = models.DeviceEvent(device_id=d2.id, event_type="UP",
                              timestamp=t0, category="uji", detail="uji")
db2.add(sebelum2)
db2.commit()
tanam_pantauan(db2, d2.id, t0, 7)                                  # 0-60 dtk
tanam_pantauan(db2, d2.id, t0 + timedelta(seconds=3600), 7)        # 3600-3660
durasi_lubang = poller.tulis_event(db2, d2.id, "DOWN", "dead", "mati", None,
                                   sebelum2, t0 + timedelta(seconds=3660))
db2.commit()
print("  -> durasi mentah 3660 dtk, sesudah dipotong: %r" % durasi_lubang)
benar("lubang pemantauan dipotong dari durasi",
      durasi_lubang is not None and durasi_lubang < 3660,
      "-> %r" % durasi_lubang)
benar("yang tersisa mendekati waktu yang BENAR-BENAR terpantau",
      durasi_lubang is not None and durasi_lubang <= 700,
      "-> %r" % durasi_lubang)

benar("durasi tidak pernah negatif walau waktunya mundur",
      poller.tulis_event(db, d.id, "UP", "uji", "mundur", None, sebelum,
                         t0 - timedelta(seconds=60)) is None)
db.commit()

benar("semua peristiwa benar-benar tersimpan",
      len(peristiwa(db, d.id)) >= 3)


# =============================================================================
print()
print("=" * 74)
print("5. periksa_device -- AMBANG GAGAL BERUNTUN (inti berkas ini)")
print("   ambang terbaca: %s kegagalan berturut-turut" % AMBANG)
print("=" * 74)

db = siapkan_db()
d = buat_device(db)

# Baseline: device menjawab.
poller.periksa_device(db, d, hasil_ping=(True, 5.0))
db.commit()
ev = peristiwa(db, d.id)
benar("pemeriksaan pertama menulis peristiwa dasar (baseline)",
      len(ev) == 1 and ev[0].event_type == "UP", "-> %r" % [e.event_type for e in ev])

poller.periksa_device(db, d, hasil_ping=(False, None), hasil_port=[])
db.commit()
ev = peristiwa(db, d.id)
benar("SATU ping gagal -> TIDAK ada peristiwa DOWN",
      all(e.event_type != "DOWN" for e in ev),
      "-> %r" % [e.event_type for e in ev])

# Raise it to JUST BELOW the threshold.
for _ in range(AMBANG - 2):
    poller.periksa_device(db, d, hasil_ping=(False, None), hasil_port=[])
db.commit()
cek("hitungan gagal beruntun sekarang", poller.gagal_beruntun[d.id], AMBANG - 1)
benar("tepat di bawah ambang -> MASIH tidak ada peristiwa DOWN",
      all(e.event_type != "DOWN" for e in peristiwa(db, d.id)),
      "-> %r" % [e.event_type for e in peristiwa(db, d.id)])

poller.periksa_device(db, d, hasil_ping=(False, None), hasil_port=[])
db.commit()
ev = peristiwa(db, d.id)
benar("mencapai ambang -> peristiwa DOWN akhirnya ditulis",
      ev[0].event_type == "DOWN", "-> %r" % [e.event_type for e in ev])
cek("kategorinya jujur", ev[0].category, "dead")

jumlah_sebelum = len(peristiwa(db, d.id))
for _ in range(3):
    poller.periksa_device(db, d, hasil_ping=(False, None), hasil_port=[])
db.commit()
cek("tetap mati -> TIDAK menulis DOWN berulang-ulang",
    len(peristiwa(db, d.id)), jumlah_sebelum)

poller.periksa_device(db, d, hasil_ping=(True, 7.0))
db.commit()
ev = peristiwa(db, d.id)
benar("pulih dicatat SEKETIKA (tanpa menunggu %s kali berhasil)" % AMBANG,
      ev[0].event_type == "UP", "-> %r" % [e.event_type for e in ev])
cek("hitungan gagal beruntun kembali nol", poller.gagal_beruntun[d.id], 0)

benar("tiap pemeriksaan juga menulis baris status_logs mentah",
      db.query(models.StatusLog).filter(
          models.StatusLog.device_id == d.id).count() >= AMBANG + 3)


# =============================================================================
print()
print("=" * 74)
print("6. RANTAI POLLER -> PEMULIH  (uji yang paling penting di berkas ini)")
print("   Dua modul, satu janji: pemulih HANYA boleh bertindak sesudah NSM")
print("   sendiri berani menyatakan perangkatnya mati. Diuji dari ujung ke")
print("   ujung karena cacat 22 Agustus 2026 hidup PERSIS di sambungannya --")
print("   masing-masing modul benar sendiri-sendiri, janjinya yang bocor.")
print("=" * 74)

from pemulih import gns3 as pemulih_gns3  # noqa: E402

db = siapkan_db()
d = buat_device(db, "Router Lokasi A", "192.168.56.60")
d.gns3_node = "R1"
db.commit()

poller.periksa_device(db, d, hasil_ping=(True, 5.0))
db.commit()
benar("router sehat -> bukan kandidat pemulihan",
      all(x.id != d.id for x in pemulih_gns3.cari_kandidat(db)))

for _ in range(AMBANG - 1):
    poller.periksa_device(db, d, hasil_ping=(False, None), hasil_port=[])
db.commit()
cek("gagal beruntun sekarang (satu langkah sebelum ambang)",
    poller.gagal_beruntun[d.id], AMBANG - 1)
benar("BELUM mencapai ambang -> pemulih TIDAK BOLEH menyentuh router ini",
      all(x.id != d.id for x in pemulih_gns3.cari_kandidat(db)),
      "-> %r" % [(x.id, x.name) for x in pemulih_gns3.cari_kandidat(db)])

poller.periksa_device(db, d, hasil_ping=(False, None), hasil_port=[])
db.commit()
benar("ambang tercapai -> pemulih BOLEH bertindak",
      any(x.id == d.id for x in pemulih_gns3.cari_kandidat(db)),
      "-> %r" % [(x.id, x.name) for x in pemulih_gns3.cari_kandidat(db)])

poller.periksa_device(db, d, hasil_ping=(True, 6.0))
db.commit()
benar("sesudah pulih -> berhenti jadi kandidat",
      all(x.id != d.id for x in pemulih_gns3.cari_kandidat(db)))


if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

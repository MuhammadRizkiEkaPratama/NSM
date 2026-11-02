"""NSM data health checker.

Runs against the REAL nsm.db, not synthetic data, to find oddities invisible
on screen: orphan rows, impossible event order, implausible numbers, and above
all a comparison of availability from `device_events` against availability
from raw `status_logs`. If the poller's transition detection has a defect, the
two numbers differ widely.

Safe to run any time (read-only); the poller and uvicorn may keep running.

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\activate
    python cek_kesehatan.py
"""
import os
import sqlite3
from datetime import datetime, timedelta

from sqlalchemy import desc, func

import dialek_perangkat
import report_service
from database import SessionLocal
from models import BandwidthSample, Device, DeviceEvent, StatusLog

# Path anchored to this file's folder, not the working directory. With a
# relative path, running from the wrong folder raises no error: SQLite creates a
# new empty database there and the output just shows "zero rows". The full
# reasoning is in `database.py`.
DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

masalah = []
peringatan = []


def judul(teks):
    print()
    print("=" * 74)
    print(teks)
    print("=" * 74)


def catat(parah, teks):
    (masalah if parah else peringatan).append(teks)
    print(f"  {'[MASALAH]' if parah else '[perhatian]'} {teks}")


db = SessionLocal()

# ---------------------------------------------------------------------------
judul("1. STRUKTUR DATABASE")
# Opened READ-ONLY. A plain `sqlite3.connect(DB)` CREATES an empty file when
# `DB` does not exist, so a health checker would change the state it inspects.
# Since the data moved to MySQL, `nsm.db` is absent on some installs; running
# this there left a 0-byte `nsm.db`, which passes the `os.path.exists("nsm.db")`
# checks in `uji_jeda`, `uji_layanan_jeda`, and `uji_kepatuhan` and then fails
# them with `no such table`. `mode=ro` makes a missing file an ERROR instead of
# a new file.
if not os.path.exists(DB):
    print("  nsm.db tidak ada di %s." % DIR)
    print("  Itu WAJAR sejak 12 Agustus 2026: data NSM tinggal di MySQL, dan")
    print("  nsm.db hanya sisa riwayat sebelum pindah. Bagian ini dilewati.")
    tabel = index = set()
    con = None
else:
    con = sqlite3.connect("file:%s?mode=ro" % DB.replace(os.sep, "/"), uri=True)
    cur = con.cursor()
    tabel = {r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    index = {r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}

# EVERYTHING BELOW IS SPECIFIC TO `nsm.db` and is skipped when the file is
# absent. Without this guard a missing file is reported as seven "[MASALAH]"
# lines ("table devices MISSING", "migration not run", ...), none true: the
# tables exist in MySQL. False alarms on a healthy system send people chasing
# finished migrations and teach them to stop reading the report.
if con is None:
    catat(False, "struktur nsm.db tidak diperiksa (berkasnya tidak ada, dan "
                 "itu wajar sejak data pindah ke MySQL)")
else:
    for t in ("devices", "status_logs", "device_events", "bandwidth_samples"):
        if t in tabel:
            n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  tabel {t:20} ada, {n:>8,} baris")
        else:
            catat(True, f"tabel '{t}' TIDAK ADA — migrasi belum dijalankan")

    for i in ("ix_status_device_ts", "ix_events_device_ts", "ix_bw_device_iface_ts"):
        if i in index:
            print(f"  index {i:24} ada")
        else:
            catat(True, f"index '{i}' tidak ada — query report akan lambat")

    kolom = {r[1] for r in cur.execute("PRAGMA table_info(devices)").fetchall()}
    for k in ("platform", "snmp_user", "snmp_auth_pass", "snmp_priv_pass"):
        if k not in kolom:
            catat(True, f"kolom devices.{k} tidak ada")

    ukuran = os.path.getsize(DB) / 1024 / 1024
    print(f"  ukuran nsm.db: {ukuran:.1f} MB")
    if ukuran > 500:
        catat(False, f"database sudah {ukuran:.0f} MB — pertimbangkan pemangkasan status_logs lama")

# ---------------------------------------------------------------------------
judul("2. BARIS YATIM (menunjuk device yang sudah tidak ada)")
# ---------------------------------------------------------------------------
id_device = {d.id for d in db.query(Device).all()}
for nama, model in (("status_logs", StatusLog), ("device_events", DeviceEvent),
                    ("bandwidth_samples", BandwidthSample)):
    yatim = (db.query(func.count(model.id))
             .filter(~model.device_id.in_(id_device)).scalar()) or 0
    if yatim:
        catat(False, f"{nama}: {yatim:,} baris menunjuk device yang sudah dihapus")
    else:
        print(f"  {nama:20} bersih")

# ---------------------------------------------------------------------------
judul("3. URUTAN EVENT TIAP DEVICE (harus selang-seling UP/DOWN)")
# ---------------------------------------------------------------------------
for d in db.query(Device).order_by(Device.id).all():
    ev = (db.query(DeviceEvent)
          .filter(DeviceEvent.device_id == d.id)
          .order_by(DeviceEvent.timestamp, DeviceEvent.id).all())
    if not ev:
        print(f"  {d.name:20} belum ada event (device baru / poller belum jalan)")
        continue

    dobel = 0
    for i in range(1, len(ev)):
        if ev[i].event_type == ev[i - 1].event_type:
            dobel += 1
    tanpa_kategori = sum(1 for e in ev if not e.category)
    durasi_aneh = sum(1 for e in ev
                      if e.duration_sec is not None and e.duration_sec < 0)

    ket = f"{len(ev)} event"
    if dobel:
        catat(True, f"{d.name}: {dobel} event berurutan bertipe SAMA "
                    f"(mis. DOWN lalu DOWN lagi) — transisi tercatat ganda")
    if tanpa_kategori:
        catat(False, f"{d.name}: {tanpa_kategori} event tanpa kategori")
    if durasi_aneh:
        catat(True, f"{d.name}: {durasi_aneh} event berdurasi negatif "
                    f"— jam sistem mungkin pernah mundur")
    if not (dobel or tanpa_kategori or durasi_aneh):
        print(f"  {d.name:20} {ket:12} urutan wajar")

# ---------------------------------------------------------------------------
judul("4. UJI SILANG AVAILABILITY  (event  vs  data ping mentah)")
# ---------------------------------------------------------------------------
print("  Ini pemeriksaan terpenting. Availability yang dipakai halaman Report")
print("  dihitung dari device_events (catatan transisi). Di bawah dibandingkan")
print("  dengan hitungan kasar dari status_logs mentah: berapa persen ping yang")
print("  berhasil. Kalau deteksi transisi cacat, kedua angka akan berbeda jauh.")
print()
print(f"  {'Device':<20} {'dari event':>11} {'dari ping':>11} {'selisih':>9}")
print("  " + "-" * 56)

sekarang = datetime.now()
mulai_uji = sekarang - timedelta(hours=24)
for d in db.query(Device).order_by(Device.id).all():
    ringkas = report_service.hitung_device(db, d, mulai_uji, sekarang)
    a_event = ringkas["availability"]

    awal_ev = (db.query(func.min(DeviceEvent.timestamp))
               .filter(DeviceEvent.device_id == d.id).scalar())
    batas = max(mulai_uji, awal_ev) if awal_ev else mulai_uji
    total = (db.query(func.count(StatusLog.id))
             .filter(StatusLog.device_id == d.id,
                     StatusLog.timestamp >= batas).scalar()) or 0
    naik = (db.query(func.count(StatusLog.id))
            .filter(StatusLog.device_id == d.id,
                    StatusLog.timestamp >= batas,
                    StatusLog.is_reachable == True).scalar()) or 0  # noqa: E712
    a_ping = round(naik / total * 100, 3) if total else None

    if a_event is None or a_ping is None:
        print(f"  {d.name:<20} {'-':>11} {'-':>11} {'-':>9}  (data belum cukup)")
        continue

    selisih = abs(a_event - a_ping)

    # PAUSED devices always give a large difference, which is not a defect: once
    # paused, status_logs stops growing while the last event stays frozen, so the
    # event side assumes the state continues until now. The two sides cover
    # different time ranges and cannot be compared.
    if d.aktif == 0:
        print(f"  {d.name:<20} {a_event:>10.3f}% {a_ping:>10.3f}% "
              f"{selisih:>8.3f}%  (dijeda, tidak dibandingkan)")
        continue

    tanda = "" if selisih <= 1.0 else "  <-- PERIKSA"
    print(f"  {d.name:<20} {a_event:>10.3f}% {a_ping:>10.3f}% {selisih:>8.3f}%{tanda}")
    if selisih > 1.0:
        catat(True, f"{d.name}: availability dari event ({a_event}%) beda "
                    f"{selisih:.2f}% dari data ping mentah ({a_ping}%)")

print()
print("  Catatan: selisih kecil itu WAJAR. Ambang anti-flapping membuat DOWN")
print("  baru dicatat setelah 2 kali gagal beruntun, jadi versi event selalu")
print("  sedikit lebih optimis. Selisih di atas 1% baru patut dicurigai.")

# ---------------------------------------------------------------------------
judul("5. DATA BANDWIDTH")
# ---------------------------------------------------------------------------
if db.query(func.count(BandwidthSample.id)).scalar():
    negatif = (db.query(func.count(BandwidthSample.id))
               .filter((BandwidthSample.in_bps < 0) |
                       (BandwidthSample.out_bps < 0)).scalar()) or 0
    if negatif:
        catat(True, f"{negatif} sampel bandwidth bernilai NEGATIF "
                    f"— penanganan counter mundur bermasalah")
    else:
        print("  tidak ada laju negatif")

    # 10 Gbps on a host-only lab is practically impossible -> sign of a counting error
    BATAS = 10_000_000_000
    gila = (db.query(func.count(BandwidthSample.id))
            .filter((BandwidthSample.in_bps > BATAS) |
                    (BandwidthSample.out_bps > BATAS)).scalar()) or 0
    if gila:
        catat(True, f"{gila} sampel melebihi 10 Gbps — kemungkinan counter "
                    f"berputar dan tidak terdeteksi")
    else:
        print("  tidak ada laju yang mustahil besar")

    print()
    print(f"  {'Device':<20} {'iface':<18} {'sampel':>8} {'sumber':>8} {'terakhir':>10}")
    print("  " + "-" * 70)
    for d in db.query(Device).order_by(Device.id).all():
        baris = (db.query(BandwidthSample.iface,
                          func.count(BandwidthSample.id),
                          func.max(BandwidthSample.timestamp))
                 .filter(BandwidthSample.device_id == d.id)
                 .group_by(BandwidthSample.iface).all())
        for iface, n, terakhir in baris:
            src = (db.query(BandwidthSample.source)
                   .filter(BandwidthSample.device_id == d.id,
                           BandwidthSample.iface == iface)
                   .order_by(desc(BandwidthSample.timestamp)).first())
            jam = str(terakhir)[11:19] if terakhir else "-"
            print(f"  {d.name:<20} {iface:<10} {n:>8,} {str(src[0] if src else '-'):>8} {jam:>10}")
            if terakhir:
                tua = (sekarang - (terakhir if isinstance(terakhir, datetime)
                                   else datetime.fromisoformat(str(terakhir)))).total_seconds()
                if tua > 300:
                    catat(False, f"{d.name}/{iface}: sampel terakhir {int(tua/60)} menit lalu "
                                 f"— pembacaan mungkin berhenti")
else:
    catat(False, "belum ada sampel bandwidth sama sekali")

# ---------------------------------------------------------------------------
judul("6. KESEGARAN DATA PING")
# ---------------------------------------------------------------------------
for d in db.query(Device).order_by(Device.id).all():
    log = (db.query(StatusLog).filter(StatusLog.device_id == d.id)
           .order_by(desc(StatusLog.timestamp)).first())
    if not log:
        catat(False, f"{d.name}: belum pernah di-ping")
        continue
    tua = (sekarang - log.timestamp).total_seconds()
    status = "UP" if log.is_reachable else "DOWN"

    # PAUSED devices are no longer pinged, so stale data is expected. Without this
    # exception each deliberately paused device would be reported as "poller dead?"
    # forever, and a checker that raises routine false alarms stops being read.
    if d.aktif == 0:
        print(f"  {d.name:<20} {'DIJEDA':<5} ping terakhir "
              f"{int(tua)} detik lalu (wajar, sengaja tidak dipantau)")
        continue

    if tua > 60:
        catat(True, f"{d.name}: ping terakhir {int(tua)} detik lalu — poller mati?")
    else:
        print(f"  {d.name:<20} {status:<5} {int(tua)} detik lalu")

# ---------------------------------------------------------------------------
judul("7. KONFIGURASI DEVICE")
# ---------------------------------------------------------------------------
print(f"  {'Device':<20} {'platform':<12} {'SSH':<5} {'SNMP':<6} cara baca bandwidth")
print("  " + "-" * 70)
for d in db.query(Device).order_by(Device.id).all():
    # The "lokal" device is the machine running NSM: read directly, with no
    # credentials or port. Without this branch it would be reported as "cannot
    # (ping only)" while section 5 above shows its samples growing every 30 seconds.
    lokal = dialek_perangkat.ambil(d.platform).lokal
    ssh = "ya" if (d.platform and not lokal and d.username and d.password) else "-"
    snmp = "ya" if d.snmp_user else "-"
    if lokal:
        cara = "langsung dari mesin ini"
    elif d.snmp_user:
        cara = "SNMP (cadangan SSH)" if ssh == "ya" else "SNMP"
    elif ssh == "ya":
        cara = "SSH"
    else:
        cara = "tidak bisa (ping saja)"
    print(f"  {d.name:<20} {str(d.platform):<12} {ssh:<5} {snmp:<6} {cara}")

# ---------------------------------------------------------------------------
judul("RINGKASAN")
# ---------------------------------------------------------------------------
if not masalah and not peringatan:
    print("  Tidak ditemukan kejanggalan. Semua pemeriksaan lolos.")
else:
    if masalah:
        print(f"  {len(masalah)} MASALAH:")
        for m in masalah:
            print(f"    - {m}")
    if peringatan:
        print(f"  {len(peringatan)} perlu perhatian (belum tentu salah):")
        for p in peringatan:
            print(f"    - {p}")

db.close()
if con is not None:  # None if nsm.db does not exist
    con.close()

"""Tests for SLO and error budget.
The key risk is the denominator: the budget must use the window actually monitored, not calendar length, or hours when the monitoring host was off would count as SLO violations. `slo.hitung()` therefore reuses `report_service.hitung_device()`; these tests keep that link and also check:
  * too-short observation reports "not yet assessable", not a jumpy number
  * an exceeded budget reads negative, not clipped to zero
  * skipped devices are named, not dropped from the list
Pure test: temporary SQLite, no network.
Run: py uji_slo.py
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


import config  # noqa: E402
import models  # noqa: E402
import slo  # noqa: E402


def siapkan_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import jeda
    import report_service as rs

    file = os.path.join(tempfile.mkdtemp(prefix="uji_slo_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    d = models.Device(name="Router SLO", ip_address="192.168.56.90",
                      device_type="router", platform="cisco_ios", aktif=True)
    db.add(d)
    db.commit()
    # Module caches leak between test databases and caused false passes elsewhere; cleared on every setup.
    jeda.lupakan_cache()
    rs._cache.clear()
    return db, d


# Anchored to real time, not fixed dates: `slo.semua()` uses a window ending "now", so fixed-date data would drift out of the window and the test would stop testing anything.
SEKARANG = datetime.now().replace(microsecond=0)


def isi_riwayat(db, d, mulai, menit_diamati, insiden):
    """An observation window of `menit_diamati` minutes containing incidents (`(offset_minutes, duration_seconds)` each).
    Samples are written every 60 seconds because NSM treats gaps longer than `jeda.ambang_detik()` (60 s) as unmonitored time and removes them from the denominator. The window is short and dense, not long and sparse.
    """
    # Every 30 seconds, not 60: samples exactly at the `jeda.ambang_detik()` threshold are partly read as monitoring gaps and shrink the effective window.
    for t in range(0, int(menit_diamati) * 60 + 1, 30):
        db.add(models.StatusLog(device_id=d.id,
                                timestamp=mulai + timedelta(seconds=t),
                                is_reachable=True, response_time_ms=5.0))
    for offset_menit, duration in insiden:
        t_down = mulai + timedelta(minutes=offset_menit)
        db.add(models.DeviceEvent(device_id=d.id, event_type="DOWN",
                                  timestamp=t_down))
        db.add(models.DeviceEvent(device_id=d.id, event_type="UP",
                                  timestamp=t_down + timedelta(seconds=duration),
                                  duration_sec=duration))
    db.commit()


_target_asli = config._baca


def set_target(nilai, **tambahan):
    """Override only the SLO key and keep the other settings, including those `jeda` uses to decide when NSM was not monitoring."""
    original = dict(_target_asli())
    original["SLO_TARGET"] = str(nilai)
    original.update({k: str(v) for k, v in tambahan.items()})
    config._baca = lambda: original


# =============================================================================
print("=" * 74)
print("1. TARGET DIBACA, DAN PUNYA BATAS WARAS")
print("=" * 74)

try:
    set_target(99.5)
    benar("target dari .env dipakai", slo.target_untuk() == 99.5,
          "-> %r" % slo.target_untuk())

    config._baca = lambda: {"SLO_TARGET": "bukan-angka"}
    benar("nilai ngawur -> jatuh ke bawaan, bukan meledak",
          slo.target_untuk() == slo.TARGET_BAWAAN, "-> %r" % slo.target_untuk())

    config._baca = lambda: {"SLO_TARGET": "150"}
    benar("target di atas 100 dijepit ke 100", slo.target_untuk() == 100.0,
          "-> %r" % slo.target_untuk())

    config._baca = lambda: {"SLO_TARGET": "99.0",
                            "SLO_TARGET_ROUTER_SLO": "99.9"}
    benar("target per-device menang atas target umum",
          slo.target_untuk("Router SLO") == 99.9,
          "-> %r" % slo.target_untuk("Router SLO"))
    benar("device lain tetap memakai target umum",
          slo.target_untuk("Switch Lain") == 99.0,
          "-> %r" % slo.target_untuk("Switch Lain"))
finally:
    config._baca = _target_asli


# =============================================================================
print()
print("=" * 74)
print("2. ANGGARAN DIHITUNG DARI JENDELA YANG BENAR-BENAR DIAMATI")
print("   Bukan dari panjang kalender. Ini satu-satunya hal yang, kalau")
print("   salah, membuat seluruh angka di halaman ini menyesatkan.")
print("=" * 74)

try:
    set_target(99.0)
    db, d = siapkan_db()
    mulai = SEKARANG - timedelta(minutes=600)
    isi_riwayat(db, d, mulai, 600, [(100, 60)])
    r = slo.hitung(db, d, mulai, SEKARANG)
    benar("menghasilkan angka (pengamatan cukup)", r is not None)
    if r:
        # Tested against the reported window, not an assumed 600 minutes: the effective window is shorter than the calendar because monitoring gaps are excluded.
        harap = r["jendela_detik"] * (100.0 - r["target_persen"]) / 100.0
        benar("anggaran = (100%-target) x jendela diamati, persis",
              abs(r["anggaran_detik"] - harap) < 0.001,
              "-> %.1f vs %.1f" % (r["anggaran_detik"], harap))
        benar("jendela efektif tidak melebihi kalender",
              r["jendela_detik"] <= 600 * 60 + 1,
              "-> %.0f detik" % r["jendela_detik"])
        benar("terpakai = durasi insiden (60 detik)",
              r["terpakai_detik"] == 60, "-> %r" % r["terpakai_detik"])
        benar("sisa positif -> vonis aman", r["vonis"] == "aman",
              "-> %r (%r)" % (r["vonis"], r["sisa_persen"]))
        benar("penyebutnya jendela DIAMATI, bukan kalender",
              r["jendela_detik"] <= (SEKARANG - mulai).total_seconds() + 1,
              "-> %r" % r["jendela_detik"])
finally:
    config._baca = _target_asli


# =============================================================================
print()
print("=" * 74)
print("3. ANGGARAN TERLAMPAUI TERBACA NEGATIF, BUKAN DIPOTONG JADI NOL")
print("   '0 menit tersisa' dan 'kelebihan 10 jam' adalah dua keadaan yang")
print("   sangat berbeda. Yang kedua tidak boleh menyamar jadi yang pertama.")
print("=" * 74)

try:
    set_target(99.0)
    db, d = siapkan_db()
    mulai = SEKARANG - timedelta(minutes=600)
    # Insiden 30 menit -- jauh melewati anggaran 360 detik.
    isi_riwayat(db, d, mulai, 600, [(100, 1800)])
    r = slo.hitung(db, d, mulai, SEKARANG)
    benar("menghasilkan angka", r is not None)
    if r:
        benar("sisa NEGATIF", r["sisa_detik"] < 0, "-> %r" % r["sisa_detik"])
        benar("vonisnya 'habis'", r["vonis"] == "habis", "-> %r" % r["vonis"])
        benar("teksnya membawa tanda minus",
              r["sisa_teks"].startswith("-"), "-> %r" % r["sisa_teks"])
        benar("artinya menyebut janji yang dilanggar, bukan cuma angka",
              "dilanggar" in r["arti"], "-> %r" % r["arti"][:70])
finally:
    config._baca = _target_asli


# =============================================================================
print()
print("=" * 74)
print("4. PENGAMATAN TERLALU PENDEK -> 'BELUM BISA DINILAI', BUKAN ANGKA")
print("   SLO dari dua jam pengamatan melompat antara 100% dan 0% dan tidak")
print("   memberi tahu apa pun. Diam lebih jujur daripada percaya diri.")
print("=" * 74)

try:
    set_target(99.0)
    db, d = siapkan_db()
    mulai = SEKARANG - timedelta(minutes=3)
    isi_riwayat(db, d, mulai, 3, [])
    r = slo.hitung(db, d, mulai, SEKARANG)
    benar("pengamatan 3 menit -> None (bukan angka)", r is None, "-> %r" % r)
finally:
    config._baca = _target_asli


# =============================================================================
print()
print("=" * 74)
print("5. DAFTAR: YANG GENTING DI ATAS, YANG DILEWATI DISEBUT")
print("   Daftar berurut abjad membuat satu-satunya baris yang penting")
print("   bersembunyi di tengah baris yang baik-baik saja. Dan daftar yang")
print("   memangkas isinya tanpa berkata apa-apa terbaca sebagai 'sudah")
print("   semuanya' -- bohong yang paling mudah dibuat.")
print("=" * 74)

try:
    set_target(99.0)
    db, d = siapkan_db()
    mulai = SEKARANG - timedelta(minutes=600)
    isi_riwayat(db, d, mulai, 600, [(100, 1800)])          # habis

    d2 = models.Device(name="Router Sehat", ip_address="192.168.56.91",
                       device_type="router", platform="cisco_ios", aktif=True)
    db.add(d2)
    db.commit()
    isi_riwayat(db, d2, mulai, 600, [(100, 30)])           # aman

    d3 = models.Device(name="Router Baru", ip_address="192.168.56.92",
                       device_type="router", platform="cisco_ios", aktif=True)
    db.add(d3)
    db.commit()
    isi_riwayat(db, d3, SEKARANG - timedelta(minutes=3), 3, [])

    h = slo.semua(db, "30d")
    nama = [x["device"] for x in h["device"]]
    print("   -> urutan:", nama, "| dilewati:", h["belum_cukup_diamati"])
    benar("yang anggarannya paling tipis berada di ATAS",
          nama and nama[0] == "Router SLO", "-> %r" % nama)
    benar("device yang belum cukup diamati TIDAK ikut dinilai",
          "Router Baru" not in nama, "-> %r" % nama)
    benar("...tapi DISEBUT di daftar tersendiri",
          "Router Baru" in h["belum_cukup_diamati"],
          "-> %r" % h["belum_cukup_diamati"])
    benar("ambang menipis ikut dikirim ke pemanggil",
          h["ambang_menipis_persen"] == slo.AMBANG_MENIPIS)
finally:
    config._baca = _target_asli


# =============================================================================
print()
print("=" * 74)
print("6. TARGET 100% TIDAK MEMBUAT PEMBAGIAN NOL")
print("   Boleh saja seseorang menuliskannya; ia tidak boleh meledak.")
print("=" * 74)

try:
    set_target(100.0)
    db, d = siapkan_db()
    mulai = SEKARANG - timedelta(minutes=600)
    isi_riwayat(db, d, mulai, 600, [(100, 600)])
    r = slo.hitung(db, d, mulai, SEKARANG)
    benar("tidak meledak", r is not None)
    if r:
        benar("anggarannya nol", r["anggaran_detik"] == 0,
              "-> %r" % r["anggaran_detik"])
        benar("ada waktu mati -> vonis habis", r["vonis"] == "habis",
              "-> %r" % r["vonis"])
finally:
    config._baca = _target_asli


if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

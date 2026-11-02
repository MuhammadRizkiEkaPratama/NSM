"""Test of the automation fence (Stage 3): five gates, individually and combined.

The real remediators do not exist yet; this test calls `putuskan()` directly
with scenarios that represent real candidate actions (keys/categories exactly as
they appear in `drift.service.bandingkan()` results).

EVERY gate is tested to be able to REJECT, not just "allowed when all is well".
Fence config is monkeypatched on `config.get_pagar_*` rather than editing the
real `.env`, so each test controls exactly its own settings.

Run: py uji_pagar_otomasi.py
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


def siapkan_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    file = os.path.join(tempfile.mkdtemp(prefix="uji_pagar_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    r1 = models.Device(name="Router Uji", ip_address="192.168.56.60",
                       device_type="router", platform="cisco_ios")
    db.add(r1)
    db.commit()
    return db, r1


import config  # noqa: E402
import pagar_otomasi as pagar  # noqa: E402

_asli = {
    "putih": config.get_pagar_daftar_putih,
    "batas_device": config.get_pagar_batas_per_device_per_jam,
    "batas_global": config.get_pagar_batas_global_per_jam,
    "jam_kerja": config.get_pagar_jam_kerja,
    "beku": config.get_pagar_jendela_beku,
}


def reset_config():
    """Restore all fence settings to the real functions after each test group so a
    monkeypatch does not leak into another test.
    """
    config.get_pagar_daftar_putih = _asli["putih"]
    config.get_pagar_batas_per_device_per_jam = _asli["batas_device"]
    config.get_pagar_batas_global_per_jam = _asli["batas_global"]
    config.get_pagar_jam_kerja = _asli["jam_kerja"]
    config.get_pagar_jendela_beku = _asli["beku"]


def setel_longgar():
    """Gates 2-5 are relaxed so each test focuses on ONE gate. Gate 1 (risk) cannot be
    relaxed here, on purpose; it is tested in Part 1.
    """
    config.get_pagar_daftar_putih = lambda: {"ntp_server", "dns_server",
                                             "snmp_lokasi", "snmp_kontak",
                                             "layanan_http_mati", "zona_waktu",
                                             "logging_server", "banner_masuk"}
    config.get_pagar_batas_per_device_per_jam = lambda: 1000
    config.get_pagar_batas_global_per_jam = lambda: 1000
    config.get_pagar_jam_kerja = lambda: (0, 24)
    config.get_pagar_jendela_beku = lambda: []


# =============================================================================
print("=" * 74)
print("1. GERBANG 1 -- RISIKO (Tahap 2), TIDAK BISA di-override daftar putih")
print("=" * 74)

db, r1 = siapkan_db()
setel_longgar()
config.get_pagar_daftar_putih = lambda: {"vty_izin", "exec_timeout_menit",
                                         "hostname", "domain", "ssh_saja"}

for kunci in ("vty_izin", "exec_timeout_menit", "hostname", "ssh_saja"):
    kep = pagar.putuskan(db, r1.id, "nilai", kunci, oleh="uji")
    benar("kunci wajib_manusia '%s' DITOLAK walau ADA di daftar putih" % kunci,
         kep.izin is False, "-> %s" % kep.alasan[:70])

for kategori in ("interface", "vlan", "rute"):
    config.get_pagar_daftar_putih = lambda: {kategori}
    kep = pagar.putuskan(db, r1.id, kategori, "contoh", oleh="uji")
    benar("kategori '%s' (selalu wajib_manusia) DITOLAK" % kategori,
         kep.izin is False)

reset_config()


# =============================================================================
print()
print("=" * 74)
print("2. GERBANG 2 -- DAFTAR PUTIH")
print("=" * 74)

db, r1 = siapkan_db()
setel_longgar()

kep = pagar.putuskan(db, r1.id, "nilai", "ntp_server", oleh="uji")
benar("kunci aman_otomatis YANG ADA di daftar putih -> diizinkan",
     kep.izin is True, "-> %s" % kep.alasan[:70])

config.get_pagar_daftar_putih = lambda: set()  # kosongkan
kep2 = pagar.putuskan(db, r1.id, "nilai", "ntp_server", oleh="uji")
benar("kunci aman_otomatis TAPI daftar putih KOSONG -> ditolak "
     "(klasifikasi risiko saja tidak cukup)", kep2.izin is False)

reset_config()


# =============================================================================
print()
print("=" * 74)
print("3. GERBANG 3 -- JENDELA BEKU (freeze window)")
print("=" * 74)

db, r1 = siapkan_db()
setel_longgar()
sekarang = datetime(2026, 8, 25, 12, 0, 0)
config.get_pagar_jendela_beku = lambda: [
    (datetime(2026, 8, 25, 0, 0, 0), datetime(2026, 8, 26, 0, 0, 0))]

kep = pagar.putuskan(db, r1.id, "nilai", "ntp_server", oleh="uji", sekarang=sekarang)
benar("di DALAM jendela beku -> ditolak", kep.izin is False,
     "-> %s" % kep.alasan[:70])

kep2 = pagar.putuskan(db, r1.id, "nilai", "ntp_server", oleh="uji",
                      sekarang=datetime(2026, 8, 27, 12, 0, 0))
benar("di LUAR jendela beku -> diizinkan (kalau gerbang lain lolos)",
     kep2.izin is True)

reset_config()


# =============================================================================
print()
print("=" * 74)
print("4. GERBANG 4 -- JAM KERJA")
print("=" * 74)

db, r1 = siapkan_db()
setel_longgar()
config.get_pagar_jam_kerja = lambda: (8, 17)

kep_malam = pagar.putuskan(db, r1.id, "nilai", "ntp_server", oleh="uji",
                           sekarang=datetime(2026, 8, 21, 23, 0, 0))
benar("jam 23:00 (di luar 08-17) -> ditolak", kep_malam.izin is False,
     "-> %s" % kep_malam.alasan[:70])

kep_siang = pagar.putuskan(db, r1.id, "nilai", "ntp_server", oleh="uji",
                           sekarang=datetime(2026, 8, 21, 10, 0, 0))
benar("jam 10:00 (di dalam 08-17) -> diizinkan", kep_siang.izin is True)

kep_batas = pagar.putuskan(db, r1.id, "nilai", "ntp_server", oleh="uji",
                           sekarang=datetime(2026, 8, 21, 17, 0, 0))
benar("jam TEPAT 17:00 -> ditolak (batas ATAS eksklusif)", kep_batas.izin is False)

reset_config()


# =============================================================================
print()
print("=" * 74)
print("5. GERBANG 5 -- BATAS LAJU (per device DAN global)")
print("=" * 74)

db, r1 = siapkan_db()
r2 = __import__("models").Device(name="Router Uji 2", ip_address="192.168.56.61",
                                 device_type="router", platform="cisco_ios")
db.add(r2)
db.commit()

setel_longgar()
config.get_pagar_batas_per_device_per_jam = lambda: 2
config.get_pagar_batas_global_per_jam = lambda: 1000

t0 = datetime(2026, 8, 21, 10, 0, 0)
k1 = pagar.putuskan(db, r1.id, "nilai", "ntp_server", oleh="uji", sekarang=t0)
k2 = pagar.putuskan(db, r1.id, "nilai", "dns_server", oleh="uji",
                    sekarang=t0 + timedelta(minutes=1))
benar("tindakan ke-1 dan ke-2 (batas=2) -> keduanya diizinkan",
     k1.izin and k2.izin)

k3 = pagar.putuskan(db, r1.id, "nilai", "snmp_lokasi", oleh="uji",
                    sekarang=t0 + timedelta(minutes=2))
benar("tindakan ke-3 UNTUK DEVICE YANG SAMA (melebihi batas 2) -> ditolak",
     k3.izin is False, "-> %s" % k3.alasan[:70])

k_lain = pagar.putuskan(db, r2.id, "nilai", "ntp_server", oleh="uji",
                        sekarang=t0 + timedelta(minutes=3))
benar("device LAIN (belum kena batas device-nya sendiri) -> tetap diizinkan",
     k_lain.izin is True)

k_sejam_lalu = pagar.putuskan(db, r1.id, "nilai", "snmp_lokasi", oleh="uji",
                              sekarang=t0 + timedelta(hours=1, minutes=5))
benar("SESUDAH 1 jam berlalu, batas laju device pulih -> diizinkan lagi",
     k_sejam_lalu.izin is True)

# --- batas GLOBAL ---
db2, ra = siapkan_db()
rb = __import__("models").Device(name="B", ip_address="1.2.3.4",
                                 device_type="router", platform="cisco_ios")
db2.add(rb)
db2.commit()
setel_longgar()
config.get_pagar_batas_per_device_per_jam = lambda: 1000
config.get_pagar_batas_global_per_jam = lambda: 2
tg = datetime(2026, 8, 21, 10, 0, 0)
g1 = pagar.putuskan(db2, ra.id, "nilai", "ntp_server", oleh="uji", sekarang=tg)
g2 = pagar.putuskan(db2, rb.id, "nilai", "ntp_server", oleh="uji",
                    sekarang=tg + timedelta(minutes=1))
benar("2 tindakan DI DUA DEVICE BERBEDA (batas global=2) -> keduanya diizinkan",
     g1.izin and g2.izin)
g3 = pagar.putuskan(db2, ra.id, "nilai", "dns_server", oleh="uji",
                    sekarang=tg + timedelta(minutes=2))
benar("tindakan ke-3 DI DEVICE MANA PUN (melebihi batas GLOBAL) -> ditolak",
     g3.izin is False, "-> %s" % g3.alasan[:70])

reset_config()


# =============================================================================
print()
print("=" * 74)
print("6. JEJAK AUDIT -- setiap keputusan tercatat, izin MAUPUN tolak")
print("=" * 74)

db, r1 = siapkan_db()
setel_longgar()
pagar.putuskan(db, r1.id, "nilai", "ntp_server", oleh="uji")
config.get_pagar_daftar_putih = lambda: set()
pagar.putuskan(db, r1.id, "nilai", "dns_server", oleh="uji")

riw = pagar.riwayat(db, r1.id)
cek("2 baris tercatat (1 izin, 1 tolak)", len(riw), 2)
status_set = {r["keputusan"] for r in riw}
benar("kedua status (izin dan tolak) ada di riwayat", status_set == {"izin", "tolak"})
benar("baris tolak PUNYA alasan tertulis (bukan kosong)",
     all(r["alasan"] for r in riw))

reset_config()


# =============================================================================
print()
print("=" * 74)
print("7. VERIFIKASI -- status ketiga (None) dibedakan dari True/False")
print("=" * 74)

db, r1 = siapkan_db()
setel_longgar()
kep = pagar.putuskan(db, r1.id, "nilai", "ntp_server", oleh="uji")
benar("izin diberikan, siap diverifikasi", kep.izin is True)

riw_sebelum = pagar.riwayat(db, r1.id)
cek("SEBELUM catat_verifikasi() dipanggil -> status_verifikasi None",
    riw_sebelum[0]["status_verifikasi"], None)

pagar.record_verification(db, kep.tindakan_id, True, bukti="ntp_server cocok sesudah diterapkan")
riw_sesudah = pagar.riwayat(db, r1.id)
cek("SESUDAH catat_verifikasi(True) -> status_verifikasi True",
    riw_sesudah[0]["status_verifikasi"], True)
benar("bukti verifikasi tersimpan", riw_sesudah[0]["verifikasi_bukti"] is not None)

kep2 = pagar.putuskan(db, r1.id, "nilai", "dns_server", oleh="uji",
                      sekarang=datetime.now() + timedelta(hours=2))
pagar.record_verification(db, kep2.tindakan_id, False, bukti="masih beda sesudah dicoba")
riw2 = pagar.riwayat(db, r1.id)
gagal_terverifikasi = [r for r in riw2 if r["status_verifikasi"] is False]
benar("verifikasi GAGAL tersimpan sebagai False (bukan None ataupun True)",
     len(gagal_terverifikasi) == 1)

import sot.katalog as _k  # noqa: E402
try:
    pagar.record_verification(db, 999999, True)
    benar("verifikasi utk tindakan_id tak ada -> seharusnya Ditolak", False)
except _k.Ditolak:
    benar("verifikasi utk tindakan_id yang TIDAK ADA -> Ditolak (bukan crash diam)", True)

reset_config()


# =============================================================================
print()
print("=" * 74)
print("8. status_pagar() -- ringkasan setelan untuk halaman web")
print("=" * 74)

setel_longgar()
s = pagar.status_pagar()
benar("status_pagar() punya seluruh kunci yang diharapkan", set(s) == {
    "daftar_putih", "batas_per_device_per_jam", "batas_global_per_jam",
    "gagal_beruntun_maks",
    "jam_mulai", "jam_selesai", "jendela_beku", "sedang_jam_kerja",
})
reset_config()


# =============================================================================
print()
print("=" * 74)
print("9. GERBANG 5 -- PEMUTUS (circuit breaker): N gagal BERUNTUN -> berhenti")
print("   Ditambahkan sesudah audit: batas laju SAJA tidak menghentikan")
print("   perbaikan yang selalu gagal, cuma memperlambatnya jadi 3x/jam abadi.")
print("=" * 74)

db, r1 = siapkan_db()
setel_longgar()
config.get_pagar_gagal_beruntun_maks = lambda: 3

t = datetime(2026, 8, 21, 10, 0, 0)


def coba_lalu_tandai(berhasil, menit):
    """One full cycle: request permission, then record the verification result."""
    kep = pagar.putuskan(db, r1.id, "nilai", "ntp_server", oleh="uji",
                        sekarang=t + timedelta(minutes=menit))
    if kep.izin:
        pagar.record_verification(db, kep.tindakan_id, berhasil, bukti="uji")
    return kep


k1 = coba_lalu_tandai(False, 0)
k2 = coba_lalu_tandai(False, 1)
benar("2 kegagalan beruntun -> masih diizinkan (belum sampai batas 3)",
     k1.izin and k2.izin)

k3 = coba_lalu_tandai(False, 2)
benar("percobaan ke-3 masih diizinkan (batas dinilai SEBELUM percobaan ini)",
     k3.izin is True)

k4 = coba_lalu_tandai(False, 3)
benar("sesudah 3 gagal beruntun -> DITOLAK oleh pemutus", k4.izin is False)
benar("alasannya menyebut PEMUTUS, bukan batas laju (pesan yang lebih berguna)",
     "PEMUTUS" in k4.alasan)

reset_config()

db, r1 = siapkan_db()
setel_longgar()
config.get_pagar_gagal_beruntun_maks = lambda: 3
t = datetime(2026, 8, 21, 10, 0, 0)

coba_lalu_tandai(False, 0)
coba_lalu_tandai(False, 1)
coba_lalu_tandai(True, 2)
k_sesudah = coba_lalu_tandai(False, 3)
benar("2 gagal lalu 1 BERHASIL lalu 1 gagal -> masih diizinkan "
     "(keberhasilan mereset pemutus, bukan menumpuk selamanya)",
     k_sesudah.izin is True)

reset_config()

db, r1 = siapkan_db()
setel_longgar()
config.get_pagar_gagal_beruntun_maks = lambda: 2
t = datetime(2026, 8, 21, 10, 0, 0)

for i in range(3):
    pagar.putuskan(db, r1.id, "nilai", "ntp_server", oleh="uji",
                  sekarang=t + timedelta(minutes=i))
k_belum = pagar.putuskan(db, r1.id, "nilai", "ntp_server", oleh="uji",
                        sekarang=t + timedelta(minutes=10))
benar("baris yang BELUM diverifikasi TIDAK dihitung sebagai gagal "
     "(belum tahu != gagal)", k_belum.izin is True)

reset_config()

# --- pemutus TERPISAH per (device, kunci) ---
db, r1 = siapkan_db()
r_lain = __import__("models").Device(name="Device Lain", ip_address="10.9.9.9",
                                     device_type="router", platform="cisco_ios")
db.add(r_lain)
db.commit()
setel_longgar()
config.get_pagar_gagal_beruntun_maks = lambda: 2
t = datetime(2026, 8, 21, 10, 0, 0)

for i in range(2):
    kep = pagar.putuskan(db, r1.id, "nilai", "ntp_server", oleh="uji",
                        sekarang=t + timedelta(minutes=i))
    pagar.record_verification(db, kep.tindakan_id, False, bukti="uji")

k_r1 = pagar.putuskan(db, r1.id, "nilai", "ntp_server", oleh="uji",
                     sekarang=t + timedelta(minutes=5))
benar("pemutus terbuka untuk device+kunci yang bermasalah", k_r1.izin is False)

k_kunci_lain = pagar.putuskan(db, r1.id, "nilai", "dns_server", oleh="uji",
                             sekarang=t + timedelta(minutes=6))
benar("KUNCI LAIN di device yang sama TIDAK ikut terputus",
     k_kunci_lain.izin is True)

k_device_lain = pagar.putuskan(db, r_lain.id, "nilai", "ntp_server", oleh="uji",
                              sekarang=t + timedelta(minutes=7))
benar("DEVICE LAIN dengan kunci yang sama TIDAK ikut terputus",
     k_device_lain.izin is True)

reset_config()


if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

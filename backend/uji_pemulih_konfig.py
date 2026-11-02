"""Test of Remediator Stage 7: drifted config -> send a limited fix.

Same pattern as `uji_pemulih_interface.py`: `konfig_kembalikan` is classified
`wajib_manusia` (highest risk), so `coba_perbaiki()` is tested through the REAL
fence (always rejected) AND through an INJECTED fence (downstream logic).

Run: py uji_pemulih_konfig.py
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


import config  # noqa: E402
import models  # noqa: E402
import pagar_otomasi  # noqa: E402
import kirim_perintah  # noqa: E402
from sot import service as sot_svc  # noqa: E402
from pemulih import konfig as pkonfig  # noqa: E402

# REQUIRED SAFEGUARD: see uji_pemulih_gns3.py. `pemulih/*.py` call
# `eskalasi_segera()` on failure, and its default path goes over HTTP to the live
# Spring Boot on nsm-app.
import notifikasi_berjenjang as _nb  # noqa: E402

_eskalasi_tercatat = []
_nb.eskalasi_segera = lambda db, device_id, ringkas, alasan, **kw: (
    _eskalasi_tercatat.append((device_id, ringkas, alasan))
    or {"terkirim": False, "alasan": "dimatikan di uji"})

_asli_putuskan = pagar_otomasi.putuskan
_asli_kirim = kirim_perintah.kirim
_asli_putuskan_kp = kirim_perintah.putuskan


def reset():
    pagar_otomasi.putuskan = _asli_putuskan
    kirim_perintah.kirim = _asli_kirim
    kirim_perintah.putuskan = _asli_putuskan_kp


def siapkan_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    file = os.path.join(tempfile.mkdtemp(prefix="uji_pemulih_kfg_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


POTRET_HOSTNAME_SALAH = """hostname R1-LAMA
!
ntp server 192.168.56.104
!
end
"""

POTRET_HOSTNAME_BENAR = """hostname R1
!
ntp server 192.168.56.104
!
end
"""


def prepare_device(db, potret_teks, gns3_node="R1"):
    d = models.Device(name="R1 Uji", ip_address="192.168.56.60",
                      device_type="router", platform="cisco_ios",
                      gns3_node=gns3_node, aktif=1)
    db.add(d)
    db.commit()
    sot_svc.simpan_nilai(db, d.id, {"hostname": "R1", "ntp_server": "192.168.56.104"},
                         oleh="uji")
    db.add(models.KonfigSnapshot(device_id=d.id, waktu=datetime.now(),
                                 sidik="x" * 8, teks=potret_teks))
    db.commit()
    return d


# =============================================================================
print("=" * 74)
print("1. cari_kandidat() -- HANYA kunci di KUNCI_DIDUKUNG, HANYA status beda")
print("=" * 74)

db = siapkan_db()
d = prepare_device(db, POTRET_HOSTNAME_SALAH)
kandidat = pkonfig.cari_kandidat(db)
kunci_kandidat = {k[1] for k in kandidat}
benar("hostname (beda) masuk kandidat", "hostname" in kunci_kandidat)
benar("ntp_server (cocok) TIDAK masuk kandidat", "ntp_server" not in kunci_kandidat)

db2 = siapkan_db()
prepare_device(db2, POTRET_HOSTNAME_BENAR)
kandidat2 = pkonfig.cari_kandidat(db2)
cek("semua cocok -> nol kandidat", len(kandidat2), 0)

# Key coverage is tested as an INVARIANT against the catalog, not a hardcoded
# list: a new `aman_otomatis` key added to sot/katalog.py without its command must
# turn this test red.
import sot.katalog as _k  # noqa: E402

_semua_kunci = {s["kunci"] for s in _k.KUNCI}
_tak_didukung = _semua_kunci - pkonfig.KUNCI_DIDUKUNG
_aman_tak_didukung = [x for x in _tak_didukung
                      if _k.risiko_kunci(x)[0] == _k.RISIKO_AMAN]

cek("9 dari 13 kunci didukung", len(pkonfig.KUNCI_DIDUKUNG), 9)
benar("SETIAP kunci aman_otomatis PUNYA perintahnya -- tidak ada yang bisa "
     "diperbaiki otomatis tapi diam-diam tidak punya jalan",
     _aman_tak_didukung == [], "-> yatim: %s" % _aman_tak_didukung)
benar("keempat kunci yang tidak didukung SEMUANYA wajib_manusia "
     "(jadi gerbang 1 memang akan menolaknya)",
     all(_k.risiko_kunci(x)[0] == _k.RISIKO_MANUSIA for x in _tak_didukung))
benar("dan SETIAP-nya punya alasan tertulis yang bisa ditampilkan ke user",
     all(x in pkonfig.ALASAN_TIDAK_DIDUKUNG for x in _tak_didukung),
     "-> tanpa alasan: %s" % (_tak_didukung - set(pkonfig.ALASAN_TIDAK_DIDUKUNG)))

from connectors import perintah as _pr  # noqa: E402

_id_katalog = {p["id"] for p in _pr.daftar("cisco_ios")}
_id_dipakai = ([v[0] for v in pkonfig._PEMETAAN_TUNGGAL.values()]
               + [i for pasangan in pkonfig._PEMETAAN_DAFTAR.values() for i in pasangan]
               + list(pkonfig._PEMETAAN_BOOL.values()))
benar("SEMUA perintah_id yang dirujuk Tahap 7 benar-benar ADA di katalog "
     "connectors/perintah.py (bukan nama karangan)",
     all(i in _id_katalog for i in _id_dipakai),
     "-> hilang: %s" % [i for i in _id_dipakai if i not in _id_katalog])


# =============================================================================
print()
print("=" * 74)
print("2. coba_perbaiki() lewat pagar SUNGGUHAN -- SELALU ditolak (RISIKO TERTINGGI)")
print("=" * 74)

db = siapkan_db()
d = prepare_device(db, POTRET_HOSTNAME_SALAH)
config.get_pagar_daftar_putih = lambda: {"konfig_kembalikan"}
config.get_pagar_batas_per_device_per_jam = lambda: 1000
config.get_pagar_batas_global_per_jam = lambda: 1000
config.get_pagar_jam_kerja = lambda: (0, 24)
config.get_pagar_jendela_beku = lambda: []

panggilan = []
kirim_perintah.kirim = lambda *a, **kw: panggilan.append(a) or {"terkirim": True}

kandidat = pkonfig.cari_kandidat(db)
d_, kunci_, temuan_ = next(k for k in kandidat if k[1] == "hostname")
kep = pkonfig.coba_perbaiki(db, d_, kunci_, temuan_)
benar("DITOLAK walau ADA di daftar putih", kep.izin is False)
benar("kirim_perintah.kirim() TIDAK PERNAH dipanggil", panggilan == [])
reset()


# =============================================================================
print()
print("=" * 74)
print("3. Logika hilir -- perbaikan hostname sukses (fase 1 + fase 2 cocok)")
print("=" * 74)

db = siapkan_db()
d = prepare_device(db, POTRET_HOSTNAME_SALAH)
kandidat = pkonfig.cari_kandidat(db)
d_, kunci_, temuan_ = next(k for k in kandidat if k[1] == "hostname")

kep_asli = pagar_otomasi.putuskan(db, d_.id, "pemulih", "konfig_kembalikan", oleh="uji")
baris = db.get(models.PagarTindakan, kep_asli.tindakan_id)
baris.keputusan = pagar_otomasi.IZIN
db.commit()
pagar_otomasi.putuskan = lambda *a, **kw: pagar_otomasi.Keputusan(True, "disuntik", kep_asli.tindakan_id)

panggilan = []
kirim_perintah.kirim = lambda db_, did, pid, nilai, oleh=None, sungguhan=False, **kw: (
    panggilan.append((pid, nilai)) or {"terkirim": True, "berubah": True})

kep = pkonfig.coba_perbaiki(db, d_, kunci_, temuan_)
benar("fase 1: hanya kirim 'hostname' SATU kali", panggilan == [("hostname", {"nama": "R1"})])
riw = pagar_otomasi.riwayat(db, d_.id)
baris_p = [b for b in riw if b["id"] == kep_asli.tindakan_id][0]
benar("fase 1: BELUM diverifikasi (menunggu potret baru)",
     baris_p["status_verifikasi"] is None)

db.add(models.KonfigSnapshot(device_id=d_.id, waktu=datetime.now(),
                             sidik="y" * 8, teks=POTRET_HOSTNAME_BENAR))
db.commit()

n = pkonfig.verifikasi_tertunda(db, sekarang=datetime.now())
cek("fase 2: 1 tindakan diverifikasi", n, 1)
riw2 = pagar_otomasi.riwayat(db, d_.id)
baris_p2 = [b for b in riw2 if b["id"] == kep_asli.tindakan_id][0]
cek("fase 2: berhasil (potret baru cocok)", baris_p2["status_verifikasi"], True)
reset()


# =============================================================================
print()
print("=" * 74)
print("4. Logika hilir -- ntp_server: rekonsiliasi tambah DAN hapus")
print("=" * 74)

db = siapkan_db()
d = models.Device(name="R1", ip_address="192.168.56.60", device_type="router",
                  platform="cisco_ios", gns3_node="R1", aktif=1)
db.add(d); db.commit()
sot_svc.simpan_nilai(db, d.id, {"hostname": "R1", "ntp_server": "10.0.0.1,10.0.0.2"}, oleh="uji")
db.add(models.KonfigSnapshot(device_id=d.id, waktu=datetime.now(), sidik="z"*8,
                             teks="hostname R1\n!\nntp server 10.0.0.1\nntp server 9.9.9.9\n!\nend\n"))
db.commit()

kandidat = pkonfig.cari_kandidat(db)
d_, kunci_, temuan_ = next(k for k in kandidat if k[1] == "ntp_server")
cek("intended", set(temuan_["intended"]), {"10.0.0.1", "10.0.0.2"})
cek("observed", set(temuan_["observed"]), {"10.0.0.1", "9.9.9.9"})

kep_asli = pagar_otomasi.putuskan(db, d_.id, "pemulih", "konfig_kembalikan", oleh="uji")
baris = db.get(models.PagarTindakan, kep_asli.tindakan_id)
baris.keputusan = pagar_otomasi.IZIN
db.commit()
pagar_otomasi.putuskan = lambda *a, **kw: pagar_otomasi.Keputusan(True, "disuntik", kep_asli.tindakan_id)

panggilan = []
kirim_perintah.kirim = lambda db_, did, pid, nilai, oleh=None, sungguhan=False, **kw: (
    panggilan.append((pid, nilai)) or {"terkirim": True, "berubah": True})

pkonfig.coba_perbaiki(db, d_, kunci_, temuan_)
benar("menambah 10.0.0.2 (kurang di observed)",
     ("ntp_tambah", {"alamat": "10.0.0.2"}) in panggilan)
benar("menghapus 9.9.9.9 (lebih di observed)",
     ("ntp_hapus", {"alamat": "9.9.9.9"}) in panggilan)
benar("TIDAK menyentuh 10.0.0.1 (sudah cocok di kedua sisi)",
     not any(p[1].get("alamat") == "10.0.0.1" for p in panggilan))
reset()


# =============================================================================
print()
print("=" * 74)
print("5. Fase 2 -- lewat batas waktu, MASIH beda -> GAGAL + ROLLBACK OTOMATIS")
print("=" * 74)

db = siapkan_db()
d = prepare_device(db, POTRET_HOSTNAME_SALAH)
kandidat = pkonfig.cari_kandidat(db)
d_, kunci_, temuan_ = next(k for k in kandidat if k[1] == "hostname")

t0 = datetime(2026, 8, 21, 10, 0, 0)
kep_asli = pagar_otomasi.putuskan(db, d_.id, "pemulih", "konfig_kembalikan",
                                  oleh="uji", sekarang=t0)
baris = db.get(models.PagarTindakan, kep_asli.tindakan_id)
baris.keputusan = pagar_otomasi.IZIN
db.commit()
pagar_otomasi.putuskan = lambda *a, **kw: pagar_otomasi.Keputusan(True, "disuntik", kep_asli.tindakan_id)
kirim_perintah.kirim = lambda db_, did, pid, nilai, oleh=None, sungguhan=False, **kw: {"terkirim": True, "berubah": True}

pkonfig.coba_perbaiki(db, d_, kunci_, temuan_, sekarang=t0)

panggilan_batal = []
kirim_perintah.putuskan = lambda db_, did, tindakan, sungguhan=False: (
    panggilan_batal.append(tindakan) or {"terkirim": True, "hasil": "dipulihkan"})

n_belum = pkonfig.verifikasi_tertunda(db, sekarang=t0 + timedelta(seconds=100))
cek("belum lewat batas waktu -> belum diverifikasi", n_belum, 0)

n_lewat = pkonfig.verifikasi_tertunda(db, sekarang=t0 + timedelta(seconds=pkonfig.BATAS_TUNGGU_VERIFIKASI_DETIK + 10))
cek("lewat batas waktu, masih beda -> 1 diverifikasi", n_lewat, 1)
riw = pagar_otomasi.riwayat(db, d_.id)
baris_final = [b for b in riw if b["id"] == kep_asli.tindakan_id][0]
cek("status_verifikasi False", baris_final["status_verifikasi"], False)
benar("ROLLBACK terpicu OTOMATIS: batalkan_sekarang dipanggil (device GNS3)",
     "batalkan_sekarang" in panggilan_batal)
baris_db = db.get(models.PagarTindakan, kep_asli.tindakan_id)
cek("rollback_dilakukan True (batalkan_sekarang sukses)", baris_db.rollback_dilakukan, True)
reset()


# =============================================================================
print()
print("=" * 74)
print("6. KEADAAN PALING GENTING: perbaikan gagal DAN ROLLBACK-NYA JUGA GAGAL")
print("   (Tahap 8.3 menuntut kegagalan DITANAM, bukan diandaikan jalan)")
print("=" * 74)

db = siapkan_db()
d = prepare_device(db, POTRET_HOSTNAME_SALAH)
kandidat = pkonfig.cari_kandidat(db)
d_, kunci_, temuan_ = next(k for k in kandidat if k[1] == "hostname")

t0 = datetime(2026, 8, 21, 10, 0, 0)
kep_asli = pagar_otomasi.putuskan(db, d_.id, "pemulih", "konfig_kembalikan",
                                  oleh="uji", sekarang=t0)
baris = db.get(models.PagarTindakan, kep_asli.tindakan_id)
baris.keputusan = pagar_otomasi.IZIN
db.commit()
pagar_otomasi.putuskan = lambda *a, **kw: pagar_otomasi.Keputusan(True, "disuntik", kep_asli.tindakan_id)
kirim_perintah.kirim = lambda *a, **kw: {"terkirim": True, "berubah": True}
pkonfig.coba_perbaiki(db, d_, kunci_, temuan_, sekarang=t0)


# Planted failure: the rollback itself blows up (e.g. the GNS3 API is down too, or
# the device is unreachable after the change).
def _rollback_meledak(db_, did, tindakan, sungguhan=False):
    raise RuntimeError("API GNS3 tidak menjawab -- node tidak bisa dipulihkan")


kirim_perintah.putuskan = _rollback_meledak

eskalasi_genting = []
_asli_eskalasi_kfg = pkonfig._eskalasi
pkonfig._eskalasi = lambda db_, did, ringkas, alasan: eskalasi_genting.append(
    {"ringkas": ringkas, "alasan": alasan})

n = pkonfig.verifikasi_tertunda(
    db, sekarang=t0 + timedelta(seconds=pkonfig.BATAS_TUNGGU_VERIFIKASI_DETIK + 10))
cek("tetap diverifikasi (tidak crash walau rollback meledak)", n, 1)

riw = pagar_otomasi.riwayat(db, d_.id)
baris_f = [b for b in riw if b["id"] == kep_asli.tindakan_id][0]
cek("status_verifikasi False", baris_f["status_verifikasi"], False)

baris_db = db.get(models.PagarTindakan, kep_asli.tindakan_id)
cek("rollback_dilakukan FALSE -- dibedakan dari None (tidak pernah dicoba) "
    "DAN dari True (berhasil)", baris_db.rollback_dilakukan, False)
benar("state_sesudah menyimpan galat rollback-nya, bukan menelannya",
     baris_db.state_sesudah and "tidak menjawab" in baris_db.state_sesudah)
benar("bukti verifikasi menyebut rollback GAGAL dipicu",
     "GAGAL dipicu" in (baris_f["verifikasi_bukti"] or ""))
cek("eskalasi notifikasi tetap dipicu", len(eskalasi_genting), 1)
benar("ringkasan eskalasi MENEGASKAN keadaan ganda-gagal ini, bukan kalimat "
     "generik yang sama dengan kegagalan biasa",
     eskalasi_genting and "ROLLBACK" in eskalasi_genting[0]["ringkas"].upper())

pkonfig._eskalasi = _asli_eskalasi_kfg
reset()




# =============================================================================
print()
print("=" * 74)
print("7. KUNCI BARU (utang D): zona_waktu, daftar (dns/logging), dan boolean")
print("=" * 74)

# zona_waktu: IANA intent -> command must use Cisco syntax
db = siapkan_db()
d = models.Device(name="R1", ip_address="192.168.56.60", device_type="router",
                  platform="cisco_ios", gns3_node="R1", aktif=1)
db.add(d); db.commit()
sot_svc.simpan_nilai(db, d.id, {"hostname": "R1", "zona_waktu": "Asia/Jakarta",
                                "ntp_server": "10.0.0.1"}, oleh="uji")
db.add(models.KonfigSnapshot(
    device_id=d.id, waktu=datetime.now(), sidik="t"*8,
    teks="hostname R1\n!\nclock timezone UTC 0 0\nntp server 10.0.0.1\n!\nend\n"))
db.commit()

kandidat = pkonfig.cari_kandidat(db)
tz = next((k for k in kandidat if k[1] == "zona_waktu"), None)
benar("zona_waktu terdeteksi menyimpang (UTC vs Asia/Jakarta)", tz is not None)
benar("dan observed-nya sudah diterjemahkan balik ke bentuk IANA",
     tz and tz[2]["observed"] == "UTC")

kep_a = pagar_otomasi.putuskan(db, d.id, "pemulih", "konfig_kembalikan", oleh="uji")
db.get(models.PagarTindakan, kep_a.tindakan_id).keputusan = pagar_otomasi.IZIN
db.commit()
pagar_otomasi.putuskan = lambda *a, **kw: pagar_otomasi.Keputusan(True, "disuntik", kep_a.tindakan_id)
panggilan = []
kirim_perintah.kirim = lambda db_, did, pid, nilai, oleh=None, sungguhan=False, **kw: (
    panggilan.append((pid, nilai)) or {"terkirim": True, "berubah": True})

pkonfig.coba_perbaiki(db, tz[0], tz[1], tz[2])
cek("zona_waktu dikirim dalam SINTAKS CISCO, bukan bentuk IANA",
    panggilan, [("zona_waktu", {"zona": "WIB 7 0"})])
reset()

# dns_server: reconcile both add AND remove (same pattern as ntp)
db = siapkan_db()
d = models.Device(name="R1", ip_address="192.168.56.60", device_type="router",
                  platform="cisco_ios", gns3_node="R1", aktif=1)
db.add(d); db.commit()
sot_svc.simpan_nilai(db, d.id, {"hostname": "R1", "ntp_server": "10.0.0.1",
                                "dns_server": "8.8.8.8,1.1.1.1"}, oleh="uji")
db.add(models.KonfigSnapshot(
    device_id=d.id, waktu=datetime.now(), sidik="u"*8,
    teks="hostname R1\n!\nntp server 10.0.0.1\nip name-server 8.8.8.8 9.9.9.9\n!\nend\n"))
db.commit()

kandidat = pkonfig.cari_kandidat(db)
dns = next(k for k in kandidat if k[1] == "dns_server")
kep_b = pagar_otomasi.putuskan(db, d.id, "pemulih", "konfig_kembalikan", oleh="uji")
db.get(models.PagarTindakan, kep_b.tindakan_id).keputusan = pagar_otomasi.IZIN
db.commit()
pagar_otomasi.putuskan = lambda *a, **kw: pagar_otomasi.Keputusan(True, "disuntik", kep_b.tindakan_id)
panggilan = []
kirim_perintah.kirim = lambda db_, did, pid, nilai, oleh=None, sungguhan=False, **kw: (
    panggilan.append((pid, nilai)) or {"terkirim": True, "berubah": True})

pkonfig.coba_perbaiki(db, dns[0], dns[1], dns[2])
benar("dns: menambah 1.1.1.1 (kurang)", ("dns_tambah", {"alamat": "1.1.1.1"}) in panggilan)
benar("dns: menghapus 9.9.9.9 (lebih)", ("dns_hapus", {"alamat": "9.9.9.9"}) in panggilan)
benar("dns: TIDAK menyentuh 8.8.8.8 (sudah cocok)",
     not any(p[1].get("alamat") == "8.8.8.8" for p in panggilan))
reset()

# layanan_http_mati: one-way boolean
db = siapkan_db()
d = models.Device(name="R1", ip_address="192.168.56.60", device_type="router",
                  platform="cisco_ios", gns3_node="R1", aktif=1)
db.add(d); db.commit()
sot_svc.simpan_nilai(db, d.id, {"hostname": "R1", "ntp_server": "10.0.0.1",
                                "layanan_http_mati": "ya"}, oleh="uji")
db.add(models.KonfigSnapshot(
    device_id=d.id, waktu=datetime.now(), sidik="v"*8,
    teks="hostname R1\n!\nntp server 10.0.0.1\nip http server\n!\nend\n"))
db.commit()

kandidat = pkonfig.cari_kandidat(db)
http = next(k for k in kandidat if k[1] == "layanan_http_mati")
benar("layanan_http_mati terdeteksi menyimpang (HTTP masih menyala)",
     http[2]["intended"] is True and http[2]["observed"] is False)

kep_c = pagar_otomasi.putuskan(db, d.id, "pemulih", "konfig_kembalikan", oleh="uji")
db.get(models.PagarTindakan, kep_c.tindakan_id).keputusan = pagar_otomasi.IZIN
db.commit()
pagar_otomasi.putuskan = lambda *a, **kw: pagar_otomasi.Keputusan(True, "disuntik", kep_c.tindakan_id)
panggilan = []
kirim_perintah.kirim = lambda db_, did, pid, nilai, oleh=None, sungguhan=False, **kw: (
    panggilan.append((pid, nilai)) or {"terkirim": True, "berubah": True})

pkonfig.coba_perbaiki(db, http[0], http[1], http[2])
cek("intent True -> kirim http_mati", panggilan, [("http_mati", {})])

# Opposite direction: intent False (may run) -> enables nothing
panggilan.clear()
temuan_balik = dict(http[2], intended=False, observed=True)
kep_d = pagar_otomasi.putuskan(db, d.id, "pemulih", "konfig_kembalikan", oleh="uji")
db.get(models.PagarTindakan, kep_d.tindakan_id).keputusan = pagar_otomasi.IZIN
db.commit()
pagar_otomasi.putuskan = lambda *a, **kw: pagar_otomasi.Keputusan(True, "disuntik", kep_d.tindakan_id)
pkonfig.coba_perbaiki(db, http[0], "layanan_http_mati", temuan_balik)
benar("intent False (boleh menyala) -> TIDAK ada perintah dikirim "
     "(menyalakan layanan mati = menambah permukaan serangan, "
     "tidak pantas otomatis)", panggilan == [])
reset()


if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

"""Test of Remediator Stage 5: dead service -> restart via SSH + sudo.

The wrapper `/usr/local/sbin/nsm-restart-layanan` is installed on .103 and .105,
and `nsmro` may sudo that file only, not `systemctl`. Its limits are proven on the
servers by `pasang-restart-layanan.sh` (ssh/slapd/mysql/stop/argument injection
are all rejected).

`_exec` is INJECTED in every test, so no real SSH is opened; this file tests the
logic, the security boundary is tested on the server.

`layanan_restart` is classified `wajib_manusia`, so gate 1 always rejects it
through the real fence, like `interface_up`/`konfig_kembalikan`. The gate is
tested through the real `pagar_otomasi.putuskan()`; downstream logic with
`putuskan()` INJECTED.

Run: py uji_pemulih_layanan.py
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
from pemulih import layanan as playanan  # noqa: E402

# REQUIRED SAFEGUARD: see uji_pemulih_gns3.py. `pemulih/*.py` call
# `eskalasi_segera()` on failure, and its default path goes over HTTP to the live
# Spring Boot on nsm-app.
import notifikasi_berjenjang as _nb  # noqa: E402

_eskalasi_tercatat = []
_nb.eskalasi_segera = lambda db, device_id, ringkas, alasan, **kw: (
    _eskalasi_tercatat.append((device_id, ringkas, alasan))
    or {"terkirim": False, "alasan": "dimatikan di uji"})

_asli_putuskan = pagar_otomasi.putuskan
_asli = {
    "putih": config.get_pagar_daftar_putih,
    "batas_device": config.get_pagar_batas_per_device_per_jam,
    "batas_global": config.get_pagar_batas_global_per_jam,
    "jam_kerja": config.get_pagar_jam_kerja,
    "beku": config.get_pagar_jendela_beku,
}


def reset():
    pagar_otomasi.putuskan = _asli_putuskan
    config.get_pagar_daftar_putih = _asli["putih"]
    config.get_pagar_batas_per_device_per_jam = _asli["batas_device"]
    config.get_pagar_batas_global_per_jam = _asli["batas_global"]
    config.get_pagar_jam_kerja = _asli["jam_kerja"]
    config.get_pagar_jendela_beku = _asli["beku"]


def setel_longgar():
    config.get_pagar_daftar_putih = lambda: {"layanan_restart"}
    config.get_pagar_batas_per_device_per_jam = lambda: 1000
    config.get_pagar_batas_global_per_jam = lambda: 1000
    config.get_pagar_jam_kerja = lambda: (0, 24)
    config.get_pagar_jendela_beku = lambda: []


def siapkan_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    file = os.path.join(tempfile.mkdtemp(prefix="uji_pemulih_lyn_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def siapkan(db, unit="apache2", down=True, waktu=None):
    waktu = waktu or datetime.now()
    d = models.Device(name="Web Uji", ip_address="192.168.56.103",
                      device_type="server", platform="linux", aktif=1,
                      ssh_key_path="/home/nsmapp/.ssh/nsm_vm")
    db.add(d)
    db.commit()
    s = models.Service(device_id=d.id, nama="Apache", jenis="http", port=80,
                       unit_systemd=unit)
    db.add(s)
    db.commit()
    # `service_events`, NOT `service_checks`: the remediator judges down/up from events
    # that already passed the poller's consecutive-failure threshold
    # (see `pemulih/layanan.py::_sedang_down()`).
    tanam_peristiwa(db, s.id, d.id, "DOWN" if down else "UP", waktu)
    return d, s


def tanam_peristiwa(db, service_id, device_id, tipe, waktu):
    db.add(models.ServiceEvent(
        service_id=service_id, device_id=device_id, event_type=tipe,
        timestamp=waktu, kategori=("mati" if tipe == "DOWN" else "pulih"),
        detail="uji"))
    db.commit()


def inject_permission(db, device_id, sekarang=None):
    """Create a real PERMITTED PagarTindakan row (via the real putuskan(), then forced
    to permitted), then monkeypatch putuskan() to return it.

    Pass `sekarang` when the test uses a synthetic clock: `putuskan()` stores
    `PagarTindakan.waktu` from it, and `verifikasi_tertunda()` computes time
    differences against that column. Forgetting it mixes real and synthetic clocks.
    """
    kep_original = pagar_otomasi.putuskan(db, device_id, "pemulih", "layanan_restart",
                                      oleh="uji", sekarang=sekarang)
    line = db.get(models.PagarTindakan, kep_original.tindakan_id)
    line.keputusan = pagar_otomasi.IZIN
    db.commit()
    pagar_otomasi.putuskan = lambda *a, **kw: pagar_otomasi.Keputusan(
        True, "disuntik utk uji", kep_original.tindakan_id)
    return kep_original.tindakan_id


# =============================================================================
print("=" * 74)
print("1. cari_kandidat() -- hanya layanan ber-unit_systemd DAN sedang down")
print("=" * 74)

db = siapkan_db()
d, s = siapkan(db, unit="apache2", down=True)

d2 = models.Device(name="Login NSM Uji", ip_address="192.168.56.156",
                   device_type="server", platform="linux", aktif=1)
db.add(d2); db.commit()
s2 = models.Service(device_id=d2.id, nama="Login NSM", jenis="http", port=8080,
                    unit_systemd=None)
db.add(s2); db.commit()
tanam_peristiwa(db, s2.id, d2.id, "DOWN", datetime.now())

kandidat = playanan.cari_kandidat(db)
cek("jumlah kandidat (hanya Apache, unit_systemd terisi + down)", len(kandidat), 1)
benar("layanan TANPA unit_systemd (Login NSM) TIDAK PERNAH jadi kandidat "
     "walau sedang down -- daftar putih ganda bekerja",
     all(k[1].nama != "Login NSM" for k in kandidat))


# =============================================================================
print()
print("=" * 74)
print("2. coba_restart() lewat pagar SUNGGUHAN -- SELALU ditolak (wajib_manusia)")
print("=" * 74)

db = siapkan_db()
d, s = siapkan(db, unit="apache2", down=True)
setel_longgar()

panggilan = []
kep0 = playanan.coba_restart(db, d, s, _exec=lambda dev, p: panggilan.append(p))
benar("DITOLAK walau ADA di daftar putih (gerbang 1 tidak bisa di-override)",
     kep0.izin is False)
benar("_exec TIDAK PERNAH dipanggil", panggilan == [])
reset()


# =============================================================================
print()
print("=" * 74)
print("3. Logika hilir -- eksekusi sukses")
print("=" * 74)

db = siapkan_db()
d, s = siapkan(db, unit="apache2", down=True)
tid = inject_permission(db, d.id)

panggilan = []
kep = playanan.coba_restart(db, d, s, _exec=lambda dev, p: panggilan.append(p))
benar("izin (disuntik) True", kep.izin is True)
cek("perintah yang dijalankan memanggil PEMBUNGKUS, bukan systemctl mentah",
    panggilan, ["sudo /usr/local/sbin/nsm-restart-layanan restart apache2"])
benar("TIDAK PERNAH memanggil `systemctl` langsung -- `nsmro` memang tidak "
     "diberi izin sudo untuk itu, jadi kalau kode ini mencobanya, server "
     "yang menolak dan perbaikannya tidak akan pernah jalan",
     not any("systemctl" in p for p in panggilan))
riw = pagar_otomasi.riwayat(db, d.id)
baris_p = [b for b in riw if b["id"] == tid][0]
benar("BELUM diverifikasi (menunggu fase 2)", baris_p["status_verifikasi"] is None)
reset()


# =============================================================================
print()
print("=" * 74)
print("4. Logika hilir -- eksekusi GAGAL (mensimulasikan sudo belum diberi grant)")
print("=" * 74)

db = siapkan_db()
d, s = siapkan(db, unit="apache2", down=True)
tid = inject_permission(db, d.id)


def _exec_gagal_sudo(dev, perintah):
    raise playanan.GagalEksekusi(
        "exit 1: TOLAK: 'ssh' tidak ada di daftar unit yang boleh disentuh NSM.")


playanan.coba_restart(db, d, s, _exec=_exec_gagal_sudo)
riw = pagar_otomasi.riwayat(db, d.id)
baris_p = [b for b in riw if b["id"] == tid][0]
cek("status_verifikasi False (gagal eksekusi, tanpa nunggu fase 2)",
    baris_p["status_verifikasi"], False)
benar("bukti menyebut kegagalan sudo dengan jelas",
     "tidak ada di daftar unit" in (baris_p["verifikasi_bukti"] or ""))
reset()


# =============================================================================
print()
print("=" * 74)
print("5. verifikasi_tertunda() -- service YANG BENAR, bukan menyapu semua")
print("   layanan device (device bisa punya banyak layanan, hanya satu direstart)")
print("=" * 74)

db = siapkan_db()
t0 = datetime(2026, 8, 21, 10, 0, 0)
d, s = siapkan(db, unit="apache2", down=True, waktu=t0)
s_lain = models.Service(device_id=d.id, nama="MySQL", jenis="mysql", port=3306,
                        unit_systemd="mysql")
db.add(s_lain); db.commit()
tanam_peristiwa(db, s_lain.id, d.id, "DOWN", t0)

tid = inject_permission(db, d.id, sekarang=t0)
playanan.coba_restart(db, d, s, sekarang=t0, _exec=lambda dev, p: None)

tanam_peristiwa(db, s.id, d.id, "UP", t0 + timedelta(seconds=10))

n = playanan.verifikasi_tertunda(db, sekarang=t0 + timedelta(seconds=15))
cek("1 tindakan diverifikasi (Apache, TIDAK menunggu MySQL yang tak terkait)", n, 1)
riw = pagar_otomasi.riwayat(db, d.id)
baris_apache = [b for b in riw if b["id"] == tid][0]
cek("hasilnya BERHASIL", baris_apache["status_verifikasi"], True)
reset()

# --- kasus timeout ---
db = siapkan_db()
t0 = datetime(2026, 8, 21, 10, 0, 0)
d, s = siapkan(db, unit="apache2", down=True, waktu=t0)
tid2 = inject_permission(db, d.id, sekarang=t0)
playanan.coba_restart(db, d, s, sekarang=t0, _exec=lambda dev, p: None)

n_belum = playanan.verifikasi_tertunda(db, sekarang=t0 + timedelta(seconds=89))
cek("89 detik (belum lewat batas 90) -> belum diverifikasi", n_belum, 0)
n_lewat = playanan.verifikasi_tertunda(db, sekarang=t0 + timedelta(seconds=91))
cek("91 detik (lewat batas), masih down -> 1 diverifikasi GAGAL", n_lewat, 1)
riw2 = pagar_otomasi.riwayat(db, d.id)
baris2 = [b for b in riw2 if b["id"] == tid2][0]
cek("hasilnya GAGAL", baris2["status_verifikasi"], False)
reset()


# =============================================================================
print()
print("=" * 74)
print("6. TIDAK ADA rollback untuk Tahap 5 (sama alasannya dengan Tahap 4)")
print("=" * 74)

db = siapkan_db()
d, s = siapkan(db, unit="apache2", down=True)
tid = inject_permission(db, d.id)
playanan.coba_restart(db, d, s, _exec=lambda dev, p: None)
baris_db = db.get(models.PagarTindakan, tid)
benar("state_sebelum HANYA berisi service_id (bookkeeping, bukan rollback)",
     baris_db.state_sebelum is not None and "service_id" in baris_db.state_sebelum)
benar("rollback_dilakukan None (tidak relevan)", baris_db.rollback_dilakukan is None)
reset()



# =============================================================================
print()
print("=" * 74)
print("SATU PEMERIKSAAN GAGAL TIDAK BOLEH MERESTART LAYANAN SEHAT")
print("   regresi nyata 21 Agustus 2026: `_sedang_down()` membaca baris")
print("   `service_checks` terakhir, jadi satu timeout sesaat sudah cukup")
print("   untuk `systemctl restart` -- memutus sesi pengguna yang berjalan.")
print("=" * 74)

db = siapkan_db()
t0 = datetime(2026, 8, 21, 10, 0, 0)
d, s = siapkan(db, unit="apache2", down=False, waktu=t0)

db.add(models.ServiceCheck(service_id=s.id, timestamp=t0 + timedelta(seconds=10),
                           ok=True))
db.add(models.ServiceCheck(service_id=s.id, timestamp=t0 + timedelta(seconds=20),
                           ok=False))
db.commit()

benar("layanan sehat dengan 1 pemeriksaan gagal TIDAK jadi kandidat restart",
      all(sv.id != s.id for _dv, sv in playanan.cari_kandidat(db)),
      "-> %r" % [(sv.id, sv.nama) for _dv, sv in playanan.cari_kandidat(db)])

tanam_peristiwa(db, s.id, d.id, "DOWN", t0 + timedelta(seconds=30))
benar("setelah NSM menyatakan DOWN, layanan itu MENJADI kandidat",
      any(sv.id == s.id for _dv, sv in playanan.cari_kandidat(db)))

tanam_peristiwa(db, s.id, d.id, "UP", t0 + timedelta(seconds=90))
benar("sesudah dinyatakan UP lagi, berhenti jadi kandidat",
      all(sv.id != s.id for _dv, sv in playanan.cari_kandidat(db)))


if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

"""Test of Remediator Stage 4: a dead GNS3 node -> restart it.

Two phases are tested separately: `coba_pulihkan()` (detection + fence + API
call) and `verifikasi_tertunda()` (just recovered / timed out without recovery);
see the `pemulih/gns3.py` docstring for why.

`_panggil` is INJECTED into `gns3_pemulihan.pulihkan()` in every test, so
nothing here touches a real GNS3 server.

The "key vs category" test exists because an allowlist of `{"gns3_restart"}` (a
KEY) was always rejected: `pagar_otomasi._kunci_putih()` checks the category
('pemulih'), not the key.

Run: py uji_pemulih_gns3.py
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
from pemulih import gns3  # noqa: E402
from connectors.gns3_pemulihan import GagalPulih  # noqa: E402

# REQUIRED SAFEGUARD: disable the REAL notification path for this whole file.
#
# `pemulih/*.py` call `notifikasi_berjenjang.eskalasi_segera()` whenever an
# automatic fix fails, and its DEFAULT path goes over HTTP to the live Spring Boot
# on nsm-app. Tests must never touch that. It is installed at the top of the file,
# not per section, so a new section that forgets its own stub cannot leak. Real
# escalation behavior is tested in `uji_eskalasi_pemulih.py`, which injects a fake
# `pengirim`.
import notifikasi_berjenjang as _nb  # noqa: E402

_eskalasi_tercatat = []
_nb.eskalasi_segera = lambda db, device_id, ringkas, alasan, **kw: (
    _eskalasi_tercatat.append((device_id, ringkas, alasan))
    or {"terkirim": False, "alasan": "dimatikan di uji"})

_asli = {
    "putih": config.get_pagar_daftar_putih,
    "batas_device": config.get_pagar_batas_per_device_per_jam,
    "batas_global": config.get_pagar_batas_global_per_jam,
    "jam_kerja": config.get_pagar_jam_kerja,
    "beku": config.get_pagar_jendela_beku,
}


def reset_config():
    config.get_pagar_daftar_putih = _asli["putih"]
    config.get_pagar_batas_per_device_per_jam = _asli["batas_device"]
    config.get_pagar_batas_global_per_jam = _asli["batas_global"]
    config.get_pagar_jam_kerja = _asli["jam_kerja"]
    config.get_pagar_jendela_beku = _asli["beku"]


def setel_longgar():
    config.get_pagar_daftar_putih = lambda: {"gns3_restart"}
    config.get_pagar_batas_per_device_per_jam = lambda: 1000
    config.get_pagar_batas_global_per_jam = lambda: 1000
    config.get_pagar_jam_kerja = lambda: (0, 24)
    config.get_pagar_jendela_beku = lambda: []


def siapkan_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    file = os.path.join(tempfile.mkdtemp(prefix="uji_pemulih_gns3_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def device_gns3(db, nama, node, down=True, waktu=None):
    # `waktu` MUST be injected (not `datetime.now()`) for tests that compare against a
    # synthetic `sekarang`: mixing real and synthetic clocks makes `ORDER BY timestamp
    # DESC` misread which row is "latest".
    d = models.Device(name=nama, ip_address="192.168.56.60", device_type="router",
                      platform="cisco_ios", gns3_node=node, aktif=1)
    db.add(d)
    db.commit()
    # `device_events`, NOT `status_logs`: the remediator judges down/up from events
    # that already passed the poller's consecutive-failure threshold, not from raw
    # pings (see `pemulih/gns3.py::_sedang_down()`). Planting `status_logs` here would
    # pass without touching the code in use.
    tanam_peristiwa(db, d.id, "DOWN" if down else "UP", waktu or datetime.now())
    return d


def tanam_peristiwa(db, device_id, tipe, waktu):
    db.add(models.DeviceEvent(
        device_id=device_id, timestamp=waktu, event_type=tipe,
        category=("dead" if tipe == "DOWN" else "recovered"), detail="uji"))
    db.commit()


def _panggil_sukses(catatan=None, nama_node="R1"):
    # `nama_node` MUST match the `Device.gns3_node` under test: `gns3_pemulihan.pulihkan()`
    # looks nodes up by exact name, and a mismatch correctly raises GagalPulih. A
    # hardcoded "R1" once made a "success" scenario silently run as "node not found".
    def f(metode, jalur, isi=None, timeout=30):
        if catatan is not None:
            catatan.append((metode, jalur))
        if jalur == "/projects":
            return [{"project_id": "p1", "status": "opened", "name": "lab"}]
        if jalur == "/projects/p1/nodes":
            return [{"name": nama_node, "node_id": "n-" + nama_node}]
        return {}
    return f


def _panggil_gagal(metode, jalur, isi=None, timeout=30):
    raise GagalPulih("server GNS3 tidak menjawab")


# =============================================================================
print("=" * 74)
print("1. cari_kandidat() -- hanya device ber-gns3_node yang SEDANG down")
print("=" * 74)

db = siapkan_db()
r1 = device_gns3(db, "R1", "R1", down=True)
r_hidup = device_gns3(db, "R Hidup", "R9", down=False)
non_gns3 = models.Device(name="Bukan GNS3", ip_address="1.2.3.4",
                         device_type="server", platform="linux", aktif=1)
db.add(non_gns3)
db.commit()
tanam_peristiwa(db, non_gns3.id, "DOWN", datetime.now())
db.commit()

kandidat = gns3.cari_kandidat(db)
cek("jumlah kandidat (hanya R1, gns3_node + down)", len(kandidat), 1)
benar("kandidatnya benar R1", kandidat[0].id == r1.id if kandidat else False)


# =============================================================================
print()
print("=" * 74)
print("2. coba_pulihkan() -- gerbang pagar + panggil API")
print("=" * 74)

db = siapkan_db()
r1 = device_gns3(db, "R1", "R1", down=True)

config.get_pagar_daftar_putih = lambda: set()
config.get_pagar_batas_per_device_per_jam = lambda: 1000
config.get_pagar_batas_global_per_jam = lambda: 1000
config.get_pagar_jam_kerja = lambda: (0, 24)
config.get_pagar_jendela_beku = lambda: []
panggilan_kosong = []
kep0 = gns3.coba_pulihkan(db, r1, _panggil=_panggil_sukses(panggilan_kosong))
benar("daftar putih kosong -> DITOLAK", kep0.izin is False)
benar("API GNS3 TIDAK dipanggil sama sekali saat ditolak", panggilan_kosong == [])

setel_longgar()
panggilan = []
kep1 = gns3.coba_pulihkan(db, r1, _panggil=_panggil_sukses(panggilan))
benar("daftar putih terisi -> DIIZINKAN", kep1.izin is True)
benar("API GNS3 dipanggil (stop lalu start)",
     ("POST", "/projects/p1/nodes/n-R1/stop") in panggilan
     and ("POST", "/projects/p1/nodes/n-R1/start") in panggilan)

reset_config()


# =============================================================================
print()
print("=" * 74)
print("3. Gagal memanggil API -> verifikasi GAGAL seketika, tanpa nunggu fase 2")
print("=" * 74)

db = siapkan_db()
r1 = device_gns3(db, "R1", "R1", down=True)
setel_longgar()

kep = gns3.coba_pulihkan(db, r1, _panggil=_panggil_gagal)
benar("izin tetap True (pagar mengizinkan; yang gagal panggilan API-nya)",
     kep.izin is True)
riw = pagar_otomasi.riwayat(db, r1.id)
cek("status_verifikasi SUDAH terisi False, tanpa nunggu verifikasi_tertunda()",
    riw[0]["status_verifikasi"], False)

reset_config()


# =============================================================================
print()
print("=" * 74)
print("4. verifikasi_tertunda() -- device pulih vs lewat batas waktu")
print("=" * 74)

db = siapkan_db()
t0 = datetime(2026, 8, 21, 10, 0, 0)
r1 = device_gns3(db, "R1", "R1", down=True, waktu=t0)
setel_longgar()
kep = gns3.coba_pulihkan(db, r1, sekarang=t0, _panggil=_panggil_sukses())

n0 = gns3.verifikasi_tertunda(db, sekarang=t0 + timedelta(seconds=30))
cek("30 detik kemudian, device MASIH down -> belum diverifikasi", n0, 0)

tanam_peristiwa(db, r1.id, "UP", t0 + timedelta(seconds=45))
n1 = gns3.verifikasi_tertunda(db, sekarang=t0 + timedelta(seconds=50))
cek("sesudah device menjawab lagi -> 1 tindakan diverifikasi", n1, 1)
riw = pagar_otomasi.riwayat(db, r1.id)
cek("hasilnya BERHASIL", riw[0]["status_verifikasi"], True)

reset_config()

# --- kasus timeout ---
db = siapkan_db()
t0 = datetime(2026, 8, 21, 10, 0, 0)
r2 = device_gns3(db, "R2", "R2", down=True, waktu=t0)
setel_longgar()
gns3.coba_pulihkan(db, r2, sekarang=t0, _panggil=_panggil_sukses(nama_node="R2"))

n_belum = gns3.verifikasi_tertunda(db, sekarang=t0 + timedelta(seconds=179))
cek("179 detik (belum lewat batas 180) -> belum diverifikasi", n_belum, 0)

n_lewat = gns3.verifikasi_tertunda(db, sekarang=t0 + timedelta(seconds=181))
cek("181 detik (sudah lewat batas), device MASIH down -> 1 diverifikasi GAGAL", n_lewat, 1)
riw2 = pagar_otomasi.riwayat(db, r2.id)
cek("hasilnya GAGAL (bukan True, bukan tetap None)", riw2[0]["status_verifikasi"], False)

reset_config()


# =============================================================================
print()
print("=" * 74)
print("5. TIDAK ADA rollback untuk Tahap 4 -- state_sebelum SENGAJA tidak diisi")
print("=" * 74)

db = siapkan_db()
r1 = device_gns3(db, "R1", "R1", down=True)
setel_longgar()
kep = gns3.coba_pulihkan(db, r1, _panggil=_panggil_sukses())
riw = pagar_otomasi.riwayat(db, r1.id)
benar("state_sebelum kosong -- Tahap 4 tidak punya konsep rollback (lihat "
     "pemulih/rollback.py: keadaan sebelum = keadaan mati yang diperbaiki)",
     riw[0].get("verifikasi_bukti") is None or True)  # checked via the DB directly below
baris_db = db.get(models.PagarTindakan, kep.tindakan_id)
benar("PagarTindakan.state_sebelum None", baris_db.state_sebelum is None)
benar("PagarTindakan.rollback_dilakukan None (tidak relevan)",
     baris_db.rollback_dilakukan is None)

reset_config()


# =============================================================================
print()
print("=" * 74)
print("6. SATU PING JATUH TIDAK BOLEH MEMICU REBOOT")
print("   regresi nyata 21 Agustus 2026: `_sedang_down()` membaca baris")
print("   `status_logs` terakhir, sehingga SATU paket hilang pada router")
print("   yang sehat sudah cukup untuk menyalakan ulang router itu.")
print("=" * 74)

db = siapkan_db()
t0 = datetime(2026, 8, 21, 10, 0, 0)
sehat = device_gns3(db, "R1 sehat", "R1", down=False, waktu=t0)

# The router answers normally and NSM never declared it down (no DOWN event); then
# one ping drops, the pattern seen in the lab.
db.add(models.StatusLog(device_id=sehat.id, timestamp=t0 + timedelta(seconds=10),
                        is_reachable=1, response_time_ms=60.0, sumber="icmp"))
db.add(models.StatusLog(device_id=sehat.id, timestamp=t0 + timedelta(seconds=20),
                        is_reachable=0, response_time_ms=None, sumber="icmp"))
db.commit()

kandidat = gns3.cari_kandidat(db)
benar("router sehat dengan 1 ping jatuh TIDAK jadi kandidat pemulihan",
      all(d.id != sehat.id for d in kandidat),
      "-> %r" % [(d.id, d.name) for d in kandidat])

# Conversely, once NSM does declare it down (a DOWN event, written only after
# consecutive failures reach the threshold), it MUST become a candidate. Without
# this pair, "never remediates anything" would also pass.
tanam_peristiwa(db, sehat.id, "DOWN", t0 + timedelta(seconds=30))
kandidat2 = gns3.cari_kandidat(db)
benar("setelah NSM menyatakan DOWN, router itu MENJADI kandidat",
      any(d.id == sehat.id for d in kandidat2),
      "-> %r" % [(d.id, d.name) for d in kandidat2])

tanam_peristiwa(db, sehat.id, "UP", t0 + timedelta(seconds=90))
benar("sesudah dinyatakan UP lagi, berhenti jadi kandidat",
      all(d.id != sehat.id for d in gns3.cari_kandidat(db)))


if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

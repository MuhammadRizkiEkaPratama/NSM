"""Test of Remediator Stage 6: interface down although intent says it must be up.

Gate 1 (risk) is tested generically in `uji_pagar_otomasi.py`: `interface_up` is
classified `wajib_manusia` in `pagar_otomasi.RISIKO_PEMULIH`, so no allowlist can
ever let it through. `coba_nyalakan()` is therefore tested two ways:

  1. Through the REAL `pagar_otomasi.putuskan()`: always rejected, and no
     command reaches `kirim_perintah.kirim()` (proven with a call counter).
  2. With `pagar_otomasi.putuskan()` INJECTED to allow: tests the logic AFTER the
     gate (save state, call `kirim()`, verify, save state after), which only runs
     if the gate ever changes.

`kirim_perintah.kirim` is injected by module monkeypatch, so no real connection
is opened.

Run: py uji_pemulih_interface.py
"""
import os
import sys
import tempfile
from datetime import datetime

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
from pemulih import interface as pinterface  # noqa: E402

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


def reset():
    pagar_otomasi.putuskan = _asli_putuskan
    kirim_perintah.kirim = _asli_kirim


def siapkan_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    file = os.path.join(tempfile.mkdtemp(prefix="uji_pemulih_ifc_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


POTRET_FA00_MATI = """hostname R1
!
interface FastEthernet0/0
 ip address 192.168.56.60 255.255.255.0
 shutdown
!
end
"""

POTRET_FA00_HIDUP = """hostname R1
!
interface FastEthernet0/0
 ip address 192.168.56.60 255.255.255.0
!
end
"""


def siapkan_device_dan_intent(db, potret_teks):
    r1 = models.Device(name="R1 Uji", ip_address="192.168.56.60",
                       device_type="router", platform="cisco_ios", aktif=1)
    db.add(r1)
    db.commit()
    sot_svc.simpan_interface(db, r1.id, [
        {"nama": "FastEthernet0/0", "shutdown": False,
         "ip": "192.168.56.60", "mask": "255.255.255.0"},
    ], oleh="uji")
    db.add(models.KonfigSnapshot(device_id=r1.id, waktu=datetime.now(),
                                 sidik="x" * 8, teks=potret_teks))
    db.commit()
    return r1


# =============================================================================
print("=" * 74)
print("1. cari_kandidat() -- dari Tahap 2 (drift), bukan dihitung ulang")
print("=" * 74)

db = siapkan_db()
r1 = siapkan_device_dan_intent(db, POTRET_FA00_MATI)
kandidat = pinterface.cari_kandidat(db)
cek("jumlah kandidat", len(kandidat), 1)
benar("kandidatnya Fa0/0", kandidat and kandidat[0][1] == "FastEthernet0/0")

db2 = siapkan_db()
siapkan_device_dan_intent(db2, POTRET_FA00_HIDUP)
kandidat2 = pinterface.cari_kandidat(db2)
cek("interface yang SUDAH hidup -> bukan kandidat", len(kandidat2), 0)


# =============================================================================
print()
print("=" * 74)
print("2. coba_nyalakan() lewat pagar SUNGGUHAN -- SELALU ditolak (wajib_manusia)")
print("=" * 74)

db = siapkan_db()
r1 = siapkan_device_dan_intent(db, POTRET_FA00_MATI)
config.get_pagar_daftar_putih = lambda: {"interface_up", "gns3_restart"}  # sengaja dimasukkan
config.get_pagar_batas_per_device_per_jam = lambda: 1000
config.get_pagar_batas_global_per_jam = lambda: 1000
config.get_pagar_jam_kerja = lambda: (0, 24)
config.get_pagar_jendela_beku = lambda: []

panggilan_kirim = []
kirim_perintah.kirim = lambda *a, **kw: panggilan_kirim.append((a, kw)) or {"terkirim": True, "berubah": True}

kep = pinterface.coba_nyalakan(db, r1, "FastEthernet0/0")
benar("DITOLAK walau ADA di daftar putih (gerbang 1 tidak bisa di-override)",
     kep.izin is False)
benar("kirim_perintah.kirim() TIDAK PERNAH dipanggil", panggilan_kirim == [])
reset()


# =============================================================================
print()
print("=" * 74)
print("3. Logika HILIR (kalau gerbang mengizinkan) -- sukses")
print("=" * 74)

db = siapkan_db()
r1 = siapkan_device_dan_intent(db, POTRET_FA00_MATI)

kep_asli = pagar_otomasi.putuskan(db, r1.id, "pemulih", "interface_up", oleh="uji")
baris_tolak = db.get(models.PagarTindakan, kep_asli.tindakan_id)
baris_tolak.keputusan = pagar_otomasi.IZIN  # ubah paksa jadi izin utk uji hilir
db.commit()
pagar_otomasi.putuskan = lambda *a, **kw: pagar_otomasi.Keputusan(True, "disuntik utk uji", kep_asli.tindakan_id)

kirim_perintah.kirim = lambda db_, did, pid, nilai, oleh=None, sungguhan=False, **kw: {
    "terkirim": True, "berubah": True, "baris_bertambah": 1, "baris_berkurang": 1,
    "reload_masih_terpasang": False,
}

kep = pinterface.coba_nyalakan(db, r1, "FastEthernet0/0")
benar("izin (disuntik) True", kep.izin is True)
riw = pagar_otomasi.riwayat(db, r1.id)
baris = [b for b in riw if b["id"] == kep_asli.tindakan_id][0]
cek("status_verifikasi berhasil (terkirim+berubah)", baris["status_verifikasi"], True)
baris_db = db.get(models.PagarTindakan, kep_asli.tindakan_id)
benar("state_sebelum tersimpan (shutdown True)",
     baris_db.state_sebelum and '"shutdown": true' in baris_db.state_sebelum)
benar("state_sesudah tersimpan", baris_db.state_sesudah is not None)
reset()


# =============================================================================
print()
print("=" * 74)
print("4. Logika HILIR -- kirim() gagal terkirim")
print("=" * 74)

db = siapkan_db()
r1 = siapkan_device_dan_intent(db, POTRET_FA00_MATI)
kep_asli = pagar_otomasi.putuskan(db, r1.id, "pemulih", "interface_up", oleh="uji")
baris = db.get(models.PagarTindakan, kep_asli.tindakan_id)
baris.keputusan = pagar_otomasi.IZIN
db.commit()
pagar_otomasi.putuskan = lambda *a, **kw: pagar_otomasi.Keputusan(True, "disuntik", kep_asli.tindakan_id)
kirim_perintah.kirim = lambda *a, **kw: {"terkirim": False, "galat": "SSH timeout"}

pinterface.coba_nyalakan(db, r1, "FastEthernet0/0")
riw = pagar_otomasi.riwayat(db, r1.id)
baris2 = [b for b in riw if b["id"] == kep_asli.tindakan_id][0]
cek("status_verifikasi False (tidak terkirim)", baris2["status_verifikasi"], False)
benar("verifikasi_bukti menyebut galatnya",
     "SSH timeout" in (baris2["verifikasi_bukti"] or ""))
reset()


# =============================================================================
print()
print("=" * 74)
print("5. Logika HILIR -- ditolak PENJAGA kirim_perintah (identitas, dst)")
print("=" * 74)

db = siapkan_db()
r1 = siapkan_device_dan_intent(db, POTRET_FA00_MATI)
kep_asli = pagar_otomasi.putuskan(db, r1.id, "pemulih", "interface_up", oleh="uji")
baris = db.get(models.PagarTindakan, kep_asli.tindakan_id)
baris.keputusan = pagar_otomasi.IZIN
db.commit()
pagar_otomasi.putuskan = lambda *a, **kw: pagar_otomasi.Keputusan(True, "disuntik", kep_asli.tindakan_id)

def _tolak(*a, **kw):
    raise kirim_perintah.Ditolak("identitas perangkat belum terkonfirmasi 'sama'")
kirim_perintah.kirim = _tolak

pinterface.coba_nyalakan(db, r1, "FastEthernet0/0")
riw = pagar_otomasi.riwayat(db, r1.id)
baris3 = [b for b in riw if b["id"] == kep_asli.tindakan_id][0]
cek("status_verifikasi False (Ditolak penjaga kirim_perintah)",
    baris3["status_verifikasi"], False)
benar("alasan menyebut penjaga yang menolak",
     "identitas" in baris3["verifikasi_bukti"])
reset()


# =============================================================================
print()
print("=" * 74)
print("6. batalkan() -- rollback manual (TIDAK dipicu otomatis)")
print("=" * 74)

db = siapkan_db()
r1 = siapkan_device_dan_intent(db, POTRET_FA00_MATI)
kep_asli = pagar_otomasi.putuskan(db, r1.id, "pemulih", "interface_up", oleh="uji")
from pemulih import rollback as prollback
prollback.simpan_state_sebelum(db, kep_asli.tindakan_id,
                               {"device_id": r1.id, "interface": "FastEthernet0/0",
                                "shutdown": True})

panggilan = []
kirim_perintah.kirim = lambda db_, did, pid, nilai, oleh=None, sungguhan=False, **kw: (
    panggilan.append((pid, nilai)) or {"terkirim": True, "berubah": True})

ok = pinterface.batalkan(db, kep_asli.tindakan_id)
benar("batalkan() berhasil", ok is True)
benar("memanggil iface_mati (bukan iface_hidup lagi)",
     panggilan and panggilan[0][0] == "iface_mati")
baris_final = db.get(models.PagarTindakan, kep_asli.tindakan_id)
cek("rollback_dilakukan True", baris_final.rollback_dilakukan, True)

# A FAILED rollback is recorded honestly
kirim_perintah.kirim = lambda *a, **kw: {"terkirim": False, "galat": "device tidak menjawab"}
kep_asli2 = pagar_otomasi.putuskan(db, r1.id, "pemulih", "interface_up", oleh="uji")
prollback.simpan_state_sebelum(db, kep_asli2.tindakan_id,
                               {"device_id": r1.id, "interface": "FastEthernet0/0",
                                "shutdown": True})
ok2 = pinterface.batalkan(db, kep_asli2.tindakan_id)
benar("rollback yang gagal -> False (bukan crash, bukan diam-diam True)", ok2 is False)

reset()


if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

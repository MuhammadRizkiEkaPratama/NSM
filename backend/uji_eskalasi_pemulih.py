"""Tests for the link from the auto recoverer to tiered notifications.

Locks two gaps found in a completeness audit:
  1. `notifikasi_berjenjang.eskalasi_segera()` had no test at all.
  2. `pemulih/interface.py` never called escalation, though the other three
     recoverers do. A failure to bring an interface up still needs reporting.

`pengirim` is INJECTED in every test, so nothing contacts Spring Boot or sends real
email; the default path of `eskalasi_segera` reaches a LIVE Java endpoint.

Run: py uji_eskalasi_pemulih.py
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
import notifikasi_berjenjang as nb  # noqa: E402

_asli_notif_enabled = config.get_notif_enabled


def reset():
    config.get_notif_enabled = _asli_notif_enabled


def siapkan_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    file = os.path.join(tempfile.mkdtemp(prefix="uji_eskalasi_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    d = models.Device(name="Router Lokasi A", ip_address="192.168.56.60",
                      device_type="router", platform="cisco_ios",
                      gns3_node="R1", aktif=1)
    db.add(d)
    db.commit()
    return db, d


# =============================================================================
print("=" * 74)
print("1. eskalasi_segera() -- jalur normal, email TERKIRIM")
print("=" * 74)

db, d = siapkan_db()
config.get_notif_enabled = lambda: True

terkirim = []


def _pengirim_sukses(cfg, subjek, isi, device_ids):
    terkirim.append({"subjek": subjek, "isi": isi, "device_ids": device_ids})
    return {"terkirim": 1}


hasil = nb.eskalasi_segera(db, d.id, "Node GNS3 dicoba dipulihkan otomatis",
                           "Masih tidak menjawab 180 detik sesudah dipulihkan.",
                           pengirim=_pengirim_sukses)
cek("mengembalikan terkirim=True", hasil["terkirim"], True)
cek("tepat 1 email dikirim", len(terkirim), 1)
benar("subjek menyebut PERBAIKAN OTOMATIS GAGAL (bukan subjek 'device mati' biasa)",
     "GAGAL" in terkirim[0]["subjek"])
benar("subjek menyebut nama device sungguhan",
     "Router Lokasi A" in terkirim[0]["subjek"])
benar("isi memuat ringkasan tindakan yang dicoba",
     "Node GNS3 dicoba dipulihkan otomatis" in terkirim[0]["isi"])
benar("isi memuat alasan/bukti kegagalannya",
     "180 detik" in terkirim[0]["isi"])
cek("dikirim untuk device yang benar", terkirim[0]["device_ids"], [d.id])
benar("isi menegaskan ini BUKAN notifikasi terjadwal biasa",
     "bukan notifikasi" in terkirim[0]["isi"].lower())
reset()


# =============================================================================
print()
print("=" * 74)
print("2. Kegagalan MENGIRIM tidak boleh menjatuhkan pemanggil")
print("=" * 74)

db, d = siapkan_db()
config.get_notif_enabled = lambda: True


def _pengirim_meledak(cfg, subjek, isi, device_ids):
    raise RuntimeError("tidak bisa menghubungi Spring Boot di localhost:8080")


try:
    hasil = nb.eskalasi_segera(db, d.id, "ringkas", "alasan",
                               pengirim=_pengirim_meledak)
    benar("TIDAK melempar exception ke pemanggil (pemulih sudah di jalur gagal, "
         "kegagalan notifikasi tidak boleh menutupi pencatatan verifikasi)", True)
    cek("melaporkan terkirim=False", hasil["terkirim"], False)
    benar("alasannya ikut dilaporkan, bukan ditelan diam-diam",
         "Spring Boot" in hasil.get("alasan", ""))
except Exception as e:
    benar("TIDAK melempar exception ke pemanggil", False, "-> malah melempar: %s" % e)
reset()


# =============================================================================
print()
print("=" * 74)
print("3. Notifikasi DIMATIKAN -> tidak mengirim apa pun, tapi jujur melapor")
print("=" * 74)

db, d = siapkan_db()
config.get_notif_enabled = lambda: False

dipanggil = []
hasil = nb.eskalasi_segera(db, d.id, "ringkas", "alasan",
                           pengirim=lambda *a, **kw: dipanggil.append(a))
cek("terkirim=False", hasil["terkirim"], False)
benar("pengirim TIDAK dipanggil sama sekali", dipanggil == [])
benar("alasannya menyebut notifikasi dimatikan",
     "dimatikan" in hasil.get("alasan", "").lower())
reset()


# =============================================================================
print()
print("=" * 74)
print("4. device_id yang TIDAK ADA -> tetap jalan, tidak crash")
print("=" * 74)

db, d = siapkan_db()
config.get_notif_enabled = lambda: True
terkirim2 = []
try:
    hasil = nb.eskalasi_segera(db, 999999, "ringkas", "alasan",
                               pengirim=lambda cfg, s, i, ids: terkirim2.append(s) or {"terkirim": 1})
    benar("tidak crash untuk device yang tidak ada", True)
    benar("subjeknya tetap menyebut sesuatu yang bisa ditelusuri",
         terkirim2 and "999999" in terkirim2[0])
except Exception as e:
    benar("tidak crash untuk device yang tidak ada", False, "-> %s" % e)
reset()


# =============================================================================
print()
print("=" * 74)
print("5. KEEMPAT pemulih memanggil eskalasi -- termasuk interface.py")
print("   (celah nyata: interface.py semula TIDAK memanggilnya sama sekali)")
print("=" * 74)

import inspect  # noqa: E402
from pemulih import gns3, layanan, interface as pinterface, konfig as pkonfig  # noqa: E402

for nama, modul in (("gns3", gns3), ("layanan", layanan),
                    ("interface", pinterface), ("konfig", pkonfig)):
    sumber = inspect.getsource(modul)
    benar("pemulih/%s.py memanggil eskalasi saat gagal" % nama,
         "_eskalasi(" in sumber and "eskalasi_segera" in sumber)


# =============================================================================
print()
print("=" * 74)
print("6. interface.py: kegagalan BENAR-BENAR memicu eskalasi (bukan cuma ada")
print("   fungsinya) -- dua jalur gagal diuji terpisah")
print("=" * 74)

import pagar_otomasi  # noqa: E402
import kirim_perintah  # noqa: E402
from sot import service as sot_svc  # noqa: E402

_asli_putuskan = pagar_otomasi.putuskan
_asli_kirim = kirim_perintah.kirim
_asli_eskalasi = nb.eskalasi_segera


def reset_penuh():
    pagar_otomasi.putuskan = _asli_putuskan
    kirim_perintah.kirim = _asli_kirim
    nb.eskalasi_segera = _asli_eskalasi
    config.get_notif_enabled = _asli_notif_enabled


POTRET_MATI = """hostname R1
!
interface FastEthernet0/0
 ip address 192.168.56.60 255.255.255.0
 shutdown
!
end
"""


def siapkan_interface_uji():
    db, d = siapkan_db()
    sot_svc.simpan_interface(db, d.id, [
        {"nama": "FastEthernet0/0", "shutdown": False,
         "ip": "192.168.56.60", "mask": "255.255.255.0"},
    ], oleh="uji")
    db.add(models.KonfigSnapshot(device_id=d.id, waktu=datetime.now(),
                                 sidik="x" * 8, teks=POTRET_MATI))
    db.commit()
    # `interface_up` is classified wajib_manusia, so the gate ALWAYS refuses. Injected so the DOWNSTREAM logic (which triggers escalation) can be tested.
    kep = _asli_putuskan(db, d.id, "pemulih", "interface_up", oleh="uji")
    line = db.get(models.PagarTindakan, kep.tindakan_id)
    line.keputusan = pagar_otomasi.IZIN
    db.commit()
    pagar_otomasi.putuskan = lambda *a, **kw: pagar_otomasi.Keputusan(
        True, "disuntik utk uji", kep.tindakan_id)
    return db, d, kep.tindakan_id


# path A: kirim() fails to send
db, d, tid = siapkan_interface_uji()
eskalasi_dipanggil = []
nb.eskalasi_segera = lambda db_, did, ringkas, alasan, **kw: eskalasi_dipanggil.append(
    {"device_id": did, "ringkas": ringkas, "alasan": alasan})
kirim_perintah.kirim = lambda *a, **kw: {"terkirim": False, "berubah": False,
                                         "galat": "SSH timeout"}

pinterface.coba_nyalakan(db, d, "FastEthernet0/0")
cek("jalur GAGAL TERKIRIM -> eskalasi dipanggil 1x", len(eskalasi_dipanggil), 1)
benar("eskalasi menyebut interface yang dimaksud",
     eskalasi_dipanggil and "FastEthernet0/0" in eskalasi_dipanggil[0]["ringkas"])
benar("eskalasi membawa galat aslinya",
     eskalasi_dipanggil and "SSH timeout" in eskalasi_dipanggil[0]["alasan"])
reset_penuh()

# path B: refused by the kirim_perintah guard
db, d, tid = siapkan_interface_uji()
eskalasi_b = []
nb.eskalasi_segera = lambda db_, did, ringkas, alasan, **kw: eskalasi_b.append(alasan)


def _tolak(*a, **kw):
    raise kirim_perintah.Ditolak("identitas perangkat belum terkonfirmasi 'sama'")


kirim_perintah.kirim = _tolak
pinterface.coba_nyalakan(db, d, "FastEthernet0/0")
cek("jalur DITOLAK PENJAGA -> eskalasi dipanggil 1x", len(eskalasi_b), 1)
benar("eskalasi menyebut alasan penolakannya",
     eskalasi_b and "identitas" in eskalasi_b[0])
reset_penuh()

# path C: SUCCESS -> must NOT send email
db, d, tid = siapkan_interface_uji()
eskalasi_c = []
nb.eskalasi_segera = lambda *a, **kw: eskalasi_c.append(a)
kirim_perintah.kirim = lambda *a, **kw: {"terkirim": True, "berubah": True,
                                         "baris_bertambah": 1, "baris_berkurang": 1}
pinterface.coba_nyalakan(db, d, "FastEthernet0/0")
benar("jalur BERHASIL -> TIDAK ada eskalasi (email cuma untuk kegagalan)",
     eskalasi_c == [])
reset_penuh()


if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

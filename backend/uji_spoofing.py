"""Tests for IP/MAC spoofing detection, `report_service.deteksi_spoofing()`.
The baseline MAC from `identitas_perangkat` is compared with the MAC actually seen in the local ARP table; a registered IP pointing at a different MAC indicates spoofing or ARP poisoning.
Deliberate limits that must stay tested:
  - Only IPs present in the local ARP table are compared; addresses behind a router show the router's MAC and would cause mass false positives.
  - IPs without a baseline are not this check's concern (`daftar_dilindungi` / `rencana_penjagaan`).
  - If `arp -a` fails or times out the result must be empty, not an error that breaks the Firewall page.
`_baca_arp_lokal()` is replaced by a fake, so no real `arp -a` runs.
Uses a temporary database.
"""
import os
import sys
import tempfile

# `report_service` only forwards; `_baca_arp_lokal` lives in `report_service/firewall.py`. Patching `rs._baca_arp_lokal` would not reach `deteksi_spoofing()` and the test would pass while reading the real ARP table. See `bantu_tambal.py`.
from bantu_tambal import patch

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

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


def sama(nama, dapat, harap):
    benar(nama, dapat == harap, "-> dapat %r, harusnya %r" % (dapat, harap))


def siapkan():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    file = os.path.join(tempfile.mkdtemp(prefix="uji_spoofing_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    server = models.Device(id=1, name="Server Web", ip_address="192.168.56.103",
                           device_type="server", platform="linux", aktif=1,
                           username="nsmro", ssh_key_path="/x/kunci")
    router = models.Device(id=2, name="Router R2", ip_address="192.168.20.1",
                           device_type="router", platform="cisco_ios",
                           aktif=1, username="nsm", password="x")
    db.add_all([server, router])
    db.add(models.IdentitasPerangkat(
        device_id=1, jenis="mac", nilai="08:00:27:AA:BB:CC",
        pertama=__import__("datetime").datetime.now(),
        terakhir=__import__("datetime").datetime.now(), sumber="ssh"))
    db.commit()
    return db


print("=" * 74)
print("UJI DETEKSI SPOOFING IP/MAC (report_service.deteksi_spoofing)")
print("=" * 74)

db = siapkan()
import report_service as rs


def arp_tiruan(hasil):
    """Replace `_baca_arp_lokal` so the test does not run a real `arp -a`."""
    def _f():
        return hasil
    return _f


# ---------------------------------------------------------------------------
print("\n1. MAC ARP COCOK BASELINE -> TIDAK ADA SPOOFING")

patch("_baca_arp_lokal", arp_tiruan({"192.168.56.103": "08:00:27:aa:bb:cc"}))
h = rs.deteksi_spoofing(db)
sama("tidak ada temuan spoofing", h["spoofing"], [])
sama("arp_terbaca True", h["arp_terbaca"], True)

# ---------------------------------------------------------------------------
print("\n2. MAC ARP BEDA DARI BASELINE -> SPOOFING DITANDAI")

patch("_baca_arp_lokal", arp_tiruan({"192.168.56.103": "de:ad:be:ef:00:01"}))
h = rs.deteksi_spoofing(db)
sama("satu temuan spoofing", len(h["spoofing"]), 1)
s = h["spoofing"][0]
sama("ip yang disamar", s["ip"], "192.168.56.103")
sama("nama device disebut", s["nama"], "Server Web")
sama("mac terlihat tercatat", s["mac_terlihat"], "de:ad:be:ef:00:01")
benar("mac terdaftar ikut disebut",
      "08:00:27:aa:bb:cc" in s["mac_terdaftar"],
      "-> %r" % s["mac_terdaftar"])
benar("alasan menyebut IP dan kedua MAC-nya",
      "192.168.56.103" in s["alasan"] and "de:ad:be:ef:00:01" in s["alasan"],
      "-> %r" % s["alasan"])

# ---------------------------------------------------------------------------
print("\n3. NORMALISASI MAC BASELINE — beda gaya penulisan tetap dianggap SAMA")
print("   (identitas tersimpan pakai tanda hubung huruf besar, seperti yang")
print("    kadang ditulis SSH/`ip link show`; `_baca_arp_lokal()` SELALU")
print("    mengembalikan bentuk titik-dua huruf kecil — keduanya harus")
print("    dianggap MAC yang sama, bukan dua MAC berbeda.)")

from models import IdentitasPerangkat as _IP
from datetime import datetime as _dt
db.add(_IP(device_id=1, jenis="mac", nilai="08-00-27-DD-EE-FF",
    pertama=_dt.now(), terakhir=_dt.now(), sumber="ssh"))
db.commit()
patch("_baca_arp_lokal", arp_tiruan({"192.168.56.103": "08:00:27:dd:ee:ff"}))
h = rs.deteksi_spoofing(db)
sama("baseline gaya tanda-hubung dinormalisasi sama dengan ARP titik-dua",
     h["spoofing"], [])

# ---------------------------------------------------------------------------
print("\n4. IP YANG TIDAK TERDAFTAR (TANPA BASELINE) DILEWATI")
print("   (bukan urusan deteksi ini — itu wilayah allowlist/rencana_penjagaan.)")

patch("_baca_arp_lokal", arp_tiruan({
    "192.168.56.103": "08:00:27:aa:bb:cc",
    "10.66.66.66": "aa:aa:aa:aa:aa:aa",
}))
h = rs.deteksi_spoofing(db)
sama("hanya IP terdaftar yang dinilai, penyerang tak terdaftar dilewati",
     h["spoofing"], [])

# ---------------------------------------------------------------------------
print("\n5. PERANGKAT DENGAN LEBIH DARI SATU MAC TERDAFTAR (multi-homed)")

from models import IdentitasPerangkat
from datetime import datetime
db.add(IdentitasPerangkat(device_id=1, jenis="mac", nilai="AA:BB:CC:DD:EE:FF",
                          pertama=datetime.now(), terakhir=datetime.now(),
                          sumber="ssh"))
db.commit()
patch("_baca_arp_lokal", arp_tiruan({"192.168.56.103": "aa:bb:cc:dd:ee:ff"}))
h = rs.deteksi_spoofing(db)
sama("cocok salah satu dari beberapa MAC terdaftar -> bukan spoofing",
     h["spoofing"], [])

patch("_baca_arp_lokal", arp_tiruan({"192.168.56.103": "11:22:33:44:55:66"}))
h = rs.deteksi_spoofing(db)
sama("tidak cocok SATU PUN dari beberapa MAC terdaftar -> spoofing",
     len(h["spoofing"]), 1)

# ---------------------------------------------------------------------------
print("\n6. ARP GAGAL DIBACA -> FAIL-SAFE, BUKAN GALAT")
print("   (mis. `arp -a` gagal/timeout di mesin yang menjalankan NSM.)")

patch("_baca_arp_lokal", arp_tiruan({}))
try:
    h = rs.deteksi_spoofing(db)
    lolos += 1
    print("  LOLOS  tidak melempar exception saat ARP kosong")
except Exception as e:
    gagal += 1
    print("  GAGAL  melempar %r, harusnya fail-safe" % e)
    h = {"spoofing": [], "arp_terbaca": True}
sama("tidak ada temuan (tidak ada apa pun untuk dibandingkan)", h["spoofing"], [])
sama("arp_terbaca False menandai ARP kosong/gagal", h["arp_terbaca"], False)

# ---------------------------------------------------------------------------
print("\n7. BASELINE IKUT DIKEMBALIKAN, UNTUK DIPAKAI ALLOWLIST (Tahap 2)")

patch("_baca_arp_lokal", arp_tiruan({"192.168.56.103": "08:00:27:aa:bb:cc"}))
h = rs.deteksi_spoofing(db)
benar("baseline device ada di hasil",
      "192.168.56.103" in h["baseline"],
      "-> %r" % sorted(h["baseline"]))
benar("baseline berisi seluruh MAC yang terdaftar untuknya",
      set(h["baseline"]["192.168.56.103"])
      == {"08:00:27:aa:bb:cc", "08:00:27:dd:ee:ff", "aa:bb:cc:dd:ee:ff"},
      "-> %r" % h["baseline"]["192.168.56.103"])

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

"""Test of the auto-ban brain: `report_service.rencana_penjagaan()` and `daftar_dilindungi()`.

These decide who is a block candidate and what is automatic vs human-reviewed,
the direct answer to "never lock out our own servers". Two core safeguards:

  1. ABSOLUTE ALLOWLIST: anything in `daftar_dilindungi()` (registered devices +
     NSM's address) is NEVER a candidate, whatever its behavior in the data.
  2. AUTO ONLY FOR CLEAR PATTERNS: breach (live connection), scanning (>=5
     targets), persistent (>=50 attempts). Everything else goes to the REVIEW
     list only.

Nothing is executed: pure decisions from data already computed by
`penolakan_acl()`/`deteksi_pembobolan()`, so fake dicts are used.

Runs on a TEMPORARY database. Does not touch nsm.db.
"""
import os
import sys
import tempfile
from datetime import datetime

# `poller` and `report_service` now only forward; the logic lives in
# `nsm/pemantau/*` and `report_service/*`. Setting `poller.nama = fake` has no
# effect, so `tambal()` patches the module that actually owns the name. See
# `bantu_tambal.py`.
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

    file = os.path.join(tempfile.mkdtemp(prefix="uji_penjagaan_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    server = models.Device(id=1, name="Server Web", ip_address="192.168.56.103",
                           device_type="server", platform="linux", aktif=1,
                           username="nsmro", ssh_key_path="/x/kunci",
                           location="Lokasi A")
    # location="Lokasi B" is the only signal used (LOKASI_ACL_ROUTER) to offer an ACL block, not the IP address.
    ldap = models.Device(id=2, name="Server LDAP", ip_address="192.168.56.101",
                         device_type="server", platform="linux", aktif=1,
                         username="nsmro", ssh_key_path="/x/kunci",
                         location="Lokasi B")
    db.add_all([server, ldap])
    db.commit()
    return db


def kandidat_dari(hasil, ip):
    for k in hasil["kandidat"]:
        if k["asal"] == ip:
            return k
    return None


print("=" * 74)
print("UJI OTAK AUTO-BAN (report_service.rencana_penjagaan / daftar_dilindungi)")
print("=" * 74)

db = siapkan()
import report_service as rs

patch("_baca_arp_lokal", lambda: {})

KOSONG_PENOLAKAN = {"per_asal": []}
KOSONG_PEMBOBOLAN = {"temuan": []}

# ---------------------------------------------------------------------------
print("\n1. daftar_dilindungi() — device terdaftar + alamat NSM")

d = rs.daftar_dilindungi(db)
benar("Server Web ada", "192.168.56.103" in d)
benar("Server LDAP ada", "192.168.56.101" in d)
benar("alamat NSM (.1) ada walau tidak terdaftar sebagai device",
      "192.168.56.1" in d)

# ---------------------------------------------------------------------------
print("\n2. HOST ASING DENGAN KONEKSI HIDUP (tembus) -> AUTO, kritis")

pembobolan = {"temuan": [{"asal": "10.66.66.66", "layanan": "SSH",
                          "device": "Server Web", "device_id": 1}]}
h = rs.rencana_penjagaan(db, KOSONG_PENOLAKAN, pembobolan)
k = kandidat_dari(h, "10.66.66.66")
benar("jadi kandidat", k is not None)
sama("pola tembus", k["pola"], "tembus")
sama("aksi otomatis", k["aksi_saran"], "blokir-otomatis")
sama("keparahan kritis", k["keparahan"], "kritis")
sama("jumlah_auto 1", h["jumlah_auto"], 1)
sama("jumlah_tinjau 0", h["jumlah_tinjau"], 0)

# ---------------------------------------------------------------------------
print("\n3. MEMINDAI (>=5 tujuan, kategori diblokir) -> AUTO")

penolakan = {"per_asal": [{"asal": "10.66.66.67", "kategori": "diblokir",
                           "tujuan_jumlah": 5, "percobaan": 5, "tujuan": []}]}
h = rs.rencana_penjagaan(db, penolakan, KOSONG_PEMBOBOLAN)
k = kandidat_dari(h, "10.66.66.67")
sama("pola memindai", k["pola"], "memindai")
sama("aksi otomatis", k["aksi_saran"], "blokir-otomatis")

# ---------------------------------------------------------------------------
print("\n4. GIGIH (>=50 percobaan, <5 tujuan, kategori diblokir) -> AUTO")

penolakan = {"per_asal": [{"asal": "10.66.66.68", "kategori": "diblokir",
                           "tujuan_jumlah": 1, "percobaan": 50, "tujuan": []}]}
h = rs.rencana_penjagaan(db, penolakan, KOSONG_PEMBOBOLAN)
k = kandidat_dari(h, "10.66.66.68")
sama("pola gigih", k["pola"], "gigih")
sama("aksi otomatis", k["aksi_saran"], "blokir-otomatis")

# ---------------------------------------------------------------------------
print("\n5. DI BAWAH AMBANG (kategori diblokir, tapi kecil) -> HANYA TINJAU")

penolakan = {"per_asal": [{"asal": "10.66.66.69", "kategori": "diblokir",
                           "tujuan_jumlah": 2, "percobaan": 10, "tujuan": []}]}
h = rs.rencana_penjagaan(db, penolakan, KOSONG_PEMBOBOLAN)
k = kandidat_dari(h, "10.66.66.69")
sama("pola kecil", k["pola"], "kecil")
sama("aksi ditinjau, BUKAN otomatis", k["aksi_saran"], "tinjau")
sama("jumlah_auto 0", h["jumlah_auto"], 0)
sama("jumlah_tinjau 1", h["jumlah_tinjau"], 1)

# ---------------------------------------------------------------------------
print("\n6. KATEGORI SELAIN 'diblokir' (mis. 'pengecekan') TIDAK PERNAH JADI KANDIDAT")
print("   (percobaan NSM sendiri / balasan layanan — sudah difilter Python,")
print("    bukan urusan auto-ban sama sekali.)")

penolakan = {"per_asal": [{"asal": "10.66.66.70", "kategori": "pengecekan",
                           "tujuan_jumlah": 99, "percobaan": 999, "tujuan": []}]}
h = rs.rencana_penjagaan(db, penolakan, KOSONG_PEMBOBOLAN)
benar("tidak jadi kandidat sama sekali", kandidat_dari(h, "10.66.66.70") is None)

# ---------------------------------------------------------------------------
print("\n7. ALLOWLIST MUTLAK — device terdaftar/NSM TIDAK PERNAH jadi kandidat")
print("   (walau datanya seolah 'tembus' atau 'gigih' — ini pengaman intinya.)")

for ip_dilindungi, ket in (("192.168.56.103", "device terdaftar"),
                           ("192.168.56.1", "alamat NSM")):
    pembobolan = {"temuan": [{"asal": ip_dilindungi, "layanan": "SSH",
                              "device": "?", "device_id": 1}]}
    penolakan = {"per_asal": [{"asal": ip_dilindungi, "kategori": "diblokir",
                               "tujuan_jumlah": 99, "percobaan": 999,
                               "tujuan": []}]}
    h = rs.rencana_penjagaan(db, penolakan, pembobolan)
    benar("%s (%s) TIDAK PERNAH jadi kandidat" % (ip_dilindungi, ket),
          kandidat_dari(h, ip_dilindungi) is None)

# ---------------------------------------------------------------------------
print("\n8. SATU ASAL MUNCUL DI DUA SUMBER SEKALIGUS -> POLA TERPARAH MENANG")
print("   (tembus dari pembobolan + memindai dari penolakan: hasilnya TETAP")
print("    'tembus', bukan diturunkan jadi 'memindai'; target digabung.)")

pembobolan = {"temuan": [{"asal": "10.66.66.71", "layanan": "SSH",
                          "device": "Server Web", "device_id": 1}]}
penolakan = {"per_asal": [{"asal": "10.66.66.71", "kategori": "diblokir",
                           "tujuan_jumlah": 5, "percobaan": 5,
                           "tujuan": ["192.168.56.101:22"]}]}
h = rs.rencana_penjagaan(db, penolakan, pembobolan)
k = kandidat_dari(h, "10.66.66.71")
sama("pola tetap tembus (paling gawat)", k["pola"], "tembus")
sama("target dari kedua sumber tergabung", sorted(k["target_ids"]), [1, 2])

# ---------------------------------------------------------------------------
print("\n9. URUTAN HASIL — otomatis dulu, lalu urut keparahan")

pembobolan = {"temuan": [{"asal": "10.1.1.1", "layanan": "SSH",
                          "device": "?", "device_id": 1}]}
penolakan = {"per_asal": [
    {"asal": "10.1.1.2", "kategori": "diblokir", "tujuan_jumlah": 1,
     "percobaan": 10, "tujuan": []},   # kecil -> tinjau, sedang
    {"asal": "10.1.1.3", "kategori": "diblokir", "tujuan_jumlah": 6,
     "percobaan": 1, "tujuan": []},    # memindai -> auto, tinggi
]}
h = rs.rencana_penjagaan(db, penolakan, pembobolan)
urutan = [k["asal"] for k in h["kandidat"]]
sama("tembus (auto, kritis) di urutan pertama", urutan[0], "10.1.1.1")
sama("memindai (auto, tinggi) sebelum yang cuma ditinjau", urutan[1], "10.1.1.3")
sama("kecil (tinjau) di urutan terakhir", urutan[-1], "10.1.1.2")

# ---------------------------------------------------------------------------
print("\n10. MAC PENYERANG DISERTAKAN KALAU TERLIHAT DI ARP LOKAL (ikatan Tahap 2)")

patch("_baca_arp_lokal", lambda: {"10.66.66.72": "de:ad:be:ef:00:02"})
pembobolan = {"temuan": [{"asal": "10.66.66.72", "layanan": "SSH",
                          "device": "Server Web", "device_id": 1}]}
h = rs.rencana_penjagaan(db, KOSONG_PENOLAKAN, pembobolan)
k = kandidat_dari(h, "10.66.66.72")
sama("MAC penyerang ikut tercatat", k["mac"], "de:ad:be:ef:00:02")
patch("_baca_arp_lokal", lambda: {})

# ---------------------------------------------------------------------------
print("\n10b. acl_router_id (§E2) — cuma terisi kalau target ADA di lokasi")
print("     yang dijaga ACL router, diambil dari Device.location")

pembobolan = {"temuan": [{"asal": "10.66.66.80", "layanan": "LDAP",
                          "device": "Server LDAP", "device_id": 2}]}
h = rs.rencana_penjagaan(db, KOSONG_PENOLAKAN, pembobolan)
k = kandidat_dari(h, "10.66.66.80")
sama("target di Lokasi B -> acl_router_id terisi (id router dari ROUTER_ACL)",
     k["acl_router_id"], 9)

pembobolan = {"temuan": [{"asal": "10.66.66.81", "layanan": "SSH",
                          "device": "Server Web", "device_id": 1}]}
h = rs.rencana_penjagaan(db, KOSONG_PENOLAKAN, pembobolan)
k = kandidat_dari(h, "10.66.66.81")
sama("target di Lokasi A -> acl_router_id kosong (tidak ada ACL router di sana)",
     k["acl_router_id"], None)

# ---------------------------------------------------------------------------
print("\n11. TIDAK ADA DATA SAMA SEKALI -> KOSONG, BUKAN GALAT")

h = rs.rencana_penjagaan(db, KOSONG_PENOLAKAN, KOSONG_PEMBOBOLAN)
sama("tidak ada kandidat", h["kandidat"], [])
sama("jumlah_auto 0", h["jumlah_auto"], 0)
sama("jumlah_tinjau 0", h["jumlah_tinjau"], 0)
benar("daftar dilindungi tetap ada walau tidak ada kandidat",
      len(h["dilindungi"]) >= 2)

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

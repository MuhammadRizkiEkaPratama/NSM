"""Test of intrusion detection: `report_service.deteksi_pembobolan()`.

Firewall logs (ufw/ACL/winfw) only record what was BLOCKED, so a successful
intrusion never appears there. The only evidence is LIVE TCP connections
(`flow_koneksi`, read from `ss -tin`). This function is the only one that says
"someone got through", so both error directions are costly:

  - an alarm that never fires (false negative): a real intrusion looks normal
  - an alarm that never clears (persistent false positive): long-dead
    connections reported as active, so people stop trusting the card

Tested: patterns that MUST count as a breach, patterns deliberately excluded
(registered devices, loopback, self connections), and the 3-minute freshness
window that clears the card once the connection really ends.

Runs on a TEMPORARY database. Does not touch nsm.db.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

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

    file = os.path.join(tempfile.mkdtemp(prefix="uji_pembobolan_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    server = models.Device(id=1, name="Server Web", ip_address="192.168.56.103",
                           device_type="server", platform="linux", aktif=1,
                           username="nsmro", ssh_key_path="/x/kunci")
    other = models.Device(id=2, name="Server LDAP", ip_address="192.168.56.101",
                         device_type="server", platform="linux", aktif=1,
                         username="nsmro", ssh_key_path="/x/kunci")
    db.add_all([server, other])
    db.commit()
    return db


print("=" * 74)
print("UJI DETEKSI PEMBOBOLAN (report_service.deteksi_pembobolan)")
print("=" * 74)

db = siapkan()
import report_service as rs
from models import Flow, Service

sekarang = datetime.now()


def flow(device_id, ip_lawan, port_lokal, ip_lokal="192.168.56.103",
        keadaan="ESTAB", waktu=None, port_lawan=51000, proses=None):
    return Flow(device_id=device_id, waktu=waktu or sekarang,
               ip_lokal=ip_lokal, port_lokal=port_lokal, ip_lawan=ip_lawan,
               port_lawan=port_lawan, keadaan=keadaan, proses=proses,
               byte_masuk=100.0, byte_keluar=50.0)


# ---------------------------------------------------------------------------
print("\n1. HOST TAK TERDAFTAR + KONEKSI HIDUP KE PORT SENSITIF = TEMUAN")

db.add(flow(1, "10.66.66.66", 22))
db.commit()
h = rs.deteksi_pembobolan(db)
sama("ada_pembobolan True", h["ada_pembobolan"], True)
sama("satu temuan", h["jumlah"], 1)
t = h["temuan"][0]
sama("asal tercatat benar", t["asal"], "10.66.66.66")
sama("layanan SSH terbaca dari nomor port", t["layanan"], "SSH")
sama("keparahan kritis", t["keparahan"], "kritis")
benar("device pemilik disebut namanya", t["device"] == "Server Web",
      "-> %r" % t["device"])

# ---------------------------------------------------------------------------
print("\n2. KONEKSI DARI DEVICE TERDAFTAR BUKAN PEMBOBOLAN")

db.query(Flow).delete(); db.commit()
db.add(flow(1, "192.168.56.101", 22))
db.commit()
h = rs.deteksi_pembobolan(db)
sama("tidak ada temuan (lalu lintas sah antar lab)", h["jumlah"], 0)

# ---------------------------------------------------------------------------
print("\n3. KONEKSI KE PORT YANG TIDAK SENSITIF DIABAIKAN")

db.query(Flow).delete(); db.commit()
db.add(flow(1, "10.66.66.67", 8080))
db.commit()
h = rs.deteksi_pembobolan(db)
sama("port publik/tak sensitif tidak memicu apa pun", h["jumlah"], 0)

# ---------------------------------------------------------------------------
print("\n4. KONEKSI PERANGKAT KE DIRINYA SENDIRI (ANTAR INTERFACE) DIABAIKAN")

db.query(Flow).delete(); db.commit()
db.add(flow(1, "192.168.56.103", 22, ip_lokal="192.168.56.103"))
db.commit()
h = rs.deteksi_pembobolan(db)
sama("ip_lawan == ip_lokal -> bukan tembus", h["jumlah"], 0)

# ---------------------------------------------------------------------------
print("\n5. KEADAAN SELAIN ESTAB (mis. LISTEN, TIME_WAIT) DIABAIKAN")

db.query(Flow).delete(); db.commit()
db.add(flow(1, "10.66.66.68", 3306, keadaan="TIME_WAIT"))
db.commit()
h = rs.deteksi_pembobolan(db)
sama("koneksi yang tidak lagi terhubung tidak dihitung", h["jumlah"], 0)

# ---------------------------------------------------------------------------
print("\n6. JENDELA KESEGARAN 3 MENIT — kartu padam sendiri")
print("   (flow_koneksi menumpuk historis; tanpa jendela ini, koneksi yang")
print("    sudah lama diblokir tetap dilaporkan sebagai tembus aktif.)")

db.query(Flow).delete(); db.commit()
db.add(flow(1, "10.66.66.69", 3389, waktu=sekarang - timedelta(minutes=10)))
db.commit()
h = rs.deteksi_pembobolan(db)
sama("baris basi (>3 menit) TIDAK memicu temuan", h["jumlah"], 0)

db.query(Flow).delete(); db.commit()
db.add(flow(1, "10.66.66.69", 3389, waktu=sekarang - timedelta(minutes=2)))
db.commit()
h = rs.deteksi_pembobolan(db)
sama("baris segar (<3 menit) memicu temuan", h["jumlah"], 1)

# ---------------------------------------------------------------------------
print("\n7. NAMA LAYANAN DARI `services` DIPAKAI KALAU ADA, BUKAN NAMA GENERIK")

db.query(Flow).delete(); db.commit()
db.add(Service(device_id=1, nama="RDP Admin Khusus", jenis="tcp", port=3389))
db.add(flow(1, "10.66.66.70", 3389))
db.commit()
h = rs.deteksi_pembobolan(db)
sama("nama layanan terdaftar dipakai", h["temuan"][0]["layanan"],
     "RDP Admin Khusus")

# ---------------------------------------------------------------------------
print("\n8. BEBERAPA POTRET UNTUK PASANGAN (asal, device, port) YANG SAMA")
print("   DIGABUNG JADI SATU TEMUAN, BUKAN DIGANDAKAN")

db.query(Flow).delete(); db.commit()
db.add(flow(1, "10.66.66.71", 22, waktu=sekarang - timedelta(seconds=120)))
db.add(flow(1, "10.66.66.71", 22, waktu=sekarang - timedelta(seconds=60)))
db.add(flow(1, "10.66.66.71", 22, waktu=sekarang))
db.commit()
h = rs.deteksi_pembobolan(db)
sama("satu temuan, bukan tiga", h["jumlah"], 1)
sama("potret tercatat 3", h["temuan"][0]["potret"], 3)
benar("waktu 'terakhir' adalah yang TERBARU",
      h["temuan"][0]["terakhir"] == sekarang.isoformat(),
      "-> %r" % h["temuan"][0]["terakhir"])

# ---------------------------------------------------------------------------
print("\n9. URUTAN: TERBARU DULU (semua sama-sama kritis)")

db.query(Flow).delete(); db.commit()
db.add(flow(1, "10.66.66.81", 22, waktu=sekarang - timedelta(minutes=2)))
db.add(flow(1, "10.66.66.82", 22, waktu=sekarang - timedelta(seconds=10)))
db.commit()
h = rs.deteksi_pembobolan(db)
sama("dua temuan", h["jumlah"], 2)
sama("yang terbaru muncul lebih dulu", h["temuan"][0]["asal"], "10.66.66.82")

# ---------------------------------------------------------------------------
print("\n10. TIDAK ADA KONEKSI SAMA SEKALI -> BERSIH, BUKAN GALAT")

db.query(Flow).delete(); db.commit()
h = rs.deteksi_pembobolan(db)
sama("ada_pembobolan False", h["ada_pembobolan"], False)
sama("jumlah 0", h["jumlah"], 0)
benar("catatan batas jujur tetap ada", bool(h.get("catatan")))

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

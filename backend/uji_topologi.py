"""Tests for `report_service.topologi()`.
 1. All registered devices become nodes, including silent ones.
 2. Node status follows the latest `status_logs` row: up / down / tanya (never checked).
 3. A connection between two known devices gives one link with `ke_id` set and `dikenal: true`.
 4. A connection to an address outside the devices table still appears: `ke_id` None, `ke_alamat` set, `dikenal: false`.
 5. Repeated snapshots of the same connection (5-tuple) in the window do not multiply connection or byte counts.
 6. Two ports between the same pair give one link, with `pintu` listing both.
 7. Connections outside the window (`JENDELA_TOPOLOGI_MENIT`) are excluded.
 8. `tautan_tetap` is always present in the result (a list, possibly empty).
 9. `::ffff:`-prefixed addresses equal their plain form (`_ip_bersih`).
10. `pintu` names the real service port, not the client's ephemeral port; registered `services` win over common-port guesses.
Run: py uji_topologi.py
"""
import os
import sys
from datetime import datetime, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import report_service
from models import Base, Device, StatusLog, Flow, Service

lolos = 0
gagal = 0


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print(f"  LOLOS  {nama}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama}  {ket}")


def bangun():
    """In-memory database, so results do not change with the lab's real data."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)
    return session()


db = bangun()

a = Device(name="Router A", ip_address="192.168.56.1", platform="cisco_ios",
           device_type="router", location="Lokasi A")
b = Device(name="Server Web", ip_address="192.168.56.103", platform="linux",
           device_type="server", location="Lokasi A")
c = Device(name="Server Sepi", ip_address="192.168.56.104", platform="linux",
           device_type="server", location="Lokasi A")
db.add_all([a, b, c])
db.flush()

# a: up. b: down. c: never checked (no StatusLog).
db.add(StatusLog(device_id=a.id, timestamp=datetime.now(), is_reachable=True))
db.add(StatusLog(device_id=b.id, timestamp=datetime.now(), is_reachable=False))
db.commit()


# ---------------------------------------------------------------------------
# 1-2. Simpul & status
# ---------------------------------------------------------------------------
print("\n1-2. Simpul dan status")
hasil = report_service.topologi(db)
simpul = {s["id"]: s for s in hasil["perangkat"]}
benar("ketiga perangkat jadi simpul, termasuk yang sepi",
      len(simpul) == 3 and c.id in simpul)
benar("Router A berstatus up", simpul[a.id]["status"] == "up")
benar("Server Web berstatus down", simpul[b.id]["status"] == "down")
benar("Server Sepi belum pernah diperiksa -> tanya",
      simpul[c.id]["status"] == "tanya")


print("\n3-4. Tautan dikenal vs tidak dikenal")

sekarang = datetime.now()
db.add(Flow(device_id=b.id, ip_lokal="192.168.56.103", port_lokal=443,
            ip_lawan="192.168.56.1", port_lawan=51000,
            byte_masuk=1000, byte_keluar=2000, waktu=sekarang))
db.add(Flow(device_id=b.id, ip_lokal="192.168.56.103", port_lokal=443,
            ip_lawan="8.8.8.8", port_lawan=51001,
            byte_masuk=500, byte_keluar=700, waktu=sekarang))
db.commit()

hasil = report_service.topologi(db)
t = hasil["tautan_lalu_lintas"]
dikenal = [x for x in t if x["dikenal"]]
luar = [x for x in t if not x["dikenal"]]

benar("tautan ke perangkat dikenal punya ke_id",
      len(dikenal) == 1 and dikenal[0]["ke_id"] == a.id, str(dikenal))
benar("tautan ke alamat luar TIDAK dibuang, ke_alamat terisi",
      len(luar) == 1 and luar[0]["ke_alamat"] == "8.8.8.8", str(luar))
benar("alamat luar ditandai luar_jaringan",
      luar and luar[0]["luar_jaringan"] is True)


print("\n5. Potret berulang atas koneksi yang sama")

db2 = bangun()
d1 = Device(name="D1", ip_address="10.0.0.1", platform="linux", device_type="server")
d2 = Device(name="D2", ip_address="10.0.0.2", platform="linux", device_type="server")
db2.add_all([d1, d2])
db2.flush()

# The same 5-tuple snapshotted 5 times with cumulative byte counters rising, as `ss -tin` reports.
for i in range(5):
    db2.add(Flow(device_id=d1.id, ip_lokal="10.0.0.1", port_lokal=443,
                 ip_lawan="10.0.0.2", port_lawan=9000,
                 byte_masuk=(i + 1) * 1000, byte_keluar=(i + 1) * 500,
                 waktu=sekarang - timedelta(seconds=(4 - i) * 60)))
db2.commit()

hasil2 = report_service.topologi(db2)
t2 = hasil2["tautan_lalu_lintas"]
benar("lima potret koneksi yang sama -> SATU tautan",
      len(t2) == 1, str(t2))
if t2:
    benar("koneksi dihitung 1, bukan 5 (potret terakhir, bukan jumlah baris)",
          t2[0]["koneksi"] == 1, str(t2[0]))
    benar("byte diambil dari potret TERAKHIR (5000), bukan dijumlah (15000)",
          t2[0]["byte_masuk"] == 5000, str(t2[0]))


print("\n6. Dua port berbeda ke pasangan yang sama")

db3 = bangun()
e1 = Device(name="E1", ip_address="10.0.1.1", platform="linux", device_type="server")
e2 = Device(name="E2", ip_address="10.0.1.2", platform="linux", device_type="server")
db3.add_all([e1, e2])
db3.flush()
db3.add(Flow(device_id=e1.id, ip_lokal="10.0.1.1", port_lokal=51000,
             ip_lawan="10.0.1.2", port_lawan=22,
             byte_masuk=100, byte_keluar=100, waktu=sekarang))
db3.add(Flow(device_id=e1.id, ip_lokal="10.0.1.1", port_lokal=51001,
             ip_lawan="10.0.1.2", port_lawan=3306,
             byte_masuk=200, byte_keluar=200, waktu=sekarang))
db3.commit()

hasil3 = report_service.topologi(db3)
t3 = hasil3["tautan_lalu_lintas"]
benar("dua port ke pasangan yang sama -> satu tautan (bukan dua garis)",
      len(t3) == 1, str(t3))
if t3:
    benar("koneksi dihitung 2 (dua koneksi nyata) dalam satu tautan",
          t3[0]["koneksi"] == 2, str(t3[0]))
    benar("kedua port tercatat di `pintu`, dengan nama dari PORT_UMUM",
          [p["port"] for p in t3[0]["pintu"]] == [22, 3306]
          and [p["nama"] for p in t3[0]["pintu"]] == ["SSH", "MySQL"],
          str(t3[0]))


print("\n7. Koneksi lama tidak ikut")

db4 = bangun()
f1 = Device(name="F1", ip_address="10.0.2.1", platform="linux", device_type="server")
f2 = Device(name="F2", ip_address="10.0.2.2", platform="linux", device_type="server")
db4.add_all([f1, f2])
db4.flush()
lama = sekarang - timedelta(minutes=report_service.JENDELA_TOPOLOGI_MENIT + 5)
db4.add(Flow(device_id=f1.id, ip_lokal="10.0.2.1", port_lokal=51000,
             ip_lawan="10.0.2.2", port_lawan=22,
             byte_masuk=100, byte_keluar=100, waktu=lama))
db4.commit()
hasil4 = report_service.topologi(db4)
benar("koneksi di luar jendela waktu tidak muncul",
      len(hasil4["tautan_lalu_lintas"]) == 0, str(hasil4["tautan_lalu_lintas"]))


print("\n8-9. tautan_tetap dan penyeragaman alamat")

hasil5 = report_service.topologi(db4)
benar("tautan_tetap selalu ada di hasil, walau kosong",
      "tautan_tetap" in hasil5 and hasil5["tautan_tetap"] == [], str(hasil5.get("tautan_tetap")))

db5 = bangun()
g1 = Device(name="G1", ip_address="10.0.3.1", platform="linux", device_type="server")
db5.add(g1)
db5.flush()
db5.add(Flow(device_id=g1.id, ip_lokal="10.0.3.1", port_lokal=51000,
             ip_lawan="::ffff:10.0.3.9", port_lawan=443,
             byte_masuk=100, byte_keluar=100, waktu=sekarang))
db5.commit()
hasil6 = report_service.topologi(db5)
t6 = hasil6["tautan_lalu_lintas"]
benar("::ffff: disamakan dengan bentuk polosnya",
      len(t6) == 1 and t6[0]["ke_alamat"] == "10.0.3.9", str(t6))


print("\n10. Port layanan yang benar, bukan port ephemeral")

db6 = bangun()
# The SERVER (H1) records an inbound SSH connection from the CLIENT (H2): the server side listens on port 22 (port_lokal); the client uses a random ephemeral port (port_lawan).
h1 = Device(name="Server", ip_address="10.0.4.1", platform="linux", device_type="server")
h2 = Device(name="Klien", ip_address="10.0.4.2", platform="linux", device_type="server")
db6.add_all([h1, h2])
db6.flush()
db6.add(Flow(device_id=h1.id, ip_lokal="10.0.4.1", port_lokal=22,
             ip_lawan="10.0.4.2", port_lawan=57753,
             byte_masuk=100, byte_keluar=100, waktu=sekarang))
db6.commit()

hasil7 = report_service.topologi(db6)
t7 = hasil7["tautan_lalu_lintas"]
benar("port layanan yang tercatat 22 (SSH), BUKAN 57753 (ephemeral klien)",
      len(t7) == 1 and t7[0]["pintu"] == [{"port": 22, "nama": "SSH"}], str(t7))

# Registered services must win over the PORT_UMUM guess: 8080 is "HTTP (port lain)" there, but if NSM knows it is "E-Canteen v2", that name is used.
db7 = bangun()
i1 = Device(name="Web", ip_address="10.0.5.1", platform="linux", device_type="server")
i2 = Device(name="Pengunjung", ip_address="10.0.5.2", platform="linux", device_type="server")
db7.add_all([i1, i2])
db7.flush()
db7.add(Service(device_id=i1.id, nama="E-Canteen v2", jenis="tcp", port=8080, aktif=1))
db7.add(Flow(device_id=i1.id, ip_lokal="10.0.5.1", port_lokal=8080,
             ip_lawan="10.0.5.2", port_lawan=44821,
             byte_masuk=100, byte_keluar=100, waktu=sekarang))
db7.commit()

hasil8 = report_service.topologi(db7)
t8 = hasil8["tautan_lalu_lintas"]
benar("nama layanan TERDAFTAR (E-Canteen v2) menang atas tebakan PORT_UMUM",
      len(t8) == 1 and t8[0]["pintu"] == [{"port": 8080, "nama": "E-Canteen v2"}],
      str(t8))


print(f"\n=== {lolos} lolos, {gagal} gagal ===")
sys.exit(1 if gagal else 0)

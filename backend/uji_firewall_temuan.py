"""Tests for the firewall rule quality checker.

A tool accusing a rule of being "unnecessary" must be tested both ways: with
violating rules AND with similar but legitimate ones, since a rule removed on a
false accusation is a hole found only when something stops working.

 1. `_urai_ke` understands '22/tcp', '80' and REFUSES to guess profile names.
 2. `_jaringan` understands CIDR, 'Anywhere', and rejects what does not parse.
 3. Entry port (SSH) open to anyone -> HIGH severity.
 4. Ordinary service port (80) open to anyone -> MEDIUM, not high.
 5. A rule from a specific subnet is NOT treated as wide open.
 6. Duplicate rules are found.
 7. A rule covered by a broader rule ABOVE it is found.
 8. A broader rule AFTER a narrow one is NOT accused (it adds reach).
 9. Same port, different protocol (161/udp vs 161/tcp) do not cover each other.
10. A monitored service without a firewall hole is found; one with a hole is not.
11. The absence of a traffic counter is STATED, not hidden.

Run: py uji_firewall_temuan.py
"""
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import report_service
from models import (Base, Device, Service, FirewallSnapshot, FirewallAturan)

lolos = 0
gagal = 0


def cek(nama, dapat, harap):
    global lolos, gagal
    if dapat == harap:
        lolos += 1
        print(f"  LOLOS  {nama}: {dapat!r}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama}: dapat {dapat!r}, harusnya {harap!r}")


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print(f"  LOLOS  {nama}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama}  {ket}")


# 1-2. Parsers, tested first
print("\n1-2. Pengurai port dan alamat")

cek("'22/tcp'", report_service._urai_ke("22/tcp"), (22, "tcp"))
cek("'80'", report_service._urai_ke("80"), (80, None))
cek("'Apache Full' tidak ditebak", report_service._urai_ke("Apache Full"), (None, None))
cek("kosong", report_service._urai_ke(None), (None, None))

benar("'Anywhere' = seluruh IPv4",
      report_service._jaringan("Anywhere").prefixlen == 0)
benar("CIDR terurai",
      str(report_service._jaringan("192.168.56.0/24")) == "192.168.56.0/24")
benar("alamat tunggal jadi /32",
      report_service._jaringan("192.168.56.1").prefixlen == 32)
# IPv6 'Anywhere (v6)' is deliberately None: comparing it with an IPv4 network would raise, and treating it as a match would accuse the wrong rule.
benar("'Anywhere (v6)' dilewati", report_service._jaringan("Anywhere (v6)") is None)
benar("sampah dilewati", report_service._jaringan("bukan alamat") is None)


# Fake database: one device, deliberately designed rules
def bangun(aturan, layanan=(), aktif=1):
    """In-MEMORY database, not a copy of nsm.db, so results do not change when someone edits the lab firewall."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)
    db = session()

    d = Device(name="Server Uji", ip_address="192.168.56.103", platform="linux")
    db.add(d)
    db.flush()

    snap = FirewallSnapshot(device_id=d.id, aktif=aktif, kebijakan_masuk="deny",
                            kebijakan_keluar="allow", jumlah_aturan=len(aturan))
    db.add(snap)
    db.flush()

    for i, (ke, aksi, arah, dari) in enumerate(aturan, start=1):
        db.add(FirewallAturan(snapshot_id=snap.id, device_id=d.id, nomor=i,
                              ke=ke, aksi=aksi, arah=arah, dari=dari))
    for nama, port in layanan:
        db.add(Service(device_id=d.id, nama=nama, jenis="tcp", port=port))
    db.commit()
    return db


def judul_temuan(db):
    hasil = report_service.firewall_temuan(db)
    if not hasil:
        return []
    return [(t["keparahan"], t["judul"]) for t in hasil[0]["temuan"]]


# 3-5. Open to anyone
print("\n3-5. Aturan yang terbuka untuk siapa saja")

db = bangun([("22/tcp", "ALLOW", "IN", "Anywhere")])
t = judul_temuan(db)
benar("SSH terbuka ke siapa saja -> tinggi",
      any(k == "tinggi" and "22/tcp" in j for k, j in t), str(t))

db = bangun([("80/tcp", "ALLOW", "IN", "Anywhere")])
t = judul_temuan(db)
benar("web terbuka ke siapa saja -> sedang, bukan tinggi",
      any(k == "sedang" for k, j in t) and not any(k == "tinggi" for k, j in t),
      str(t))

db = bangun([("22/tcp", "ALLOW", "IN", "192.168.56.0/24")])
benar("dari subnet tertentu bukan temuan terbuka luas",
      not any("terbuka untuk siapa saja" in j for k, j in judul_temuan(db)),
      str(judul_temuan(db)))


# ---------------------------------------------------------------------------
# 6. Aturan kembar
# ---------------------------------------------------------------------------
print("\n6. Aturan kembar")

db = bangun([("22/tcp", "ALLOW", "IN", "192.168.56.0/24"),
             ("22/tcp", "ALLOW", "IN", "192.168.56.0/24")])
benar("dua aturan identik -> temuan kembar",
      any("kembar" in j for k, j in judul_temuan(db)), str(judul_temuan(db)))

db = bangun([("22/tcp", "ALLOW", "IN", "192.168.56.0/24"),
             ("80/tcp", "ALLOW", "IN", "192.168.56.0/24")])
benar("port berbeda bukan kembar",
      not any("kembar" in j for k, j in judul_temuan(db)), str(judul_temuan(db)))


# 7-9. Rules already covered by a rule above
print("\n7-9. Aturan yang sudah tercakup")

db = bangun([("3306/tcp", "ALLOW", "IN", "192.168.20.0/24"),
             ("3306/tcp", "ALLOW", "IN", "192.168.20.101")])
benar("aturan sempit sesudah yang luas -> tercakup",
      any("tercakup" in j for k, j in judul_temuan(db)), str(judul_temuan(db)))

# REVERSED order. In ufw a broader rule adds reach even if written later; accusing it of being "covered" would tell people to delete the only rule that allows the rest of the subnet.
db = bangun([("3306/tcp", "ALLOW", "IN", "192.168.20.101"),
             ("3306/tcp", "ALLOW", "IN", "192.168.20.0/24")])
benar("aturan luas SESUDAH yang sempit tidak dituduh",
      not any("tercakup" in j for k, j in judul_temuan(db)), str(judul_temuan(db)))

db = bangun([("161/udp", "ALLOW", "IN", "192.168.56.0/24"),
             ("161/tcp", "ALLOW", "IN", "192.168.56.1")])
benar("protokol berbeda tidak saling menutupi",
      not any("tercakup" in j for k, j in judul_temuan(db)), str(judul_temuan(db)))


# 10. Monitored service without a hole
print("\n10. Layanan yang dipantau tetapi tidak diizinkan")

db = bangun([("22/tcp", "ALLOW", "IN", "192.168.56.0/24")],
            layanan=[("E-Canteen", 8080)])
benar("layanan tanpa lubang -> temuan",
      any("8080" in j for k, j in judul_temuan(db)), str(judul_temuan(db)))

db = bangun([("22/tcp", "ALLOW", "IN", "192.168.56.0/24"),
             ("8080/tcp", "ALLOW", "IN", "192.168.56.0/24")],
            layanan=[("E-Canteen", 8080)])
benar("layanan yang punya lubang bukan temuan",
      not any("8080" in j for k, j in judul_temuan(db)), str(judul_temuan(db)))

# Firewall OFF: reporting "port not allowed" is pointless since ALL ports are open.
db = bangun([], layanan=[("E-Canteen", 8080)], aktif=0)
benar("firewall mati tidak melaporkan layanan tanpa lubang",
      not any("8080" in j for k, j in judul_temuan(db)), str(judul_temuan(db)))


# 11. What cannot be checked must be STATED
print("\n11. Batas pemeriksaan disebutkan")

db = bangun([("22/tcp", "ALLOW", "IN", "192.168.56.0/24")])
hasil = report_service.firewall_temuan(db)
benar("ketiadaan pencacah lalu lintas disebutkan",
      hasil and "iptables" in (hasil[0].get("tak_terperiksa") or ""),
      str(hasil[0].get("tak_terperiksa") if hasil else None))


print(f"\n=== {lolos} lolos, {gagal} gagal ===")
sys.exit(1 if gagal else 0)

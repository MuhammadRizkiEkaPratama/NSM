"""Tests for drift detection: observed extraction + comparison.

`POTRET_R1` below is a real configuration snapshot of R1, copied verbatim, so
extraction is verified against what the lab router actually prints (e.g. a
three-word `ip domain name`, `line vty 0 4`) rather than generic Cisco docs.

Four layers tested separately:
1. EXTRACTION against the real R1 snapshot: every value must equal what a human reads.
2. COMPARISON of the four statuses (cocok/beda/tidak_terbaca/hilang), with a
   scenario that FORCES all four to appear.
3. RISK: every catalog key must be classified, none falling to a silent default.
4. SERVICE (bandingkan/ringkasan) through temporary SQLite, same pattern as `uji_sot.py`.

Run: py uji_drift.py
"""
import os
import sys
import tempfile

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


# REAL R1 snapshot, copied verbatim from `konfig_snapshots.teks`.
POTRET_R1 = """! No configuration change since last restart
!
version 15.2
service timestamps debug datetime msec
service timestamps log datetime msec localtime show-timezone
!
hostname R1
!
boot-start-marker
boot-end-marker
!
logging buffered 16384 informational
logging rate-limit 20 except errors
!
no aaa new-model
no ip icmp rate-limit unreachable
ip cef
!
no ip domain lookup
ip domain name lab.local
no ipv6 cef
!
multilink bundle-name authenticated
!
username nsm privilege 15 secret 5 <DISAMARKAN>
!
ip tcp synwait-time 5
ip ssh version 2
!
interface FastEthernet0/0
 description lewat tombol NSM
 ip address 192.168.56.60 255.255.255.0
 duplex full
!
interface FastEthernet1/0
 description WAN ke R2 (lokasi B)
 ip address 10.10.10.1 255.255.255.252
 speed auto
 duplex auto
!
interface FastEthernet1/1
 no ip address
 shutdown
 speed auto
 duplex auto
!
ip forward-protocol nd
!
no ip http server
no ip http secure-server
ip route 0.0.0.0 0.0.0.0 10.10.10.2
ip route 192.168.20.0 255.255.255.0 10.10.10.2
!
snmp-server group NSMGRUP v3 priv read NSMVIEW
snmp-server view NSMVIEW iso included
!
control-plane
!
line con 0
 exec-timeout 0 0
 privilege level 15
 logging synchronous
 stopbits 1
line aux 0
 exec-timeout 0 0
 privilege level 15
 logging synchronous
 stopbits 1
line vty 0 4
 login local
 transport input ssh
!
ntp server 192.168.56.104
!
end
"""


# =============================================================================
print("=" * 74)
print("1. EKSTRAKSI -- terhadap potret R1 sungguhan")
print("=" * 74)

from drift import ekstrak  # noqa: E402

h = ekstrak.cisco_ios(POTRET_R1)

cek("hostname", h["nilai"]["hostname"], "R1")
cek("domain (bentuk 'ip domain name' TIGA kata)", h["nilai"]["domain"], "lab.local")
cek("zona_waktu (tidak ada baris clock timezone sama sekali)",
    h["nilai"]["zona_waktu"], None)
cek("ntp_server", h["nilai"]["ntp_server"], ["192.168.56.104"])
cek("dns_server (tidak ada baris)", h["nilai"]["dns_server"], None)
cek("logging_server (tidak ada baris logging host)", h["nilai"]["logging_server"], None)
cek("snmp_lokasi (tidak diset)", h["nilai"]["snmp_lokasi"], None)
cek("banner_masuk (tidak diset)", h["nilai"]["banner_masuk"], None)
cek("exec_timeout_menit (dari line con 0, BUKAN vty)",
    h["nilai"]["exec_timeout_menit"], 0)
cek("vty_izin (blok vty ADA, access-class TIDAK ADA -> daftar kosong)",
    h["nilai"]["vty_izin"], [])
cek("ssh_saja (transport input ssh, line vty 0 4 -- BUKAN 0 15)",
    h["nilai"]["ssh_saja"], True)
cek("layanan_http_mati (kedua baris 'no ip http ...' ada)",
    h["nilai"]["layanan_http_mati"], True)

nama_if = {i["nama"]: i for i in h["interface"]}
benar("ketiga interface terbaca", set(nama_if) ==
     {"FastEthernet0/0", "FastEthernet1/0", "FastEthernet1/1"})
cek("Fa0/0 deskripsi", nama_if["FastEthernet0/0"]["deskripsi"], "lewat tombol NSM")
cek("Fa0/0 ip", nama_if["FastEthernet0/0"]["ip"], "192.168.56.60")
cek("Fa0/0 mask", nama_if["FastEthernet0/0"]["mask"], "255.255.255.0")
cek("Fa0/0 shutdown (tidak ada baris shutdown/no shutdown -> default False)",
    nama_if["FastEthernet0/0"]["shutdown"], False)
cek("Fa1/1 shutdown (baris 'shutdown' eksplisit ada)",
    nama_if["FastEthernet1/1"]["shutdown"], True)
cek("Fa1/1 ip (tidak ada -- 'no ip address')", nama_if["FastEthernet1/1"]["ip"], None)

cek("vlan (router ini tidak punya blok vlan)", h["vlan"], [])

rute_set = {(r["tujuan"], r["mask"], r["next_hop"]) for r in h["rute"]}
benar("kedua rute statis terbaca", rute_set == {
    ("0.0.0.0", "0.0.0.0", "10.10.10.2"),
    ("192.168.20.0", "255.255.255.0", "10.10.10.2"),
})

# syntax variants that MUST still be recognized
benar("bentuk 'ip domain-name' (dengan tanda hubung) tetap dikenali",
     ekstrak.cisco_ios("ip domain-name contoh.id\n")["nilai"]["domain"] == "contoh.id")
benar("dua alamat DNS dalam SATU baris tetap terbaca",
     ekstrak.cisco_ios("ip name-server 8.8.8.8 8.8.4.4\n")["nilai"]["dns_server"]
     == ["8.8.8.8", "8.8.4.4"])
benar("'line vty 0 15' (rentang lain) tetap ditemukan sebagai blok vty",
     ekstrak.cisco_ios("line vty 0 15\n transport input ssh\n!\n")
     ["nilai"]["ssh_saja"] is True)
benar("transport input BUKAN ssh -> ssh_saja False",
     ekstrak.cisco_ios("line vty 0 4\n transport input telnet ssh\n!\n")
     ["nilai"]["ssh_saja"] is False)
benar("banner motd multi-kata terbaca",
     ekstrak.cisco_ios("banner motd ^CAkses terbatas.^C\n")
     ["nilai"]["banner_masuk"] == "Akses terbatas.")


# =============================================================================
print()
print("=" * 74)
print("2. PERBANDINGAN -- empat status sekaligus")
print("=" * 74)

from drift import service as drift_svc  # noqa: E402

INTENT_NILAI = {
    "hostname": "R1", "domain": "lab.local",       # -> cocok, cocok
    "zona_waktu": "Asia/Jakarta",  # -> tidak_terbaca (observed None)
    "exec_timeout_menit": 10,                       # -> beda (observed 0)
}
OBSERVED_NILAI = h["nilai"]
hasil_nilai = drift_svc._banding_nilai("cisco_ios", INTENT_NILAI, OBSERVED_NILAI)
peta = {x["kunci"]: x for x in hasil_nilai}

cek("hostname -> cocok", peta["hostname"]["status"], drift_svc.COCOK)
cek("domain -> cocok", peta["domain"]["status"], drift_svc.COCOK)
cek("zona_waktu -> tidak_terbaca", peta["zona_waktu"]["status"], drift_svc.TIDAK_TERBACA)
cek("exec_timeout_menit -> beda", peta["exec_timeout_menit"]["status"], drift_svc.BEDA)
benar("kunci yang TIDAK dinyatakan intent (mis. ntp_server) TIDAK muncul di hasil",
     "ntp_server" not in peta)
cek("exec_timeout_menit risiko wajib_manusia", peta["exec_timeout_menit"]["risiko"],
    "wajib_manusia")

hasil_if = drift_svc._banding_interface(
    [{"nama": "FastEthernet0/0", "ip": "192.168.56.60", "mask": "255.255.255.0",
      "deskripsi": "lewat tombol NSM", "shutdown": False, "vlan": None},
     {"nama": "FastEthernet2/0", "ip": None, "mask": None, "deskripsi": None,
      "shutdown": False, "vlan": None}],
    h["interface"])
peta_if = {x["kunci"]: x for x in hasil_if}
cek("Fa0/0 (identik) -> cocok", peta_if["FastEthernet0/0"]["status"], drift_svc.COCOK)
cek("Fa2/0 (tidak ada di observed) -> hilang", peta_if["FastEthernet2/0"]["status"],
    drift_svc.HILANG)

hasil_rute = drift_svc._banding_rute(
    [{"tujuan": "192.168.20.0", "mask": "255.255.255.0", "next_hop": "10.10.10.2"},
     {"tujuan": "172.16.0.0", "mask": "255.255.0.0", "next_hop": "10.10.10.9"}],
    h["rute"])
benar("rute yang ADA di observed -> cocok",
     any(r["status"] == drift_svc.COCOK for r in hasil_rute))
benar("rute yang TIDAK ADA di observed -> hilang",
     any(r["status"] == drift_svc.HILANG for r in hasil_rute))

benar("daftar dibandingkan sebagai HIMPUNAN (urutan beda tetap cocok)",
     drift_svc._sama(["a", "b"], ["b", "a"]))
benar("nilai skalar tetap dibandingkan tepat (bukan ikut jadi himpunan)",
     not drift_svc._sama(1, 2))


# =============================================================================
print()
print("=" * 74)
print("3. RISIKO -- semua kunci katalog terklasifikasi, tidak ada default diam-diam")
print("=" * 74)

from sot import katalog as k  # noqa: E402

belum = [s["kunci"] for s in k.KUNCI if s["kunci"] not in k.RISIKO_KUNCI]
benar("semua 13 kunci punya klasifikasi risiko eksplisit", belum == [],
     "-> belum: %s" % belum)
for spec in k.KUNCI:
    level, alasan = k.risiko_kunci(spec["kunci"])
    benar("%s: level sah (aman_otomatis/wajib_manusia)" % spec["kunci"],
         level in (k.RISIKO_AMAN, k.RISIKO_MANUSIA))
    benar("%s: alasan risiko tidak kosong" % spec["kunci"], bool(alasan and alasan.strip()))

for kategori in ("interface", "vlan", "rute"):
    level, alasan = k.risiko_kategori(kategori)
    cek("kategori '%s' -> wajib_manusia (risiko tertinggi, sesuai urutan Tahap 4-7)"
        % kategori, level, k.RISIKO_MANUSIA)


# =============================================================================
print()
print("=" * 74)
print("4. SERVICE -- bandingkan()/ringkasan() lewat basis data sementara")
print("=" * 74)


def siapkan_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    file = os.path.join(tempfile.mkdtemp(prefix="uji_drift_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    r1 = models.Device(name="Router Uji", ip_address="192.168.56.60",
                       device_type="router", platform="cisco_ios")
    linux1 = models.Device(name="Server Uji", ip_address="192.168.56.103",
                           device_type="server", platform="linux")
    db.add_all([r1, linux1])
    db.commit()
    return db, r1, linux1


import datetime  # noqa: E402
import models  # noqa: E402
from sot import service as sot_svc  # noqa: E402

db, r1, linux1 = siapkan_db()

r = drift_svc.bandingkan(db, r1.id)
benar("device tanpa intent -> punya_intent False", r.get("punya_intent") is False)

r_linux = drift_svc.bandingkan(db, linux1.id)
benar("platform linux -> didukung False (potret Linux beda domain data)",
     r_linux["didukung"] is False)

sot_svc.simpan_nilai(db, r1.id, {"hostname": "R1"}, oleh="uji")
r = drift_svc.bandingkan(db, r1.id)
benar("ada intent tapi belum ada potret -> punya_potret False",
     r.get("punya_potret") is False)

db.add(models.KonfigSnapshot(device_id=r1.id, waktu=datetime.datetime.now(),
                             sidik="x" * 8, teks=POTRET_R1))
db.commit()
r = drift_svc.bandingkan(db, r1.id)
cek("hostname R1 vs R1 -> selaras total (1 kunci, semua cocok)", r["selaras"], True)
cek("jumlah_diperiksa", r["jumlah_diperiksa"], 1)

sot_svc.simpan_nilai(db, r1.id, {"exec_timeout_menit": 10}, oleh="uji")
r = drift_svc.bandingkan(db, r1.id)
benar("sesudah tambah kunci yang BEDA -> selaras jadi False", r["selaras"] is False)
cek("jumlah_menyimpang", r["jumlah_menyimpang"], 1)
cek("jumlah_wajib_manusia", r["jumlah_wajib_manusia"], 1)

ring = drift_svc.ringkasan(db)
nama_ring = {x["device"]: x for x in ring}
benar("ringkasan mencakup Router Uji", "Router Uji" in nama_ring)
benar("ringkasan mencakup Server Uji (linux, ditandai tidak didukung)",
     "Server Uji" in nama_ring and nama_ring["Server Uji"]["didukung"] is False)
benar("Router Uji di ringkasan tidak selaras (sesuai isi di atas)",
     nama_ring["Router Uji"]["selaras"] is False)

db.close()


if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

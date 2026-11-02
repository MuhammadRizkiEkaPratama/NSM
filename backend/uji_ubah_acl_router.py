"""Tests for the router ACL block guards in `ubah_acl_router.py`.
This path can stop a router from serving a whole site, so the tests cover everything that must be refused before any connection is opened. Follows `uji_ubah_firewall.py`: `periksa_izin()` is fully tested (all refusals happen before `_sambung()`, so no SSH is needed). The real SSH path is verified live (docs/design/AUTO-BAN.md), not here. The pure functions `_baca_acl()` (parser of `show access-list`) and `_pilih_seq_aman()` (sequence number chooser) are tested directly.
Uses a temporary database; touches no device.
"""
import os
import sys
import tempfile
from datetime import datetime

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


def ditolak(nama, fungsi, potongan=None):
    global lolos, gagal
    import ubah_acl_router as ar
    try:
        fungsi()
    except ar.Ditolak as e:
        if potongan and potongan.lower() not in str(e).lower():
            gagal += 1
            print("  GAGAL  %s -> ditolak, tetapi pesannya %r tidak menyebut %r"
                  % (nama, str(e)[:80], potongan))
            return
        lolos += 1
        print("  LOLOS  %s" % nama)
        return
    except Exception as e:
        gagal += 1
        print("  GAGAL  %s -> melempar %r, bukan Ditolak" % (nama, e))
        return
    gagal += 1
    print("  GAGAL  %s -> TIDAK DITOLAK. Ini akan sampai ke perangkat." % nama)


ACL_NAMA = "DARI-LOKASI-A"

# Real router config excerpt, used as the KonfigSnapshot so `periksa_izin()` is checked against the real text shape.
POTRET_ACL_SUNGGUHAN = """
interface FastEthernet0/1
 description WAN ke ISP - disaring ACL DARI-LOKASI-A
 ip address 10.10.20.2 255.255.255.252
 ip access-group DARI-LOKASI-A in
 duplex auto
 speed auto
!
ip access-list extended DARI-LOKASI-A
 remark dibuat NSM - memisahkan Lokasi A dari Lokasi B
 permit tcp any any established
 permit icmp 192.168.56.0 0.0.0.255 192.168.20.0 0.0.0.255
 permit tcp host 192.168.56.1 192.168.20.0 0.0.0.255 eq 22
 deny   ip any any log
!
"""

# Real `show access-list DARI-LOKASI-A` output, used to test `_baca_acl()`, including the "Extended IP access list ..." header that must be ignored.
KELUARAN_SHOW_ACL_SUNGGUHAN = """Extended IP access list DARI-LOKASI-A
    10 permit tcp any any established (459845 matches)
    20 permit icmp 192.168.56.0 0.0.0.255 192.168.20.0 0.0.0.255 (16060 matches)
    30 permit tcp host 192.168.56.1 192.168.20.0 0.0.0.255 eq 22 (8955 matches)
    40 permit tcp host 192.168.56.1 host 192.168.20.101 eq 389 (1618 matches)
    50 permit udp host 192.168.56.1 host 192.168.20.101 eq snmp (15836 matches)
    60 permit tcp host 192.168.56.103 host 192.168.20.101 eq 389 (243 matches)
    70 permit tcp host 192.168.56.104 host 192.168.20.101 eq 389 (200 matches)
    80 permit udp host 192.168.56.104 eq ntp 192.168.20.0 0.0.0.255 (1008 matches)
    90 deny ip any any log (833 matches)
"""


def siapkan():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    file = os.path.join(tempfile.mkdtemp(prefix="uji_aclrouter_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    # Site B router, registered in ROUTER_ACL, healthy, identity already verified (`identitas.boleh_ditulisi`, the same guard `kirim_perintah.py` uses).
    router = models.Device(id=9, name="Router Lokasi B", ip_address="192.168.20.1",
                           device_type="router", platform="cisco_ios", aktif=1,
                           username="nsm", password="x", identitas_vonis="sama")
    # Another router on the same platform, but not in ROUTER_ACL.
    router_asing = models.Device(id=20, name="Router Tak Dikenal",
                                 ip_address="10.0.0.1", device_type="router",
                                 platform="cisco_ios", aktif=1,
                                 username="nsm", password="x")
    # Router Lokasi B, tapi SEDANG DIJEDA.
    router_pause = models.Device(id=21, name="Router Dijeda",
                               ip_address="192.168.20.9", device_type="router",
                               platform="cisco_ios", aktif=0,
                               jeda_alasan="pemeliharaan",
                               username="nsm", password="x")
    linux = models.Device(id=22, name="Server Linux", ip_address="192.168.56.200",
                          device_type="server", platform="linux", aktif=1,
                          username="nsmro", ssh_key_path="/x/kunci")
    db.add_all([router, router_asing, router_pause, linux])

    db.add(models.KonfigSnapshot(
        device_id=9, waktu=datetime.now(), sidik="a",
        teks=POTRET_ACL_SUNGGUHAN))
    # Stale snapshot: the expected ACL is gone.
    db.add(models.KonfigSnapshot(
        device_id=21, waktu=datetime.now(), sidik="b",
        teks="hostname R-lain\n!\n"))
    db.commit()
    return db


print("=" * 74)
print("UJI PENJAGAAN BLOKIR ACL ROUTER (ubah_acl_router.py, §E2)")
print("=" * 74)

db = siapkan()
import ubah_acl_router as ar

# ---------------------------------------------------------------------------
print("\n1. PERANGKAT YANG TIDAK ADA / BUKAN CISCO_IOS DITOLAK")

ditolak("device tidak ada ditolak",
        lambda: ar.periksa_izin(db, 999, ip="10.20.30.40", menit=60,
                                _periksa_ip=True, _periksa_menit=True),
        "tidak ada")
# `ubah_acl_router` checks the device capability (`kemampuan.firewall: acl` in its definition file), not the brand. Linux devices are still refused; the message names the platform from the definition file.
ditolak("device Linux ditolak (bukan pemblokir lewat ACL)",
        lambda: ar.periksa_izin(db, 22, ip="10.20.30.40", menit=60,
                                _periksa_ip=True, _periksa_menit=True),
        "ACL router")

# ---------------------------------------------------------------------------
print("\n2. ROUTER YANG TIDAK TERDAFTAR DI ROUTER_ACL DITOLAK")
print("   (menambah router baru ke daftar ini WAJIB keputusan sadar,")
print("    bukan otomatis dapat izin menulis.)")

ditolak("router asing (belum di ROUTER_ACL) ditolak",
        lambda: ar.periksa_izin(db, 20, ip="10.20.30.40", menit=60,
                                _periksa_ip=True, _periksa_menit=True),
        "belum terdaftar")

import models

# Fake ROUTER_ACL entry injected so each device hits only the guard under test, not an earlier one.
for _id in (21, 23, 24):
    ar.ROUTER_ACL[_id] = {"acl": ACL_NAMA, "interface": "FastEthernet0/1",
                          "contoh_host_lokasi": "192.168.20.101",
                          "port_uji": 389}

# ---------------------------------------------------------------------------
print("\n3. ROUTER YANG DIJEDA DITOLAK, ALASAN JEDA IKUT DISEBUT")

try:
    ar.periksa_izin(db, 21, ip="10.20.30.40", menit=60,
                    _periksa_ip=True, _periksa_menit=True)
    pesan_jeda = ""
except ar.Ditolak as e:
    pesan_jeda = str(e)
benar("router dijeda ditolak dan alasannya disebut",
      "dijeda" in pesan_jeda.lower() and "pemeliharaan" in pesan_jeda,
      "-> %r" % pesan_jeda[:120])

# ---------------------------------------------------------------------------
print("\n4. POTRET KONFIGURASI TIDAK ADA / ACL TIDAK DITEMUKAN DITOLAK")
print("   (menyisip ke ACL yang sudah tidak dipakai siapa pun akan")
print("    'berhasil' tanpa mengubah apa pun.)")

db.add(models.Device(id=23, name="Router Belum Terbaca",
                     ip_address="192.168.20.5", device_type="router",
                     platform="cisco_ios", aktif=1, username="nsm",
                     password="x"))
# Separate from the paused device 21: this one is active but its snapshot lacks the expected ACL, so it hits the ACL guard and not the pause guard.
db.add(models.Device(id=24, name="Router ACL Hilang",
                     ip_address="192.168.20.6", device_type="router",
                     platform="cisco_ios", aktif=1, username="nsm",
                     password="x", identitas_vonis="sama"))
db.add(models.KonfigSnapshot(device_id=24, waktu=datetime.now(), sidik="c",
                             teks="hostname R-lain\n!\n"))
db.commit()
ditolak("router terdaftar tapi BELUM PERNAH terbaca potretnya ditolak",
        lambda: ar.periksa_izin(db, 23, ip="10.20.30.40", menit=60,
                                _periksa_ip=True, _periksa_menit=True),
        "belum pernah berhasil membaca")

ditolak("potret ADA tapi ACL-nya sudah tidak ditemukan di sana ditolak",
        lambda: ar.periksa_izin(db, 24, ip="10.20.30.40", menit=60,
                                _periksa_ip=True, _periksa_menit=True),
        "tidak ditemukan")

# ---------------------------------------------------------------------------
print("\n5. ALAMAT TERLARANG / TAK SAH DITOLAK (mirip ubah_firewall)")

for ip, ket in (("192.168.56.1", "laptop NSM"),
                ("192.168.20.101", "server direktori & basis data"),
                ("192.168.56.103", "server web & berkas"),
                ("192.168.20.1", "router itu sendiri"),
                ("127.0.0.1", "localhost")):
    ditolak("%-20s ditolak (%s)" % (ip, ket),
            lambda ip=ip: ar.periksa_izin(db, 9, ip=ip, menit=60,
                                          _periksa_ip=True, _periksa_menit=True),
            # 192.168.20.1 (the router's own address) is also in the forbidden list (defense in depth), so it is caught there first with the same message.
            "tidak boleh diblokir")

for buruk in ("bukan-ip", "300.1.1.1", "", None):
    ditolak("alamat tidak sah %r ditolak" % (buruk,),
            lambda b=buruk: ar.periksa_izin(db, 9, ip=b, menit=60,
                                            _periksa_ip=True, _periksa_menit=True),
            "IPv4")

# ---------------------------------------------------------------------------
print("\n6. LAMA BLOKIR DI LUAR BATAS DITOLAK")

for menit in (0, -5, 1441, 99999, None, "sepuluh", 5.5, True):
    ditolak("lama blokir %r ditolak" % (menit,),
            lambda m=menit: ar.periksa_izin(db, 9, ip="10.20.30.40", menit=m,
                                            _periksa_ip=True, _periksa_menit=True),
            "menit")

# ---------------------------------------------------------------------------
print("\n7. PERMINTAAN YANG SAH LOLOS SAMPAI KE UJUNG periksa_izin()")

try:
    d, cfg = ar.periksa_izin(db, 9, ip="10.66.66.66", menit=60,
                             _periksa_ip=True, _periksa_menit=True)
    lolos += 1
    print("  LOLOS  permintaan sah tidak ditolak")
    sama("nama device benar", d.name, "Router Lokasi B")
    sama("nama ACL benar", cfg["acl"], ACL_NAMA)
except ar.Ditolak as e:
    gagal += 1
    print("  GAGAL  permintaan sah malah ditolak: %s" % e)

# ---------------------------------------------------------------------------
print("\n8. _nama_applet() — nama applet EEM yang sah dari IP")

sama("titik jadi tanda hubung",
     ar._nama_applet("192.168.56.151"), "NSM-ACL-192-168-56-151")

# ---------------------------------------------------------------------------
print("\n9. _baca_acl() — mengurai keluaran `show access-list` SUNGGUHAN")
print("   (termasuk baris header yang HARUS diabaikan, bukan diartikan")
print("    sebagai baris aturan.)")

baris_terurai = ar._baca_acl(
    type("Palsu", (), {"send_command": lambda self, _c: KELUARAN_SHOW_ACL_SUNGGUHAN})(),
    ACL_NAMA)
sama("9 baris aturan terurai (bukan 10 — header diabaikan)",
     len(baris_terurai), 9)
sama("baris pertama: sequence 10", baris_terurai[0][0], 10)
benar("teks baris pertama benar (jumlah 'matches' TIDAK ikut)",
      baris_terurai[0][1] == "permit tcp any any established",
      "-> %r" % baris_terurai[0][1])
sama("baris terakhir: sequence 90, deny catch-all",
     baris_terurai[-1], (90, "deny ip any any log"))
sama("terurut naik berdasarkan sequence",
     [s for s, _ in baris_terurai], sorted(s for s, _ in baris_terurai))

# ---------------------------------------------------------------------------
print("\n10. _pilih_seq_aman() — celah 1-9, tidak pernah bertabrakan")

seq = ar._pilih_seq_aman(baris_terurai)
sama("sequence 1 dipilih (celah kosong, aturan nyata mulai di 10)", seq, 1)

# Slots 1-9 partly used: pick a free one.
sebagian = baris_terurai + [(1, "deny ip host 10.1.1.1 any log"),
                            (2, "deny ip host 10.1.1.2 any log")]
seq2 = ar._pilih_seq_aman(sebagian)
sama("sequence 3 dipilih (1 dan 2 sudah dipakai)", seq2, 3)

# Slots 1-9 full: refuse rather than overwrite anyone's line.
penuh = baris_terurai + [(n, "deny ip host 10.1.1.%d any log" % n)
                         for n in range(1, 10)]
try:
    ar._pilih_seq_aman(penuh)
    gagal += 1
    print("  GAGAL  celah penuh -> TIDAK DITOLAK, akan menimpa baris orang lain")
except ar.Ditolak as e:
    lolos += 1
    print("  LOLOS  celah penuh -> ditolak rapi: %s" % str(e)[:70])

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

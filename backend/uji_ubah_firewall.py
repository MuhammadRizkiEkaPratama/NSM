"""Tests for the firewall change guards.
This is the only NSM path that can make a server stop answering, so the tests cover what must be refused:
  1. the default sends nothing (sungguhan=False)
  2. addresses that would cut off NSM or server-to-server traffic are refused
  3. blocks without a time limit are refused
  4. paused devices are refused
  5. a firewall that is OFF is refused (rules to a dead firewall look successful but block nothing)
  6. real changes without a written reason are refused
  7. the forbidden list in Python equals the one in the server script (duplicated on purpose; a diverging copy is worse than none)
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
    """Must raise Ditolak; otherwise it is a dangerous failure."""
    global lolos, gagal
    import ubah_firewall as uf
    try:
        fungsi()
    except uf.Ditolak as e:
        if potongan and potongan.lower() not in str(e).lower():
            gagal += 1
            print("  GAGAL  %s -> ditolak, tetapi pesannya %r tidak menyebut %r"
                  % (nama, str(e)[:70], potongan))
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


def siapkan():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    file = os.path.join(tempfile.mkdtemp(prefix="uji_ubahfw_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    healthy = models.Device(id=1, name="Server Sehat", ip_address="192.168.56.200",
                          device_type="server", platform="linux", aktif=1,
                          username="nsmro", ssh_key_path="/x/kunci")
    pause = models.Device(id=2, name="Server Dijeda", ip_address="192.168.56.201",
                         device_type="server", platform="linux", aktif=0,
                         jeda_alasan="sedang dirawat",
                         username="nsmro", ssh_key_path="/x/kunci")
    down = models.Device(id=3, name="Server Tanpa FW", ip_address="192.168.56.202",
                         device_type="server", platform="linux", aktif=1,
                         username="nsmro", ssh_key_path="/x/kunci")
    cisco = models.Device(id=4, name="Router", ip_address="192.168.56.60",
                          device_type="router", platform="cisco_ios", aktif=1,
                          username="nsm", password="x")
    db.add_all([healthy, pause, down, cisco])
    db.add(models.FirewallSnapshot(device_id=1, waktu=datetime.now(),
                                   sidik="a", aktif=1, kebijakan_masuk="deny",
                                   jumlah_aturan=3))
    db.add(models.FirewallSnapshot(device_id=2, waktu=datetime.now(),
                                   sidik="b", aktif=1, kebijakan_masuk="deny",
                                   jumlah_aturan=3))
    db.add(models.FirewallSnapshot(device_id=3, waktu=datetime.now(),
                                   sidik="c", aktif=0, jumlah_aturan=0))
    db.commit()
    return db


print("=" * 74)
print("UJI PENJAGAAN PENGUBAHAN FIREWALL")
print("=" * 74)

db = siapkan()
import ubah_firewall as uf

# ---------------------------------------------------------------------------
print("\n1. BAWAANNYA TIDAK MENGIRIM APA PUN")
print("   (yang mengubah keadaan perangkat harus diminta dengan sengaja,")
print("    bukan jadi akibat sampingan dari memanggil fungsi.)")

r = uf.blokir(db, 1, "10.20.30.40", 5, "uji", "rina")
sama("hasilnya RENCANA, bukan terkirim", r["hasil"], "RENCANA")
sama("dan ditandai belum sungguhan", r["sungguhan"], False)
benar("perintahnya ditampilkan supaya bisa diperiksa dulu",
      "blokir 10.20.30.40 5" in r["perintah"], "-> %r" % r["perintah"])

# ---------------------------------------------------------------------------
print("\n2. ALAMAT YANG MEMUTUS NSM ATAU ANTAR SERVER DITOLAK")
print("   (alamat yang paling mungkin salah diblokir justru alamat yang")
print("    paling sering muncul di data — dan di lab ini ketiganya.)")

for ip, ket in (("192.168.56.1", "laptop, tempat NSM memantau"),
                ("192.168.20.101", "server direktori & basis data (Lokasi B)"),
                ("192.168.56.103", "server web & berkas"),
                ("127.0.0.1", "localhost")):
    ditolak("%-30s ditolak" % ip,
            lambda ip=ip: uf.blokir(db, 1, ip, 5, "uji", "rina", sungguhan=True),
            "tidak boleh diblokir")

ditolak("alamat perangkat itu sendiri ditolak",
        lambda: uf.blokir(db, 1, "192.168.56.200", 5, "uji", "rina",
                          sungguhan=True),
        "perangkat itu sendiri")

for buruk in ("bukan-ip", "192.168.56", "300.1.1.1", "", None):
    ditolak("alamat tidak sah %r ditolak" % (buruk,),
            lambda b=buruk: uf.blokir(db, 1, b, 5, "uji", "rina",
                                      sungguhan=True),
            "IPv4")

# ---------------------------------------------------------------------------
print("\n3. BLOKIR TANPA BATAS WAKTU DITOLAK")
print("   (blokir permanen yang dipasang mesin akan tetap ada lama setelah")
print("    alasannya terlupakan, dan tidak ada yang berani menghapusnya.)")

for menit in (0, -5, 1441, 99999, None, "sepuluh", 5.5):
    ditolak("lama blokir %r ditolak" % (menit,),
            lambda m=menit: uf.blokir(db, 1, "10.20.30.40", m, "uji", "rina",
                                      sungguhan=True),
            "menit")

benar("1 menit dan 1440 menit masih diterima",
      uf.periksa_izin(db, 1, "10.20.30.40", 1) is not None
      and uf.periksa_izin(db, 1, "10.20.30.40", 1440) is not None)

# ---------------------------------------------------------------------------
print("\n4. PERANGKAT YANG DIJEDA DITOLAK")
print("   (perangkat yang dijeda tidak dipantau, jadi mengubah firewallnya")
print("    berarti mengubah sesuatu yang tidak sedang diawasi siapa pun.)")

ditolak("device dijeda ditolak",
        lambda: uf.blokir(db, 2, "10.20.30.40", 5, "uji", "rina",
                          sungguhan=True),
        "dijeda")

# The pause reason must appear in the refusal message so the reader does not have to look it up.
try:
    uf.blokir(db, 2, "10.20.30.40", 5, "uji", "rina", sungguhan=True)
    pesan_jeda = ""
except uf.Ditolak as e:
    pesan_jeda = str(e)
benar("dan alasan jedanya ikut disebut di pesannya",
      "dirawat" in pesan_jeda, "-> %r" % pesan_jeda[:90])

# ---------------------------------------------------------------------------
print("\n5. FIREWALL YANG MATI DITOLAK")
print("   (aturan yang ditulis ke firewall mati tidak menolak apa pun,")
print("    tetapi akan terlihat seperti berhasil — dan halaman akan")
print("    melaporkan alamat itu terblokir padahal lalu lintasnya lewat.)")

ditolak("firewall mati ditolak",
        lambda: uf.blokir(db, 3, "10.20.30.40", 5, "uji", "rina",
                          sungguhan=True),
        "MATI")

# ---------------------------------------------------------------------------
print("\n6. PLATFORM & KEADAAN LAIN")

# `ubah_firewall` checks the device capability (`kemampuan.firewall: ufw` in its definition file), not the brand. Cisco routers are still refused, now with a more useful reason ("this device does not block with ufw").
ditolak("router Cisco ditolak (belum didukung)",
        lambda: uf.blokir(db, 4, "10.20.30.40", 5, "uji", "rina",
                          sungguhan=True),
        "ufw")
ditolak("device yang tidak ada ditolak",
        lambda: uf.blokir(db, 999, "10.20.30.40", 5, "uji", "rina",
                          sungguhan=True),
        "tidak ada")

# ---------------------------------------------------------------------------
print("\n7. PERUBAHAN SUNGGUHAN TANPA ALASAN DITOLAK")
print("   (blokir tanpa alasan tertulis tidak bisa dinilai ulang nanti;")
print("    yang membacanya minggu depan cuma punya alamat dan jam.)")

for alasan in ("", "   ", None):
    ditolak("alasan %r ditolak" % (alasan,),
            lambda a=alasan: uf.blokir(db, 1, "10.20.30.40", 5, a, "rina",
                                       sungguhan=True),
            "Alasan wajib")

# ---------------------------------------------------------------------------
print("\n8. DAFTAR TERLARANG DI PYTHON SAMA DENGAN DI SKRIP SERVER")
print("   (keduanya sengaja diduplikasi supaya tidak hilang bersamaan.")
print("    Duplikat yang menyimpang lebih buruk daripada tidak ada duplikat:")
print("    ia memberi rasa aman untuk penjagaan yang sudah tidak sama.)")

jalur_skrip = os.path.join(os.path.dirname(DIR), "firewall", "nsm-ubah-firewall")
if not os.path.exists(jalur_skrip):
    print("  LEWAT  %s tidak ada" % jalur_skrip)
else:
    isi = open(jalur_skrip, encoding="utf-8").read()
    baris = [b for b in isi.splitlines() if b.startswith("DILARANG=")]
    benar("skrip server punya baris DILARANG", len(baris) == 1,
          "-> ketemu %d baris" % len(baris))
    if len(baris) == 1:
        di_skrip = set(baris[0].split("=", 1)[1].strip().strip('"').split())
        sama("isinya sama persis dengan DILARANG di Python",
             di_skrip, uf.DILARANG)

    for kata in ("ufw disable", "ufw reset", "default allow"):
        benar("skrip server tidak mengandung %r" % kata,
              kata not in isi.lower())

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

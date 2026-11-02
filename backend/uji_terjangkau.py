"""Tests that everything that must stay reachable after the firewall is enabled still is.
Besides SSH, other systems rely on ports silently:
    .101:389   used by sssd on .103 and .104 for central login
    .104:3306  used by E-Canteen on .103, not by this laptop
    .103:8080  used by phones via port forwarding on the laptop
The target list changes with the design (MySQL data moved to .104).
Run after the firewall is enabled and before the safety net is lifted; while the net is still in place, failures are not an emergency (ufw turns itself off).
Skips itself if the lab is unreachable.
"""
import os
import socket
import sys
import urllib.error
import urllib.request

DIR = os.path.dirname(os.path.abspath(__file__))
LDAP_DIR = os.path.join(os.path.dirname(DIR), "ldap")
KUNCI_NSM = r"C:\Users\<user>\.ssh\nsm_vm"

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


def lewati(alasan):
    print("  LEWAT  %s" % alasan)
    print("\n" + "=" * 74)
    print("HASIL: 0 lolos, 0 gagal (dilewati)")
    print("=" * 74)
    sys.exit(0)


def port_terbuka(ip, port, batas=4):
    try:
        s = socket.create_connection((ip, port), batas)
        s.close()
        return True
    except Exception:
        return False


if not port_terbuka("192.168.20.101", 22) and not port_terbuka("192.168.56.103", 22):
    lewati("kedua VM tidak menjawab di port 22")

print("=" * 74)
print("UJI KETERJANGKAUAN SETELAH FIREWALL")
print("=" * 74)

# ---------------------------------------------------------------------------
print("\n1. Port yang dipakai NSM sendiri")

for ip, port, nama in (
        ("192.168.20.101", 22, "SSH .101 (pemantauan NSM)"),
        ("192.168.20.101", 389, "LDAP .101 (login NSM & E-Canteen)"),
        ("192.168.56.103", 22, "SSH .103 (pemantauan + server berkas SFTP)"),
        ("192.168.56.103", 80, "HTTP .103 (Apache)"),
        ("192.168.56.103", 8080, "HTTP .103 (E-Canteen)"),
        ("192.168.56.104", 22, "SSH .104 (pemantauan data server)"),
        ("192.168.56.104", 3306, "MySQL .104 (basis data NSM & E-Canteen)")):
    benar("%-46s" % nama, port_terbuka(ip, port),
          "-> %s:%d tidak menjawab" % (ip, port))

# ---------------------------------------------------------------------------
print("\n2. Pemantauan NSM benar-benar bisa bekerja, bukan cuma port terbuka")
print("   (port yang menerima koneksi TCP belum tentu melayani. Yang")
print("    membuktikan hanya menjalankan perintah sungguhan.)")

try:
    import paramiko
except ImportError:
    paramiko = None

if paramiko is None:
    print("  LEWAT  paramiko belum terpasang")
else:
    for ip, nama_mesin in (("192.168.20.101", "nsm-ubuntu"),
                           ("192.168.56.103", "testUbuntu"),
                           ("192.168.56.104", "nsm-data")):
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            c.connect(ip, username="nsmro", key_filename=KUNCI_NSM, timeout=15,
                      allow_agent=False, look_for_keys=False)
            _i, o, _e = c.exec_command("hostname", timeout=10)
            h = o.read().decode().strip()
            c.close()
        except Exception as e:
            h = "GAGAL: %s" % e
        benar("kunci NSM masih diterima di %s" % ip, h == nama_mesin,
              "-> %r; pemantauan ke mesin ini PUTUS" % h)

# ---------------------------------------------------------------------------
print("\n3. Yang dipakai DIAM-DIAM oleh mesin lain, bukan oleh laptop ini")
print("   (ini yang paling mudah terlupakan: putusnya tidak terasa di sini,")
print("    dan baru ketahuan saat ada orang yang mencoba login.)")

if paramiko is not None:
    # sssd on .103 queries LDAP on .101. If .101:389 is closed to .103, SSH password logins on .103 fail while key-based SSH from the laptop still works, so it is invisible from here.
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect("192.168.56.103", username="nsmro", key_filename=KUNCI_NSM,
                  timeout=15, allow_agent=False, look_for_keys=False)
        _i, o, _e = c.exec_command("id rina 2>&1", timeout=15)
        jawab = o.read().decode().strip()
        c.close()
    except Exception as e:
        jawab = "GAGAL: %s" % e
    benar(".103 masih bisa menanyai direktori di .101 (sssd)",
          "uid=10001" in jawab,
          "-> %r; login SSH lewat LDAP di .103 akan gagal" % jawab[:80])

# E-Canteen on .103 uses MySQL on .104. If 3306 is closed to .103, the login page still renders and only fails on submit.
try:
    with urllib.request.urlopen("http://192.168.56.103:8080/login",
                                timeout=10) as r:
        kode = r.status
except urllib.error.HTTPError as e:
    kode = e.code
except Exception as e:
    kode = "GAGAL: %s" % e
benar("E-Canteen menjawab halaman login", kode == 200, "-> %r" % kode)

# Real proof: a real login touches MySQL and LDAP on .101; a rendered page proves neither.
jalur_sandi = os.path.join(LDAP_DIR, "sandi-user.txt")
if os.path.exists(jalur_sandi):
    sandi = {}
    for baris in open(jalur_sandi, encoding="utf-8"):
        if baris.startswith("#") or not baris.strip():
            continue
        b = baris.rstrip("\n").split("\t")
        if len(b) >= 3:
            sandi[b[0]] = b[2]

    if "dewi" in sandi:
        import urllib.parse

        class Diam(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        data = urllib.parse.urlencode(
            {"username": "dewi", "password": sandi["dewi"]}).encode()
        try:
            with urllib.request.build_opener(Diam).open(
                    "http://192.168.56.103:8080/login", data, timeout=15) as r:
                hasil = r.status
        except urllib.error.HTTPError as e:
            hasil = e.code
        except Exception as e:
            hasil = "GAGAL: %s" % e
        # The failure message must not state a cause as fact: the port checks above run from the laptop, not from .103. Possible causes: a stale password in `sandi-user.txt`, a locked LDAP account, or E-Canteen no longer answering 302 on successful login.
        benar("login E-Canteen sungguhan berhasil "
              "(MySQL di .104 + LDAP di .101)",
              hasil == 302,
              "-> %r (diharapkan 302). SEBABNYA BELUM DIPASTIKAN. Periksa "
              "berurutan: (1) sandi `dewi` di sandi-user.txt masih benar, "
              "(2) akun `dewi` tidak terkunci di LDAP .101, (3) E-Canteen "
              "memang masih menjawab 302 saat login sukses. Keterjangkauan "
              "port dari .103 SUDAH diperiksa terpisah dan terbuka." % hasil)

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

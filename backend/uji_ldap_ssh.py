"""Test of SSH login through LDAP on both VMs, and its limits.

Wiring SSH to a central directory is the riskiest change here: one PAM/NSS
mistake locks everyone out, including NSM itself. Tested:

  1. an LDAP user in group `sysadmin` CAN log in
  2. an LDAP user WITHOUT that group is REJECTED, even with a correct password
  3. NSM's key account (`nsmro`) can STILL log in

Number 3 is NSM's own monitoring: a PAM change that cut it would make NSM stop
reading config, flows, and access logs without any error.

Skips itself if the VMs are unreachable or the password file is missing.
"""
import os
import socket
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
LDAP_DIR = os.path.join(os.path.dirname(DIR), "ldap")
KUNCI_NSM = r"C:\Users\<user>\.ssh\nsm_vm"

VM = [("192.168.20.101", "nsm-ubuntu"), ("192.168.56.103", "testUbuntu")]

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


try:
    import paramiko
except ImportError:
    lewati("paramiko belum terpasang")

jalur_sandi = os.path.join(LDAP_DIR, "sandi-user.txt")
if not os.path.exists(jalur_sandi):
    lewati("sandi-user.txt tidak ada")

sandi = {}
for baris in open(jalur_sandi, encoding="utf-8"):
    if baris.startswith("#") or not baris.strip():
        continue
    b = baris.rstrip("\n").split("\t")
    if len(b) >= 3:
        sandi[b[0]] = b[2]

hidup = []
for ip, nama in VM:
    try:
        s = socket.create_connection((ip, 22), 4)
        s.close()
        hidup.append((ip, nama))
    except Exception:
        pass
if not hidup:
    lewati("tidak ada VM yang menjawab di port 22")


def ssh_sandi(host, user, pw):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(host, username=user, password=pw, timeout=20,
                  allow_agent=False, look_for_keys=False)
        _i, o, _e = c.exec_command("id -u")
        uid = o.read().decode().strip()
        c.close()
        return uid
    except Exception:
        return None


def ssh_kunci(host, user):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(host, username=user, key_filename=KUNCI_NSM, timeout=20,
                  allow_agent=False, look_for_keys=False)
        _i, o, _e = c.exec_command("hostname")
        h = o.read().decode().strip()
        c.close()
        return h
    except Exception:
        return None


def uji_arif_sftp_saja(host):
    """`arif` may use sftp on .103 but nothing else. Three independent limits:

      1. shell commands are rejected       <- ForceCommand internal-sftp
      2. sftp itself works                 <- otherwise the file server is useless
      3. `/` shows the chroot contents     <- ChrootDirectory

    Number 3 breaks most silently: without the chroot sftp still works perfectly,
    only the directory listing differs.
    """
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(host, username="arif", password=sandi["arif"], timeout=20,
                  allow_agent=False, look_for_keys=False)
    except Exception as e:
        benar("arif bisa terautentikasi di .103 (anggota grup berkas)", False,
              "-> %s" % e)
        return

    try:
        _i, o, _e = c.exec_command("id -u", timeout=15)
        answer = o.read().decode("utf-8", "replace")
        benar("arif TIDAK bisa menjalankan perintah apa pun",
              "sftp connections only" in answer.lower(),
              "-> ia dapat shell; ForceCommand internal-sftp tidak berlaku "
              "(jawaban: %r)" % answer[:80])

        s = c.open_sftp()
        content = set(s.listdir("/"))
        benar("tetapi sftp-nya memang bekerja", "publik" in content,
              "-> isi /: %r" % sorted(content))
        benar("dan `/` yang ia lihat adalah isi chroot, bukan / sungguhan",
              not ({"etc", "root", "var", "usr"} & content),
              "-> ia melihat seluruh sistem berkas: %r" % sorted(content))
        s.close()
    finally:
        c.close()


for ip, nama_vm in hidup:
    print("\n== %s (%s) ==" % (ip, nama_vm))

    # 1. sysadmin may log in
    if "rina" in sandi:
        uid = ssh_sandi(ip, "rina", sandi["rina"])
        benar("rina (sysadmin) bisa SSH", uid is not None)
        if uid is not None:
            benar("dan uid-nya dari LDAP, bukan akun lokal", uid == "10001",
                  "-> uid=%s; kalau <2000 berarti akun lokal yang dipakai" % uid)

    # 2. neither sysadmin nor a member of `berkas`: REJECTED even with a correct password
    if "siti" in sandi:
        benar("siti (bukan sysadmin, bukan grup berkas) DITOLAK",
              ssh_sandi(ip, "siti", sandi["siti"]) is None,
              "-> ia berhasil masuk; simple_allow_groups tidak bekerja")

    # 3. `arif` differs per machine, and that is the point. He belongs to group
    #    `berkas`, which `.103` allows, so he may authenticate there, but only for sftp
    #    inside the chroot. The test is deliberately not loosened to "accepted": it
    #    must prove acceptance stops at the intended boundary (no commands, nothing
    #    outside /srv/berkas), or losing ForceCommand would go unnoticed.
    if "arif" in sandi:
        if ip == "192.168.20.101":
            benar("arif DITOLAK di .101 (tidak ada server berkas di sini)",
                  ssh_sandi(ip, "arif", sandi["arif"]) is None,
                  "-> ia masuk ke mesin direktori & basis data")
        else:
            uji_arif_sftp_saja(ip)

    if "rina" in sandi:
        benar("rina + sandi salah ditolak",
              ssh_sandi(ip, "rina", "sandi-yang-jelas-salah") is None)

    # 4. NSM's own monitoring still works
    h = ssh_kunci(ip, "nsmro")
    benar("kunci NSM (nsmro) masih diterima", h is not None,
          "-> pemantauan NSM ke mesin ini PUTUS")
    if h:
        benar("dan menjawab dari mesin yang benar", h == nama_vm,
              "-> %r" % h)

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

"""Test against the LIVE LDAP on .101: authentication really works.

Unlike `uji_ldif_ldap.py`, which only checks the LDIF file before it is applied.
A correct file does not guarantee a correct server (default ACLs differ between
versions, entries can partially fail to load).

Checked, most critical first:

  1. the RIGHT password is accepted (otherwise everyone is locked out)
  2. a WRONG password is rejected (a misconfigured server may accept any bind)
  3. anonymous cannot read `userPassword`
  4. group membership is readable, since it determines access rights
  5. non-sysadmin accounts have no shell

Skips itself if the server is unreachable or `ldap3` is not installed.
"""
import os
import socket
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
LDAP_DIR = os.path.join(os.path.dirname(DIR), "ldap")

HOST = "192.168.20.101"
PORT = 389
BASE = "dc=bsp,dc=id"

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
    import ldap3
except ImportError:
    lewati("pustaka ldap3 belum terpasang")

try:
    s = socket.create_connection((HOST, PORT), 4)
    s.close()
except Exception as e:
    lewati("server LDAP %s:%d tidak terjangkau (%s)" % (HOST, PORT, type(e).__name__))

jalur_sandi = os.path.join(LDAP_DIR, "sandi-user.txt")
if not os.path.exists(jalur_sandi):
    lewati("sandi-user.txt tidak ada, tidak bisa menguji bind")

sandi = {}
for baris in open(jalur_sandi, encoding="utf-8"):
    if baris.startswith("#") or not baris.strip():
        continue
    b = baris.rstrip("\n").split("\t")
    if len(b) >= 3:
        sandi[b[0]] = b[2]

# `get_info=NONE` plus a timeout. `get_info=ALL` makes ldap3 download the whole
# directory schema; since `.101` moved to Location B that crosses a 0.11 Mbit/s
# link (measured: 0.6 s with NONE vs 17.4 s with ALL) and this test opens a dozen
# connections. Without `connect_timeout`/`receive_timeout`, `bind()` would wait
# forever if no reply ever came, which over a WAN a single lost packet can cause.
srv = ldap3.Server(HOST, port=PORT, get_info=None, connect_timeout=10)


def dn(uid):
    return "uid=%s,ou=people,%s" % (uid, BASE)


# ---------------------------------------------------------------------------
print("\n1. SANDI YANG BENAR DITERIMA")
print("   (kalau tidak, seluruh orang terkunci keluar dari semua sistem)")

diterima = 0
for uid, s in sorted(sandi.items()):
    c = ldap3.Connection(srv, user=dn(uid), password=s, receive_timeout=20)
    ok = c.bind()
    diterima += ok
    benar("%-8s bind diterima" % uid, ok,
          "-> %s" % (c.result or {}).get("description"))
    c.unbind()
benar("kedelapan orang bisa masuk", diterima == len(sandi),
      "-> %d dari %d" % (diterima, len(sandi)))

# ---------------------------------------------------------------------------
print("\n2. SANDI YANG SALAH DITOLAK")
print("   (server yang salah konfigurasi bisa menerima bind apa pun, dan")
print("    gejalanya 'semua orang bisa login' — dari luar terlihat seperti")
print("    fitur yang berhasil)")

uid0 = sorted(sandi)[0]
for buruk in ("salah", "sandi-yang-jelas-salah", sandi[uid0] + "x",
              sandi[uid0].upper()):
    c = ldap3.Connection(srv, user=dn(uid0), password=buruk, receive_timeout=20)
    hasil = c.bind()
    c.unbind()
    benar("sandi %-24r ditolak" % buruk[:24], not hasil,
          "-> DITERIMA, ini bahaya")

# EMPTY password: the classic LDAP trap. A simple bind with a valid DN and an empty
# password is an unauthenticated bind (RFC 4513), and many servers answer success
# as anonymous. `ldap3` refuses to send it (LDAPPasswordIsMandatoryError). The test
# checks that the library refuses, and that even if sent it is not treated as a login.
try:
    c = ldap3.Connection(srv, user=dn(uid0), password="", receive_timeout=20)
    hasil_kosong = c.bind()
    c.unbind()
    benar("sandi KOSONG tidak dianggap login berhasil", not hasil_kosong,
          "-> server menerima unauthenticated bind sebagai sukses")
except Exception as e:
    benar("sandi KOSONG ditolak pustaka sebelum dikirim",
          "mandatory" in str(e).lower(), "-> %s" % type(e).__name__)

c = ldap3.Connection(srv, user=dn("tidak-ada-orang-ini"),
                     password="apa saja", receive_timeout=20)
hasil = c.bind()
c.unbind()
benar("user yang tidak ada ditolak", not hasil)

# ---------------------------------------------------------------------------
print("\n3. ANONIM TIDAK BISA MEMBACA SANDI")

c = ldap3.Connection(srv, receive_timeout=20)
c.bind()
c.search(BASE, "(uid=%s)" % uid0, attributes=["userPassword", "cn", "title"])
entri = c.entries[0] if c.entries else None
benar("anonim boleh melihat nama (direktori memang untuk dicari)",
      bool(entri and str(entri.cn)))
benar("anonim TIDAK bisa membaca userPassword",
      not (entri and entri.userPassword.value))
c.unbind()

# ---------------------------------------------------------------------------
print("\n4. KEANGGOTAAN GRUP TERBACA")
print("   (grup yang menentukan hak akses; kalau tidak terbaca, semua orang")
print("    berakhir dengan hak yang sama)")

c = ldap3.Connection(srv, user=dn("rina"), password=sandi["rina"],
                     receive_timeout=20)
c.bind()
c.search("ou=groups,%s" % BASE, "(objectClass=posixGroup)",
         attributes=["cn", "memberUid", "gidNumber"])
grup = {str(e.cn): [str(x) for x in e.memberUid] for e in c.entries}
for wajib in ("sysadmin", "nsm-admin", "nsm-viewer", "ecanteen"):
    benar("grup %-11s ada" % wajib, wajib in grup, "-> %r" % sorted(grup))
benar("rina anggota sysadmin", "rina" in grup.get("sysadmin", []))
benar("siti BUKAN anggota sysadmin", "siti" not in grup.get("sysadmin", []),
      "-> penjaga kantin tidak boleh bisa SSH ke server")
benar("siti anggota ecanteen", "siti" in grup.get("ecanteen", []))

# ---------------------------------------------------------------------------
print("\n5. HANYA SYSADMIN YANG PUNYA SHELL")
print("   ('satu akun untuk semua sistem' tidak boleh berarti 'semua orang")
print("    bisa masuk ke server')")

c.search("ou=people,%s" % BASE, "(objectClass=posixAccount)",
         attributes=["uid", "loginShell"])
shell = {str(e.uid): str(e.loginShell) for e in c.entries}
sysadmin = set(grup.get("sysadmin", []))
for uid, sh in sorted(shell.items()):
    if uid in sysadmin:
        benar("%-8s (sysadmin) punya shell" % uid, sh != "/usr/sbin/nologin",
              "-> %r" % sh)
    else:
        benar("%-8s TIDAK bisa login shell" % uid, sh == "/usr/sbin/nologin",
              "-> %r" % sh)
c.unbind()

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

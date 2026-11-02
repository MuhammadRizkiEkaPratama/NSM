"""Test of E-Canteen login through LDAP, and above all its LIMITS.

1. A WRONG password for an LDAP user must be rejected, with no silent fallback to
   the BCrypt hash in MySQL; otherwise deactivating someone in the directory
   would not close their access.
2. An EMPTY password must be rejected: a bind with a valid DN and empty password
   is an "unauthenticated bind" that some servers answer with success.
3. Existing in the directory does not mean being allowed to use this app: `arif`
   has a valid LDAP account but is not in the E-Canteen `users` table.

Skips itself if the E-Canteen server does not answer or the password file is
missing, so the suite still runs on machines without this lab.
"""
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

DIR = os.path.dirname(os.path.abspath(__file__))
LDAP_DIR = os.path.join(os.path.dirname(DIR), "ldap")
SERVER = "192.168.56.103"
PORT = 8080
URL = "http://%s:%d/login" % (SERVER, PORT)

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

try:
    s = socket.create_connection((SERVER, PORT), 4)
    s.close()
except Exception:
    lewati("E-Canteen di %s:%d tidak menjawab" % (SERVER, PORT))


def attempt_login(username, password):
    """Return (code, redirect_target). Success = 302 to the role page.

    Redirects are deliberately not followed; otherwise the code is always 200,
    whether login succeeded or not.
    """
    data = urllib.parse.urlencode(
        {"username": username, "password": password}).encode()

    class Diam(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    opener = urllib.request.build_opener(Diam)
    try:
        with opener.open(URL, data, timeout=20) as r:
            return r.status, r.headers.get("Location"), r.read().decode(
                "utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location"), e.read().decode(
            "utf-8", "replace")


print("== %s ==" % URL)

# 1. An LDAP user can log in and lands on the page for their role. The role comes
#    from the `users` table; LDAP is only asked whether the password is right.
for orang, tujuan in (("siti", "/admin"), ("rina", "/superadmin"),
                      ("dewi", "/menu")):
    if orang not in sandi:
        continue
    kode, lokasi, _ = attempt_login(orang, sandi[orang])
    benar("%s masuk lewat sandi LDAP" % orang, kode == 302,
          "-> kode %s; 200 berarti ditolak" % kode)
    if kode == 302:
        benar("  dan diarahkan ke %s" % tujuan,
              (lokasi or "").endswith(tujuan), "-> %r" % lokasi)

# 2. A WRONG password is rejected. This is the core of the test: a leftover BCrypt
#    fallback would let it through, since the old MySQL password still exists.
if "siti" in sandi:
    kode, lokasi, isi = attempt_login("siti", "sandi-yang-jelas-salah")
    benar("siti + sandi salah DITOLAK", kode == 200 and not lokasi,
          "-> kode %s ke %r; ia masuk lewat BCrypt lama" % (kode, lokasi))

# 3. An EMPTY password is rejected (unauthenticated bind trap).
if "siti" in sandi:
    kode, lokasi, _ = attempt_login("siti", "")
    benar("siti + sandi KOSONG ditolak", kode == 200 and not lokasi,
          "-> kode %s ke %r; unauthenticated bind lolos" % (kode, lokasi))

# 4. Having a directory account does not mean being allowed to use this app.
if "arif" in sandi:
    kode, lokasi, _ = attempt_login("arif", sandi["arif"])
    benar("arif (ada di LDAP, tidak ada di tabel users) ditolak",
          kode == 200 and not lokasi, "-> kode %s ke %r" % (kode, lokasi))

# 5. Legacy users are not pulled into LDAP. Their password is unknown here, so the
#    test checks that an arbitrary password is still rejected.
kode, lokasi, _ = attempt_login("student1", "asal-asalan")
benar("student1 + sandi ngawur tetap ditolak", kode == 200 and not lokasi,
      "-> kode %s ke %r" % (kode, lokasi))

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

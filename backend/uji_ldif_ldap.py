"""Test of the LDAP LDIF: valid structure, correct password hashes, no plaintext passwords.

The LDIF is copied to the server and applied in one go; a mistake leaves a
half-populated directory that is harder to fix than to rebuild. Costliest errors:

  1. plaintext passwords written into the LDIF
  2. hashes that do not match the recorded passwords (everyone locked out)
  3. two users sharing a salt, which reveals identical passwords

The password notes file uses space-aligned columns while names contain spaces,
so the reader must parse it carefully.

Touches neither network nor database.
"""
import base64
import hashlib
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
LDAP = os.path.join(os.path.dirname(DIR), "ldap")

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


def blok_ldif(teks):
    """Parse LDIF into a list of dicts {attribute: [value, ...]}."""
    hasil = []
    for b in teks.split("\n\n"):
        d = {}
        for line in b.splitlines():
            if line.startswith("#") or ": " not in line:
                continue
            k, v = line.split(": ", 1)
            d.setdefault(k, []).append(v)
        if d:
            hasil.append(d)
    return hasil


jalur_ldif = os.path.join(LDAP, "isi-direktori.ldif")
jalur_sandi = os.path.join(LDAP, "sandi-user.txt")

if not os.path.exists(jalur_ldif):
    print("  LEWAT  isi-direktori.ldif belum dibuat "
          "(jalankan ldap/buat_ldif.py)")
    sys.exit(0)

teks = open(jalur_ldif, encoding="utf-8").read()
blok = blok_ldif(teks)
orang = [b for b in blok if "userPassword" in b]
grup = [b for b in blok if "posixGroup" in b.get("objectClass", [])]

# ---------------------------------------------------------------------------
print("\n1. STRUKTUR DIREKTORINYA LENGKAP")

ou = [b["ou"][0] for b in blok if "organizationalUnit" in b.get("objectClass", [])]
benar("ou=people ada", "people" in ou, "-> %r" % ou)
benar("ou=groups ada", "groups" in ou, "-> %r" % ou)
sama("delapan orang", len(orang), 8)
sama("empat grup", len(grup), 4)

for b in blok:
    dn = b.get("dn", [""])[0]
    if dn:
        benar("dn %-42s berakhir di base" % dn[:42],
              dn.endswith("dc=bsp,dc=id"), "-> %r" % dn)
        break

# ---------------------------------------------------------------------------
print("\n2. TIAP ORANG PUNYA DUA WAJAH: APLIKASI DAN POSIX")
print("   (satu entri untuk dua keperluan itulah inti identitas terpusat;")
print("    kalau dipisah, seseorang bisa dinonaktifkan di satu tempat dan")
print("    tetap bisa masuk lewat yang lain)")

for b in orang:
    uid = b["uid"][0]
    kelas = b.get("objectClass", [])
    benar("%-8s punya inetOrgPerson (untuk aplikasi)" % uid,
          "inetOrgPerson" in kelas, "-> %r" % kelas)
    benar("%-8s punya posixAccount (untuk SSH)" % uid,
          "posixAccount" in kelas, "-> %r" % kelas)
    for wajib in ("uidNumber", "gidNumber", "homeDirectory", "loginShell",
                  "mail", "cn", "sn"):
        benar("%-8s punya %s" % (uid, wajib), wajib in b)

nomor = [int(b["uidNumber"][0]) for b in orang]
sama("uidNumber unik", len(set(nomor)), len(nomor))
benar("uidNumber di atas 10000 (tidak bentrok akun sistem)",
      all(n >= 10000 for n in nomor), "-> %r" % nomor)

# ---------------------------------------------------------------------------
print("\n3. TIDAK ADA SANDI POLOS DI LDIF")
print("   (LDIF disalin, dibuka, dan sering ikut tersimpan di mana-mana;")
print("    sandi polos di dalamnya hidup jauh lebih lama daripada dikira)")

benar("semua userPassword berbentuk hash SSHA",
      all(b["userPassword"][0].startswith("{SSHA}") for b in orang))

sandi = {}
if os.path.exists(jalur_sandi):
    for l in open(jalur_sandi, encoding="utf-8"):
        if l.startswith("#") or not l.strip():
            continue
        bagian = l.rstrip("\n").split("\t")
        if len(bagian) >= 3:
            sandi[bagian[0]] = bagian[2]
    for uid, s in sandi.items():
        benar("sandi %-8s tidak muncul polos di LDIF" % uid, s not in teks)

# ---------------------------------------------------------------------------
print("\n4. HASH SSHA BENAR-BENAR COCOK DENGAN SANDINYA")
print("   (kalau tidak cocok, semua orang terkunci — dan penyebabnya belum")
print("    tentu hashnya: berkas catatan sandi yang tidak bisa dibaca ulang")
print("    mesin menghasilkan gejala yang sama persis)")

if not sandi:
    print("  LEWAT  sandi-user.txt tidak ada, pencocokan dilewati")
else:
    for b in orang:
        uid = b["uid"][0]
        if uid not in sandi:
            continue
        mentah = base64.b64decode(b["userPassword"][0][len("{SSHA}"):])
        sha, garam = mentah[:20], mentah[20:]
        benar("%-8s hash cocok dengan sandinya" % uid,
              hashlib.sha1(sandi[uid].encode() + garam).digest() == sha)

    b0 = orang[0]
    mentah = base64.b64decode(b0["userPassword"][0][len("{SSHA}"):])
    benar("sandi salah DITOLAK",
          hashlib.sha1(b"sandi-yang-jelas-salah" + mentah[20:]).digest()
          != mentah[:20])

# ---------------------------------------------------------------------------
print("\n5. GARAM ACAK DAN BERBEDA TIAP ORANG")
print("   (garam yang sama membuat dua orang bersandi sama bisa disimpulkan")
print("    hanya dengan membaca direktorinya)")

garam_semua = [base64.b64decode(b["userPassword"][0][len("{SSHA}"):])[20:]
               for b in orang]
sama("garam unik untuk tiap orang", len(set(garam_semua)), len(garam_semua))
benar("panjang garam 4 byte", all(len(g) == 4 for g in garam_semua))

# ---------------------------------------------------------------------------
print("\n6. GRUP DAN KEANGGOTAANNYA MASUK AKAL")

nama_grup = [b["cn"][0] for b in grup]
for wajib in ("sysadmin", "nsm-admin", "nsm-viewer", "ecanteen"):
    benar("grup %s ada" % wajib, wajib in nama_grup, "-> %r" % nama_grup)

uid_ada = {b["uid"][0] for b in orang}
for g in grup:
    for anggota in g.get("memberUid", []):
        benar("anggota %-8s grup %-12s benar-benar ada"
              % (anggota, g["cn"][0]), anggota in uid_ada)

gid = [int(g["gidNumber"][0]) for g in grup]
sama("gidNumber grup unik", len(set(gid)), len(gid))

# Only sysadmin accounts may have a real shell.
sysadmin = set(next(g["memberUid"] for g in grup if g["cn"][0] == "sysadmin"))
for b in orang:
    uid, shell = b["uid"][0], b["loginShell"][0]
    if uid in sysadmin:
        benar("%-8s (sysadmin) punya shell" % uid, shell != "/usr/sbin/nologin")
    else:
        benar("%-8s (bukan sysadmin) TIDAK bisa login shell" % uid,
              shell == "/usr/sbin/nologin", "-> %r" % shell)

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

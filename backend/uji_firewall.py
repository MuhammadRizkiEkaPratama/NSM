"""Tests for the firewall (ufw) rule reader.

The dangerous failure is returning "no rules" for a machine that is actually
locked down: firewall OFF, command DENIED and ufw NOT INSTALLED all give zero
rules, yet the first means "machine is open" and the others "NSM knows nothing".
So each failure must RAISE and never pose as an empty list.

Guards:
  1. the default policy (deny incoming) is read
  2. each rule parses: number, target, action, direction, source, comment
  3. sudo denied -> ERROR, not an empty list
  4. ufw missing -> ERROR, not an empty list
  5. firewall off -> aktif=0 WITH a legitimately empty list
  6. the fingerprint ignores rule NUMBERS (ufw renumbers on delete)
"""
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

from connectors import firewall

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


def melempar(nama, fungsi, potongan):
    global lolos, gagal
    try:
        fungsi()
    except ValueError as e:
        if potongan.lower() in str(e).lower():
            lolos += 1
            print("  LOLOS  %s" % nama)
        else:
            gagal += 1
            print("  GAGAL  %s -> pesannya %r, tidak menyebut %r"
                  % (nama, str(e), potongan))
        return
    except Exception as e:
        gagal += 1
        print("  GAGAL  %s -> melempar %r, bukan ValueError" % (nama, e))
        return
    gagal += 1
    print("  GAGAL  %s -> TIDAK melempar apa pun (menyamar jadi daftar kosong)"
          % nama)


# The real shape of ufw output, including its spacing.
VERBOSE = """\
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), disabled (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW IN    Anywhere
"""

BERNOMOR = """\
Status: active

     To                         Action      From
     --                         ------      ----
[ 1] 22/tcp                     ALLOW IN    Anywhere
[ 2] 80/tcp                     ALLOW IN    192.168.56.0/24
[ 3] 3306/tcp                   ALLOW IN    192.168.56.103             # E-Canteen
[ 4] 23/tcp                     DENY IN     Anywhere
[ 5] 22/tcp (v6)                ALLOW IN    Anywhere (v6)
"""

UTUH = VERBOSE + "---PISAH---\n" + BERNOMOR

print("=" * 74)
print("UJI PEMBACA FIREWALL")
print("=" * 74)

# ---------------------------------------------------------------------------
print("\n1. Kebijakan bawaan terbaca")
print("   (ini yang menentukan arti seluruh daftarnya. 'deny incoming'")
print("    berarti daftar itu daftar IZIN; 'allow incoming' membuat daftar")
print("    yang sama persis berarti hal yang berlawanan.)")

k = firewall.urai(UTUH)
sama("firewall aktif", k["aktif"], 1)
sama("kebijakan masuk", k["kebijakan_masuk"], "deny")
sama("kebijakan keluar", k["kebijakan_keluar"], "allow")
sama("kebijakan rute", k["kebijakan_rute"], "disabled")
sama("logging", k["logging"], "on (low)")

# ---------------------------------------------------------------------------
print("\n2. Tiap aturan terurai lengkap")

sama("lima aturan terbaca", len(k["aturan"]), 5)

a1 = k["aturan"][0]
sama("nomor", a1["nomor"], 1)
sama("tujuan", a1["ke"], "22/tcp")
sama("aksi", a1["aksi"], "ALLOW")
sama("arah", a1["arah"], "IN")
sama("asal", a1["dari"], "Anywhere")

a2 = k["aturan"][1]
sama("asal berupa subnet ikut terbaca utuh", a2["dari"], "192.168.56.0/24")

a3 = k["aturan"][2]
sama("komentar dipisahkan dari asalnya", a3["dari"], "192.168.56.103")
sama("dan komentarnya tersimpan", a3["komentar"], "E-Canteen")

sama("aturan DENY tidak tertukar jadi ALLOW", k["aturan"][3]["aksi"], "DENY")
sama("baris IPv6 ikut terbaca", k["aturan"][4]["ke"], "22/tcp (v6)")

# ---------------------------------------------------------------------------
print("\n3. KEGAGALAN TIDAK BOLEH MENYAMAR JADI DAFTAR KOSONG")
print("   (firewall mati dan firewall yang tak terbaca sama-sama menghasilkan")
print("    nol aturan, tetapi artinya berlawanan: yang satu 'mesin ini")
print("    terbuka', yang satunya 'NSM tidak tahu apa-apa'.)")

melempar("sudo minta sandi -> galat",
         lambda: firewall.urai("sudo: a password is required"),
         "belum diizinkan")

melempar("nsmro tidak boleh sudo -> galat",
         lambda: firewall.urai("sudo: Sorry, user nsmro may not run sudo"),
         "belum diizinkan")

melempar("dijalankan tanpa sudo -> galat",
         lambda: firewall.urai("ERROR: You need to be root to run this script"),
         "tidak lewat sudo")

melempar("ufw tidak terpasang -> galat",
         lambda: firewall.urai("bash: ufw: command not found"),
         "tidak terpasang")

melempar("keluaran asing -> galat",
         lambda: firewall.urai("halo, ini bukan keluaran ufw"),
         "tidak dikenali")

melempar("keluaran kosong -> galat",
         lambda: firewall.urai(None),
         "tidak ada keluaran")

# ---------------------------------------------------------------------------
print("\n4. Firewall MATI adalah keadaan sah, bukan galat")
print("   (dan justru keadaan yang paling pantas terlihat di layar.)")

mati = firewall.urai("Status: inactive\n---PISAH---\nStatus: inactive\n")
sama("aktif = 0", mati["aktif"], 0)
sama("daftarnya kosong", mati["aturan"], [])
benar("tetapi dikembalikan, tidak melempar", isinstance(mati, dict))

# ---------------------------------------------------------------------------
print("\n5. Sidik jari mengabaikan NOMOR aturan")
print("   (ufw menomori ULANG seluruh daftar tiap kali satu aturan dihapus.")
print("    Sidik yang ikut menghitung nomor akan melaporkan 'seluruh firewall")
print("    berubah' untuk satu penghapusan — dan laporan yang melebih-lebihkan")
print("    akan berhenti dibaca.)")

geser = UTUH.replace("[ 1]", "[ 7]").replace("[ 2]", "[ 8]")
sama("nomor berubah, sidiknya tetap",
     firewall.urai(geser)["sidik"], k["sidik"])

ubah = UTUH.replace("ALLOW IN    192.168.56.0/24",
                    "ALLOW IN    Anywhere        ")
benar("membuka 80/tcp ke Anywhere MENGUBAH sidiknya",
      firewall.urai(ubah)["sidik"] != k["sidik"],
      "-> perubahan aturan tidak terdeteksi")

matikan = UTUH.replace("Status: active", "Status: inactive", 1)
benar("mematikan firewall juga mengubah sidiknya",
      firewall.urai(matikan)["sidik"] != k["sidik"])

kebijakan = UTUH.replace("deny (incoming)", "allow (incoming)")
benar("mengubah kebijakan bawaan juga",
      firewall.urai(kebijakan)["sidik"] != k["sidik"],
      "-> kebijakan bawaan tidak masuk sidik; membalik arti seluruh "
      "daftar tidak akan terdeteksi")

# ---------------------------------------------------------------------------
print("\n6. Perintahnya memang read-only")
print("   (penjagaan sesungguhnya ada di aturan sudo server, tetapi kode yang")
print("    menyimpang dari itu akan gagal dengan pesan minta sandi — dan")
print("    kegagalan yang membingungkan lebih baik dicegah di sini.)")

for kata in ("disable", "delete", "reset", "allow ", "deny "):
    benar("perintahnya tidak mengandung %r" % kata,
          kata not in firewall.PERINTAH.lower(),
          "-> %r" % firewall.PERINTAH)
benar("dan memakai jalur lengkap /usr/sbin/ufw",
      "/usr/sbin/ufw" in firewall.PERINTAH,
      "-> aturan sudo mencocokkan seluruh baris perintah; tanpa jalur "
      "lengkap ia tidak cocok dan sudo akan minta sandi")

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

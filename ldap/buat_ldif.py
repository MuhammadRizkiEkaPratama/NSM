"""Build the LDIF for the lab LDAP: directory structure, 8 simulated users, and groups.

Runs on the laptop and the result is copied to `.101` and applied there. It does
not touch the network.

Passwords are written to the LDIF as salted SSHA hashes (SHA-1 plus a random
salt per user), never as plain text. The plain passwords are written once to
`sandi-user.txt` in this folder for demos; do not copy that file to the server or
include it in any backup.

The base DN `dc=bsp,dc=id` follows the existing app package name (`id.bsp.frontend`).

Each user entry is both `inetOrgPerson` (used by applications: name, email,
password) and `posixAccount` (used by SSH login through sssd: uid, gid, home,
shell), so one entry serves both and a user cannot be disabled in one place yet
still log in through the other.
"""
import base64
import hashlib
import os
import secrets
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
BASE = "dc=bsp,dc=id"
ORG = "BSP"

# Eight users with varied names and roles, so one account can be shown to work
# across systems with access decided by group.
USER = [
    # uid,        nama lengkap,        jabatan,              uid_num, grup
    ("rina",     "Rina Maharani",     "Administrator Jaringan", 10001,
     ["sysadmin", "nsm-admin", "ecanteen"]),
    ("doni",    "Doni Saputra",      "Administrator Server",   10002,
     ["sysadmin", "nsm-admin", "ecanteen"]),
    # Group order matters: `gidNumber` is taken from the LAST group in the list (see
    # below), so `berkas` is deliberately placed in the middle. Moving it to the end
    # would change the primary group of four users and their uploaded files would be
    # owned by the wrong group.
    ("dewi",      "Dewi Anggraini",    "Staf Keuangan",          10003,
     ["nsm-viewer", "berkas", "ecanteen"]),
    ("bagas",     "Bagas Pratama",     "Staf Operasional",       10004,
     ["nsm-viewer", "berkas", "ecanteen"]),
    ("siti",      "Siti Nurhaliza",    "Penjaga Kantin",         10005,
     ["ecanteen"]),
    ("joko",      "Joko Susilo",       "Penjaga Kantin",         10006,
     ["ecanteen"]),
    ("intan",     "Intan Permata",     "Magang IT",              10007,
     ["nsm-viewer", "berkas", "ecanteen"]),
    ("arif",      "Arif Rahman",       "Auditor",                10008,
     ["berkas", "nsm-viewer"]),
]

GRUP = [
    ("sysadmin",   20001, "Boleh SSH ke server dan mengubah konfigurasi"),
    ("nsm-admin",  20002, "Boleh mengelola NSM: jeda device, kelola user"),
    ("nsm-viewer", 20003, "Boleh melihat NSM, tidak boleh mengubah apa pun"),
    ("ecanteen",   20004, "Pengguna aplikasi E-Canteen"),
    # sysadmin is deliberately NOT a member of `berkas`: the `Match Group berkas` rule
    # in sshd applies ForceCommand internal-sftp, which would remove an administrator's
    # SSH shell.
    ("berkas",     20005, "Boleh memakai server berkas SFTP di .103, tanpa shell"),
]


def ssha(sandi):
    """SSHA hash as produced by `slappasswd -h {SSHA}`.

    A random 4-byte salt per user means two identical passwords still hash differently.
    """
    garam = os.urandom(4)
    h = hashlib.sha1(sandi.encode("utf-8") + garam).digest()
    return "{SSHA}" + base64.b64encode(h + garam).decode("ascii")


def sandi_acak():
    """Password that is readable and retypeable in a demo but not guessable."""
    return secrets.token_urlsafe(12)


def main():
    # Refuse to overwrite passwords already in use. Each run generates NEW passwords for
    # all eight users, but the ones already loaded into the directory on .101 do not
    # change, so `sandi-user.txt` would be wrong and every login would fail.
    jalur_sandi = os.path.join(DIR, "sandi-user.txt")
    if os.path.exists(jalur_sandi) and "--paksa" not in sys.argv:
        print("BERHENTI: %s sudah ada." % jalur_sandi)
        print()
        print("Menjalankan ulang akan membuat sandi BARU untuk semua orang,")
        print("sementara sandi di direktori .101 tidak ikut berubah. Isinya akan")
        print("salah semua, dan gejalanya cuma 'login gagal' tanpa petunjuk.")
        print()
        print("Untuk menambah grup/user, pakai LDIF terpisah (lihat sftp/berkas.ldif).")
        print("Kalau memang ingin membuat ulang SELURUHNYA: --paksa")
        raise SystemExit(1)

    baris = []
    rahasia = []

    # --- kerangka direktori ---
    baris += [
        "# Struktur dasar. Dijalankan setelah slapd terpasang dan basednya",
        "# sudah dc=bsp,dc=id.",
        "",
        "dn: ou=people,%s" % BASE,
        "objectClass: organizationalUnit",
        "ou: people",
        "",
        "dn: ou=groups,%s" % BASE,
        "objectClass: organizationalUnit",
        "ou: groups",
        "",
    ]

    # --- grup POSIX ---
    for nama, gid, ket in GRUP:
        anggota = [u for u, _n, _j, _un, g in USER if nama in g]
        baris += [
            "dn: cn=%s,ou=groups,%s" % (nama, BASE),
            "objectClass: posixGroup",
            "cn: %s" % nama,
            "gidNumber: %d" % gid,
            "description: %s" % ket,
        ]
        baris += ["memberUid: %s" % a for a in anggota]
        baris += [""]

    # --- orang ---
    for uid, nama, jabatan, uidnum, grup in USER:
        sandi = sandi_acak()
        rahasia.append((uid, nama, sandi, ", ".join(grup)))
        depan = nama.split()[0]
        belakang = " ".join(nama.split()[1:]) or depan
        baris += [
            "dn: uid=%s,ou=people,%s" % (uid, BASE),
            "objectClass: inetOrgPerson",
            "objectClass: posixAccount",
            "objectClass: shadowAccount",
            "uid: %s" % uid,
            "cn: %s" % nama,
            "givenName: %s" % depan,
            "sn: %s" % belakang,
            "title: %s" % jabatan,
            "mail: %s@bsp.id" % uid,
            "uidNumber: %d" % uidnum,
            # The primary group is `ecanteen` if present, otherwise the first group. Access is
            # decided by group membership, not by this gidNumber.
            "gidNumber: %d" % dict((g, n) for g, n, _k in GRUP)[grup[-1]],
            "homeDirectory: /home/%s" % uid,
            "loginShell: %s" % ("/bin/bash" if "sysadmin" in grup
                                else "/usr/sbin/nologin"),
            "userPassword: %s" % ssha(sandi),
            "",
        ]

    jalur = os.path.join(DIR, "isi-direktori.ldif")
    with open(jalur, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(baris))

    # TAB-separated, not space-aligned: names contain spaces, so a space-aligned file
    # cannot be parsed back by a machine (the third column would not be the password).
    with open(jalur_sandi, "w", encoding="utf-8") as f:
        f.write("# SANDI USER LDAP SIMULASI — JANGAN disalin ke server,\n")
        f.write("# JANGAN masuk backup, JANGAN dibagikan.\n")
        f.write("# Dibuat oleh buat_ldif.py. Hapus setelah demo selesai.\n")
        f.write("# Kolom dipisah TAB: uid, nama, sandi, grup\n")
        for uid, nama, sandi, grup in rahasia:
            f.write("%s\t%s\t%s\t%s\n" % (uid, nama, sandi, grup))

    print("LDIF   : %s  (%d baris)" % (jalur, len(baris)))
    print("Sandi  : %s" % jalur_sandi)
    print()
    print("%d user, %d grup." % (len(USER), len(GRUP)))
    print()
    print("Sidik tiap sandi (bukan sandinya) supaya bisa dicocokkan nanti:")
    for uid, _n, sandi, _g in rahasia:
        sidik = hashlib.sha256(sandi.encode()).hexdigest()[:12]
        print("  %-8s %s" % (uid, sidik))
    print()
    print("Sandi aslinya HANYA ada di berkas di atas, tidak dicetak di sini.")


if __name__ == "__main__":
    main()

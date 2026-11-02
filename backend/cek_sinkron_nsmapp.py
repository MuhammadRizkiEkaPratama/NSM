"""Compare the SOURCE code on the laptop with what is actually on `nsm-app`.

Why: 8 frontend source files on `nsm-app` were found STALE (its
`SecurityConfig.java` lacked the `/api/sot`, `/api/drift`, and `/api/pagar`
rules even though those pages demonstrably worked live). This is not a bug but
the shape of the Java deploy: what runs on `nsm-app` is the COMPILED `.jar`
built on the laptop (`nsm-app` has no Maven or JDK). The `.java`/`.html`/`.js`
files on its disk are copies that happened to be sent, unused at runtime. NEW
files ship, but CHANGES to existing files only enter the `.jar`.

It is dangerous because it is subtle: anyone who SSHes into `nsm-app` and reads
the code draws wrong conclusions about the running system with no warning. It
is the third occurrence of this problem class (`requirements.txt`,
`uji_kunci_tulis.py`), so the check is a script rather than memory.

Usage:
    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\python.exe cek_sinkron_nsmapp.py

Exits 0 when in sync, 1 on differences. Changes nothing; reads both sides.
"""
import hashlib
import os
import sys

import config

HOST = "192.168.56.156"
USER = "nsmapp"

# The password is read from `.env`, NOT written here. This file once held the
# nsm-app SSH password in plain text AND was itself shipped to nsm-app, the
# "house key inside the house" situation that `SENGAJA_HANYA_LAPTOP` below uses
# as the reason not to ship `kirim_ke_nsmapp.py`. The reason applies equally
# here; `get_nsmapp_sandi()` was added later and this file was not migrated.

LOKAL_AKAR = r"C:\Users\<user>\NSM"
REMOTE_AKAR = "/home/nsmapp/NSM"

# (local subfolder, remote subfolder, extensions checked)
CAKUPAN = [
    ("backend", "backend", (".py",)),
    # Includes `.svg` and `.woff2`: the icon sprite and the Manrope font files go
    # into the `.jar`, so the app runs correctly without them ever being copied as
    # source. That is the problem: anyone who SSHes into nsm-app and reads its static
    # folder would conclude NSM still uses the old sprite and system fonts.
    (os.path.join("frontend", "src"), "frontend/src",
     (".java", ".html", ".js", ".css", ".svg", ".woff2")),
]

LEWATI_FOLDER = {"venv", "__pycache__", ".git", "target", "node_modules"}

LEWATI_BERKAS = {"penyangga.db", "penyangga.db-shm", "penyangga.db-wal"}

# LAPTOP-ONLY ON PURPOSE.
#
# Since `kirim_ke_nsmapp.py` runs this checker on every deploy, the two files
# below would otherwise make it report "DIFFERENCES" on every deploy forever,
# for a state that is intended. An alarm with no path to green trains people to
# ignore it.
#
#   kirim_ke_nsmapp.py  holds the nsm-app SSH credential in plain form; copying
#                       it to nsm-app puts the house key inside the house.
#   injeksi_r1.py       deliberately destructive (shuts down a real router
#                       interface); run from the laptop under supervision, never
#                       from the primary lab instance.
#
# They are still COUNTED and NAMED in the report, just not treated as failures.
# Unexpected differences still turn this checker red.
SENGAJA_HANYA_LAPTOP = {
    "kirim_ke_nsmapp.py",  # contains the nsm-app SSH credential in plain form
    "injeksi_r1.py",  # deliberately destructive, run under supervision
    "perbaiki_sandi_ldap.py",  # holds the LDAP admin credential
    "nyalakan_otomasi.py",  # holds the nsm-app SSH credential
    "atur_gns3_nsmapp.py",  # holds the nsm-app SSH credential
    "terowongan_gns3.py",  # holds the nsm-app SSH credential; only useful on the laptop
    "injeksi_r1_otomatis.py",  # deliberately destructive, run under supervision
    # LDAP hash backup; local only, must not go to any machine
    "ldap-userPassword-cadangan-20260822.json",
}


def sidik_lokal(jalur):
    with open(jalur, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def kumpulkan_lokal(akar, ekstensi):
    hasil = {}
    for dirpath, dirnames, filenames in os.walk(akar):
        dirnames[:] = [d for d in dirnames if d not in LEWATI_FOLDER]
        for nama in filenames:
            if not nama.endswith(ekstensi) or nama in LEWATI_BERKAS:
                continue
            full = os.path.join(dirpath, nama)
            rel = os.path.relpath(full, akar).replace(os.sep, "/")
            hasil[rel] = sidik_lokal(full)
    return hasil


def kumpulkan_remote(c, akar, ekstensi):
    prune = " ".join("-name %s -prune -o" % f for f in sorted(LEWATI_FOLDER))
    pattern = " -o ".join("-name '*%s'" % e for e in ekstensi)
    cmd = ("cd %s && find . %s \\( %s \\) -print0 2>/dev/null "
           "| xargs -0 sha256sum 2>/dev/null" % (akar, prune, pattern))
    _stdin, stdout, _stderr = c.exec_command(cmd)
    hasil = {}
    for line in stdout.read().decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        section = line.split(None, 1)
        if len(section) != 2:
            continue
        sidik, jalur = section[0], section[1].strip()
        rel = jalur[2:] if jalur.startswith("./") else jalur
        if os.path.basename(rel) in LEWATI_BERKAS:
            continue
        hasil[rel] = sidik
    return hasil


def main():
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER,
              password=config.get_nsmapp_sandi(), timeout=15)

    total_diff = 0
    try:
        for sub_local, sub_remote, ekstensi in CAKUPAN:
            root_cause_local = os.path.join(LOKAL_AKAR, sub_local)
            root_cause_remote = REMOTE_AKAR + "/" + sub_remote
            print("=" * 70)
            print("%s  <->  %s:%s" % (sub_local, HOST, sub_remote))
            print("=" * 70)

            local = kumpulkan_lokal(root_cause_local, ekstensi)
            remote = kumpulkan_remote(c, root_cause_remote, ekstensi)

            all_only_local = sorted(set(local) - set(remote))
            disengaja = [k for k in all_only_local
                         if os.path.basename(k) in SENGAJA_HANYA_LAPTOP]
            only_local = [k for k in all_only_local
                           if os.path.basename(k) not in SENGAJA_HANYA_LAPTOP]
            only_remote = sorted(set(remote) - set(local))
            diff_content = sorted(k for k in set(local) & set(remote)
                              if local[k] != remote[k])

            for k in disengaja:
                print("  (sengaja di laptop saja)  %s" % k)
            for k in only_local:
                print("  HANYA DI LAPTOP   %s" % k)
            for k in only_remote:
                print("  HANYA DI NSM-APP  %s" % k)
            for k in diff_content:
                print("  ISI BERBEDA       %s" % k)

            n = len(only_local) + len(only_remote) + len(diff_content)
            total_diff += n
            print("  -> %d berkas laptop, %d berkas nsm-app, %d perbedaan\n"
                  % (len(local), len(remote), n))
    finally:
        c.close()

    print("=" * 70)
    if total_diff == 0:
        print("SINKRON: tidak ada perbedaan.")
    else:
        print("TIDAK SINKRON: %d perbedaan total." % total_diff)
        print()
        print("Untuk berkas Java/HTML/JS: ingat bahwa yang BERJALAN di")
        print("nsm-app adalah .jar terkompilasi, bukan sumber di disk sana.")
        print("Sumber yang basi TIDAK mengubah perilaku aplikasi, tetapi")
        print("MENYESATKAN siapa pun yang membacanya. Kirim ulang sumbernya.")
    print("=" * 70)
    return 1 if total_diff else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("GAGAL: %s" % e)
        sys.exit(2)

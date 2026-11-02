"""Simulate lab traffic: people fetch files over SFTP and pages over HTTP. For demos and reports.

Run from the laptop. Each user connects with their own LDAP password, so the server logs real SFTP sessions; nothing is injected into the NSM database. The pattern is deliberately uneven (e.g. the auditor pulls the largest file twice) so the "who fetched what" pages have something to show, and `daftar-inventaris.xlsx` is pulled by four users.

HTTP requests are fired from two sources, this laptop (192.168.56.1) and `nsm-data` (192.168.56.104) over SSH, so the per-address table has more than one address. Events are spread over several minutes so "last seen" values differ.

    python simulasi_transfer.py                 # spread over 15 minutes (default)
    python simulasi_transfer.py --menit 3       # faster, for trying out
    python simulasi_transfer.py --sekaligus     # no delay at all
    python simulasi_transfer.py --tanpa-http    # SFTP only
"""
import argparse
import io
import os
import random
import sys
import time

DIR = os.path.dirname(os.path.abspath(__file__))
LDAP_DIR = os.path.join(os.path.dirname(DIR), "ldap")

SERVER = "192.168.56.103"
KUNCI_NSM = os.path.expanduser(r"~\.ssh\nsm_vm")

# Second machine that fires HTTP requests; skipped with a message if it is down.
PENEMBAK_KEDUA = ("192.168.56.104", "nsmro")

SKENARIO_SFTP = [
    ("arif",  ["/publik/rekaman-cctv-lobi.zip",
               "/publik/rekaman-cctv-lobi.zip",
               "/publik/laporan-keuangan-q2.pdf"], None),
    ("dewi",  ["/publik/laporan-keuangan-q2.pdf",
               "/publik/laporan-keuangan-q2.pdf",
               "/publik/daftar-inventaris.xlsx"], None),
    ("bagas", ["/publik/panduan-jaringan.pdf",
               "/publik/daftar-inventaris.xlsx"], None),
    ("intan", ["/publik/daftar-inventaris.xlsx"], "/unggah/catatan-magang.txt"),
]

# `arif` and `joko` are deliberately absent: as admins (`nsm-admin`/`sysadmin`) their SFTP sessions are not chrooted and cannot read `/srv/berkas/publik` (not in group `berkas`). That is correct lab behavior, and the server is not changed to make the scenario work.

# `siti` and `joko` are deliberately absent: they are only in group `ecanteen`, and sshd on .103 rejects them with "Authentication failed" before an SFTP session forms.

# HTTP targets: (port, path, count). Sizes differ widely (`uji-50mb.bin` vs a few KB for `/menu`) so the "Rata-rata" column is meaningful. Every path was verified to return 200 or 302.
JALUR_HTTP = [
    (80,   "/index.html",                    6),   # 10,6 KB
    (80,   "/uji-50mb.bin",                  2),   # 50 MB
    (8080, "/login",                         6),   # 10,9 KB
    (8080, "/register",                      3),   # 10,4 KB
    (8080, "/register-vendor",               2),   # 11,9 KB
    (8080, "/images/food/kungpao.png",       4),   # 1,5 MB
    (8080, "/images/food/noodle-bowl.png",   3),   # 1,7 MB
    (8080, "/menu",                          3),
    (8080, "/superadmin",                    2),
    # One request to a nonexistent page on purpose, to show that 404s are logged.
    (8080, "/keranjang",                     1),
]


def sandi_semua():
    jalur = os.path.join(LDAP_DIR, "sandi-user.txt")
    if not os.path.exists(jalur):
        print("BERHENTI: %s tidak ada." % jalur)
        raise SystemExit(1)
    peta = {}
    for baris in open(jalur, encoding="utf-8"):
        if baris.startswith("#") or not baris.strip():
            continue
        b = baris.rstrip("\n").split("\t")
        if len(b) >= 3:
            peta[b[0]] = b[2]
    return peta


def susun_kejadian(sandi):
    """Build the event list before shuffling, so events from different users interleave instead of running in per-user blocks."""
    kejadian = []

    for uid, ambil, unggah in SKENARIO_SFTP:
        if uid not in sandi:
            print("  LEWAT  %s tidak ada di sandi-user.txt" % uid)
            continue
        for jalur in ambil:
            kejadian.append(("sftp-ambil", uid, jalur))
        if unggah:
            kejadian.append(("sftp-kirim", uid, unggah))

    for port, jalur, kali in JALUR_HTTP:
        for _ in range(kali):
            kejadian.append(("http", port, jalur))

    random.shuffle(kejadian)
    return kejadian


def sftp_ambil(sandi, uid, jalur):
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(SERVER, username=uid, password=sandi[uid], timeout=20,
                  allow_agent=False, look_for_keys=False)
    except Exception as e:
        print("  %-6s GAGAL sambung (%s)" % (uid, e))
        return False
    ok = False
    try:
        s = c.open_sftp()
        # Written to the null device, not disk: only the transfer and its logging matter, not the content.
        buang = io.BytesIO()
        s.getfo(jalur, buang)
        print("  %-6s AMBIL  %-38s %d byte" % (uid, jalur, buang.tell()))
        ok = True
        s.close()
    except Exception as e:
        print("  %-6s GAGAL  %s (%s)" % (uid, jalur, e))
    c.close()
    return ok


def sftp_kirim(sandi, uid, jalur):
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(SERVER, username=uid, password=sandi[uid], timeout=20,
                  allow_agent=False, look_for_keys=False)
    except Exception as e:
        print("  %-6s GAGAL sambung (%s)" % (uid, e))
        return False
    ok = False
    try:
        s = c.open_sftp()
        with s.open(jalur, "w") as f:
            f.write("Catatan magang %s\n" % uid * 40)
        print("  %-6s KIRIM  %s" % (uid, jalur))
        ok = True
        s.close()
    except Exception as e:
        print("  %-6s GAGAL kirim %s (%s)" % (uid, jalur, e))
    c.close()
    return ok


class PenembakKedua:
    """One SSH connection to `nsm-data`, reused for `curl`; reconnecting per request would flood its auth.log with logins."""

    def __init__(self):
        self.c = None
        try:
            import paramiko
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(PENEMBAK_KEDUA[0], username=PENEMBAK_KEDUA[1],
                      key_filename=KUNCI_NSM, timeout=15,
                      allow_agent=False, look_for_keys=False)
            self.c = c
        except Exception as e:
            print("  CATATAN: %s tidak bisa dipakai menembak (%s)."
                  % (PENEMBAK_KEDUA[0], e))
            print("           Semua permintaan HTTP datang dari laptop saja.")

    def hidup(self):
        return self.c is not None

    def ambil(self, port, jalur):
        perintah = ('curl -s -o /dev/null -w "%%{http_code} %%{size_download}" '
                    '--max-time 60 http://%s:%d%s' % (SERVER, port, jalur))
        _, o, _ = self.c.exec_command(perintah)
        return o.read().decode(errors="replace").strip()

    def tutup(self):
        if self.c:
            self.c.close()


def http_lokal(port, jalur):
    import urllib.request
    alamat = "http://%s:%d%s" % (SERVER, port, jalur)
    try:
        with urllib.request.urlopen(alamat, timeout=60) as r:
            n = len(r.read())
            return "%s %d" % (r.status, n)
    except urllib.error.HTTPError as e:
        # 404s and similar are not script failures: the access log entry is the goal.
        n = len(e.read())
        return "%s %d" % (e.code, n)
    except Exception as e:
        return "gagal (%s)" % e


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--menit", type=float, default=15.0,
                   help="lama sebaran kejadian, dalam menit (bawaan 15)")
    p.add_argument("--sekaligus", action="store_true",
                   help="tanpa jeda; semua kejadian ditembak berurutan")
    p.add_argument("--tanpa-http", action="store_true",
                   help="SFTP saja")
    p.add_argument("--tanpa-sftp", action="store_true",
                   help="HTTP saja")
    a = p.parse_args()

    try:
        import paramiko  # noqa: F401
    except ImportError:
        print("BERHENTI: paramiko belum terpasang.")
        print("Jalankan dengan python dari venv: backend\\venv\\Scripts\\python.exe")
        raise SystemExit(1)

    sandi = sandi_semua()
    kejadian = susun_kejadian(sandi)
    if a.tanpa_http:
        kejadian = [k for k in kejadian if k[0] != "http"]
    if a.tanpa_sftp:
        kejadian = [k for k in kejadian if not k[0].startswith("sftp")]
    if not kejadian:
        print("Tidak ada yang dikerjakan.")
        return

    jeda_rata = 0.0 if a.sekaligus else (a.menit * 60.0) / len(kejadian)
    print("%d kejadian, disebar %s." % (
        len(kejadian),
        "tanpa jeda" if a.sekaligus else "selama sekitar %.0f menit" % a.menit))
    print()

    kedua = None if a.tanpa_http else PenembakKedua()
    berhasil = 0
    giliran_kedua = False

    for i, k in enumerate(kejadian, 1):
        if k[0] == "sftp-ambil":
            if sftp_ambil(sandi, k[1], k[2]):
                berhasil += 1
        elif k[0] == "sftp-kirim":
            if sftp_kirim(sandi, k[1], k[2]):
                berhasil += 1
        else:
            port, jalur = k[1], k[2]
            pakai_kedua = kedua and kedua.hidup() and giliran_kedua
            giliran_kedua = not giliran_kedua
            if pakai_kedua:
                hasil = kedua.ambil(port, jalur)
                dari = PENEMBAK_KEDUA[0]
            else:
                hasil = http_lokal(port, jalur)
                dari = "laptop"
            print("  %-14s HTTP   :%-5d %-28s %s" % (dari, port, jalur, hasil))
            berhasil += 1

        if jeda_rata and i < len(kejadian):
            # Randomized delay around the mean; perfectly regular intervals look scripted.
            time.sleep(max(0.5, random.uniform(0.35, 1.65) * jeda_rata))

    if kedua:
        kedua.tutup()

    print()
    print("%d dari %d kejadian berhasil." % (berhasil, len(kejadian)))
    print("Tunggu satu putaran poller (maks 60 detik), lalu buka halaman")
    print("Lalu Lintas — tab 'Berkas diambil' dan 'Siapa mengambil berkas apa'.")


if __name__ == "__main__":
    sys.exit(main())

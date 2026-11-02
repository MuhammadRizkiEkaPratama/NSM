"""Configure GNS3 access on nsm-app (through an SSH tunnel), then enable the
GNS3 remediator.

Background: the nsm-app poller detects a dead R1 and the gate allows recovery
(`poller_pemulih_gns3`), but the action always failed because the code
assumed it runs on the machine hosting GNS3. `DASAR` was hard-coded to
`http://127.0.0.1:3080/v2` (on nsm-app that points at nsm-app itself) and
credentials were read from a Windows `%APPDATA%` path that does not exist on
Linux. Both are now set through `.env` (`GNS3_URL`, `GNS3_USER`,
`GNS3_PASSWORD`).

Why an SSH tunnel instead of binding GNS3 to 0.0.0.0: GNS3's own security
guidance rates remote access as weak (brute-forceable, emulator consoles
exposed to anyone who can reach the server) and recommends a VPN or SSH
tunnel. This uses a reverse tunnel opened FROM the laptop:

    ssh -fN -R 3080:127.0.0.1:3080 nsmapp@192.168.56.156

GNS3 stays bound to 127.0.0.1 on the laptop (no new listening port),
`127.0.0.1:3080` on nsm-app reaches the controller so `GNS3_URL` needs no
special case, and the traffic is encrypted and authenticated by SSH.

Limit: the tunnel does not persist. It dies when the laptop sleeps, restarts,
or the SSH session drops. That is acceptable because GNS3 only matters while
the lab is up. What must not happen is NSM believing it can recover GNS3 over
a dead tunnel, so this script verifies the path end to end from nsm-app
BEFORE enabling the remediator and refuses to enable it otherwise.

Run: venv\\Scripts\\python.exe atur_gns3_nsmapp.py
"""
import subprocess
import sys

import paramiko

# The password is read from `.env` (untracked by Git), never written here.
import config
HOST, USER = "192.168.56.156", "nsmapp"
SANDI = config.get_nsmapp_sandi()
ENV = "/home/nsmapp/NSM/backend/.env"
AKAR = "/home/nsmapp/NSM/backend"
KUNCI = r"C:\Users\<user>\.ssh\nsm_laptop"


def buka_terowongan():
    """Make sure the reverse tunnel is up. Safe to re-run: if port 3080 on nsm-app
    is already taken, ssh fails fast (`ExitOnForwardFailure`), which means the
    tunnel already exists.
    """
    p = subprocess.run(
        ["ssh", "-i", KUNCI, "-o", "BatchMode=yes",
         "-o", "StrictHostKeyChecking=no", "-o", "ExitOnForwardFailure=yes",
         "-fN", "-R", "3080:127.0.0.1:3080", "%s@%s" % (USER, HOST)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
    if p.returncode == 0:
        print("  terowongan dibuka")
    else:
        print("  ssh keluar %d (kemungkinan terowongan sudah ada): %s"
              % (p.returncode, (p.stderr or "").strip()[:120]))


def main():
    from connectors import gns3_pemulihan as g
    try:
        u, s = g._kredensial()
    except Exception as e:
        print("Kredensial GNS3 tidak terbaca di laptop:", e)
        return 1
    print("kredensial GNS3 di laptop: user=%r sandi=%s"
          % (u, "(terisi)" if s else "(kosong)"))

    print("\n1. pastikan terowongan hidup")
    buka_terowongan()

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=SANDI, timeout=20)

    def jalan(cmd, t=90):
        i, o, e = c.exec_command(cmd, timeout=t)
        return o.read().decode(errors="replace"), e.read().decode(errors="replace")

    try:
        print("\n2. tulis setelan GNS3 ke .env nsm-app (kalau belum ada)")
        # Idempotent by checking file contents, not grep's exit code (a
        # `grep -c ... || echo 0` check gave a false positive and skipped installing the
        # SSH key).
        content, _ = jalan("cat %s" % ENV)
        add = []
        if "GNS3_URL=" not in content:
            add.append("GNS3_URL=http://127.0.0.1:3080")
        if "GNS3_USER=" not in content:
            add.append("GNS3_USER=%s" % u)
        if "GNS3_PASSWORD=" not in content:
            add.append("GNS3_PASSWORD=%s" % s)
        if add:
            sftp = c.open_sftp()
            with sftp.open(ENV, "a") as f:
                f.write("\n# --- GNS3 lewat terowongan SSH dari laptop "
                        "(22 Agustus 2026) ---\n")
                f.write("\n".join(add) + "\n")
            sftp.close()
            print("  ditambahkan:", [t.split("=")[0] for t in add])
        else:
            print("  semua kunci GNS3 sudah ada")

        print("\n3. BUKTIKAN nsm-app benar-benar bisa memanggil controller")
        out, err = jalan(
            "cd %s && ./venv/bin/python -c \""
            "from connectors import gns3_pemulihan as g;"
            "print('dasar=%%s' %% g._dasar());"
            "print('versi=%%s' %% g.panggil('GET','/version'))\"" % AKAR)
        print("  " + (out.strip() or err.strip()[:300]))
        if "versi=" not in out:
            print("\n  GAGAL menjangkau controller dari nsm-app.")
            print("  Pemulih GNS3 TIDAK dinyalakan -- menyalakannya sekarang")
            print("  hanya akan mengulang kegagalan yang sudah diketahui.")
            return 1

        print("\n4. nyalakan pemulih GNS3 dan restart layanan")
        jalan("sed -i 's/^PEMULIH_GNS3_AKTIF=0/PEMULIH_GNS3_AKTIF=1/' %s" % ENV)
        out, _ = jalan("echo %s | sudo -S -p '' systemctl restart "
                       "nsm-poller nsm-api && echo RESTARTED" % SANDI)
        print("  " + out.strip())

        out, err = jalan(
            "cd %s && ./venv/bin/python -c \"import config as k;"
            "print('gns3     =', k.get_pemulih_gns3_aktif());"
            "print('layanan  =', k.get_pemulih_layanan_aktif());"
            "print('interface=', k.get_pemulih_interface_aktif());"
            "print('konfig   =', k.get_pemulih_konfig_aktif())\"" % AKAR)
        print("\n--- keadaan efektif ---")
        print(out or err[:300])
        return 0
    finally:
        c.close()


if __name__ == "__main__":
    sys.exit(main())

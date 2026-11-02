"""Keep the SSH reverse tunnel from the laptop to nsm-app for the GNS3 API alive.

Why a tunnel: GNS3's own docs rate remote access security as low (brute
force, exposed emulator consoles) and recommend a VPN or SSH tunnel rather
than exposing the controller.

    ssh -N -R 3080:127.0.0.1:3080 <user>@<nsm-app-host>

GNS3 stays bound to `127.0.0.1`, nsm-app uses `GNS3_URL=http://127.0.0.1:3080`
unchanged, and traffic is encrypted and authenticated by SSH.

Two requirements learned from testing under Task Scheduler:
1. Call `ssh.exe` by absolute path. Task Scheduler's PATH differs from a
   normal shell, and a missing `ssh` must not skip the code that disables
   the GNS3 recovery task. All failure paths are wrapped so disabling always runs.
2. Do not use `ssh -f`. Task Scheduler kills the task's whole process tree
   when the main process exits, so a detached ssh dies with it. This script
   runs `ssh -N` as a child and stays alive (guard mode); Task Scheduler is the
   supervisor (single instance, `IgnoreNew`, periodic), restarting a dead tunnel.

Modes:
    (default)   check; if down, open the tunnel and guard it (blocks)
    --periksa   check only, change nothing
    --sekali    check and open, but do not block (for testing)
"""
import os
import subprocess
import sys
import time

import paramiko

# The password is not written here; it is read from `.env`, which Git does not
# track. Git history is permanent, so a committed secret cannot be taken back.
import config
HOST, USER = "192.168.56.156", "nsmapp"
SANDI = config.get_nsmapp_sandi()
KUNCI = r"C:\Users\<user>\.ssh\nsm_laptop"
ENV = "/home/nsmapp/NSM/backend/.env"

# Absolute path, not plain "ssh" (see note 1 in the module docstring).
SSH_KANDIDAT = [
    r"C:\Windows\System32\OpenSSH\ssh.exe",
    r"C:\Program Files\Git\usr\bin\ssh.exe",
]


def jalur_ssh():
    for j in SSH_KANDIDAT:
        if os.path.exists(j):
            return j
    return None


def _ssh_nsmapp():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=SANDI, timeout=20)
    return c


def terowongan_hidup(c):
    """True if nsm-app can really talk to the controller.

    Tested by calling the API, not just probing the port: an accepted TCP
    connection may not be serving. 401 counts as alive (the request reached the
    controller, which asked for authentication).
    """
    i, o, e = c.exec_command(
        "curl -s -o /dev/null -w '%{http_code}' --max-time 6 "
        "http://127.0.0.1:3080/v2/version", timeout=30)
    code = o.read().decode(errors="replace").strip()
    return code in ("200", "401"), code


def set_pemulih_gns3(c, nyala):
    old, baru = ("0", "1") if nyala else ("1", "0")
    i, o, e = c.exec_command(
        "sed -i 's/^PEMULIH_GNS3_AKTIF=%s/PEMULIH_GNS3_AKTIF=%s/' %s && "
        "grep ^PEMULIH_GNS3_AKTIF %s" % (old, baru, ENV, ENV), timeout=40)
    hasil = o.read().decode(errors="replace").strip()
    i2, o2, e2 = c.exec_command(
        "echo %s | sudo -S -p '' systemctl restart nsm-poller && echo OK"
        % SANDI, timeout=60)
    return "%s (%s)" % (hasil, o2.read().decode(errors="replace").strip())


def main(mode):
    ssh = jalur_ssh()
    c = _ssh_nsmapp()
    child = None
    try:
        alive, code = terowongan_hidup(c)
        print("terowongan -> controller GNS3 dari nsm-app: %s (HTTP %s)"
              % ("HIDUP" if alive else "MATI", code))
        if alive:
            if mode == "jaga":
                # Another instance already holds the tunnel; exit quietly so two supervisors
                # do not clash.
                print("sudah dipegang instance lain -- keluar")
            return 0
        if mode == "periksa":
            print("(--periksa: tidak mengubah apa pun)")
            return 1

        if not ssh:
            raise FileNotFoundError(
                "ssh.exe tidak ditemukan di: %s" % ", ".join(SSH_KANDIDAT))

        print("membuka terowongan: %s" % ssh)
        perintah = [ssh, "-i", KUNCI,
                    "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                    "-o", "ExitOnForwardFailure=yes",
                    "-o", "ServerAliveInterval=30",
                    "-o", "ServerAliveCountMax=3",
                    "-N", "-R", "3080:127.0.0.1:3080",
                    "%s@%s" % (USER, HOST)]
        child = subprocess.Popen(perintah, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE)
        time.sleep(6)
        alive, code = terowongan_hidup(c)
        print("  sesudah dibuka: %s (HTTP %s)"
              % ("HIDUP" if alive else "MASIH MATI", code))

        if not alive:
            error = ""
            if child.poll() is not None:
                error = (child.stderr.read() or b"").decode(errors="replace")[:200]
            print("  ssh keluar/gagal: %s" % (error or "(tanpa pesan)"))
            raise RuntimeError("terowongan tidak bisa dihidupkan")

        print("  memastikan pemulih GNS3 menyala kembali")
        print("  ", set_pemulih_gns3(c, True))

        if mode == "sekali":
            return 0

        # Guard mode: stay alive alongside ssh. `-f` is avoided because Task Scheduler
        # kills the task's process tree, taking a detached ssh with it.
        print("  menjaga terowongan (tekan Ctrl+C untuk berhenti)...")
        child.wait()
        print("  ssh berhenti dengan kode %s" % child.returncode)
        return 1

    except Exception as e:
        print("GAGAL: %s: %s" % (type(e).__name__, str(e)[:200]))
        # Disabling must always run, whatever failed above.
        try:
            print("MEMATIKAN PEMULIH GNS3 di nsm-app: lebih baik sengaja mati")
            print("dan terlihat mati, daripada menyala sambil selalu gagal.")
            print(" ", set_pemulih_gns3(c, False))
        except Exception as e2:
            print(" [PERINGATAN] penonaktifan juga gagal: %s" % str(e2)[:150])
        return 1
    finally:
        if child is not None and child.poll() is None and mode == "sekali":
            pass  # left running on purpose in --sekali mode
        c.close()


if __name__ == "__main__":
    m = "jaga"
    if "--periksa" in sys.argv:
        m = "periksa"
    elif "--sekali" in sys.argv:
        m = "sekali"
    sys.exit(main(m))

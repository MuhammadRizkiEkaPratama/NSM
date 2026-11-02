"""Test of the auditd command-history parser (`connectors/perintahlog.py`).

The sample lines are copied verbatim from /var/log/audit/audit.log on the file
server during a real test (an actual SSH login as `dewi` running `ls -la
/srv/sharing` and `whoami`).
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from connectors import perintahlog

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
    benar(nama, dapat == harap, "-> dapat %r, harap %r" % (dapat, harap))


SYSCALL_DEWI = (
    'type=SYSCALL msg=audit(1787127164.487:446): arch=c000003e syscall=59 '
    'success=yes exit=0 a0=5dd309967d60 a1=5dd309967e50 a2=5dd309966d50 '
    'a3=5dd309967f00 items=2 ppid=100364 pid=100365 auid=10003 uid=10003 '
    'gid=20004 euid=10003 suid=10003 fsuid=10003 egid=20004 sgid=20004 '
    'fsgid=20004 tty=(none) ses=2196 comm="ls" exe="/usr/bin/ls" '
    'subj=unconfined key="perintah_pengguna"ARCH=x86_64 SYSCALL=execve '
    'AUID="dewi" UID="dewi" GID="ecanteen" EUID="dewi" SUID="dewi" '
    'FSUID="dewi" EGID="ecanteen" SGID="ecanteen" FSGID="ecanteen"')
EXECVE_DEWI = ('type=EXECVE msg=audit(1787127164.487:446): argc=3 a0="ls" '
               'a1="-la" a2="/srv/sharing"')

USER_START_DEWI = (
    'type=USER_START msg=audit(1787127164.000:440): pid=100294 uid=0 '
    'auid=10003 ses=2196 subj=unconfined msg=\'op=PAM:session_open '
    'grantors=pam_unix,pam_sss acct="dewi" exe="/usr/sbin/sshd" '
    'hostname=192.168.56.1 addr=192.168.56.1 terminal=ssh res=success\'')

# A local admin (UID 1000) running `sudo tail -20 ...` is caught by the same rule.
SYSCALL_ADMIN = (
    'type=SYSCALL msg=audit(1787127201.042:700): arch=c000003e syscall=59 '
    'success=yes exit=0 a0=5fc4ffa30ae8 a1=5fc4ffa40040 a2=5fc4ffa551d0 '
    'a3=64 items=2 ppid=100663 pid=100664 auid=1000 uid=0 gid=0 euid=0 '
    'suid=0 fsuid=0 egid=0 sgid=0 fsgid=0 tty=(none) ses=2203 comm="tail" '
    'exe="/usr/bin/tail" subj=unconfined key="perintah_pengguna"'
    'ARCH=x86_64 SYSCALL=execve AUID="labadmin" UID="root" GID="root" '
    'EUID="root" SUID="root" FSUID="root" EGID="root" SGID="root" '
    'FSGID="root"')
EXECVE_ADMIN = ('type=EXECVE msg=audit(1787127201.042:700): argc=3 '
                 'a0="tail" a1="-20" a2="/var/log/audit/audit.log"')

# A systemd child triggered by the login session, not typed by anyone (comm="9").
SYSCALL_SISTEM = (
    'type=SYSCALL msg=audit(1787127174.710:450): arch=c000003e syscall=59 '
    'success=yes exit=0 a0=7ffefe647930 a1=7ffefe647950 a2=7ffefe6482c0 '
    'a3=8 items=2 ppid=100298 pid=100366 auid=10003 uid=10003 gid=20004 '
    'euid=10003 suid=10003 fsuid=10003 egid=20004 sgid=20004 fsgid=20004 '
    'tty=(none) ses=2197 comm="9" exe="/usr/lib/systemd/systemd-executor" '
    'subj=unconfined key="perintah_pengguna"ARCH=x86_64 SYSCALL=execve '
    'AUID="dewi" UID="dewi" GID="ecanteen" EUID="dewi" SUID="dewi" '
    'FSUID="dewi" EGID="ecanteen" SGID="ecanteen" FSGID="ecanteen"')

print("=" * 74)
print("UJI PENGURAI RIWAYAT COMMAND (connectors/perintahlog.py)")
print("=" * 74)

# ---------------------------------------------------------------------------
print("\n1. Baris SYSCALL dewi terurai -- termasuk AUID sudah nama, bukan angka")

sc = perintahlog.urai_baris_syscall(SYSCALL_DEWI)
benar("baris terurai (bukan None)", sc is not None)
if sc:
    sama("pengguna dari AUID (nama, bukan '10003')", sc["pengguna"], "dewi")
    sama("nama perintah", sc["perintah"], "ls")
    sama("nomor sesi", sc["sesi"], "2196")
    sama("berhasil", sc["berhasil"], True)
    benar("waktu terurai", isinstance(sc["waktu"], datetime))

# ---------------------------------------------------------------------------
print("\n2. Baris EXECVE tergabung dengan SYSCALL lewat id kejadian yang sama")

ev = perintahlog.urai_baris_execve(EXECVE_DEWI)
benar("EXECVE terurai", ev is not None)
if ev and sc:
    sama("id kejadian SAMA dengan SYSCALL", ev[0], sc["id"])
    sama("argumen lengkap tergabung", ev[1], "ls -la /srv/sharing")

# ---------------------------------------------------------------------------
print("\n3. gabung() penuh: SYSCALL+EXECVE+USER_START -> satu kejadian dengan IP")

kejadian, disaring = perintahlog.gabung(
    [USER_START_DEWI, SYSCALL_DEWI, EXECVE_DEWI])
sama("satu kejadian dihasilkan", len(kejadian), 1)
if kejadian:
    k = kejadian[0]
    sama("pengguna", k["pengguna"], "dewi")
    sama("perintah lengkap", k["argumen"], "ls -la /srv/sharing")
    sama("IP dikaitkan lewat nomor sesi", k["ip_klien"], "192.168.56.1")

# ---------------------------------------------------------------------------
print("\n4. Admin lokal (UID 1000) tertangkap aturan yang SAMA persis")

kejadian2, _ = perintahlog.gabung([SYSCALL_ADMIN, EXECVE_ADMIN])
sama("admin lokal tercatat", len(kejadian2), 1)
if kejadian2:
    sama("nama admin dari AUID", kejadian2[0]["pengguna"], "labadmin")
    sama("perintah admin", kejadian2[0]["argumen"], "tail -20 /var/log/audit/audit.log")

# ---------------------------------------------------------------------------
print("\n5. Turunan systemd (comm='9') DISARING, bukan dicatat sebagai perintah")

benar("comm='9' ditolak urai_baris_syscall",
      perintahlog.urai_baris_syscall(SYSCALL_SISTEM) is None)

# ---------------------------------------------------------------------------
print("\n6. SYSCALL tanpa EXECVE pasangannya (terpotong batas baca) DIBUANG")
print("   (bukan disimpan setengah -- ini kelas bug yang sama dengan MAKS_BACA)")

kejadian3, disaring3 = perintahlog.gabung([SYSCALL_DEWI])   # EXECVE-nya HILANG
sama("tidak ada kejadian yang tercatat", len(kejadian3), 0)
benar("terhitung sebagai disaring, bukan diam-diam hilang", disaring3 >= 1)

# ---------------------------------------------------------------------------
print("\n7. Baris asing / bukan yang dicari dilewati dengan aman")

benar("baris kosong -> None", perintahlog.urai_baris_syscall("") is None)
benar("SYSCALL dengan key lain -> None",
      perintahlog.urai_baris_syscall(
          'type=SYSCALL msg=audit(1.0:1): key="lain"') is None)
benar("baris CWD (bukan SYSCALL/EXECVE) -> keduanya None",
      perintahlog.urai_baris_syscall('type=CWD msg=audit(1.0:1): cwd="/"') is None
      and perintahlog.urai_baris_execve('type=CWD msg=audit(1.0:1): cwd="/"') is None)

# ---------------------------------------------------------------------------
print("\n8. AUID hilang (nyata di bawah beban tinggi) -> peta cadangan dipakai")
print("   (ditemukan langsung di server 19 Agustus 2026, bukan dugaan)")

SYSCALL_TANPA_AUID = (
    'type=SYSCALL msg=audit(1787127164.487:9001): arch=c000003e syscall=59 '
    'success=yes exit=0 a0=1 a1=1 a2=1 a3=1 items=2 ppid=1 pid=2 auid=10003 '
    'uid=10003 gid=20004 euid=10003 suid=10003 fsuid=10003 egid=20004 '
    'sgid=20004 fsgid=20004 tty=(none) ses=2196 comm="ls" exe="/usr/bin/ls" '
    'subj=unconfined key="perintah_pengguna"')

sc_cadangan = perintahlog.urai_baris_syscall(SYSCALL_TANPA_AUID)
sama("nama tetap terisi dari peta cadangan", sc_cadangan and sc_cadangan["pengguna"], "dewi")

print("\n8b. UID yang TIDAK dikenal peta cadangan -> angka mentah, BUKAN ditebak")
SYSCALL_UID_ASING = SYSCALL_TANPA_AUID.replace("auid=10003", "auid=55555")
sc_asing = perintahlog.urai_baris_syscall(SYSCALL_UID_ASING)
sama("UID asing tetap angka, tidak dipaksa jadi nama",
     sc_asing and sc_asing["pengguna"], "55555")

# ---------------------------------------------------------------------------
print("\n9. Turunan skrip MOTD disaring lewat ppid, BUKAN lewat nama perintah")
print("   ('grep' yang lahir dari MOTD hilang; 'grep' yang BERDIRI SENDIRI tetap ada)")


def P(epoch, id_, pid, ppid, ses, comm, auid="10003", auid_nama="dewi"):
    return (
        'type=SYSCALL msg=audit(%s:%s): success=yes auid=%s ses=%s pid=%s '
        'ppid=%s comm="%s" exe="/usr/bin/%s" key="perintah_pengguna"'
        'AUID="%s"' % (epoch, id_, auid, ses, pid, ppid, comm, comm, auid_nama))


def E(epoch, id_, *argv):
    section = " ".join('a%d="%s"' % (i, a) for i, a in enumerate(argv))
    return 'type=EXECVE msg=audit(%s:%s): argc=%d %s' % (
        epoch, id_, len(argv), section)


BARIS_POHON = [
    # Akar: sh menjalankan run-parts /etc/update-motd.d (pid 100, induk sesi)
    P("1.0", "1", "100", "1", "9000", "sh"),
    E("1.0", "1", "sh", "-c", "run-parts --lsbsysinit /etc/update-motd.d"),
    # Direct child of the root (pid 101, ppid 100) is named "grep" but comes from the
    # MOTD tree, so it must be filtered.
    P("1.1", "2", "101", "100", "9000", "grep"),
    E("1.1", "2", "grep", "-q", "-m", "1", "."),
    P("1.2", "3", "102", "101", "9000", "date"),
    E("1.2", "3", "date", "+%s"),
    # A REAL command with no ppid link to the tree above (ppid=9000, own interactive
    # shell) MUST remain.
    P("1.3", "4", "200", "9000", "9000", "grep"),
    E("1.3", "4", "grep", "rahasia", "laporan.txt"),
]

kejadian9, disaring9 = perintahlog.gabung(BARIS_POHON)
sama("hanya 1 kejadian tersisa (punya dewi sungguhan)", len(kejadian9), 1)
if kejadian9:
    sama("yang tersisa perintah grep BERDIRI SENDIRI",
         kejadian9[0]["argumen"], "grep rahasia laporan.txt")
benar("3 turunan MOTD (akar+anak+cucu) ikut disaring", disaring9 >= 3,
      "-> disaring %d" % disaring9)

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

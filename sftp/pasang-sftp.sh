#!/bin/bash
# Install the SFTP file server on .103. Run once, with sudo, on .103:
#
#     sudo bash pasang-sftp.sh
#
# Idempotent. Prerequisite: group `berkas` exists in LDAP on .101; the script stops if it does not, since folders created with the wrong owner are hard to find.
#
# SFTP instead of FTP: it runs inside the existing SSH (one port, encrypted, LDAP identities), with no new daemon, port, or second password list.

set -e

BASIS=/srv/berkas
ORANG="dewi bagas intan arif"

echo "== 0/6 Memeriksa prasyarat =="
# Clear the sssd cache first so a group just added on .101 is visible here.
sss_cache -E 2>/dev/null || true
if ! getent group berkas >/dev/null; then
    echo "   BERHENTI: grup 'berkas' tidak terlihat dari mesin ini."
    echo "   Tambahkan dulu di .101:  ldapadd -x -D cn=admin,dc=bsp,dc=id -W -f berkas.ldif"
    exit 1
fi
echo "   grup berkas: $(getent group berkas)"

echo "== 1/6 Membuat struktur folder =="
# ChrootDirectory must be root-owned and not group/other writable, otherwise sshd rejects the session with "bad ownership or modes" (logged on the server only).
install -d -o root -g root -m 755 "$BASIS"
install -d -o root -g root -m 755 "$BASIS/home"

# The chroot's /dev must be writable by `syslog`: rsyslog drops root privileges before opening its sockets, otherwise it fails with "cannot create '/srv/berkas/dev/log': Permission denied". Safe to relax: the root-ownership rule applies only to the chroot folder itself and its parents.
install -d -o root -g syslog -m 775 "$BASIS/dev"

# publik = read-only, unggah = writable, so fetching and uploading can be told apart by path alone.
install -d -o root -g berkas -m 750 "$BASIS/publik"
install -d -o root -g berkas -m 770 "$BASIS/unggah"

for u in $ORANG; do
    # Inside the chroot this appears as /home/<name>, matching homeDirectory in LDAP; without it sshd cannot enter the home and the session drops after login.
    install -d -o "$u" -g berkas -m 700 "$BASIS/home/$u"
done
echo "   $(ls -1 $BASIS | tr '\n' ' ')"

echo "== 2/6 Mengisi berkas contoh =="
# Random content, not zeros: zero-filled files compress heavily in transit, so the volumes shown in NSM would not be realistic.
buat() {
    if [ ! -f "$BASIS/publik/$1" ]; then
        head -c "$2" /dev/urandom > "$BASIS/publik/$1"
        echo "   dibuat: $1 ($2)"
    fi
}
buat "laporan-keuangan-q2.pdf"   2M
buat "daftar-inventaris.xlsx"    512K
buat "panduan-jaringan.pdf"      5M
buat "rekaman-cctv-lobi.zip"     40M
chown root:berkas "$BASIS"/publik/*
chmod 640 "$BASIS"/publik/*

echo "== 3/6 Menyetel sshd =="
cp -n /etc/ssh/sshd_config /etc/ssh/sshd_config.bak-sftp 2>/dev/null || true

# The sftp subsystem must switch to internal-sftp: the default /usr/lib/openssh/sftp-server lies outside the chroot and every connection would drop. The old line is commented out, not deleted, because sshd refuses to start if `Subsystem sftp` is defined twice.
sed -i 's|^Subsystem\s*sftp\s*/usr/lib/openssh/sftp-server|#&   # digantikan 60-sftp.conf|' \
    /etc/ssh/sshd_config

cat > /etc/ssh/sshd_config.d/60-sftp.conf <<'EOF'
# SFTP file server, installed by NSM/sftp/pasang-sftp.sh.
#
# -l INFO logs every file open, close, delete and rename with byte counts; without it only logins are recorded. -f AUTH sends the log to /var/log/auth.log, which the NSM monitoring account (nsmro, group adm) can already read.
Subsystem sftp internal-sftp -f AUTH -l INFO

Match Group berkas
    ChrootDirectory /srv/berkas
    # ForceCommand is set even though their shell is nologin: relying on the shell alone is too thin, since a loginShell change in the directory would open an SSH shell.
    ForceCommand internal-sftp -f AUTH -l INFO
    AllowTcpForwarding no
    X11Forwarding no
    PermitTTY no
EOF

# Test before restarting: a bad sshd config does not drop running sessions but makes every later login fail, including NSM's. Recovery would need the VirtualBox console.
if ! sshd -t; then
    echo "   BERHENTI: konfigurasi sshd tidak sah. Layanan TIDAK disentuh."
    echo "   Kembalikan dengan: cp /etc/ssh/sshd_config.bak-sftp /etc/ssh/sshd_config"
    exit 1
fi
systemctl restart ssh
echo "   sshd disetel ulang, konfigurasi lolos uji"

echo "== 4/6 Menyalakan pencatatan di dalam chroot =="
# internal-sftp logs through the /dev/log socket. After chroot the system's /dev/log is out of reach and logging silently vanishes (sftp works, auth.log stays empty), so rsyslog is told to open a second socket inside the chroot.
#
# Filesystem permissions are not enough: the AppArmor profile `usr.sbin.rsyslogd` lists writable paths one by one and only anticipates `/var/lib/*/dev/log` and `/var/spool/postfix/dev/log`. /srv/berkas is not covered, so rsyslog gets a "Permission denied" that looks like a normal permission error even though `ls -l` is correct.
if ! grep -qs '/srv/berkas/dev/log' /etc/apparmor.d/local/usr.sbin.rsyslogd; then
    cat >> /etc/apparmor.d/local/usr.sbin.rsyslogd <<'EOF'

# Log socket for the SFTP chroot in /srv/berkas, modeled on the existing /var/lib/*/dev/log line.
/srv/berkas/dev/log rwl,
EOF
    apparmor_parser -r /etc/apparmor.d/usr.sbin.rsyslogd
    echo "   izin AppArmor ditambahkan"
fi

cat > /etc/rsyslog.d/49-sftp-chroot.conf <<'EOF'
# Extra log socket inside the SFTP chroot; without it internal-sftp cannot reach rsyslog and no transfer is logged.
input(type="imuxsock" Socket="/srv/berkas/dev/log" CreatePath="on")
EOF
systemctl restart rsyslog
sleep 1
if [ -S "$BASIS/dev/log" ]; then
    echo "   soket $BASIS/dev/log siap ($(stat -c '%U:%G %a' $BASIS/dev/log))"
else
    echo "   PERINGATAN: soket belum terbentuk — TIDAK ADA transfer yang akan tercatat."
    echo "   Sebabnya hampir selalu izin tulis. Lihat alasan aslinya dengan:"
    echo "     journalctl -u rsyslog -n 20 --no-pager | grep -i 'srv/berkas'"
fi

echo "== 5/6 Mengizinkan grup berkas login =="
# Done last on purpose: loosening sssd earlier would leave a window where these users may log in before the sftp-only rule in sshd applies.
if grep -q '^simple_allow_groups.*berkas' /etc/sssd/sssd.conf; then
    echo "   sudah ada, dilewati"
else
    cp -n /etc/sssd/sssd.conf /etc/sssd/sssd.conf.bak-sftp 2>/dev/null || true
    sed -i 's/^simple_allow_groups\s*=.*/simple_allow_groups = sysadmin, berkas/' \
        /etc/sssd/sssd.conf
    systemctl restart sssd
    sleep 2
    echo "   $(grep '^simple_allow_groups' /etc/sssd/sssd.conf)"
fi

echo "== 6/6 Keadaan akhir =="
echo "   sshd    : $(systemctl is-active ssh)"
echo "   sssd    : $(systemctl is-active sssd)"
echo "   rsyslog : $(systemctl is-active rsyslog)"
echo "   isi publik:"
ls -lh "$BASIS/publik" | tail -n +2 | sed 's/^/     /'
echo
echo "SELESAI. Uji dari laptop:  sftp dewi@192.168.56.103"

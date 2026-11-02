#!/bin/bash
# Install the restricted firewall-change path for NSM. Run with sudo on .101 and .103:
#
#     sudo bash pasang-ubah-firewall.sh
#
# Prerequisite: `nsm-ubah-firewall` has been copied to /tmp/ on this machine.
# What is granted is permission to run ONE file, which decides what may happen:
#     allowed  block one IPv4 address, for 1-1440 minutes
#     allowed  remove blocks it installed itself
#     allowed  list rules
#     NOT      disable the firewall
#     NOT      change default policy
#     NOT      delete existing allow rules
#     NOT      block the laptop, .101, .103 or localhost
# sudoers argument patterns cannot express any of these limits.

set -e

SUMBER=/tmp/nsm-ubah-firewall
TUJUAN=/usr/local/sbin/nsm-ubah-firewall
SUDOERS_TMP=/tmp/nsm-ubah-firewall.sudoers
SUDOERS=/etc/sudoers.d/nsm-ubah-firewall
AKUN=nsmro

echo "== 1/5 Memeriksa prasyarat =="
if [ ! -f "$SUMBER" ]; then
    echo "   BERHENTI: $SUMBER tidak ada. Salin dulu dengan scp."
    exit 1
fi
if ! id "$AKUN" >/dev/null 2>&1; then
    echo "   BERHENTI: akun $AKUN tidak ada."
    exit 1
fi
if [ ! -x /usr/sbin/ufw ]; then
    echo "   BERHENTI: /usr/sbin/ufw tidak ada."
    exit 1
fi
if ! bash -n "$SUMBER"; then
    echo "   BERHENTI: skripnya tidak sah menurut bash -n."
    exit 1
fi
echo "   berkas ada, sintaksnya sah, akun $AKUN ada"

echo "== 2/5 Memasang skrip =="
# 0755 owned by root: if $AKUN could write this file, sudo permission to run it would be permission to run anything.
install -o root -g root -m 0755 "$SUMBER" "$TUJUAN"
rm -f "$SUMBER"
echo "   $(ls -l $TUJUAN)"

echo "== 3/5 Menyusun aturan sudo =="
cat > "$SUDOERS_TMP" <<'EOF'
# NSM may run this ONE file, which holds the whole policy. Installed by NSM/firewall/pasang-ubah-firewall.sh.
# No argument pattern on purpose: rules like "this address must not be blocked" and "blocks need a time limit" cannot be enforced in sudoers.
nsmro ALL=(root) NOPASSWD: /usr/local/sbin/nsm-ubah-firewall
EOF

echo "== 4/5 Memeriksa keabsahannya SEBELUM dipasang =="
# One broken file in /etc/sudoers.d disables sudo on the machine for everyone. Checked in /tmp, moved only if valid.
if ! visudo -c -f "$SUDOERS_TMP"; then
    echo "   BERHENTI: berkas sudoers tidak sah. TIDAK ada yang dipasang."
    rm -f "$SUDOERS_TMP"
    exit 1
fi
install -o root -g root -m 0440 "$SUDOERS_TMP" "$SUDOERS"
rm -f "$SUDOERS_TMP"

echo "== 5/5 Membuktikan batasnya benar-benar berlaku =="
# Tested by trying what must be refused, not only what should succeed.
gagal=0

if sudo -n -u "$AKUN" sudo -n "$TUJUAN" blokir 192.168.56.1 5 >/dev/null 2>&1; then
    echo "   GAGAL: alamat laptop BISA diblokir. Ini harus ditolak."
    gagal=1
else
    echo "   memblokir 192.168.56.1 (laptop)  -> DITOLAK (benar)"
fi

if sudo -n -u "$AKUN" sudo -n "$TUJUAN" blokir 10.9.9.9 99999 >/dev/null 2>&1; then
    echo "   GAGAL: blokir 99999 menit diterima. Batas waktunya tidak berlaku."
    gagal=1
else
    echo "   blokir 99999 menit               -> DITOLAK (benar)"
fi

if sudo -n -u "$AKUN" sudo -n /usr/sbin/ufw disable >/dev/null 2>&1; then
    echo "   GAGAL: $AKUN bisa mematikan firewall."
    gagal=1
else
    echo "   ufw disable                      -> DITOLAK (benar)"
fi

if [ "$gagal" -ne 0 ]; then
    echo
    echo "BERHENTI: ada batas yang tidak berlaku. Periksa $TUJUAN dan $SUDOERS."
    exit 1
fi

echo
echo "Yang boleh dijalankan $AKUN tanpa sandi:"
sudo -n -l -U "$AKUN" 2>/dev/null | grep NOPASSWD | sed 's/^/   /'
echo
echo "SELESAI."

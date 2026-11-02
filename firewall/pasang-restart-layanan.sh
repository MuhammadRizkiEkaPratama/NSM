#!/bin/bash
# Install the restricted service-restart path for NSM. Run with sudo on servers that have restartable services:
#
#     sudo bash pasang-restart-layanan.sh
#
# Prerequisite: `nsm-restart-layanan` has been copied to /tmp/ on this machine.
# Same pattern as `pasang-ubah-firewall.sh`, including proving the limits by trying what must be refused.

set -e

SUMBER=/tmp/nsm-restart-layanan
TUJUAN=/usr/local/sbin/nsm-restart-layanan
SUDOERS_TMP=/tmp/nsm-restart-layanan.sudoers
SUDOERS=/etc/sudoers.d/nsm-restart-layanan
AKUN=nsmro

echo "== 1/5 Memeriksa prasyarat =="
if [ ! -f "$SUMBER" ]; then
    echo "   BERHENTI: $SUMBER tidak ada. Salin dulu dengan scp/sftp."
    exit 1
fi
if ! id "$AKUN" >/dev/null 2>&1; then
    echo "   BERHENTI: akun $AKUN tidak ada."
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
# NSM may run this ONE file, which holds the whole policy. Installed by NSM/firewall/pasang-restart-layanan.sh.
# No argument pattern on purpose: "which units may be restarted" cannot be enforced in sudoers. The allowlist is inside the script.
nsmro ALL=(root) NOPASSWD: /usr/local/sbin/nsm-restart-layanan
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
gagal=0

# What must be refused is tested one by one, not assumed.
if sudo -n -u "$AKUN" sudo -n "$TUJUAN" restart ssh >/dev/null 2>&1; then
    echo "   GAGAL: ssh BISA direstart. Ini harus ditolak -- itu jalur NSM sendiri."
    gagal=1
else
    echo "   restart ssh                      -> DITOLAK (benar)"
fi

if sudo -n -u "$AKUN" sudo -n "$TUJUAN" restart slapd >/dev/null 2>&1; then
    echo "   GAGAL: slapd BISA direstart. Ini harus ditolak."
    gagal=1
else
    echo "   restart slapd                    -> DITOLAK (benar)"
fi

if sudo -n -u "$AKUN" sudo -n "$TUJUAN" restart mysql >/dev/null 2>&1; then
    echo "   GAGAL: mysql BISA direstart. Ini harus ditolak."
    gagal=1
else
    echo "   restart mysql                    -> DITOLAK (benar)"
fi

if sudo -n -u "$AKUN" sudo -n "$TUJUAN" stop apache2 >/dev/null 2>&1; then
    echo "   GAGAL: aksi 'stop' diterima. Hanya restart/status yang boleh."
    gagal=1
else
    echo "   stop apache2 (aksi terlarang)    -> DITOLAK (benar)"
fi

if sudo -n -u "$AKUN" sudo -n "$TUJUAN" restart 'apache2;id' >/dev/null 2>&1; then
    echo "   GAGAL: nama unit dengan aksara aneh diterima."
    gagal=1
else
    echo "   restart 'apache2;id' (suntikan)  -> DITOLAK (benar)"
fi

if sudo -n -u "$AKUN" sudo -n /usr/bin/systemctl restart ssh >/dev/null 2>&1; then
    echo "   GAGAL: $AKUN bisa memanggil systemctl LANGSUNG, melewati skrip ini."
    gagal=1
else
    echo "   systemctl langsung               -> DITOLAK (benar)"
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

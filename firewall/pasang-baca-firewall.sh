#!/bin/bash
# Give the NSM monitoring account permission to READ firewall rules, nothing more. Run with sudo on .101 and .103:
#
#     sudo bash pasang-baca-firewall.sh
#
# Safe to re-run.
# `ufw status` and `nft list ruleset` need root, because the rule list shows which ports are open.
# The commands are written out with their arguments on purpose. `nsmro ALL=(root) NOPASSWD: /usr/sbin/ufw` would grant every ufw command, including `ufw disable` and `ufw reset`. sudo matches the whole command line, so `sudo ufw disable` stays refused.

set -e

SUMBER=/tmp/nsm-baca-firewall.sudoers
TUJUAN=/etc/sudoers.d/nsm-baca-firewall
AKUN=nsmro

echo "== 1/4 Memeriksa prasyarat =="
if ! id "$AKUN" >/dev/null 2>&1; then
    echo "   BERHENTI: akun $AKUN tidak ada di mesin ini."
    exit 1
fi
if [ ! -x /usr/sbin/ufw ]; then
    echo "   BERHENTI: /usr/sbin/ufw tidak ada."
    exit 1
fi
echo "   akun $AKUN ada, ufw terpasang"

echo "== 2/4 Menyusun aturan sudo =="
cat > "$SUMBER" <<'EOF'
# The NSM monitoring account may READ firewall rules, nothing more. Installed by NSM/firewall/pasang-baca-firewall.sh.
# Arguments are spelled out on purpose; without them this line would grant all ufw commands, including `disable` and `reset`. Allowing NSM to change rules later would be a separate line and a separate decision.
nsmro ALL=(root) NOPASSWD: /usr/sbin/ufw status verbose
nsmro ALL=(root) NOPASSWD: /usr/sbin/ufw status numbered
EOF

echo "== 3/4 Memeriksa keabsahannya SEBELUM dipasang =="
# Do not skip this step. One broken file in /etc/sudoers.d breaks all of sudo on the machine for everyone, and recovery is through the VirtualBox console. So the file is built in /tmp, checked there, and moved into place only if valid.
if ! visudo -c -f "$SUMBER"; then
    echo "   BERHENTI: berkasnya tidak sah. TIDAK ada yang dipasang."
    rm -f "$SUMBER"
    exit 1
fi

echo "== 4/4 Memasang =="
# 0440 owned by root: sudo silently ignores sudoers files that others can write.
install -o root -g root -m 0440 "$SUMBER" "$TUJUAN"
rm -f "$SUMBER"

echo
echo "Yang boleh dijalankan $AKUN tanpa sandi sekarang:"
sudo -n -l -U "$AKUN" 2>/dev/null | sed 's/^/   /'
echo
echo "Uji cepat bahwa yang BERBAHAYA tetap ditolak:"
if sudo -n -l -U "$AKUN" 2>/dev/null | grep -q 'ufw disable'; then
    echo "   GAGAL: 'ufw disable' ikut terizinkan. Periksa $TUJUAN."
    exit 1
fi
echo "   ufw disable  -> TIDAK terizinkan (benar)"
echo
echo "SELESAI."

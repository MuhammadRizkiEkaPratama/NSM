#!/bin/bash
# Enable ufw on a lab VM, WITH A SAFETY NET. Run with sudo on .101 or .103:
#
#     sudo bash nyalakan-firewall.sh
#
# This is the riskiest action in the program: these machines are reachable only over the network, and a wrong SSH rule leaves them unreachable (recovery is through the VirtualBox console).
# Before enabling ufw, this script installs a timer that disables it again after 10 minutes. The timer is removed only after it has been proven that we can still log in; the script deliberately does not remove it itself.
# Same pattern as `reload in 10` when pushing config to Cisco routers.

set -e

SUBNET=192.168.56.0/24
UNIT=ufw-jaring-pengaman

# Safety net duration in minutes, optionally as an argument:
#
#     sudo bash nyalakan-firewall.sh 20
#
# Default 10. A window that is too narrow makes people rush, which is the last thing wanted when enabling a firewall on a network-only machine.
MENIT=${1:-10}
case "$MENIT" in
    ''|*[!0-9]*) echo "BERHENTI: lama jaring harus angka menit, dapat '$MENIT'."; exit 1 ;;
esac
if [ "$MENIT" -lt 2 ] || [ "$MENIT" -gt 60 ]; then
    echo "BERHENTI: lama jaring di luar batas wajar (2-60 menit), dapat $MENIT."
    exit 1
fi

IP=$(ip -4 -o addr show | awk '{print $4}' | cut -d/ -f1 | grep '^192\.168\.56\.' | head -1)

echo "== 0/5 Mengenali mesin ini =="
case "$IP" in
    192.168.56.101)
        NAMA="nsm-ubuntu (.101)"
        # 22   SSH   used by NSM (key nsmro) and the administrator
        # 389  LDAP  used by NSM login, E-Canteen login, and sssd on .103
        # 3306 MySQL used by E-Canteen on .103 and NSM service checks
        PORT="22 389 3306"
        ;;
    192.168.56.103)
        NAMA="testUbuntu (.103)"
        # 22   SSH   used by NSM, the administrator, and the SFTP file server
        # 80   Apache
        # 8080 E-Canteen (including phone access via port forwarding on the laptop, which arrives from 192.168.56.1)
        PORT="22 80 8080"
        ;;
    *)
        echo "   BERHENTI: mesin ini bukan .101 atau .103 (alamat: ${IP:-tidak ada})."
        echo "   Daftar port yang boleh dibuka ditulis per mesin dengan sengaja."
        exit 1
        ;;
esac
echo "   $NAMA, port yang akan diizinkan: $PORT"
echo "   sumber yang diizinkan: $SUBNET"

echo "== 1/5 Memasang jaring pengaman ($MENIT menit) =="
# systemd-run, not `sleep ... &`: background processes from an SSH session die when it closes, which is exactly what happens if the firewall is wrong. A systemd timer lives outside the session.
systemctl stop "$UNIT.timer" 2>/dev/null || true
systemd-run --on-active="${MENIT}min" --unit="$UNIT" \
    /usr/sbin/ufw --force disable >/dev/null

# Verify the timer is installed rather than assuming; enabling the firewall believing a net exists is more dangerous than having none.
if ! systemctl list-timers --all "$UNIT.timer" 2>/dev/null | grep -q "$UNIT"; then
    echo "   BERHENTI: jaring pengaman TIDAK terpasang. Firewall tidak disentuh."
    exit 1
fi
systemctl list-timers --all "$UNIT.timer" --no-pager | sed -n '2p' | sed 's/^/   /'
echo "   terbukti terpasang: ufw akan MATI sendiri dalam $MENIT menit"

echo "== 2/5 Menyusun aturan izin (sebelum firewall menyala) =="
# Order matters: allow rules first, firewall on afterwards. Otherwise there is a gap where everything is denied and the SSH session running this script is cut.
for p in $PORT; do
    ufw allow from "$SUBNET" to any port "$p" proto tcp comment "lab NSM" >/dev/null
    echo "   izinkan $p/tcp dari $SUBNET"
done

echo "== 3/5 Menyalakan ufw =="
# --force avoids the "may disrupt existing ssh connections" prompt; the SSH rules are already in place from the earlier steps.
ufw --force enable >/dev/null
echo "   $(ufw status | head -1)"

echo "== 4/5 Keadaan sekarang =="
ufw status numbered | sed 's/^/   /'

echo "== 5/5 Yang HARUS dilakukan sekarang =="
cat <<EOF

   Jaring pengaman aktif. ufw akan MATI SENDIRI dalam $MENIT menit.

   1. Buktikan dulu semuanya masih terjangkau dari laptop.
   2. Kalau semua baik, LEPAS jaringnya:

        sudo systemctl stop $UNIT.timer

   3. Kalau ada yang terputus: JANGAN lakukan apa-apa. Tunggu $MENIT menit,
      ufw mati sendiri, dan mesin ini kembali seperti semula.

   Selama jaringnya belum dilepas, perubahan ini BELUM permanen.
EOF

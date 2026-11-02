"""Enable the stage 1-9 automation on nsm-app, with backup and verification.

Appends lines to `.env` (already backed up to `.env.sebelum-otomasi`) and never
overwrites existing keys: a key already present is skipped and reported, so
running this twice does not create duplicate keys. The result is verified
through `config`, not the file contents, then the poller and API are restarted
so the new settings are read.
"""
import sys

import paramiko

# Passwords are not written here; they are read from `.env`, which Git does not
# track. Git history is permanent, so a committed secret cannot be taken back.
import config
HOST, USER = "192.168.56.156", "nsmapp"
SANDI = config.get_nsmapp_sandi()
ENV = "/home/nsmapp/NSM/backend/.env"
AKAR = "/home/nsmapp/NSM/backend"

BARIS = [
    ("PEMULIH_GNS3_AKTIF", "1"),
    ("PEMULIH_LAYANAN_AKTIF", "1"),
    ("PEMULIH_INTERFACE_AKTIF", "1"),
    ("PEMULIH_KONFIG_AKTIF", "1"),
    ("OTOMASI_PENUH_LAYANAN", "1"),
    ("OTOMASI_PENUH_INTERFACE", "1"),
    ("OTOMASI_PENUH_KONFIG", "1"),
    ("BATAS_RESTART_LAYANAN_HARIAN", "3"),
    ("PAGAR_DAFTAR_PUTIH",
     "gns3_restart,layanan_restart,interface_up,konfig_kembalikan"),
    ("PAGAR_JAM_KERJA", "0-24"),
]

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=SANDI, timeout=20)


def jalan(cmd, t=90):
    i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode(errors="replace"), e.read().decode(errors="replace")


ada, _ = jalan("grep -oE '^[A-Z_]+' %s 2>/dev/null | sort -u" % ENV)
sudah = set(ada.split())
tambah = [(k, v) for k, v in BARIS if k not in sudah]
for k, _ in BARIS:
    if k in sudah:
        print("  LEWATI (sudah ada):", k)

if tambah:
    isi = ("\\n# --- Otomasi Tahap 1-9 dinyalakan 22 Agustus 2026 (diminta pemilik) ---\\n"
           + "\\n".join("%s=%s" % (k, v) for k, v in tambah) + "\\n")
    out, err = jalan("printf '%s' >> %s && echo DITULIS" % (isi, ENV))
    print("menulis:", out.strip() or err.strip())
    for k, v in tambah:
        print("  +", k, "=", v)

# .env settings are read at process start, so a restart is REQUIRED for them to apply.
print("\nmenyalakan ulang poller + api...")
out, err = jalan("sudo -S -p '' systemctl restart nsm-poller nsm-api "
                 "&& echo RESTARTED" % {}, t=60) if False else jalan(
    "echo %s | sudo -S -p '' systemctl restart nsm-poller nsm-api && echo RESTARTED"
    % SANDI, t=60)
print(" ", out.strip() or err.strip()[:200])

# Verify through config (the source of truth), not the file contents.
out, err = jalan(
    "cd %s && ./venv/bin/python -c \""
    "import config;"
    "print('gns3      =', config.get_pemulih_gns3_aktif());"
    "print('layanan   =', config.get_pemulih_layanan_aktif());"
    "print('interface =', config.get_pemulih_interface_aktif());"
    "print('konfig    =', config.get_pemulih_konfig_aktif());"
    "print('penuh_lay =', config.get_otomasi_penuh_layanan());"
    "print('penuh_if  =', config.get_otomasi_penuh_interface());"
    "print('penuh_kfg =', config.get_otomasi_penuh_konfig());"
    "print('putih     =', sorted(config.get_pagar_daftar_putih()));"
    "print('jam_kerja =', config.get_pagar_jam_kerja());"
    "print('batas_rst =', config.get_batas_restart_layanan_harian())\"" % AKAR,
    t=60)
print("\n--- keadaan efektif di nsm-app ---")
print(out or err[:600])

# Is the service actually up?
out, _ = jalan("systemctl is-active nsm-poller nsm-api nsm-frontend")
print("layanan:", " ".join(out.split()))
c.close()

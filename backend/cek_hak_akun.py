"""Check the PRIVILEGES of the NSM monitoring account on each device.

A compliance assessment found `username nsm privilege 15` on a router: the
account NSM uses to READ could WRITE anything. The anti-write guard lives on
the NSM side (`connectors/ssh.py`), not on the device, so anyone holding a copy
of `nsm.db` holds fully privileged credentials. The mirror question is what the
`nsm` account on the Ubuntu VM and the monitoring account on the testUbuntu VM
may do; if either can `sudo` without a password, the router finding repeats.

READ-ONLY: it changes no file, writes nothing to devices, and stores no
password. The commands it runs are all state checks, listed openly below so
anyone can review them first.

    python cek_hak_akun.py
"""
import sys

import dialek_perangkat
import identitas
from database import SessionLocal
from models import Device

# Check commands; all read-only. `sudo -n` is deliberate: `-n` means never ask
# for a password, so it FAILS instead of hanging on input that never comes. The
# failure is itself the answer sought.
PEMERIKSAAN_LINUX = [
    ("akun yang dipakai", "id -un"),
    ("grup yang diikuti", "id -Gn"),
    ("anggota grup sudo/wheel", "id -Gn | tr ' ' '\\n' | grep -Ec '^(sudo|wheel|admin)$'"),
    ("bisa sudo TANPA sandi", "sudo -n true 2>/dev/null && echo YA || echo tidak"),
    ("shell login", "getent passwd \"$(id -un)\" | cut -d: -f7"),
    ("berkas sshd_config terbaca", "test -r /etc/ssh/sshd_config && echo ya || echo tidak"),
    ("jumlah port mendengarkan", "ss -tlnH 2>/dev/null | wc -l"),
    ("layanan firewall aktif", "systemctl is-active ufw 2>/dev/null || echo tidak-ada"),
]

PEMERIKSAAN_CISCO = [
    ("tingkat hak sesi login ini", "show privilege"),
]


def check_linux(ip, user, sandi, kunci):
    import paramiko
    cl = paramiko.SSHClient()
    cl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    sambung = {"timeout": 15, "allow_agent": False, "look_for_keys": False}
    if kunci:
        cl.connect(ip, username=user, key_filename=kunci, **sambung)
    else:
        cl.connect(ip, username=user, password=sandi, **sambung)
    hasil = []
    try:
        for label, perintah in PEMERIKSAAN_LINUX:
            _i, o, e = cl.exec_command(perintah, timeout=15)
            keluar = (o.read().decode(errors="replace")
                      + e.read().decode(errors="replace")).strip()
            hasil.append((label, keluar.replace("\n", " ") or "(kosong)"))
    finally:
        cl.close()
    return hasil


def main():
    db = SessionLocal()
    try:
        print("=" * 74)
        print("HAK AKUN PEMANTAU NSM DI TIAP PERANGKAT")
        print("=" * 74)
        print("  Hanya membaca. Tidak ada satu perintah pun yang mengubah.")
        print()

        print("  PENJAGA IDENTITAS — apakah jalur MENULIS terbuka?")
        print("  " + "-" * 70)
        for d in db.query(Device).all():
            if not dialek_perangkat.ambil(d.platform).kemampuan("identitas"):
                continue
            allowed, v, alasan = identitas.boleh_ditulisi(db, d.id)
            print("  %-20s %-18s %s" % (d.name[:20], v or "-",
                                        "BOLEH" if allowed else "DITOLAK"))
            print("      %s" % alasan)
        print()

        # Part 2: the actual privileges on the device.
        print("  HAK SEBENARNYA DI PERANGKAT")
        print("  " + "-" * 70)
        for d in db.query(Device).all():
            # Hosts whose privileges can be queried through a shell. `lokal` is also
            # `jenis: host` but has empty `identitas`; it is never contacted over the network.
            _d = dialek_perangkat.ambil(d.platform)
            if not (_d.akses.get("jenis") == "host"
                    and _d.kemampuan("identitas")):
                continue
            if not (d.username and (d.password or d.ssh_key_path)):
                continue
            print(f"\n  {d.name}  ({d.ip_address}, akun {d.username})")
            try:
                for label, value in check_linux(d.ip_address, d.username,
                                                  d.password, d.ssh_key_path):
                    print("      %-28s %s" % (label, value[:44]))
            except Exception as e:
                print(f"      gagal tersambung: {e}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

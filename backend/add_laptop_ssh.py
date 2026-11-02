"""Register a SECOND device row for this laptop, accessed over SSH with a key.

Why a second row instead of changing the existing one:

The laptop is already monitored through the LOCAL connector (the "Laptop
Sendiri" device row), the everyday path since it opens no port, stores no
credentials, and collects richer data. This second row exists to PROVE
remote access to Windows, which was part of the original internship brief.

The dashboard then shows one machine through two paths side by side, so the
numbers and the cost difference can be compared with evidence.

The command TESTS the connection first and saves only on success.

    cd C:\\\\Users\\\\<user>\\\\NSM\\\\backend
    venv\\\\Scripts\\\\activate
    python add_laptop_ssh.py nsmssh C:\\\\Users\\\\<user>\\\\.ssh\\\\nsm_laptop

To remove the row again:

    python add_laptop_ssh.py --hapus
"""
import argparse
import os
import sys

from database import SessionLocal
from models import Device
from connectors.ssh import SshConnector
from connectors.lokal import ip_sekarang

NAMA = "Laptop (via SSH)"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("username", nargs="?",
                   help="akun Windows khusus untuk NSM, non-admin")
    p.add_argument("key_path", nargs="?",
                   help="jalur berkas kunci PRIVAT (bukan yang .pub)")
    p.add_argument("--ip", default=None,
                   help="alamat yang dipakai; bawaannya alamat mesin ini sekarang")
    p.add_argument("--hapus", action="store_true")
    a = p.parse_args()

    db = SessionLocal()
    try:
        old = db.query(Device).filter(Device.name == NAMA).first()

        if a.hapus:
            if not old:
                print(f"Baris \"{NAMA}\" tidak ada, tidak ada yang dihapus.")
                return 0
            db.delete(old)
            db.commit()
            print(f"Baris \"{NAMA}\" dihapus.")
            print("Riwayat lamanya masih tersimpan di status_logs dan "
                  "device_events, tidak ikut terhapus.")
            print()
            print("Jangan lupa cabut juga aksesnya di sisi Windows kalau tidak "
                  "dipakai lagi: hapus baris kunci di authorized_keys, dan "
                  "matikan layanan sshd bila memang tidak diperlukan.")
            return 0

        if not a.username or not a.key_path:
            p.print_help()
            return 1

        if not os.path.exists(a.key_path):
            print(f"Berkas kunci tidak ditemukan: {a.key_path}")
            return 1
        if a.key_path.endswith(".pub"):
            print("Itu kunci PUBLIK. Yang dipakai NSM adalah kunci PRIVAT, "
                  "yaitu berkas dengan nama yang sama tanpa akhiran .pub.")
            return 1

        ip = a.ip or ip_sekarang()
        if not ip:
            print("Alamat mesin ini tidak bisa ditentukan. Sebutkan manual "
                  "dengan --ip.")
            return 1

        # Test FIRST, save after. Wrong credentials must never be stored silently and
        # then turn into false alarms every 30 seconds.
        print(f"Menguji SSH ke {ip} sebagai '{a.username}' memakai kunci ...")
        conn = SshConnector(ip, platform="windows", username=a.username,
                            key_path=a.key_path)
        try:
            data = conn.get_info()
        except Exception as e:
            print(f"  GAGAL: {e}")
            print()
            print("Yang paling sering jadi sebabnya:")
            print("  - layanan sshd belum jalan       -> Get-Service sshd")
            print("  - kunci publik belum terpasang   -> periksa authorized_keys")
            print("  - izin berkas authorized_keys terlalu longgar, OpenSSH "
                  "menolak diam-diam")
            print("  - firewall memblokir port 22 dari alamat ini")
            return 1

        print("  BERHASIL. Contoh yang terbaca:")
        for k in ("Hostname", "OS", "Alamat IP"):
            if data.get(k):
                one = str(data[k]).strip().splitlines()
                print(f"    {k:<12}: {one[0] if one else '-'}")

        d = old or Device(name=NAMA)
        d.ip_address = ip
        d.device_type = "pc"
        d.platform = "windows"
        d.username = a.username
        d.password = None  # intentionally empty: key auth is used
        d.ssh_key_path = a.key_path
        d.location = "Laptop sendiri, jalur SSH"
        d.aktif = 1
        if not old:
            db.add(d)
        db.commit()

        print()
        print(f"{'Diperbarui' if old else 'Ditambahkan'} sebagai device "
              f"id={d.id}: {NAMA}")
        print(f"  alamat   : {d.ip_address}")
        print(f"  login    : {d.username} (kunci, tanpa password)")
        print(f"  kunci    : {d.ssh_key_path}")
        print()
        print("Kolom password sengaja DIBIARKAN KOSONG, jadi nsm.db tidak "
              "menyimpan rahasia apa pun untuk device ini. Yang tersimpan "
              "hanya jalur berkas kuncinya.")
        print()
        print("Restart poller & uvicorn supaya berlaku:")
        print("   Ctrl+C di CMD poller,  lalu  py poller.py")
        print("   Ctrl+C di CMD uvicorn, lalu  uvicorn main:app --port 8000")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

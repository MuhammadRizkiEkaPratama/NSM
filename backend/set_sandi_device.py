"""Replace the stored SSH password for a device, only if the password is proven to work.

Credential rotation has a dangerous window: the password is changed on the DEVICE but not
yet in NSM. The symptom is not "wrong password" but "device unreachable", "empty bandwidth"
or "service not monitored". A mistyped copy into the database would make that permanent,
because `UPDATE devices SET password=...` always succeeds. So this script TESTS FIRST and
SAVES AFTER: if the login fails, nothing is written.

It deliberately does NOT change anything on the device. Changing a password on a network
device can lock everyone out, so that decision belongs to a human watching their own open
SSH session. Devices are changed by humans, the NSM copy by this script.

Usage:
    python set_sandi_device.py 5            # ask for the password, test, then save
    python set_sandi_device.py 5 --uji      # test only, save nothing
    python set_sandi_device.py --daftar     # which devices store a password

The password is requested via `getpass`, so it does not appear on screen, in shell
history or in the process list.
"""
import argparse
import getpass
import os
import sys

import dialek_perangkat

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

from database import SessionLocal  # noqa: E402
from models import Device  # noqa: E402


def daftar(db):
    print("%-4s %-26s %-16s %-12s %-10s %s" % (
        "id", "nama", "alamat", "platform", "user", "sandi tersimpan"))
    print("-" * 84)
    for d in db.query(Device).order_by(Device.id).all():
        if not d.username:
            continue
        print("%-4s %-26s %-16s %-12s %-10s %s" % (
            d.id, (d.name or "")[:26], d.ip_address or "",
            (d.platform or "-")[:12], (d.username or "-")[:10],
            "ya" if d.password else "tidak (kunci SSH / tanpa sandi)"))


def try_login(d, sandi):
    """Return (success, message). Never raises to the caller."""
    _d = dialek_perangkat.ambil(d.platform)
    if _d.akses.get("jenis") == "jaringan":
        try:
            from netmiko import ConnectHandler
            conn = ConnectHandler(device_type=_d.netmiko_device_type,
                                  host=d.ip_address,
                                  username=d.username, password=sandi,
                                  conn_timeout=15, timeout=30)
            prompt = conn.find_prompt().strip("#> ")
            conn.disconnect()
            return True, "masuk sebagai '%s', prompt: %s" % (d.username, prompt)
        except Exception as e:
            return False, str(e).splitlines()[0][:120]

    # Linux / other: plain SSH via paramiko.
    try:
        import paramiko
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(d.ip_address, username=d.username, password=sandi,
                  timeout=20, allow_agent=False, look_for_keys=False)
        _, out, _ = c.exec_command("hostname", timeout=15)
        nama = out.read().decode("utf-8", "replace").strip()
        c.close()
        return True, "masuk sebagai '%s', hostname: %s" % (d.username, nama)
    except Exception as e:
        return False, str(e).splitlines()[0][:120]


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("device_id", nargs="?", type=int,
                   help="id device di tabel devices")
    p.add_argument("--uji", action="store_true",
                   help="uji sandi saja, JANGAN simpan")
    p.add_argument("--daftar", action="store_true",
                   help="tampilkan device yang menyimpan sandi")
    a = p.parse_args()

    db = SessionLocal()
    try:
        if a.daftar or a.device_id is None:
            daftar(db)
            return 0

        d = db.get(Device, a.device_id)
        if not d:
            print("device id %s tidak ada." % a.device_id)
            return 1
        if not d.username:
            print("device '%s' tidak punya username. Isi dulu sebelum sandinya."
                  % d.name)
            return 1

        print("Device : %s (id %s)" % (d.name, d.id))
        print("Alamat : %s   platform: %s   user: %s"
              % (d.ip_address, d.platform or "-", d.username))
        print()

        sandi = getpass.getpass("Sandi BARU untuk '%s' (tidak ditampilkan): " % d.username)
        if not sandi:
            print("kosong — dibatalkan, tidak ada yang diubah.")
            return 1
        retry = getpass.getpass("Ketik ulang untuk memastikan             : ")
        if sandi != retry:
            # Checked BEFORE touching the network: a typo caught here costs nothing.
            print("dua masukan berbeda — dibatalkan, tidak ada yang diubah.")
            return 1

        print("\nMenguji login ke %s ..." % d.ip_address)
        succeed, note = try_login(d, sandi)
        if not succeed:
            print("  GAGAL: %s" % note)
            print("\nTIDAK ADA yang disimpan. Basis data tetap memegang sandi lama.")
            print("Periksa: sudahkah sandi ini benar-benar dipasang di perangkat")
            print("(`write memory` sudah dijalankan?), dan apakah perangkatnya hidup.")
            return 1

        print("  BERHASIL: %s" % note)

        if a.uji:
            print("\n--uji dipakai: sandi terbukti bekerja, tetapi TIDAK disimpan.")
            return 0

        d.password = sandi
        db.commit()
        print("\nDisimpan. NSM sekarang memakai sandi baru untuk device ini.")
        print("Buktikan seluruh rotasi dengan: python cek_rotasi.py --sambung")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

"""Mark a device as THIS MACHINE, so it is read without SSH.

A device with `platform = "lokal"` is read directly by `connectors/lokal.py`: no open
ports and no stored credentials (see the header of that connector).

The command REFUSES if the device address does not belong to this machine; otherwise NSM
would report this machine's numbers as another device's.

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\activate
    python set_lokal.py --daftar
    python set_lokal.py 2
    python set_lokal.py 2 --batal
"""
import argparse
import sys

from database import SessionLocal
from models import Device
from connectors.lokal import LokalConnector, _alamat_sendiri, ip_sekarang


def main():
    p = argparse.ArgumentParser()
    p.add_argument("device_id", nargs="?", type=int)
    p.add_argument("--daftar", action="store_true")
    p.add_argument("--batal", action="store_true",
                   help="kembalikan platform jadi kosong")
    a = p.parse_args()

    db = SessionLocal()
    try:
        if a.daftar or a.device_id is None:
            owned = _alamat_sendiri()
            print("Alamat IPv4 milik mesin ini:")
            for x in sorted(owned):
                print("   ", x)
            print()
            print(f"{'ID':>3}  {'Nama':<22} {'IP':<16} {'Platform':<10} mesin ini?")
            print("-" * 70)
            for d in db.query(Device).order_by(Device.id).all():
                mark = "YA" if d.ip_address in owned else "-"
                print(f"{d.id:>3}  {d.name:<22} {d.ip_address:<16} "
                      f"{str(d.platform or '-'):<10} {mark}")
            print()
            print("Jalankan  python set_lokal.py <ID>  untuk menandainya.")
            return 0

        d = db.query(Device).filter(Device.id == a.device_id).first()
        if not d:
            print(f"Device {a.device_id} tidak ada.")
            return 1

        if a.batal:
            d.platform = None
            db.commit()
            print(f"Device {d.id} ({d.name}) tidak lagi ditandai lokal. "
                  f"Platform dikosongkan, jadi tombol Data SSH ikut hilang.")
            return 0

        conn = LokalConnector(d.ip_address)
        if not conn.ini_mesin_ini():
            baru = ip_sekarang()
            if not baru:
                print("DITOLAK. Alamat mesin ini tidak bisa ditentukan, "
                      "jaringan kemungkinan sedang mati.")
                return 1
            print(f"Alamat di baris device ({d.ip_address}) sudah tidak "
                  f"dipakai mesin ini. Diperbarui ke {baru}.")
            d.ip_address = baru

        d.platform = "lokal"
        db.commit()
        print(f"Device {d.id} ({d.name}) ditandai lokal, alamat {d.ip_address}.")
        print()
        info = conn.get_info()
        print("Contoh data yang kini bisa dibaca NSM tanpa SSH:")
        for k in ("Hostname", "OS", "Uptime", "CPU", "Memori", "Disk"):
            if k in info:
                print(f"   {k:<10}: {info[k]}")
        print()
        bw = conn.get_bandwidth()
        print(f"Interface yang akan dipantau lalu lintasnya: {len(bw)}")
        for nama in bw:
            print("   ", nama)
        print()
        print("Restart poller & uvicorn supaya berlaku:")
        print("   Ctrl+C di CMD poller, lalu  py poller.py")
        print("   Ctrl+C di CMD uvicorn, lalu uvicorn main:app --port 8000")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

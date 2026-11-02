"""Register a service monitored by NSM on a device.

Like `set_snmp.py`, it TESTS before saving, so a mistyped address or port never gets
stored and turns into a false outage every 30 seconds.

Safe to run while the poller and uvicorn are running: only one row is written.

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\activate

List devices and registered services:

    python set_layanan.py --daftar

Add a service:

    python set_layanan.py 6 http  80   --nama "Web Server BSP" --path /hello.php
    python set_layanan.py 6 http  80   --nama "Halaman Hello" --path /hello.php --teks "Hello World"
    python set_layanan.py 4 mysql 3306 --nama "MySQL labweb"
    python set_layanan.py 6 tcp   22   --nama "SSH testUbuntu"

Remove a service (use the service number from --daftar):

    python set_layanan.py --hapus 3

Pause without deleting its history:

    python set_layanan.py --jeda 3
    python set_layanan.py --lanjut 3
"""
import argparse
import sys

from database import SessionLocal
from models import Device, Service
from connectors import layanan

JENIS = ("tcp", "http", "mysql")


def daftar(db):
    print(f"{'Dev':>4}  {'Device':<22} {'IP':<16} Layanan terdaftar")
    print("-" * 78)
    for d in db.query(Device).order_by(Device.id).all():
        svc = db.query(Service).filter(Service.device_id == d.id).all()
        print(f"{d.id:>4}  {d.name:<22} {d.ip_address:<16} "
              f"{len(svc)} layanan")
        for s in svc:
            jeda = "  [DIJEDA]" if s.aktif == 0 else ""
            path = f" {s.path}" if s.path else ""
            teks = f" cari:\"{s.harap_teks}\"" if s.harap_teks else ""
            print(f"        #{s.id} {s.jenis:<6} port {s.port:<6} "
                  f"{s.nama}{path}{teks}{jeda}")
    print()
    print("Nomor setelah tanda # adalah nomor LAYANAN, dipakai untuk "
          "--hapus / --jeda / --lanjut.")


def main():
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("device_id", nargs="?", type=int)
    p.add_argument("jenis", nargs="?", choices=JENIS)
    p.add_argument("port", nargs="?", type=int)
    p.add_argument("--nama", default=None)
    p.add_argument("--path", default=None,
                   help="halaman yang diminta, khusus jenis http")
    p.add_argument("--teks", default=None,
                   help="teks yang harus ada di halaman (penangkal halaman "
                        "galat yang tetap berkode 200)")
    p.add_argument("--status", type=int, default=200,
                   help="kode status yang dianggap sehat, khusus http")
    p.add_argument("--timeout", type=int, default=5)
    p.add_argument("--daftar", action="store_true")
    p.add_argument("--hapus", type=int, metavar="ID_LAYANAN")
    p.add_argument("--jeda", type=int, metavar="ID_LAYANAN")
    p.add_argument("--lanjut", type=int, metavar="ID_LAYANAN")
    p.add_argument("--paksa", action="store_true",
                   help="simpan walau uji koneksinya gagal")
    a = p.parse_args()

    db = SessionLocal()
    try:
        if a.daftar:
            daftar(db)
            return 0

        for aksi, value in (("hapus", a.hapus), ("jeda", a.jeda),
                            ("lanjut", a.lanjut)):
            if value is None:
                continue
            s = db.query(Service).filter(Service.id == value).first()
            if not s:
                print(f"Layanan #{value} tidak ada. "
                      f"Jalankan --daftar untuk melihat nomornya.")
                return 1
            if aksi == "hapus":
                db.delete(s)
                print(f"Layanan #{value} ({s.nama}) dihapus.")
                print("Catatan: riwayat pemeriksaan lamanya masih tersimpan di "
                      "service_checks dan service_events.")
            else:
                s.aktif = 0 if aksi == "jeda" else 1
                print(f"Layanan #{value} ({s.nama}) "
                      f"{'dijeda' if aksi == 'jeda' else 'dilanjutkan'}.")
            db.commit()
            return 0

        if a.device_id is None or a.jenis is None or a.port is None:
            p.print_help()
            print("\nContoh lengkap ada di bagian atas berkas ini.")
            return 1

        d = db.query(Device).filter(Device.id == a.device_id).first()
        if not d:
            print(f"Device {a.device_id} tidak ada. Jalankan --daftar.")
            return 1

        nama = a.nama or f"{a.jenis.upper()} {a.port} di {d.name}"

        # Test FIRST, save after. This is what distinguishes the command from a plain INSERT.
        print(f"Menguji {a.jenis} ke {d.ip_address}:{a.port} ...")
        hasil = layanan.periksa(a.jenis, d.ip_address, a.port, path=a.path,
                                timeout=a.timeout, harap_status=a.status,
                                harap_teks=a.teks)
        if hasil["ok"]:
            ms = hasil["waktu_ms"]
            print(f"  BERHASIL, dijawab dalam {ms} ms"
                  + (f", kode {hasil['kode']}" if hasil["kode"] else ""))
            if hasil["detail"]:
                print(f"  {hasil['detail']}")
        else:
            print(f"  GAGAL [{hasil['kategori']}]")
            print(f"  {hasil['detail']}")
            if not a.paksa:
                print("\nTidak disimpan. Perbaiki dulu, atau pakai --paksa "
                      "kalau memang ingin memantau layanan yang saat ini "
                      "sedang mati.")
                return 1
            print("\n--paksa dipakai, tetap disimpan.")

        s = Service(device_id=d.id, nama=nama, jenis=a.jenis, port=a.port,
                    path=a.path, harap_status=a.status if a.jenis == "http" else None,
                    harap_teks=a.teks, timeout_detik=a.timeout, aktif=1)
        db.add(s)
        db.commit()
        print(f"\nTersimpan sebagai layanan #{s.id}: {nama}")
        print("Restart poller supaya layanan ini mulai diperiksa:")
        print("  Ctrl+C di CMD poller, lalu  py poller.py")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

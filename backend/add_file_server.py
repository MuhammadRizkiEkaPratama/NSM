"""Register the SMB file server (`nsm-files` / 192.168.56.105) with NSM.

Adds ONE device and ONE service. Safe to rerun: existing rows are skipped,
not duplicated.

The service uses `jenis='smb'` with `log_akses` pointing at the Samba audit
log. Same pattern as the SFTP service on `.103` (see `migrate_sftp.py`): the
poller picks the log by `jenis`, so another SMB host only needs one more row
here, with no code changes.

    cd C:\\\\Users\\\\<user>\\\\NSM\\\\backend
    venv\\\\Scripts\\\\python.exe add_file_server.py
"""
import sys

from database import SessionLocal
from models import Device, Service

IP = "192.168.56.105"
NAMA_DEVICE = "Server Berkas SMB (Lokasi A)"
NAMA_LAYANAN = "Folder Sharing SMB"
LOG_AUDIT = "/var/log/samba-audit.log"
KUNCI = r"C:\Users\<user>\.ssh\nsm_vm"


def main():
    db = SessionLocal()
    try:
        d = db.query(Device).filter(Device.ip_address == IP).first()
        if d:
            print("  lewat  device %s sudah ada (id %d)" % (IP, d.id))
        else:
            d = Device(
                name=NAMA_DEVICE,
                ip_address=IP,
                device_type="server",
                platform="linux",
                location="Lokasi A",
                aktif=1,
                # READ-ONLY robot account. Unlike .103/.104, nsmro has no sudo at all on this
                # host; membership in group `adm` is enough to read the audit log. Least
                # privilege that gets the job done.
                username="nsmro",
                ssh_key_path=KUNCI,
            )
            db.add(d)
            db.flush()
            print("  BUAT   device '%s' (id %d)" % (NAMA_DEVICE, d.id))

        already = (db.query(Service)
                 .filter(Service.device_id == d.id, Service.jenis == "smb")
                 .first())
        if already:
            print("  lewat  layanan SMB sudah terdaftar (id %d)" % already.id)
        else:
            db.add(Service(
                device_id=d.id,
                nama=NAMA_LAYANAN,
                jenis="smb",
                port=445,
                aktif=1,
                log_akses=LOG_AUDIT,
                timeout_detik=5,
            ))
            print("  BUAT   layanan '%s' (port 445, log %s)"
                  % (NAMA_LAYANAN, LOG_AUDIT))

        db.commit()
        print("\nSelesai.")
    finally:
        db.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("GAGAL: %s" % e)
        sys.exit(1)

"""Populate `services.unit_systemd`: which services may be restarted automatically.

NULL (the default) means "not mapped, never auto-restart". Unit names are never
guessed from service names; a wrong guess would restart the wrong unit on the
wrong server.

The list is deliberately short. Three service types are left out (the
`firewall/nsm-restart-layanan` wrapper documents the same reasons):

    SSH (id 1, 2, 8)  NSM's own access path; a failed restart would lock NSM out.
    LDAP (id 7)       an outage breaks both NSM and E-Canteen logins.
    MySQL (id 3)      hosts NSM's own database.

Even for mapped services, the `PEMULIH_LAYANAN_AKTIF` kill switch (off by default)
and `PAGAR_DAFTAR_PUTIH` allowlist (empty by default) still apply; filling this
column enables nothing by itself.

Idempotent. Rows are matched by (device IP, service name), not `services.id`,
which changes if a service is deleted and re-registered.

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\python.exe isi_unit_systemd.py
"""
import sys

import database
from models import Device, Service

# (device_ip, service_name, unit_systemd, short reason)
PEMETAAN = [
    ("192.168.56.103", "Web Server BSP", "apache2",
     "Apache. Restart adalah perbaikan bakunya; tidak ada sesi manajemen "
     "NSM yang lewat sini."),
    ("192.168.56.103", "E-Canteen v2", "ecanteen",
     "Unit systemd TERPISAH dari apache2 (dikonfirmasi lewat "
     "`systemctl list-units` di .103, 21 Agustus 2026) -- jadi merestartnya "
     "tidak ikut menjatuhkan Web Server BSP."),
    ("192.168.56.105", "Folder Sharing SMB", "smbd",
     "Samba. Sesi SMB yang terputus disambung ulang klien sendiri."),
    ("192.168.56.105", "Riwayat Command (auditd)", "auditd",
     "auditd. Restart menyebabkan jeda pencatatan beberapa detik -- "
     "diterima, karena alternatifnya auditd mati sama sekali."),
]


def main():
    db = database.SessionLocal()
    try:
        filled = same = skipped = 0
        for ip, nama, unit, alasan in PEMETAAN:
            d = db.query(Device).filter(Device.ip_address == ip).first()
            if d is None:
                print("  LEWAT  %-26s (tidak ada device beralamat %s)" % (nama, ip))
                skipped += 1
                continue
            s = (db.query(Service)
                 .filter(Service.device_id == d.id, Service.nama == nama)
                 .first())
            if s is None:
                print("  LEWAT  %-26s (layanan tidak ada di %s)" % (nama, d.name))
                skipped += 1
                continue
            if s.unit_systemd == unit:
                print("  sama   %-26s -> %s" % (nama, unit))
                same += 1
                continue
            s.unit_systemd = unit
            filled += 1
            print("  ISI    %-26s -> %-10s  (%s)" % (nama, unit, d.name))
        db.commit()

        print()
        print("%d diisi, %d sudah sama, %d dilewati." % (filled, same, skipped))

        # Unmapped services are printed too, so the output explains why they are never
        # auto-repaired.
        print("\nSENGAJA TIDAK dipetakan (tidak akan pernah direstart otomatis):")
        for s in db.query(Service).filter(Service.unit_systemd.is_(None)).all():
            d = db.get(Device, s.device_id)
            print("   %-28s di %s" % (s.nama, d.name if d else "?"))
    finally:
        db.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("GAGAL: %s" % e)
        sys.exit(1)

"""Set or remove the SNMP v3 credentials of a device, then test the connection.

Use AFTER SNMP is enabled on the device (see docs/SNMP.md).

Examples (placeholders only; use your own credentials):
    python set_snmp.py 6 nsmmon <AUTH_PASSWORD> <PRIV_PASSWORD>
    python set_snmp.py 5 nsmmon <AUTH_PASSWORD> <PRIV_PASSWORD> --proto SHA AES
    python set_snmp.py 6 --hapus          (disable SNMP, back to SSH)
    python set_snmp.py --daftar           (list devices and SNMP status)

Security note: the credentials are stored as-is in nsm.db, like SSH passwords.
Make sure nsm.db never enters Git.
"""
import sys

from database import SessionLocal
from models import Device
from connectors.snmp import SnmpConnector


def daftar(db):
    print(f"{'ID':<4} {'Nama':<20} {'IP':<17} {'Platform':<12} SNMP")
    print("-" * 72)
    for d in db.query(Device).order_by(Device.id).all():
        if d.snmp_user:
            snmp = (f"{d.snmp_user} ({d.snmp_auth_proto or 'SHA'}/"
                    f"{d.snmp_priv_proto or 'AES'}:{d.snmp_port or 161})")
        else:
            snmp = "-"
        print(f"{d.id:<4} {d.name:<20} {d.ip_address:<17} "
              f"{str(d.platform):<12} {snmp}")


def main():
    args = sys.argv[1:]
    db = SessionLocal()
    try:
        if not args or args[0] == "--daftar":
            daftar(db)
            return

        device_id = int(args[0])
        d = db.query(Device).filter(Device.id == device_id).first()
        if not d:
            print(f"Device id {device_id} tidak ditemukan.")
            return

        if "--hapus" in args:
            d.snmp_user = d.snmp_auth_pass = d.snmp_priv_pass = None
            d.snmp_auth_proto = d.snmp_priv_proto = None
            d.snmp_port = None
            db.commit()
            print(f"SNMP dimatikan untuk {d.name}. "
                  f"Bandwidth akan dibaca lewat SSH lagi.")
            return

        if len(args) < 4:
            print(__doc__)
            return

        user, auth_pass, priv_pass = args[1], args[2], args[3]
        auth_proto, priv_proto = "SHA", "AES"
        if "--proto" in args:
            i = args.index("--proto")
            auth_proto = args[i + 1]
            priv_proto = args[i + 2]
        port = 161
        if "--port" in args:
            port = int(args[args.index("--port") + 1])

        # Test before saving; never store wrong credentials.
        print(f"Menguji SNMP ke {d.name} ({d.ip_address}:{port}) "
              f"sebagai '{user}' [{auth_proto}/{priv_proto}]...")
        conn = SnmpConnector(d.ip_address, user=user, auth_pass=auth_pass,
                             priv_pass=priv_pass, auth_proto=auth_proto,
                             priv_proto=priv_proto, port=port, timeout=3, retries=1)
        alive, rtt = conn.check_reachable()
        if not alive:
            print("\nGAGAL terhubung. Kredensial TIDAK disimpan.")
            print("Periksa:")
            print("  - snmpd sudah jalan di device?  (sudo systemctl status snmpd)")
            print("  - user SNMP v3 sudah dibuat dengan nama & sandi yang sama?")
            print("  - snmpd mendengarkan di alamat yang benar, bukan hanya 127.0.0.1?")
            print("  - firewall device mengizinkan UDP 161?")
            return

        print(f"Berhasil, balasan {rtt} ms. Contoh data:")
        try:
            for k, v in conn.get_info().items():
                if "\n" not in str(v):
                    print(f"   {k}: {v}")
        except Exception as e:
            print(f"   (get_info gagal: {e})")

        d.snmp_user = user
        d.snmp_auth_pass = auth_pass
        d.snmp_priv_pass = priv_pass
        d.snmp_auth_proto = auth_proto
        d.snmp_priv_proto = priv_proto
        d.snmp_port = port
        db.commit()
        print(f"\nTersimpan. Poller akan memakai SNMP untuk {d.name} "
              f"pada putaran bandwidth berikutnya.")
    finally:
        db.close()


if __name__ == "__main__":
    main()

"""Simulate real connection attempts that the lab firewalls reject, so the Firewall page shows denials recorded by the router and `ufw`, read by the poller like any other event. Nothing is injected into the database.

Two sources: attacker A is the laptop (192.168.56.1) hitting the Site A server (ufw); attacker B is `nsm-data` (192.168.56.104) hitting LDAP at Site B (router ACL `DARI-LOKASI-A` on R2). That ACL permits `.104` only to `.101:389`, so almost everything else it sends is denied; port 389 is left out of the scan list because it is open by design.

These are plain TCP connection attempts to ports already known to be closed; nothing is exploited. Rate-limited, stops by itself, run manually. Delays are randomized, as in `sftp/simulasi_transfer.py`.

    python simulasi_serangan.py                  # full, ~7 minutes
    python simulasi_serangan.py --menit 2         # faster, for trying out
    python simulasi_serangan.py --sekaligus       # no delay at all
    python simulasi_serangan.py --hanya-a         # laptop only
    python simulasi_serangan.py --hanya-b         # nsm-data only
"""
import argparse
import random
import socket
import sys
import time

KUNCI_NSM = r"C:\Users\<user>\.ssh\nsm_vm"
DATA_SERVER = ("192.168.56.104", "nsmro")

# Attacker A ports are taken from ports known to be closed: the Firewall page allows only 22/80/8080/161(udp) on `.103` and 22/3306/161/123 on `.104`. Hitting allowed ports would produce no denials.
SASARAN_A = [
    ("192.168.56.103", "Server Web (Lokasi A)",
     [21, 23, 25, 443, 445, 1433, 3306, 3389, 5432, 8443]),
    ("192.168.56.104", "Server Data (Lokasi A)",
     [21, 23, 25, 80, 443, 445, 1433, 3389, 5432, 8443]),
]

# Attacker B: `nsm-data` to LDAP at Site B through the router ACL. Port 389 is excluded because the ACL has an explicit permit for `.104 -> .101:389`.
PORT_SCAN_B = [21, 22, 23, 25, 80, 443, 445, 1433,
               3306, 3389, 5432, 8080, 8443, 9200]
LDAP_B = ("192.168.20.101", "Direktori LDAP (Lokasi B)")
# One port hit repeatedly, separate from the scan list: a brute-force pattern (many attempts at one destination) rather than a scan (many destinations from one source).
PORT_BRUTE_B = 22
ULANG_BRUTE_B = 6


def jeda(rata, sekaligus):
    if sekaligus or rata <= 0:
        return
    time.sleep(max(0.15, random.uniform(0.4, 1.6) * rata))


def coba_tcp(alamat, port, timeout=2.5):
    """One plain TCP connection attempt. Returns True if it connected, meaning the port is open, which for the lists above is noteworthy."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((alamat, port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def jalankan_a(menit, sekaligus):
    print("=== Penyerang A: laptop (192.168.56.1) -> server Lokasi A, lewat ufw ===")
    kejadian = []
    for alamat, nama, ports in SASARAN_A:
        for p in ports:
            kejadian.append((alamat, nama, p))
    random.shuffle(kejadian)

    rata = 0.0 if sekaligus else (menit * 60.0) / max(1, len(kejadian))
    for i, (alamat, nama, port) in enumerate(kejadian, 1):
        terbuka = coba_tcp(alamat, port)
        tanda = "TERBUKA (!)" if terbuka else "ditolak/tak dijawab"
        print("  [%2d/%2d] %-16s :%-5d (%s)  %s"
              % (i, len(kejadian), alamat, port, nama, tanda))
        if i < len(kejadian):
            jeda(rata, sekaligus)
    print()


def jalankan_b(menit, sekaligus):
    print("=== Penyerang B: nsm-data (192.168.56.104) -> LDAP Lokasi B, lewat ACL router ===")
    try:
        import paramiko
    except ImportError:
        print("  BERHENTI: paramiko tidak terpasang. Jalankan dengan python "
              "dari backend\\venv\\Scripts\\python.exe")
        return

    cl = paramiko.SSHClient()
    cl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        cl.connect(DATA_SERVER[0], username=DATA_SERVER[1],
                  key_filename=KUNCI_NSM, timeout=15,
                  allow_agent=False, look_for_keys=False)
    except Exception as e:
        print("  BERHENTI: tidak bisa SSH ke nsm-data (%s)" % e)
        return

    def tembak(port):
        # `/dev/tcp` in bash tests a TCP port without installing tools on the server. The 3 s timeout keeps silently dropped packets from hanging the SSH session.
        cmd = ('timeout 3 bash -c "echo > /dev/tcp/%s/%d" 2>&1 && echo OK '
               '|| echo TUTUP') % (LDAP_B[0], port)
        _in, out, _err = cl.exec_command(cmd, timeout=8)
        hasil = out.read().decode(errors="replace").strip()
        return "OK" in hasil

    # Pattern 1: scan, spread over many destinations
    urutan = list(PORT_SCAN_B)
    random.shuffle(urutan)
    rata = 0.0 if sekaligus else (menit * 60.0 * 0.6) / max(1, len(urutan))
    print("  -- pola pemindaian: %d port berbeda di %s --"
          % (len(urutan), LDAP_B[0]))
    for i, port in enumerate(urutan, 1):
        terbuka = tembak(port)
        tanda = "TERBUKA (!)" if terbuka else "ditolak ACL"
        print("  [%2d/%2d] %-16s :%-5d (%s)  %s"
              % (i, len(urutan), LDAP_B[0], port, LDAP_B[1], tanda))
        if i < len(urutan):
            jeda(rata, sekaligus)

    # Pattern 2: "brute-force", piled onto one destination
    print("  -- pola brute-force: port %d, %d kali beruntun --"
          % (PORT_BRUTE_B, ULANG_BRUTE_B))
    rata2 = 0.0 if sekaligus else (menit * 60.0 * 0.4) / ULANG_BRUTE_B
    for i in range(1, ULANG_BRUTE_B + 1):
        terbuka = tembak(PORT_BRUTE_B)
        tanda = "TERBUKA (!)" if terbuka else "ditolak ACL"
        print("  [%2d/%2d] %-16s :%-5d (%s)  %s"
              % (i, ULANG_BRUTE_B, LDAP_B[0], PORT_BRUTE_B, LDAP_B[1], tanda))
        if i < ULANG_BRUTE_B:
            jeda(rata2, sekaligus)

    cl.close()
    print()


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--menit", type=float, default=7.0,
                   help="lama sebaran kejadian per penyerang, dalam menit (bawaan 7)")
    p.add_argument("--sekaligus", action="store_true",
                   help="tanpa jeda; semua percobaan ditembak berurutan")
    p.add_argument("--hanya-a", action="store_true", help="cuma Penyerang A (laptop)")
    p.add_argument("--hanya-b", action="store_true", help="cuma Penyerang B (nsm-data)")
    a = p.parse_args()

    jalan_a = not a.hanya_b
    jalan_b = not a.hanya_a

    print("Simulasi serangan lab NSM — %s\n"
          % ("tanpa jeda" if a.sekaligus else "disebar ~%.0f menit per penyerang" % a.menit))

    if jalan_a:
        jalankan_a(a.menit, a.sekaligus)
    if jalan_b:
        jalankan_b(a.menit, a.sekaligus)

    print("Selesai. Tunggu satu putaran poller (firewall dibaca tiap "
          "beberapa menit — lihat `get_firewall_interval()`), lalu buka "
          "halaman Firewall NSM: bagian 'Percobaan yang ditolak' dan "
          "'Percobaan yang ditolak ACL router'.")
    print("Kalau ada baris 'TERBUKA (!)' di atas: itu bukan kegagalan skrip "
          "ini — itu berarti port itu SUNGGUH tidak tertutup firewall, dan "
          "pantas diperiksa langsung, bukan diabaikan.")


if __name__ == "__main__":
    sys.exit(main())

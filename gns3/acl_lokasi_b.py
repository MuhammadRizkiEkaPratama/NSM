"""Install the ACL on R2: the inter-site firewall.

    Site A == ISP ==> [ R2 Fa0/1 ] --> Site B
                        ACL applied here, inbound

Fa0/1 is the only entrance to Site B, so unauthorized packets are dropped before entering the local network. Filtering outbound on Fa0/0 would also work, but packets would already have crossed the router and the ACL would not protect the router itself.

The allow list is derived from measurement:
    192.168.56.1    NSM  -> ping, SSH 22, SNMP 161, LDAP login 389
    192.168.56.103  web  -> LDAP 389 (sssd and E-Canteen)
Every `permit` must map to a real user. The database moved to Site A because the inter-site link adds 152 ms per round trip (a web page issues 10-50 queries); LDAP (once per login) and file servers may cross sites.

`permit tcp any any established` is a guard so replies are never held by this ACL. `deny ip any any log` is last, and `log` matters: without it, denials leave no trace.

Rollback: the config is sent over the GNS3 console, not the network, so a bad ACL cannot cut off the way to fix it; no timed safety net is needed.
"""
import sys

import konsol

HOST = "192.168.56.102"
PORT_R2 = 5004

NAMA_ACL = "DARI-LOKASI-A"

PERINTAH = [
    "configure terminal",
    # Remove any existing ACL first so re-running the script does not accumulate lines.
    "no ip access-list extended " + NAMA_ACL,
    "ip access-list extended " + NAMA_ACL,
    " remark dibuat NSM - memisahkan Lokasi A dari Lokasi B",
    " remark balasan untuk koneksi yang dimulai dari Lokasi B",
    " permit tcp any any established",
    " remark pemantauan NSM: ping ke seluruh Lokasi B",
    " permit icmp 192.168.56.0 0.0.0.255 192.168.20.0 0.0.0.255",
    " remark NSM: SSH ke .101, R2, dan SW-B (ambil konfigurasi)",
    " permit tcp host 192.168.56.1 192.168.20.0 0.0.0.255 eq 22",
    # The 3306 permits were removed when the database moved to Site A; a permit with no real user does not belong.
    " remark NSM: login lewat LDAP (satu-satunya yang masih perlu 389)",
    " permit tcp host 192.168.56.1 host 192.168.20.101 eq 389",
    # SNMP was found by the `log` line, not by planning: it is how bandwidth is monitored, not a monitored service. Without `log`, the bandwidth samples for .101 would silently stop.
    " remark NSM: SNMP untuk sampel bandwidth (ditemukan lewat deny log)",
    " permit udp host 192.168.56.1 host 192.168.20.101 eq 161",
    " remark server web .103: sssd dan E-Canteen ke direktori LDAP",
    " permit tcp host 192.168.56.103 host 192.168.20.101 eq 389",
    # Allows LDAP for hosts that need the directory, so admins do not need local accounts on every machine.
    " remark data server .104: sssd ke direktori LDAP (login admin terpusat)",
    " permit tcp host 192.168.56.104 host 192.168.20.101 eq 389",
    # NTP: the reply is what gets filtered. The request leaves Site B, but its UDP reply enters, and `permit tcp any any established` covers only TCP; without a UDP rule the clock never syncs.
    " remark NTP: JAWABAN dari sumber waktu lab (UDP tidak tertutup established)",
    " permit udp host 192.168.56.104 eq ntp 192.168.20.0 0.0.0.255",
    " remark sisanya ditolak DAN DICATAT",
    " deny ip any any log",
    " exit",
    "interface FastEthernet0/1",
    " description WAN ke ISP - disaring ACL " + NAMA_ACL,
    " ip access-group " + NAMA_ACL + " in",
    " exit",
    "end",
]


def main():
    print("=" * 66)
    print("Memasang ACL %s di R2 Fa0/1 (arah masuk)" % NAMA_ACL)
    print("=" * 66)

    k = konsol.Konsol(HOST, PORT_R2, timeout=60)
    try:
        konsol.masuk_enable(k)
        k.kirim("terminal length 0", 1.0)

        _out, salah = k.jalankan(PERINTAH, jeda=0.7)
        # `no ip access-list` for a missing ACL gives a harmless complaint; filtered so it does not read as a failure.
        salah = [(p, m) for p, m in salah if not p.startswith("no ip access-list")]
        if salah:
            for p, pesan in salah:
                print("  DITOLAK  %s" % p)
                print("           %s" % pesan.replace("\r\n", " ")[:150])
            return 1
        print("  semua perintah diterima")

        simpan = k.kirim("write memory", 5.0) + k.baca(5.0)
        if "[confirm]" in simpan:
            simpan += k.kirim("", 4.0)
        print("  simpan: %s" % ("OK" if "[OK]" in simpan else simpan.strip()[-90:]))

        print()
        print("== ACL terpasang ==")
        print(k.kirim("show ip access-lists " + NAMA_ACL, 3.0))
        print(k.kirim("show ip interface FastEthernet0/1 | include access list", 2.5))
    finally:
        k.tutup()
    return 0


if __name__ == "__main__":
    sys.exit(main())

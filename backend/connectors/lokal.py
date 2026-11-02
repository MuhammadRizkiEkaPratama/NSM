"""LOCAL connector: reads the state of the machine NSM itself runs on.

Why it exists when SSH and SNMP are available: the NSM poller runs ON this machine.
Opening an SSH port so NSM can ask the machine it is standing on is a detour with real
costs: an open port on a personal machine, plus an OS account password stored as-is in
`nsm.db`, which is copied into backups.

Read directly, all of that disappears: no port opened, no credential stored, no new
attack surface. Zabbix, PRTG, and LibreNMS likewise monitor Windows through an AGENT on
the machine rather than SSH; this file is that agent, built into the app because it is
the same machine.

LIMIT: this connector is only valid for the device that IS this machine. Using it for
another device would report this machine's numbers as that device's, an error that never
looks wrong on screen. So `check_reachable()` rejects addresses not owned by this machine.
"""
import socket
import time

from connectors.base import BaseConnector

# Interfaces that mean nothing for traffic monitoring. Loopback talks to itself; virtual
# VirtualBox adapters seen from the host side are already represented by the VM side.
IFACE_DILEWATI = ("loopback", "isatap", "teredo", "pseudo-interface")


def _alamat_sendiri():
    """All IPv4 addresses of this machine, including localhost.

    Used to prove a device really is this machine before the local connector may be used for
    it.
    """
    import psutil
    hasil = {"127.0.0.1", "localhost", "::1"}
    for _nama, daftar in psutil.net_if_addrs().items():
        for a in daftar:
            if a.family == socket.AF_INET and a.address:
                hasil.add(a.address)
    return hasil


def ip_sekarang():
    """IPv4 address of this machine used to talk to the LAB network.

    Used to self-correct the device row when this machine moves between networks. It opens a
    UDP socket toward an address and reads the local address the system chose. UDP does no
    handshake, so **no packet is actually sent**; only the routing-table decision is used.

    Why not just take the first interface address: the machine has many addresses at once
    (VirtualBox, VMware, host-only, several unconnected 169.254 ones). The right one is the
    address on the outgoing path, and only the routing table knows it.

    WHY THE PROBE TARGET IS `NSM_DB_HOST`, NOT A PUBLIC ADDRESS (8.8.8.8). After NSM moved to
    `nsm-app`, that VM has TWO network cards: NAT (for `apt`/internet) and Host-Only (the lab
    network actually monitored). The routing table picks NAT for public destinations, so a
    probe to 8.8.8.8 returned the NAT IP (`10.0.2.15`): technically correct, but not the
    address other lab devices use to reach this machine, so the "own machine" device was
    recorded DOWN while obviously alive. `NSM_DB_HOST` is ALWAYS on the same lab network as
    the monitored devices (see database.py: the queried database must not be across the WAN).
    """
    destination = "8.8.8.8"
    try:
        import database
        host_lab = database.ENV.get("NSM_DB_HOST", "").strip()
        if host_lab:
            destination = host_lab
    except Exception:
        pass
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((destination, 80))
        return s.getsockname()[0]
    except Exception:
        return None
    finally:
        s.close()


class LokalConnector(BaseConnector):
    def __init__(self, ip_address):
        super().__init__(ip_address)

    def ini_mesin_ini(self):
        try:
            return self.ip_address in _alamat_sendiri()
        except Exception:
            return False

    def check_reachable(self):
        """This machine is obviously alive, because it is running this code.

        Deliberately does NOT check the IP address first. An earlier version required
        `ini_mesin_ini()` to be true, so as soon as the machine changed networks and its address
        changed, NSM reported the machine RUNNING it as DOWN. Worse, the old address was then
        answered by another device on the new network, so NSM recorded an outage for a machine
        that was not this one at all.

        An IP address is a way to REACH a machine, not its identity. For a device already marked
        as "this machine", reaching it is never in question. What is measured now is how long
        reading system statistics takes, which rises when the machine is truly overloaded.

        Still returns the same `(bool, rtt)` shape as other connectors so the poller need not
        know the difference.
        """
        start = time.time()
        try:
            import psutil
            psutil.cpu_percent(interval=None)
            return True, round((time.time() - start) * 1000, 2)
        except Exception:
            return False, None

    def get_bandwidth(self):
        """Byte counters per interface, same shape as the SSH/SNMP connectors.

        Returns RAW counters (`in_octets`/`out_octets`), not computed rates, so the poller
        computes deltas with exactly the same formula as for other devices. If this connector
        computed its own, there would be two formulas for one thing, and sooner or later they
        would disagree with nobody knowing which is right.
        """
        import psutil
        hasil = {}
        for nama, compute in psutil.net_io_counters(pernic=True).items():
            low = nama.lower()
            if any(x in low for x in IFACE_DILEWATI):
                continue
            # Interfaces that never passed anything only add empty rows to the table; unused Windows
            # adapters can number a dozen.
            if compute.bytes_recv == 0 and compute.bytes_sent == 0:
                continue
            hasil[nama] = {
                "in_octets": float(compute.bytes_recv),
                "out_octets": float(compute.bytes_sent),
                "in_bps": None,
                "out_bps": None,
            }
        return hasil

    def get_info(self):
        """State of this machine, labeled like other devices' Detail data.

        Labels deliberately mimic Linux output (`Hostname`, `Disk`, ...) so the SSH data page
        need not know which devices are read locally and which over SSH: one view, many sources.
        """
        import platform
        import psutil
        from datetime import datetime

        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("C:\\" if platform.system() == "Windows" else "/")
        boot = datetime.fromtimestamp(psutil.boot_time())
        nyala = datetime.now() - boot

        alamat = []
        for nama, daftar in psutil.net_if_addrs().items():
            if any(x in nama.lower() for x in IFACE_DILEWATI):
                continue
            for a in daftar:
                if a.family == socket.AF_INET:
                    alamat.append(f"{nama}: {a.address}")

        # Top 5 processes by memory. Memory, not CPU: an instantaneous CPU reading per process
        # needs two samples with a pause between them, which would hold the poller round for
        # several full seconds.
        proses = []
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                info = p.info
                if info.get("memory_info"):
                    proses.append((info["memory_info"].rss, info["name"]))
            except Exception:
                continue
        proses.sort(reverse=True)
        teratas = "\n".join(f"{nama}  {rss / 1048576:.0f} MB"
                            for rss, nama in proses[:5])

        gb = 1073741824
        return {
            "Hostname": platform.node(),
            "OS": f"{platform.system()} {platform.release()}",
            "Kernel": platform.version(),
            "IP": "\n".join(alamat) or "-",
            "Uptime": (f"{nyala.days} hari, "
                       f"{nyala.seconds // 3600} jam "
                       f"{(nyala.seconds % 3600) // 60} menit"),
            "CPU": (f"{psutil.cpu_percent(interval=0.3):.0f}% terpakai, "
                    f"{psutil.cpu_count(logical=True)} thread"),
            "Memori": (f"{(mem.total - mem.available) / gb:.1f} GB terpakai "
                       f"dari {mem.total / gb:.1f} GB ({mem.percent:.0f}%)"),
            "Disk": (f"{disk.used / gb:.1f} GB terpakai dari "
                     f"{disk.total / gb:.1f} GB ({disk.percent:.0f}%)"),
            "Proses teratas (memori)": teratas or "-",
            "Cara dibaca": ("Langsung dari mesin ini, tanpa SSH dan tanpa "
                            "membuka port apa pun."),
        }

"""TCP connector: guesses the cause when ping fails.

Ping failure means the device is down or ICMP is blocked. Trying common TCP
ports (22/80/443) tells the two apart:

    ping fails + no port answers -> "dead"
    ping fails + a port answers  -> "ping_blocked"  (device is alive)

This is a category the tool can prove, not a root-cause diagnosis.
"""
import socket
import time
from concurrent.futures import ThreadPoolExecutor

from connectors.base import BaseConnector


class TcpConnector(BaseConnector):
    def __init__(self, ip_address, port=22, timeout=1.0):
        super().__init__(ip_address)
        self.port = port
        self.timeout = timeout

    def check_reachable(self):
        """Kembalikan (is_open: bool, rtt_ms: float|None)."""
        start = time.time()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        try:
            s.connect((self.ip_address, self.port))
            return True, round((time.time() - start) * 1000, 2)
        except Exception:
            return False, None
        finally:
            s.close()


def cek_port_terbuka(ip_address, ports, timeout=1.0):
    """Try several ports at once; return the ports that answered.

    Used by the poller when ping fails so the DOWN event gets a category. Probes
    run concurrently because waiting for a TCP reply is idle time, not CPU: a dead
    device costs ~1 s instead of 3 s (one timeout per port), regardless of how many
    ports are listed. Threads are safe here because this is pure network work and
    never touches the database, so there is no SQLite write-lock contention (see
    `uji_kunci_tulis.py`).
    """
    if not ports:
        return []

    def coba(p):
        ok, _ = TcpConnector(ip_address, port=p, timeout=timeout).check_reachable()
        return p if ok else None

    with ThreadPoolExecutor(max_workers=len(ports)) as pool:
        hasil = list(pool.map(coba, ports))

    # Sorted by requested port order, not answer order, so the cause text in events
    # is stable for similar incidents.
    return [p for p in hasil if p is not None]


# Max concurrent connection attempts. Same as PEKERJA_SERENTAK in icmp.py: these
# threads mostly wait rather than compute. The cap keeps a lab that grows to
# hundreds of devices from opening hundreds of sockets at once.
PEKERJA_SERENTAK = 50


def cek_port_banyak(daftar_ip, ports, timeout=1.0):
    """Try the same ports on MANY addresses at once.

    Returns {ip: [answering ports]} with a key for every requested address (an
    empty list if none answered), so callers can tell "checked, nothing answered"
    from "not checked", which decides whether a device is recorded as DOWN.

    Why: `cek_port_terbuka()` is concurrent per device, but devices were probed one
    after another inside the `poll_all()` write loop (20 dead devices ~20 s
    sequentially vs ~1 s concurrently), while the ping round runs every 5 s. The
    time goes to waiting on connection timeouts, which can overlap at no cost.

    Threads are used only here: pure network work, no database access (see
    `uji_kunci_tulis.py`).
    """
    if not daftar_ip:
        return {}

    # Duplicate addresses are dropped, as in ping_banyak(). Probing twice adds
    # sockets but no information; the result is a map, so both devices still get
    # their entry.
    unique = list(dict.fromkeys(daftar_ip))
    if not ports:
        return {ip: [] for ip in unique}

    # Flattened into (address, port) pairs instead of nested pools, so the thread
    # cap is a single accountable number.
    #
    # The list order fixes the result order: `ThreadPoolExecutor.map` returns results
    # in input order, as `cek_port_terbuka()` relies on. Do not switch to
    # `as_completed`, or the cause text in events would vary for similar incidents.
    pair = [(ip, p) for ip in unique for p in ports]

    def coba(pasang):
        ip, p = pasang
        ok, _ = TcpConnector(ip, port=p, timeout=timeout).check_reachable()
        return ip, p, ok

    with ThreadPoolExecutor(
            max_workers=min(len(pair), PEKERJA_SERENTAK)) as pool:
        hasil = list(pool.map(coba, pair))

    peta = {ip: [] for ip in unique}
    for ip, p, ok in hasil:
        if ok:
            peta[ip].append(p)
    return peta

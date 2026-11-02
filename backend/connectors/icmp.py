from icmplib import multiping, ping
from connectors.base import BaseConnector

# Ping settings, defined once so single and bulk checks cannot silently differ (two
# timeouts would mean two definitions of "down" in one product).
#
# Three packets with a 2-second timeout, not one packet and 1 second. Measured on devices
# behind the emulated GNS3 WAN (R1 -> ISP -> R2), where 100-1000 ms round trips are normal
# on Dynamips: with one packet, 15.8% of samples failed (314 of 1993), with a maximum of
# exactly 1000 ms, which is our own timeout. Devices that never went down flapped UP/DOWN
# all day.
#
# `is_alive` is True if at least one of the three packets is answered, so one lost packet
# no longer means "device down". This complements `DOWN_THRESHOLD` (consecutive failures):
# the threshold absorbs repeated brief failures, multiple packets absorb a single loss.
#
# Measured over 25 checks: 1 packet/1 s failed once (0.35 s per check); 3 packets/2 s never
# (1.24 s); 4 packets/2 s never (1.79 s). Three was chosen: it removed the false verdicts
# and is 0.55 s cheaper. Bulk ping runs in parallel (`multiping`), so 1.24 s covers all
# devices at once, well under the 10-second poll interval.
COUNT = 3
TIMEOUT = 2

# Gap between packets within ONE check. The `icmplib` default of 1 s would make each check
# take 3 s for no reason; 0.2 s avoids sending three packets at once (which can look like a
# burst) while keeping checks short.
INTERVAL = 0.2

PRIVILEGED = False

# How many checks may wait at once. This is not a count of busy threads; it is how many
# replies may be awaited concurrently, and waiting uses no CPU. Measured on 46 addresses:
# 0.02 s of CPU, while wall-clock time dropped from 53.99 s to 1.01 s.
PEKERJA_SERENTAK = 50


class IcmpConnector(BaseConnector):
    def check_reachable(self):
        host = ping(self.ip_address, count=COUNT, timeout=TIMEOUT,
                    interval=INTERVAL, privileged=PRIVILEGED)
        return host.is_alive, host.avg_rtt


def ping_banyak(daftar_ip):
    """Ping many addresses at once. Returns a map of ip to (alive, rtt).

    Sequential time grows linearly with the number of DEAD addresses, because proving that
    nobody answers means waiting out the timeout; concurrent time stays flat (46 addresses:
    53.99 s sequential vs 1.01 s concurrent). CPU time is near zero either way, so concurrency
    adds almost no load.

    The same address may appear more than once in `daftar_ip`; the result is a map keyed by
    address.
    """
    if not daftar_ip:
        return {}

    # Duplicate addresses are removed before sending: two devices can share an address (e.g.
    # one machine registered twice), and pinging it twice only doubles packets.
    unique = list(dict.fromkeys(daftar_ip))

    hasil = multiping(unique, count=COUNT, timeout=TIMEOUT, interval=INTERVAL,
                      privileged=PRIVILEGED, concurrent_tasks=PEKERJA_SERENTAK)
    return {h.address: (h.is_alive, h.avg_rtt) for h in hasil}

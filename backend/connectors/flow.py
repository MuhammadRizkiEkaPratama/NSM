"""FLOW reader: the network conversations currently active on a device.

Answers "which device talks to which, and how much" for ANY protocol, not just web
traffic. The source is `ss -tin`, which includes `bytes_sent` and `bytes_received` per
connection.

Three traffic sources in NSM, each answering something different:
    bandwidth_samples: bytes through an interface (no peer)
    akses_web:         who requested which page (HTTP only)
    flow_koneksi:      who talks to whom (all TCP)

Limitation: this is a periodic SNAPSHOT, not a full recording. Connections that start
and end between two reads are never seen, and `bytes_sent` is cumulative since the
connection opened, not a delta since the previous read.

READ-ONLY and needs no root: `ss` without `-p` does not touch process information.
"""
import re

# First line: state, queue, local address, peer address. `state established` already
# filters on the device, so the first column is Recv-Q rather than State.
#
# The address pattern forbids only NUL bytes (`[^\s\x00]+`), not a strict whitelist of IP
# characters. A strict class broke on real `ss -tin` output that contains Linux interface
# zone IDs such as `10.0.2.15%enp0s3`, which would silently drop valid connections. The
# NUL-only rule closes the real root cause (a NUL byte swallowed into a huge address, seen
# in `akseslog.py`) without rejecting valid but unfamiliar address forms.
POLA_ALAMAT = re.compile(
    r"^\s*(?P<recvq>\d+)\s+(?P<sendq>\d+)\s+"
    r"(?P<lokal>[^\s\x00]+):(?P<port_lokal>\d+)\s+"
    r"(?P<lawan>[^\s\x00]+):(?P<port_lawan>\d+)"
)

POLA_KIRIM = re.compile(r"bytes_sent:(\d+)")
POLA_TERIMA = re.compile(r"bytes_received:(\d+)")

PERINTAH = "ss -tin state established 2>/dev/null | tail -n +2"


def urai(keluaran, batas=200):
    """Parse `ss -tin` output into a list of connections.

    Two lines per connection: addresses on the first, metrics on the indented second line,
    which belongs to the most recently read connection, as `ss` lays it out.
    """
    hasil = []
    current = None
    for line in (keluaran or "").splitlines():
        if not line.strip():
            continue

        if line[0].isspace() and current is not None:
            send = POLA_KIRIM.search(line)
            receive = POLA_TERIMA.search(line)
            if send:
                current["byte_keluar"] = float(send.group(1))
            if receive:
                current["byte_masuk"] = float(receive.group(1))
            continue

        cocok = POLA_ALAMAT.match(line)
        if not cocok:
            continue
        g = cocok.groupdict()
        # [:45] is a second net, for the same reason as `POLA_ALAMAT` above: the column
        # (IP = String(45)) is length-limited whatever passes the regex.
        current = {
            "ip_lokal": g["lokal"].strip("[]")[:45],
            "port_lokal": int(g["port_lokal"]),
            "ip_lawan": g["lawan"].strip("[]")[:45],
            "port_lawan": int(g["port_lawan"]),
            "byte_masuk": None,
            "byte_keluar": None,
            "keadaan": "ESTAB",
        }
        hasil.append(current)
        if len(hasil) >= batas:
            break
    return hasil


def ambil(conn_ssh, timeout=20, batas=200):
    _in, out, _err = conn_ssh.exec_command(PERINTAH, timeout=timeout)
    return urai(out.read().decode("utf-8", errors="replace"), batas)


def ringkas_per_lawan(koneksi):
    """Sum per peer address. This is the shape that answers the real question: not "40
    connections" but "192.168.56.1 pulled 2.5 MB and sent 1.7 MB".
    """
    per = {}
    for k in koneksi:
        p = per.setdefault(k["ip_lawan"], {
            "ip": k["ip_lawan"], "koneksi": 0,
            "byte_masuk": 0.0, "byte_keluar": 0.0, "port": set(),
        })
        p["koneksi"] += 1
        p["byte_masuk"] += k.get("byte_masuk") or 0
        p["byte_keluar"] += k.get("byte_keluar") or 0
        if k.get("port_lokal"):
            p["port"].add(k["port_lokal"])
    for p in per.values():
        p["port"] = sorted(p["port"])
    return sorted(per.values(), key=lambda x: -(x["byte_masuk"] + x["byte_keluar"]))

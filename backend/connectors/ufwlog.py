"""Reader for /var/log/ufw.log: who TRIED to get through the Linux firewall and
was denied.

`ufw` writes every packet it rejects to the kernel syslog, like `deny ip any any
log` on a router ACL. `ufw status` only shows the rules, so without this reader
the Firewall page would look safe simply because NSM never asked.

Line format (standard syslog, one line per packet):

    2026-08-14T15:43:01+00:00 testUbuntu kernel: [UFW BLOCK] IN=enp0s8
    OUT= MAC=... SRC=192.168.56.1 DST=192.168.56.103 LEN=40 ...
    PROTO=TCP SPT=64323 DPT=80 ... ACK URGP=0

Read incrementally by byte offset, like the access log, not by per-line
fingerprint like router ACLs: `show logging` returns the whole buffer on every
call, so only fingerprints can tell old lines from new, but `ufw.log` is a real
file that grows at the end, so `tail -c +N` is enough and cheaper.

Stored in the existing `penolakan_acl` table (device_id, waktu, proto, dari,
port_dari, ke, port_ke). The `acl` column holds the literal "ufw" as the source
marker; readers tell router rows from ufw rows by that column, not by device
platform.

Read-only, like every log reader in the project.
"""
import hashlib
import re
from datetime import datetime, timezone

from connectors.akseslog import perintah_baca, baca_potongan

POLA_WAKTU = re.compile(r'^(\S+)\s+(\S+)\s+kernel:\s+\[UFW BLOCK\]\s+(.*)$')
# KEY=VALUE fields separated by spaces. `IN=enp0s8` matches; bare TCP flags such
# as `ACK` (no `=`) are not needed by the page and are skipped.
POLA_FIELD = re.compile(r'(\w+)=(\S*)')


def urai_waktu(teks):
    """'2026-08-14T15:43:01.140713+00:00' -> naive datetime in local time.

    Like `akseslog.urai_waktu`: the kernel writes UTC, NSM works in local time.
    Separate from the access log because the format is plain ISO 8601 (rsyslog
    default), not Apache's.
    """
    try:
        # Python < 3.11 rejects a literal "Z"; handled here even though the VM writes an
        # explicit +00:00 offset.
        t = teks.replace("Z", "+00:00")
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().replace(tzinfo=None)
    except Exception:
        return None


def urai_baris(baris):
    """One ufw.log line -> dict ready to store in `penolakan_acl`.

    None if the line is not a complete [UFW BLOCK]. Other lines (e.g. [UFW ALLOW])
    are skipped on purpose: only denied attempts matter, as with router ACLs.

    The hostname is included (`_hostname`) for a reason: the data host (nsm-data)
    shares a syslog socket with the SFTP chroot host (`/srv/berkas/dev/log`), so
    its `ufw.log` also contains messages written by the other host. Without the
    original hostname they would be stored as events on the wrong device. Callers
    MUST match this hostname against the device's real identity rather than assume
    a line belongs to the device whose log is being read.
    """
    cocok = POLA_WAKTU.match(baris.strip())
    if not cocok:
        return None
    # Order in the syslog line: TIMESTAMP HOSTNAME kernel: [UFW BLOCK] ...
    stamp_text, hostname, remaining = cocok.groups()
    waktu = urai_waktu(stamp_text)
    if waktu is None:
        return None

    f = dict(POLA_FIELD.findall(remaining))
    dari = f.get("SRC")
    ke = f.get("DST")
    if not dari or not ke:
        return None

    def ke_int(nilai):
        try:
            return int(nilai)
        except (TypeError, ValueError):
            return None

    # Shortened, without microseconds: `cap_router` is varchar(30) and the full ISO
    # stamp with microseconds and offset (32 chars) does not fit. Full precision is
    # kept in `waktu` (a separate DATETIME column); this is only the display text.
    cap_pendek = stamp_text.split(".")[0] if "." in stamp_text else stamp_text
    d = {
        "cap_router": cap_pendek[:30],  # legacy column name; holds the ufw stamp here
        "acl": "ufw",  # source marker, not a router ACL
        "aksi": "BLOCK",
        "proto": f.get("PROTO") or "?",
        "dari": dari,
        "port_dari": ke_int(f.get("SPT")),
        "ke": ke,
        "port_ke": ke_int(f.get("DPT")),
        "jumlah": 1,  # ufw logs ONE line per packet, no aggregation
        "baris": baris.strip()[:500],
        "_waktu_baca": waktu,
        "_hostname": hostname,
    }
    # Fingerprint from the ufw stamp plus addresses, not the whole line. The stamp
    # has microsecond precision so it is nearly unique per packet; dedup is done by
    # byte offset, and this only fills the column as router ACL rows do.
    d["sidik"] = hashlib.sha1(
        ("ufw|" + stamp_text + "|" + dari + "|" + ke + "|" + (f.get("DPT") or ""))
        .encode("utf-8")).hexdigest()
    return d


def ambil(conn_ssh, jalur, posisi_lama, timeout=25):
    """Read a chunk of ufw.log over an already-open SSH session.

    Returns the same shape as `akseslog.ambil()`: (entries, new_position, rotated,
    raw_line_count, exists), so the poller handles both with the same framework.
    """
    _in, out, _err = conn_ssh.exec_command(perintah_baca(jalur, posisi_lama),
                                           timeout=timeout)
    output = out.read().decode("utf-8", errors="replace")
    baris, posisi_baru, diputar, exists = baca_potongan(output, posisi_lama)
    entry = []
    for b in baris:
        d = urai_baris(b)
        if d:
            entry.append(d)
    return entry, posisi_baru, diputar, len(baris), exists

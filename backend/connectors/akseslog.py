"""Web server access log reader: who fetched what, and how much.

Interface counters know how many bytes passed but not who the peer was; only the server
that handled the request knows. Counters give a symptom, this log gives evidence.

Read INCREMENTALLY: the last read position is kept in the `posisi_log` table, otherwise
every round would re-insert the whole file and duplicate its own data.

READ-ONLY: log files are only read, never truncated or rotated.
"""
import re
from datetime import datetime

# Apache "combined" log line:
#   192.168.56.1 - - [28/Jul/2026:02:12:02 +0000] "GET /hello.php HTTP/1.1" 200 423 "-" "Mozilla/5.0"
#
# The last two fields are optional because the "common" format lacks them. The two extra
# trailing fields (bytes in and out) exist only if mod_logio is enabled; without them
# uploads are not recorded, and the page must say so instead of showing zero.
POLA = re.compile(
    r'^(?P<ip>[0-9a-fA-F:.]+)\s+\S+\s+(?P<pengguna>\S+)\s+'
    r'\[(?P<waktu>[^\]]+)\]\s+'
    r'"(?P<metode>[A-Z]+)\s+(?P<path>[^"\s]*)(?:\s+(?P<protokol>[^"]*))?"\s+'
    r'(?P<status>\d{3})\s+(?P<kirim>\d+|-)'
    r'(?:\s+"(?P<rujukan>[^"]*)"\s+"(?P<agen>[^"]*)")?'
    r'(?:\s+(?P<masuk>\d+)\s+(?P<keluar>\d+))?'
)

# Marker so NSM's own requests can be told apart from real visitors. Marked, not dropped:
# a monitor that hides its own traffic makes its numbers untrustworthy.
AGEN_NSM = "NSM-Monitor"

BULAN = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
         "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def urai_waktu(teks):
    """Convert '28/Jul/2026:02:12:02 +0000' to a datetime in local time.

    The timezone offset is applied, not discarded: Apache on the VM logs in UTC while NSM
    works in local time, and dropping the offset would shift the whole history by the UTC
    offset and make it impossible to compare with other events in the database.
    """
    try:
        date, remaining = teks.split(":", 1)
        hour_section, _, zona = remaining.rpartition(" ")
        d, b, y = date.split("/")
        hour, minute, second = hour_section.split(":")
        waktu = datetime(int(y), BULAN.get(b, 1), int(d),
                         int(hour), int(minute), int(second))
        if zona and len(zona) == 5 and zona[0] in "+-":
            shift = int(zona[1:3]) * 3600 + int(zona[3:5]) * 60
            if zona[0] == "+":
                shift = -shift
            from datetime import timedelta, timezone
            utc = waktu + timedelta(seconds=shift)
            return utc.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        return waktu
    except Exception:
        return None


def urai_baris(baris):
    cocok = POLA.match(baris.strip())
    if not cocok:
        return None
    g = cocok.groupdict()
    waktu = urai_waktu(g["waktu"])
    if waktu is None:
        return None

    def angka(nilai):
        if nilai is None or nilai == "-":
            return None
        try:
            return float(nilai)
        except ValueError:
            return None

    agen = g.get("agen") or ""
    return {
        "waktu": waktu,
        # [:45] = maximum length of an IPv6 literal (39 characters plus margin). A corrupt log
        # line (NUL bytes before the real IP) once got through as an `ip_klien` hundreds of bytes
        # long, exceeded the MySQL column ("Data too long"), and rolled back the whole round's
        # transaction: every other row for that device, including the SFTP log read progress.
        # `POLA` was tightened so such lines no longer match; this truncation is the second net,
        # like `path`/`rujukan`/`user_agent` below.
        "ip_klien": g["ip"][:45],
        "metode": g["metode"],
        "path": g["path"][:400],
        "protokol": (g.get("protokol") or "")[:20] or None,
        "status": int(g["status"]),
        "byte_kirim": angka(g.get("keluar")) or angka(g["kirim"]),
        "byte_terima": angka(g.get("masuk")),
        "rujukan": (g.get("rujukan") or "")[:300] or None,
        "user_agent": agen[:300] or None,
        "dari_nsm": 1 if AGEN_NSM in agen else 0,
    }


# Cap on how much is read in one pass. If NSM was down for days while the server stayed
# busy, the file can grow to tens of MB and pulling it over SSH would stall the poller
# round. Nothing is lost: the read position advances, so the next round continues there.
MAKS_BACA = 1_000_000     # 1 MB per putaran


def perintah_baca(jalur, posisi):
    """Shell command that fetches a log chunk from a given position.

    Returns the file size on the FIRST line, then the content. The size is read in the SAME
    command so there is no gap between measuring and reading; as two commands, lines
    arriving in between would be skipped silently.
    """
    posisi = int(max(0, posisi))
    # `-1` when the file does NOT EXIST, not `0`. A `|| echo 0` made a missing file
    # indistinguishable from an empty one (both give "zero new lines", no error), so the
    # poller
    # reported successful reads for files that never existed.
    return (
        f"stat -c %s {jalur} 2>/dev/null || echo -1; "
        f"tail -c +{posisi + 1} {jalur} 2>/dev/null | head -c {MAKS_BACA}"
    )


def baca_potongan(keluaran, posisi_lama):
    """Parse the output of `perintah_baca` into `(baris_baru, posisi_baru, diputar, ada)`.

    `diputar` is True when the file is smaller than the last position, meaning the log was
    rotated and reading must restart from the beginning. Without it NSM would go silent
    after logrotate because its position points past the end of the file.

    `ada` is False when the file does NOT EXIST. Distinguished from an empty file on
    purpose: both yield zero new lines, but one is normal and the other is a misconfiguration.

    A TRUNCATED LAST LINE IS DROPPED AND DOES NOT ADVANCE THE POSITION. `head -c MAKS_BACA`
    cuts the output at an exact byte, even mid-line. Counting that partial line and moving
    past it made the next round start mid-line, so the remainder (e.g. `168.56.1 - - [...]`)
    passed as a complete line with a WRONG client IP and appeared as a ghost address on the
    Traffic page. If the chunk does not end with a newline, the last line is incomplete (cut
    by `MAKS_BACA`, or the writer was half-way through a line). It is removed from `isi`
    before splitting, so it is excluded from `baris` and `posisi_baru`, and the next round
    re-reads it whole.

    Known limit: a single line longer than `MAKS_BACA` (1 MB) would stall the position, which
    does not happen with real access, SFTP or ufw log lines.
    """
    if not keluaran:
        return [], posisi_lama, False, True
    header, _, content = keluaran.partition("\n")
    try:
        size = int(header.strip())
    except ValueError:
        return [], posisi_lama, False, True

    if size < 0:
        return [], posisi_lama, False, False

    diputar = size < posisi_lama
    if diputar:
        posisi_lama = 0

    if content and not content.endswith("\n"):
        limit = content.rfind("\n")
        content = content[:limit + 1] if limit >= 0 else ""

    baris = [b for b in content.splitlines() if b.strip()]
    readable = sum(len(b.encode("utf-8", errors="replace")) + 1 for b in baris)
    posisi_baru = min(size, posisi_lama + readable)
    return baris, posisi_baru, diputar, True


def ambil(conn_ssh, jalur, posisi_lama, timeout=25):
    """Read a log chunk over an already-open SSH session. Takes a connected paramiko client
    instead of opening its own, so one poller round needs one connection for all commands.
    """
    _in, out, _err = conn_ssh.exec_command(perintah_baca(jalur, posisi_lama),
                                           timeout=timeout)
    keluaran = out.read().decode("utf-8", errors="replace")
    baris, posisi_baru, diputar, exists = baca_potongan(keluaran, posisi_lama)
    entry = []
    for b in baris:
        d = urai_baris(b)
        if d:
            entry.append(d)
    return entry, posisi_baru, diputar, len(baris), exists

"""Samba audit log reader: who touched which file on the shared folder.

Complements `sftplog.py`: that module covers SFTP (SSH) access, this one
covers users opening the SMB share from Windows Explorer.

Line format
-----------
Samba's `full_audit` module logs to syslog; rsyslog splits it into
`/var/log/samba-audit.log` (see `/etc/rsyslog.d/50-samba-audit.conf` on the
file server). Example:

    2026-08-19T01:49:57.351920+00:00 file-server smbd_audit: dewi|192.168.56.1|sharing|lab-pc|unlinkat|ok|/srv/sharing/secret.xlsx

Fields, separated by `|` and set by `full_audit:prefix = %u|%I|%S|%m`:

    user | client ip | share | client machine | operation | result | file

`result` is `ok` or `fail (<reason>)`; the reason is kept.

The two `openat` forms
----------------------
For `openat` only, Samba inserts one extra `r` or `w` field before the file
name (found by testing; the man page does not mention it). It is what
distinguishes reading/copying from modifying:

    dewi|...|openat|ok|r|/srv/sharing/report.xlsx     <- read / copied
    dewi|...|openat|ok|w|/srv/sharing/report.xlsx     <- written / modified

Noise filtering
---------------
Explorer polls folders constantly: opening a folder and deleting one file
yields ~40 lines, most of them `openat` on the same folder. Only noise that
answers no question is dropped:

    1. `openat` on the share root itself (Explorer refreshing the listing).
    2. `openat` on `.` and `..` (directory traversal artifacts).
    3. Identical events repeated within seconds (one action split into
       several protocol calls).

Never filtered: `unlinkat`, `renameat`, `mkdirat`, and any failed operation.
Filtering only decides what enters the NSM database; the raw log on the file
server is left intact for review.

READ-ONLY: the log file is never truncated or rotated.

Server-side copy (`offload_read_send`/`offload_write_send`)
-----------------------------------------------------------
When source and destination are on the same share, Windows asks the server
to copy the data itself via SMB2 FSCTL_SRV_COPYCHUNK, without the bytes
crossing the network. Samba logs this as `offload_read_send` followed by one
or more `offload_write_send` lines (one per chunk; large files produce many
lines for a single copy).

Limitation: `offload_*` lines carry no file name. The destination is taken
from the `openat...w` observed <10 ms before the offload sequence; the
source file is unknown (its handle was opened earlier and is not logged
again). A copy row therefore means "this file was created by a server-side
copy", not "copied from X". If no matching `openat...w` is found within a
reasonable window, the offload lines are dropped rather than guessed.
"""
import re
from datetime import datetime

# Syslog prefix plus the smbd_audit tag. The RFC3339 zone offset is used, not
# dropped: the file server runs in UTC while NSM uses local time (WIB), same
# as in sftplog.py.
KEPALA = re.compile(
    r"^(?P<waktu>\d{4}-\d{2}-\d{2}T[\d:.]+(?:[+-]\d{2}:\d{2}|Z))\s+"
    r"\S+\s+smbd_audit:\s+(?P<isi>.*)$"
)

# Modifying operations: never filtered as noise, however frequent.
MENGUBAH = {"unlinkat", "renameat", "mkdirat"}

# Labels used by the page (same vocabulary as sftplog.py so a combined table
# stays consistent).
AKSI = {
    "unlinkat": "HAPUS",
    "renameat": "GANTI_NAMA",
    "mkdirat": "BUAT_FOLDER",
    "connect": "SAMBUNG",
    "disconnect": "PUTUS",
    # Synthetic operation, never present in the raw log; see
    # `_tandai_salin_server()`.
    "salin_server": "SALIN",
}

# Max gap between `openat...w` and the offload sequence for them to count as
# one copy. Observed gaps are <10 ms; 2 s is deliberately loose to absorb
# network jitter.
OFFLOAD_JENDELA_DETIK = 2
# Max gap between consecutive offload_write_send chunks of the same copy
# (a large file produces many chunks).
OFFLOAD_BURST_DETIK = 5

# Seconds within which identical events count as one action.
JENDELA_KEMBAR_DETIK = 3


def urai_waktu(teks):
    """'2026-08-19T01:49:57.351920+00:00' -> local-time datetime."""
    try:
        t = datetime.fromisoformat(teks.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        return t
    return t.astimezone().replace(tzinfo=None)


def urai_baris(baris):
    """Parse one log line into a dict, or None if it is not a valid audit line.

    No filtering here: `gabung()` filters noise because it needs the
    neighboring lines. This keeps the parser testable against raw server lines.
    """
    k = KEPALA.match(baris.strip())
    if not k:
        return None
    isi = k.group("isi")

    # Guard against rsyslog repeat compression. Unless disabled (see
    # /etc/rsyslog.d/49-no-repeat.conf), rsyslog collapses identical consecutive
    # lines into:
    #   "message repeated N times: [ <original line> ]"
    # The tag and the original fields survive, so the "|" split below would still
    # yield >=7 fields and `pengguna` would read
    # "message repeated N times: [ <user>". `49-no-repeat.conf` prevents new
    # ones; this check rejects those already in the log.
    if isi.lstrip().lower().startswith("message repeated"):
        return None

    waktu = urai_waktu(k.group("waktu"))
    if waktu is None:
        return None

    section = isi.split("|")
    # user|ip|share|machine|operation|result|[rw]|file -> at least 7 fields
    if len(section) < 7:
        return None

    pengguna, ip, berbagi, engine, operasi, hasil = section[:6]
    remaining = section[6:]

    # `openat` inserts a direction field (r/w) before the file name; other
    # operations do not. Detected from the field content, not the field count,
    # because file names may contain "|" (e.g. "report|final.xlsx").
    arah = None
    if operasi == "openat" and remaining and remaining[0] in ("r", "w"):
        arah = remaining[0]
        remaining = remaining[1:]
    jalur = "|".join(remaining)

    # `renameat` writes "old|new" in the file field.
    jalur_baru = None
    if operasi == "renameat" and "|" in jalur:
        jalur, jalur_baru = jalur.split("|", 1)

    return {
        "waktu": waktu,
        "pengguna": (pengguna or None) and pengguna[:100],
        "ip_klien": (ip or None) and ip[:45],
        "berbagi": (berbagi or None) and berbagi[:100],
        "mesin_klien": (engine or None) and engine[:100],
        "operasi": operasi,
        "arah": arah,
        # "ok" or "fail (reason)"; the reason is kept intact.
        "hasil": "ok" if hasil == "ok" else "gagal",
        "sebab": None if hasil == "ok" else hasil,
        "jalur": jalur.strip()[:500],
        "jalur_baru": jalur_baru.strip()[:500] if jalur_baru else None,
    }


# Files Windows Explorer probes in every opened folder (custom icons, view
# metadata), not something the user asked for. Only FAILED attempts on these
# names are filtered; a successful open means the file really exists and is
# still worth logging.
INTAIAN_EXPLORER = {
    "folder.jpg", "folder.gif", "folder.ico", "desktop.ini",
    "thumbs.db", "autorun.inf", "albumart.jpg", "albumartsmall.jpg",
}


def _direktori_dari_data(diurai):
    """Set of paths proven to be folders by the log data itself, not guessed.

    Evidence: (1) the path is the target of a successful `mkdirat`; (2) another
    path in the same log chunk starts with "<path>/".

    Folders are deliberately not guessed from the name (e.g. "no extension"):
    Windows folders often have free-form names and extensionless files exist
    (Dockerfile, Makefile, README).
    """
    direktori = set()
    all_path = set()
    for p in diurai:
        if p["jalur"]:
            all_path.add(p["jalur"])
        if p["jalur_baru"]:
            all_path.add(p["jalur_baru"])
        if p["operasi"] == "mkdirat" and p["hasil"] == "ok" and p["jalur"]:
            direktori.add(p["jalur"])

    for candidate in all_path:
        prefix = candidate + "/"
        if any(j.startswith(prefix) for j in all_path if j != candidate):
            direktori.add(candidate)
    return direktori


def _derau(p, akar_share, direktori):
    """True if the line is just Explorer browsing, not a user action.

    `akar_share` is the shared folder path, e.g. "/srv/sharing".
    `direktori` is the output of `_direktori_dari_data()` for the same log chunk.
    """
    jalur = (p["jalur"] or "").rstrip("/")

    if p["operasi"] == "openat" and p["hasil"] != "ok":
        if jalur.rsplit("/", 1)[-1].lower() in INTAIAN_EXPLORER:
            return True  # Explorer probing custom icons, not a user action
    if p["operasi"] in MENGUBAH or p["hasil"] != "ok":
        return False  # other changes and failures are never filtered
    if p["operasi"] != "openat":
        return False  # connect/disconnect are kept
    if jalur in ("", akar_share.rstrip("/")):
        return True  # opening the share root = refreshing the listing
    if jalur.endswith("/.") or jalur.endswith("/.."):
        return True  # directory traversal artifact
    if p["arah"] == "r" and jalur in direktori:
        # Opening a folder, not a file. Explorer reopens the same folder while its
        # window is open or refreshed; otherwise this would look like a file download.
        return True
    return False


def _tandai_salin_server(diurai):
    """Pair offload_read_send/offload_write_send with the preceding `openat...w`
    and collapse the sequence into one "salin_server" event.

    Returns (diurai_baru, jumlah_disaring). Raw offload lines never reach
    `diurai_baru`: matched sequences become one copy row; unmatched ones are
    dropped, since the file is unknown and a row without a file name only
    confuses.

    A matched `openat...w` is also removed and replaced by the copy row;
    otherwise one copy would be recorded twice (as `KIRIM` and as `SALIN`).
    """
    write_last = {}  # (user, machine) -> unclaimed openat...w event
    burst_active = {}  # (user, machine) -> synthetic copy event being built
    diklaim = set()  # id() of openat...w events already turned into copies
    tambahan = []
    filtered = 0

    for p in diurai:
        if p["operasi"] == "openat" and p["arah"] == "w" and p["hasil"] == "ok":
            write_last[(p["pengguna"], p["mesin_klien"])] = p
            continue

        if p["operasi"] not in ("offload_read_send", "offload_write_send"):
            continue

        kunci = (p["pengguna"], p["mesin_klien"])
        if p["hasil"] != "ok":
            filtered += 1
            continue

        burst = burst_active.get(kunci)
        if burst is not None:
            pause = (p["waktu"] - burst["waktu"]).total_seconds()
            if 0 <= pause <= OFFLOAD_BURST_DETIK:
                burst["waktu"] = p["waktu"]  # extend to the last chunk
                filtered += 1
                continue

        w = write_last.get(kunci)
        if w is None or not (0 <= (p["waktu"] - w["waktu"]).total_seconds()
                              <= OFFLOAD_JENDELA_DETIK):
            # No matching openat...w within the window: drop it rather than guess a copy
            # without a file name.
            filtered += 1
            burst_active.pop(kunci, None)
            continue

        diklaim.add(id(w))
        copy = dict(w)
        copy["operasi"] = "salin_server"
        copy["arah"] = None
        copy["waktu"] = p["waktu"]
        tambahan.append(copy)
        burst_active[kunci] = copy

    diurai_baru = [p for p in diurai
                   if p["operasi"] not in ("offload_read_send", "offload_write_send")
                   and id(p) not in diklaim]
    diurai_baru.extend(tambahan)
    return diurai_baru, filtered


def gabung(baris_baris, akar_share="/srv/sharing"):
    """Turn log lines into a list of events ready to store.

    Returns (kejadian, jumlah_derau_disaring). The noise count is reported so
    that a page that looks incomplete can be checked against it.
    """
    diurai = [p for p in (urai_baris(b) for b in baris_baris) if p is not None]
    diurai, filtered_copy = _tandai_salin_server(diurai)
    direktori = _direktori_dari_data(diurai)

    occurrence = []
    filtered = 0
    last = {}  # (user, operation, path, direction) -> last seen time

    for p in diurai:
        if _derau(p, akar_share, direktori):
            filtered += 1
            continue

        # Identical events within seconds are one human action split by the protocol.
        # Two kinds are exempt from deduplication:
        #
        #   - modifying operations: two deletes of the same file within 3 s are two
        #     distinct events.
        #   - failures: a failed attempt on a file that was just opened successfully
        #     is not a duplicate, so `hasil` is part of the dedup key.
        if p["operasi"] not in MENGUBAH and p["hasil"] == "ok":
            kunci = (p["pengguna"], p["operasi"], p["jalur"], p["arah"])
            previous = last.get(kunci)
            if previous is not None:
                difference = (p["waktu"] - previous).total_seconds()
                if 0 <= difference < JENDELA_KEMBAR_DETIK:
                    filtered += 1
                    continue
            last[kunci] = p["waktu"]

        occurrence.append(_siap_simpan(p, akar_share))

    return occurrence, filtered + filtered_copy


def _siap_simpan(p, akar_share):
    """Final shape matching the `TransferBerkas` columns."""
    if p["operasi"] == "openat":
        aksi = "AMBIL" if p["arah"] == "r" else "KIRIM"
    else:
        aksi = AKSI.get(p["operasi"], p["operasi"].upper())

    # Paths are shortened relative to the share root ("/srv/sharing/a/b.txt" ->
    # "a/b.txt"); the common prefix only wastes column width.
    def pendek(j):
        if not j:
            return j
        root_cause = akar_share.rstrip("/")
        return j[len(root_cause) + 1:] if j.startswith(root_cause + "/") else j

    return {
        "waktu": p["waktu"],
        "pengguna": p["pengguna"],
        "ip_klien": p["ip_klien"],
        "mesin_klien": p["mesin_klien"],
        "berbagi": p["berbagi"],
        "aksi": aksi,
        "hasil": p["hasil"],
        "jalur": pendek(p["jalur"]),
        "jalur_baru": pendek(p["jalur_baru"]),
        "sumber": "SMB",
        # full_audit logs operations, not volume. Zero here means "unknown", not
        # "zero bytes"; see the note in models.py.
        "byte_baca": 0.0,
        "byte_tulis": 0.0,
        "pid": None,
    }


def ambil(conn_ssh, jalur, posisi_lama, akar_share="/srv/sharing", timeout=25):
    """Read a chunk of the audit log over an already-open SSH session.

    Reuses `akseslog.perintah_baca`/`baca_potongan`, shared with the access log
    and SFTP readers (including dropping a trailing line cut at the 1 MB limit).
    Duplicating that logic would risk silently skipped lines.

    File sizes are not fetched via `stat`: the `nsmro` SSH account is not in the
    `berkas` group, and `/srv/sharing` is `drwxrws---` owned by `root:berkas`, so
    it cannot even enter the folder. Fixing that would need ACL changes on the
    file server, so SMB transfers keep an unknown size.
    """
    from connectors import akseslog

    _in, out, _err = conn_ssh.exec_command(
        akseslog.perintah_baca(jalur, posisi_lama), timeout=timeout)
    output = out.read().decode("utf-8", errors="replace")
    baris, position_new, rotated, exists = akseslog.baca_potongan(
        output, posisi_lama)
    occurrence, filtered = gabung(baris, akar_share)
    return occurrence, filtered, position_new, rotated, exists

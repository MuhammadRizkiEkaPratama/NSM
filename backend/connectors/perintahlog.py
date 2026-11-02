"""Reader for command history from auditd: who ran which command.

Complements the SMB audit (`sambaaudit.py`): that answers "which file was touched", this
answers "which command was typed". The server's shell for the file-share group is
overridden locally on this server only, not in the directory.

WHY AUDITD, NOT TLOG. `tlog` (re-recording the terminal screen, replayable like a video)
does not produce a tidy list; you must replay it to know what happened. A table is what is
needed: time, who, which command, like the existing file Event Log. `auditd` with an
`execve` rule gives that directly.

LINE SHAPE. One EVENT (one command run) is spread over TWO consecutive log lines, joined
by the same event id (the number after the colon in `audit(<epoch>:<id>)`):

    type=SYSCALL msg=audit(1787127164.487:446): ... auid=10003 ... ses=2196
        comm="ls" exe="/usr/bin/ls" ... key="perintah_pengguna" ...
        AUID="dewi" ...
    type=EXECVE msg=audit(1787127164.487:446): argc=3 a0="ls" a1="-la"
        a2="/srv/sharing"

The first line (SYSCALL) says WHO (`AUID`, translated by auditd itself from number to
name) and the command NAME (`comm`). The second (EXECVE) gives the arguments. CWD/PATH/
PROCTITLE lines in between are ignored; they are not harmful noise, just not needed here.

The client IP is in neither line. It is in the `USER_START` record (once per SSH session,
not per command) with the SAME `ses=`. So those are collected separately and joined by
session number. If the session was opened BEFORE the log chunk being read (e.g. someone
logged in long ago and only now runs a command), the address is unknown for that event.
It is left empty, not guessed.

KNOWN LIMIT. The MOTD-descendant filter (see `_PENANDA_AKAR_DERAU`) cuts login noise from
about 90% of lines to far fewer (576 -> 63 events in a real test), but it is NOT
perfect. Fragments such as `cut -d ' ' -f4` or `sort -r` sometimes slip through because
their names are too common to filter by content (filtering by name could hide REAL
commands with the same name), and the ppid link to the MOTD script is sometimes broken
through pipes. They are left visible on purpose: honest noise beats filtering that
silently drops real commands.

TWO LINES OF ONE EVENT CAN BE CUT AT THE LOG CHUNK BOUNDARY. `baca_potongan` (used via
`akseslog`) guarantees whole LINES, not whole EVENTS: a SYSCALL line can be the LAST line
of a chunk with its EXECVE arriving in the NEXT chunk. A SYSCALL without its EXECVE in the
same chunk is DROPPED for this round, not stored half-done. Worst case an event is
recorded slightly late, never recorded wrong.
"""
import re
from datetime import datetime

# Event id = "<epoch_seconds>.<epoch_millis>:<sequence>", used to join the SYSCALL and
# EXECVE that describe the SAME event.
#
# The join key must be EPOCH+NUMBER, not the number alone: auditd sequence numbers are NOT
# unique forever, they restart from a small value whenever auditd is reloaded
# (`augenrules --load` or a service restart). After several reloads, two events from
# DIFFERENT times can share a sequence number, and keying on it alone pairs a SYSCALL with
# the EXECVE of another moment, producing a wrong user name with no error at all. Epoch plus
# number never collides because the epoch is unique across the log.
_ID = re.compile(r'msg=audit\((?P<epoch>\d+\.\d+):(?P<id>\d+)\):')

# FALLBACK UID -> name translator, and why it must exist.
#
# `auditd` should translate by itself (`log_format = ENRICHED` in /etc/audit/auditd.conf,
# which is the case on this server). But under heavy load (thousands of lines in seconds)
# some lines lose the `AUID="..."` field and keep only the raw `auid=10003`: the translation
# depends on a name lookup (NSS/sssd) at the moment of writing, which can fail silently when
# the system is busy.
#
# This map is used ONLY as a fallback when the `AUID=` field that auditd should have filled
# is MISSING. It lists the human accounts that really exist on this server (checked with
# `getent passwd`, not guessed). A UID not listed here is still written as the raw number,
# never guessed into a wrong name.
_PETA_UID_CADANGAN = {
    "1000": "labadmin",
    "10003": "dewi",
    "10004": "bagas",
    "10007": "intan",
    "10008": "arif",
}

# Commands not worth recording: systemd child processes triggered by the login session
# itself. Filtered by EXE (full path), NOT by comm: comm turned out to be just "9" (a
# random number from the kernel, not a meaningful process name) while exe clearly names
# "/usr/lib/systemd/systemd-executor".
_EXE_SISTEM = ("/usr/lib/systemd/systemd-executor",)


def _teks_argc(isi):
    """Fields a0..aN of an EXECVE line -> list of command+argument texts.

    Values are USUALLY quoted ("ls"), but auditd switches to unquoted HEX when an argument
    contains characters that cannot be printed as-is. Both forms are handled, so an odd
    argument (a file name with control characters, say) still comes out as correct text, not
    an error or a raw hex string.
    """
    m = re.match(r'^argc=(\d+)\s+(.*)$', isi)
    if not m:
        return None
    argc = int(m.group(1))
    remaining = m.group(2)
    hasil = []
    for i in range(argc):
        find = re.search(r'\ba%d=(?:"(?P<kutip>[^"]*)"|(?P<heks>[0-9A-Fa-f]+))' % i,
                         remaining)
        if not find:
            hasil.append("?")
            continue
        if find.group("kutip") is not None:
            hasil.append(find.group("kutip"))
        else:
            try:
                hasil.append(bytes.fromhex(find.group("heks")).decode(
                    "utf-8", errors="replace"))
            except ValueError:
                hasil.append(find.group("heks"))
    return hasil


def urai_baris_syscall(baris):
    """One `type=SYSCALL ... key="perintah_pengguna"` line -> dict, or None if it is not the
    wanted line (not a SYSCALL, or another key).
    """
    if 'type=SYSCALL' not in baris or 'key="perintah_pengguna"' not in baris:
        return None
    idm = _ID.search(baris)
    if not idm:
        return None

    def ambil(pola, wajib=True):
        m = re.search(pola, baris)
        return m.group(1) if m else (None if not wajib else None)

    sukses = ambil(r'\bsuccess=(yes|no)\b')
    auid = ambil(r'\bauid=(\d+)\b')
    ses = ambil(r'\bses=(\d+)\b')
    pid = ambil(r'\bpid=(\d+)\b')
    ppid = ambil(r'\bppid=(\d+)\b')
    comm = ambil(r'\bcomm="([^"]*)"')
    exe = ambil(r'\bexe="([^"]*)"')
    auid_nama = ambil(r'\bAUID="([^"]*)"')
    # "unset" is a legitimate auditd value (a process with no login session, e.g.
    # auid=4294967295), not something that needs a fallback lookup.
    if auid_nama in (None, "unset", "?"):
        auid_nama = _PETA_UID_CADANGAN.get(auid)

    if exe in _EXE_SISTEM:
        return None

    try:
        waktu = datetime.fromtimestamp(float(idm.group("epoch")))
    except (ValueError, OSError):
        return None

    return {
        "id": idm.group("epoch") + ":" + idm.group("id"),
        "waktu": waktu,
        "auid": auid,
        "pengguna": (auid_nama or auid or "?")[:100],
        "sesi": ses,
        "pid": pid,
        "ppid": ppid,
        "perintah": (comm or "?")[:100],
        "exe": (exe or None) and exe[:300],
        "berhasil": sukses == "yes",
    }


def urai_baris_execve(baris):
    if 'type=EXECVE' not in baris:
        return None
    idm = _ID.search(baris)
    if not idm:
        return None
    argc_m = re.search(r':\s*(argc=.*)$', baris)
    if not argc_m:
        return None
    argumen = _teks_argc(argc_m.group(1))
    if not argumen:
        return None
    return idm.group("epoch") + ":" + idm.group("id"), " ".join(argumen)[:1000]


def urai_baris_sesi_mulai(baris):
    """`type=USER_START` (SSH session opened) -> `(session_number, ip)` or None.

    Used ONLY to attach an IP address to commands through `ses=`. Not a replacement for NSM's
    own login audit (different page, different table); it is just the address attached to a
    session.
    """
    if 'type=USER_START' not in baris or 'sshd' not in baris:
        return None
    ses = re.search(r'\bses=(\d+)\b', baris)
    ip = re.search(r'\baddr=(\S+)\b', baris)
    if not ses or not ip or ip.group(1) in ("?", "(none)"):
        return None
    return ses.group(1), ip.group(1)[:45]


# Markers for the ROOT of automatic login noise. Every SSH login triggers
# `run-parts /etc/update-motd.d` (the welcome message), which runs DOZENS of child scripts
# (find, grep, cut, tr, stat, date, expr, awk, sort, id, ...). They cannot be filtered by
# command NAME: a real person CAN type `find` or `grep`, and filtering by name would hide
# those too.
#
# What is used instead is PROCESS RELATIONSHIP: an event whose ARGUMENTS mention one of
# these auto-login script paths is the ROOT, and ALL its descendants (tracked via
# ppid -> pid, at any depth) are filtered with it, not because of their names but because
# they were spawned by the same process.
_PENANDA_AKAR_DERAU = (
    # No trailing slash on purpose: `run-parts` itself names the directory WITHOUT a trailing
    # slash (`run-parts ... /etc/update-motd.d`) while its child scripts are called WITH one
    # (`/etc/update-motd.d/00-header`). A substring without the slash matches BOTH forms.
    "/etc/update-motd.d", "/usr/lib/update-notifier",
    "/usr/lib/ubuntu-release-upgrader", "/usr/share/unattended-upgrades",
    "landscape-sysinfo",
    # These two are not script paths but TYPICAL CONTENT of checks that escaped ppid tracking:
    # a pipe (`|`) creates a new process whose ppid is not always recorded straight to the same
    # parent. The content is distinctive enough (who types "overlayroot|/media/root-ro"
    # themselves?) to be a safe direct marker.
    "overlayroot|/media/root-ro", "/proc/loadavg",
)


def gabung(baris_baris):
    """Turn log lines into a list of events (commands) ready to store.

    Returns `(events, filtered_count)`. The filtered count covers SYSCALL lines whose EXECVE
    is missing from the same chunk AND all descendants of the auto-login scripts (see
    `_PENANDA_AKAR_DERAU`), not only the system commands dropped in `urai_baris_syscall`.
    """
    syscall_tertunda = {}
    ip_per_session = {}          # nomor sesi -> alamat IP
    raw = []
    filtered = 0

    for b in baris_baris:
        session_ip = urai_baris_sesi_mulai(b)
        if session_ip:
            ip_per_session[session_ip[0]] = session_ip[1]
            continue

        sc = urai_baris_syscall(b)
        if sc:
            syscall_tertunda[sc["id"]] = sc
            continue

        ev = urai_baris_execve(b)
        if ev:
            id_, argumen = ev
            sc = syscall_tertunda.pop(id_, None)
            if sc is None:
                filtered += 1
                continue
            raw.append({
                "waktu": sc["waktu"],
                "pengguna": sc["pengguna"],
                "perintah": sc["perintah"],
                "argumen": argumen,
                "berhasil": sc["berhasil"],
                "ip_klien": ip_per_session.get(sc["sesi"]),
                "sesi": sc["sesi"],
                "pid": sc["pid"],
                "ppid": sc["ppid"],
            })

    # SYSCALL that never got its EXECVE in this chunk: cut off by the read limit. Dropped, not
    # stored half-done.
    filtered += len(syscall_tertunda)

    # Filter all descendants of the auto-login script, via ppid->pid
    root_cause = {k["pid"] for k in raw
            if k["pid"] and any(p in k["argumen"] for p in _PENANDA_AKAR_DERAU)}
    if root_cause:
        child_from = {}
        for k in raw:
            if k["pid"] and k["ppid"]:
                child_from.setdefault(k["ppid"], []).append(k["pid"])
        derau_pid = set(root_cause)
        antrian = list(root_cause)
        while antrian:
            parent = antrian.pop()
            for child in child_from.get(parent, []):
                if child not in derau_pid:
                    derau_pid.add(child)
                    antrian.append(child)
    else:
        derau_pid = set()

    occurrence = []
    for k in raw:
        if k["pid"] in derau_pid:
            filtered += 1
            continue
        k.pop("pid", None)
        k.pop("ppid", None)
        occurrence.append(k)

    return occurrence, filtered


def ambil(conn_ssh, jalur, posisi_lama, timeout=25):
    """Read an auditd log chunk over an already-open SSH session.

    Uses the same `akseslog.perintah_baca`/`baca_potongan` as every other log reader in NSM,
    including the truncated-line fix: one place to fix, shared, not copied.
    """
    from connectors import akseslog

    _in, out, _err = conn_ssh.exec_command(
        akseslog.perintah_baca(jalur, posisi_lama), timeout=timeout)
    output = out.read().decode("utf-8", errors="replace")
    baris, position_new, rotated, exists = akseslog.baca_potongan(
        output, posisi_lama)
    occurrence, filtered = gabung(baris)
    return occurrence, filtered, position_new, rotated, exists

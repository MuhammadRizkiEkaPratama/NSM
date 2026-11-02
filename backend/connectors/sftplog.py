"""SFTP log reader: who downloaded which file, and how large it was.

Interface counters and web access logs identify addresses, which change
hands (shared laptops, DHCP). SFTP runs on LDAP identities, so this log
identifies the person:

    interface counter : "48 MB left .103 this afternoon"
    web access log    : "192.168.56.1 downloaded /uji-50mb.bin, 200"
    SFTP log          : "DEWI downloaded cctv-lobby.zip, 40 MB, 23:15"

Log format and why the PID is the key
-------------------------------------
`internal-sftp -l INFO` writes to auth.log like this:

    ... internal-sftp[607516]: session opened for local user dewi from [192.168.56.1]
    ... internal-sftp[607516]: open "/public/report.pdf" flags READ mode 0666
    ... internal-sftp[607516]: close "/public/report.pdf" bytes read 2097152 written 0
    ... internal-sftp[607516]: session closed for local user dewi from [192.168.56.1]

Only the first line names the user; the file and byte lines are linked to it
solely by the process id. A session can outlive many poller cycles and NSM
restarts, so the pid -> user map is persisted in the `sesi_sftp` table
rather than kept in memory.

scp is captured too: modern OpenSSH runs scp over SFTP, so administrator
transfers are included on purpose.

READ-ONLY: the log file is never truncated or rotated.
"""
import re
from datetime import datetime, timezone

# Line prefix: RFC3339 time, host name, program, pid.
#
# The zone offset (e.g. `+00:00`) is used, not dropped: the VM runs in UTC
# while NSM uses local time (WIB). Dropping it would shift all history by
# seven hours relative to other events in the database.
KEPALA = re.compile(
    r'^(?P<waktu>\d{4}-\d{2}-\d{2}T[\d:.]+(?:[+-]\d{2}:\d{2}|Z))\s+'
    r'\S+\s+internal-sftp\[(?P<pid>\d+)\]:\s+(?P<isi>.*)$'
)

# `[192.168.56.1]`: the brackets are part of the OpenSSH format.
#
# `ip` is restricted to valid IPv4/IPv6 characters instead of `[^\]]+`, so NUL
# bytes or other junk inside the brackets cannot end up in `ip_klien`. Such
# values make MySQL reject the row (`Data too long`), and because
# `simpan_traffic_device()` stores SFTP and access log rows in one
# transaction, that would roll back all of the device's traffic data for the
# cycle (the same issue was seen in `akseslog.py`).
SESI_BUKA = re.compile(
    r'^session opened for local user (?P<pengguna>\S+) from \[(?P<ip>[0-9a-fA-F:.]+)\]')
SESI_TUTUP = re.compile(r'^session closed for local user (?P<pengguna>\S+)')

BUKA = re.compile(r'^open "(?P<jalur>.*)" flags (?P<flags>\S+)')
TUTUP = re.compile(
    r'^close "(?P<jalur>.*)" bytes read (?P<baca>\d+) written (?P<tulis>\d+)')
HAPUS = re.compile(r'^remove name "(?P<jalur>.*)"')
GANTI = re.compile(r'^rename old "(?P<lama>.*)" new "(?P<baru>.*)"')
BUAT_FOLDER = re.compile(r'^mkdir name "(?P<jalur>.*)"')
HAPUS_FOLDER = re.compile(r'^rmdir name "(?P<jalur>.*)"')

AMBIL = "AMBIL"
KIRIM = "KIRIM"


def urai_waktu(teks):
    """'2026-08-08T23:15:40.390913+00:00' -> local-time datetime."""
    try:
        t = datetime.fromisoformat(teks.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        return t
    return t.astimezone().replace(tzinfo=None)


def urai_baris(baris):
    """Parse one auth.log line into an event, or None if it is not an sftp line.

    The result has no user because the line does not name one; `gabung()`
    attaches the user via the pid map.
    """
    k = KEPALA.match(baris.strip())
    if not k:
        return None
    waktu = urai_waktu(k.group("waktu"))
    if waktu is None:
        return None
    pid = int(k.group("pid"))
    isi = k.group("isi")

    m = SESI_BUKA.match(isi)
    if m:
        return {"jenis": "buka_sesi", "waktu": waktu, "pid": pid,
                "pengguna": m.group("pengguna"), "ip": m.group("ip")}

    m = SESI_TUTUP.match(isi)
    if m:
        return {"jenis": "tutup_sesi", "waktu": waktu, "pid": pid}

    m = BUKA.match(isi)
    if m:
        return {"jenis": "buka_berkas", "waktu": waktu, "pid": pid,
                "jalur": m.group("jalur"), "flags": m.group("flags")}

    m = TUTUP.match(isi)
    if m:
        return {"jenis": "tutup_berkas", "waktu": waktu, "pid": pid,
                "jalur": m.group("jalur"),
                "baca": int(m.group("baca")), "tulis": int(m.group("tulis"))}

    for pattern, aksi in ((HAPUS, "HAPUS"), (BUAT_FOLDER, "BUAT_FOLDER"),
                       (HAPUS_FOLDER, "HAPUS_FOLDER")):
        m = pattern.match(isi)
        if m:
            return {"jenis": "aksi", "waktu": waktu, "pid": pid,
                    "aksi": aksi, "jalur": m.group("jalur")}

    m = GANTI.match(isi)
    if m:
        return {"jenis": "aksi", "waktu": waktu, "pid": pid,
                "aksi": "GANTI_NAMA", "jalur": m.group("lama"),
                "jalur_baru": m.group("baru")}

    # opendir/closedir/stat/lstat/realpath and similar are ignored on purpose:
    # they are numerous, answer nothing about who took what, and would bury real
    # transfers among folder-browsing lines.
    return None


def arah(baca, tulis, flags):
    """Download (`AMBIL`) or upload (`KIRIM`)?

    Byte counts are trusted over flags because they show what actually
    happened: a file opened for writing and then abandoned still says WRITE in
    its flags, yet no bytes moved.

    Flags are only a fallback when both counts are zero (e.g. a genuinely empty
    upload).
    """
    if baca > 0:
        return AMBIL
    if tulis > 0:
        return KIRIM
    if flags:
        if "WRITE" in flags or "CREATE" in flags or "APPEND" in flags:
            return KIRIM
        if "READ" in flags:
            return AMBIL
    return "BUKA"


def _potong(nilai, n):
    """Second safeguard for `pengguna`/`ip_klien`, like `[:45]` in `akseslog.py`.
    The stricter regex (see SESI_BUKA) should be enough, but unbounded text sent
    to MySQL is an easy hole to reopen when the regex changes later.
    """
    return nilai[:n] if nilai else nilai


def gabung(baris_baris, sesi_awal):
    """Merge log lines into transfers using the pid -> user map.

    `sesi_awal` is `{pid: {"pengguna": ..., "ip": ...}}` carried over from the
    previous cycle. Returns `(transfer, sesi_akhir, sesi_selesai)`:

        transfer      rows ready to store, each with its owner
        sesi_akhir    pids still open, to persist again
        sesi_selesai  pids whose session closed, to clean up

    Transfers from unknown pids are still recorded with `pengguna=None`.
    Dropping them would hide real transfers just because NSM started reading
    mid-session, and those are usually long sessions with large files.
    """
    session = dict((p, dict(v)) for p, v in (sesi_awal or {}).items())
    flags_terbuka = {}
    transfer = []
    finish = []

    for b in baris_baris:
        p = urai_baris(b)
        if p is None:
            continue
        pid = p["pid"]

        if p["jenis"] == "buka_sesi":
            session[pid] = {"pengguna": p["pengguna"], "ip": p["ip"],
                         "mulai": p["waktu"]}
            continue

        if p["jenis"] == "tutup_sesi":
            if pid in session:
                finish.append(pid)
                session.pop(pid, None)
            # Also forget files still open under this pid; otherwise a reused pid would
            # inherit another session's flags.
            for kunci in [k for k in flags_terbuka if k[0] == pid]:
                flags_terbuka.pop(kunci, None)
            continue

        person = session.get(pid) or {}

        if p["jenis"] == "buka_berkas":
            flags_terbuka[(pid, p["jalur"])] = p["flags"]
            continue

        if p["jenis"] == "tutup_berkas":
            f = flags_terbuka.pop((pid, p["jalur"]), "")
            transfer.append({
                "waktu": p["waktu"], "pid": pid,
                "pengguna": _potong(person.get("pengguna"), 100),
                "ip_klien": _potong(person.get("ip"), 45),
                "aksi": arah(p["baca"], p["tulis"], f),
                "jalur": p["jalur"][:400], "jalur_baru": None,
                "byte_baca": float(p["baca"]), "byte_tulis": float(p["tulis"]),
            })
            continue

        if p["jenis"] == "aksi":
            jb = p.get("jalur_baru")
            transfer.append({
                "waktu": p["waktu"], "pid": pid,
                "pengguna": _potong(person.get("pengguna"), 100),
                "ip_klien": _potong(person.get("ip"), 45),
                "aksi": p["aksi"], "jalur": p["jalur"][:400],
                "jalur_baru": jb[:400] if jb else None,
                "byte_baca": 0.0, "byte_tulis": 0.0,
            })

    return transfer, session, finish


def ambil(conn_ssh, jalur, posisi_lama, sesi_awal, timeout=25):
    """Read a chunk of auth.log over an already-open SSH session.

    Uses the same read command and rotation detection as the access log reader.
    Duplicating the read-position logic could drift silently and show up only
    as skipped lines.
    """
    from connectors import akseslog

    _in, out, _err = conn_ssh.exec_command(
        akseslog.perintah_baca(jalur, posisi_lama), timeout=timeout)
    output = out.read().decode("utf-8", errors="replace")
    baris, position_new, rotated, exists = akseslog.baca_potongan(
        output, posisi_lama)
    transfer, session, finish = gabung(baris, sesi_awal)
    return transfer, session, finish, position_new, rotated, exists

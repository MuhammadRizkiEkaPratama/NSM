"""Reader for Windows Firewall on the machine NSM itself runs on.

Supplies the third firewall layer (alongside `ufw` on the Linux servers and the
ACL on router R2) to the Firewall page as real data.

No SSH, on purpose: the poller runs on this machine, so it calls `netsh`
directly via `subprocess` (present on every Windows, no extra modules), the
same reasoning as `connectors/lokal.py`.

`netsh`, not the PowerShell cmdlet `Get-NetFirewallRule`: the cmdlets (plus the
port and address filters per rule) took 82.5 s for 257 inbound rules, too long
for a 5-minute firewall poll interval. `netsh advfirewall firewall show rule
name=all verbose` reads all ~12,000 lines in 2 s, because the cmdlets use a
separate CIM association query per rule while `netsh` reads the rule store
directly.

Only INBOUND + ENABLED rules are kept: the page asks "which doors are open
inward". Outbound rules (allowed by default) and disabled rules do not answer
that.

READ-ONLY. Only `netsh ... show ...` is called. Changing rules or toggling
profiles is a human decision (`Set-NetFirewallProfile`), just as `ufw.py` never
calls `ufw enable`.
"""
import hashlib
import re
import subprocess

# --- read rules ---

PERINTAH_ATURAN = ["netsh", "advfirewall", "firewall", "show", "rule",
                    "name=all", "verbose"]
PERINTAH_PROFIL = ["netsh", "advfirewall", "show", "allprofiles", "state"]

POLA_FIELD = re.compile(r"^([A-Za-z][A-Za-z0-9 /'-]*?):\s{2,}(.*?)\s*$")


def _jalankan(perintah, timeout=20):
    """Run `netsh` as a local process. Raises on failure or empty output: empty does
    NOT mean "no rules", it can mean an unknown command or a stopped firewall
    service, and the two must be told apart (as `ufw.py` does).
    """
    try:
        r = subprocess.run(perintah, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace",
                           creationflags=subprocess.CREATE_NO_WINDOW
                           if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
    except FileNotFoundError:
        raise ValueError("netsh tidak ditemukan di PATH")
    except subprocess.TimeoutExpired:
        raise ValueError("netsh tidak menjawab dalam %ss" % timeout)
    if r.returncode != 0:
        raise ValueError("netsh keluar dengan kode %d: %s"
                         % (r.returncode, (r.stderr or r.stdout or "")[:200]))
    return r.stdout


def parse_profile(keluaran):
    """Profile settings text ('Domain Profile Settings: ... State ON') ->
    {"Domain": "ON", ...}.

    Used as `kebijakan_masuk` in FirewallSnapshot. The name is not an exact fit, but
    the table exists and adding a column for one new device type costs more than
    reusing it.
    """
    hasil = {}
    profile_now = None
    for baris in keluaran.splitlines():
        m = re.match(r"^(\w+) Profile Settings:", baris.strip())
        if m:
            profile_now = m.group(1)
            continue
        m2 = re.match(r"^State\s+(\w+)", baris.strip())
        if m2 and profile_now:
            hasil[profile_now] = m2.group(1)
            profile_now = None
    return hasil


def _urai_blok_aturan(blok):
    """One 'Rule Name: ... \\n Action: ...' block -> dict of raw fields."""
    d = {}
    for baris in blok.splitlines():
        m = POLA_FIELD.match(baris)
        if m:
            d[m.group(1).strip()] = m.group(2).strip()
    return d


def parse_rule(keluaran):
    """`netsh ... show rule name=all verbose` output -> list of rule dicts.

    Only Inbound + Enabled=Yes rules are returned (see the module docstring).
    `netsh` prints a rule that applies to several profiles as several identical
    blocks (one per active profile); blocks identical to the previous one (same
    name, action, port, address) are merged so they are not counted repeatedly.
    """
    block_list = re.split(r"\r?\n\r?\n(?=Rule Name:)", keluaran)
    dilihat = set()
    aturan = []
    for blok in block_list:
        if "Rule Name:" not in blok:
            continue
        f = _urai_blok_aturan(blok)
        if f.get("Enabled") != "Yes":
            continue
        if (f.get("Direction") or "").strip().lower() != "in":
            continue

        nama = f.get("Rule Name") or "(tanpa nama)"
        aksi = f.get("Action") or "?"
        proto = f.get("Protocol") or "Any"
        port = f.get("LocalPort") or "Any"
        alamat = f.get("RemoteIP") or "Any"

        kunci = (nama, aksi, proto, port, alamat)
        if kunci in dilihat:
            continue
        dilihat.add(kunci)

        aturan.append({
            "nomor": len(aturan) + 1,
            "ke": ("%s/%s" % (proto, port)) if port not in (None, "Any") else proto,
            "aksi": aksi,
            "arah": "IN",
            "dari": alamat,
            "komentar": nama[:200],
        })
    return aturan


def baca_keadaan():
    """Read rules + profile state; return a dict ready for `simpan_firewall()`.

    Same shape that `poller.simpan_firewall()` expects for ufw/Cisco: sidik, aktif,
    kebijakan_masuk, teks, aturan[]. The page and the storage code need not know
    the source is Windows.
    """
    text_profile = _jalankan(PERINTAH_PROFIL)
    profile = parse_profile(text_profile)
    aktif = 1 if any(v == "ON" for v in profile.values()) else 0

    text_rule = _jalankan(PERINTAH_ATURAN, timeout=30)
    aturan = parse_rule(text_rule)

    # The `kebijakan_masuk` column inherited from ufw/Cisco is String(30) and cannot
    # hold "Domain=ON, Private=ON, Public=ON" (33 chars). Summarize into a form that
    # always fits and is more useful: name what is OFF instead of relisting what is
    # ON, so a disabled profile is visible at a glance.
    down = [k for k in ("Domain", "Private", "Public") if profile.get(k) != "ON"]
    summarize_profile = ("semua profil ON" if not down
                      else "OFF: " + ",".join(down))
    summarize_text_complete = ", ".join(
        "%s=%s" % (k, v) for k, v in sorted(profile.items()))

    # Fingerprint from rule contents + profile state, sorted for stability. If
    # nothing changed, `simpan_firewall()` writes no new row, same as ufw and the
    # router ACL.
    representasi = summarize_text_complete + "|" + "|".join(
        "%s;%s;%s;%s;%s" % (a["komentar"], a["aksi"], a["ke"], a["dari"], a["arah"])
        for a in sorted(aturan, key=lambda a: a["komentar"]))
    sidik = hashlib.sha1(representasi.encode("utf-8")).hexdigest()

    return {
        "sidik": sidik,
        "aktif": aktif,
        "kebijakan_masuk": summarize_profile[:60],
        "kebijakan_keluar": None,
        "kebijakan_rute": None,
        "logging": None,
        "teks": (text_profile + "\n" + text_rule)[:20000],
        "aturan": aturan,
    }


# --- read the block log ---
#
# Verified against real log lines (with `LogBlocked` enabled and read permission
# on the file granted to the monitoring account; by default only
# SYSTEM/Administrators can read it). Two things differed from the documentation:
#
# 1. The real header has 18 fields, not the 17 in Microsoft's example (an extra
#    `pid` at the end). So `urai_baris_log()` always prefers the order from the
#    `#Fields:` line actually present at the head of the file (via
#    `baca_log_potongan()`); FIELD_BAWAAN is only a fallback when the chunk read
#    lacks that header (e.g. continuing from a byte offset).
#
# 2. The first line after a blank line can contain hundreds of NUL bytes (`\x00`)
#    before the real data (Windows preallocates log file space). NUL is not
#    whitespace for `str.split()`, so it would stick to the first token and shift
#    the whole column mapping. It is stripped in `urai_baris_log()` before
#    anything else.
JALUR_LOG = r"%SystemRoot%\System32\LogFiles\Firewall\pfirewall.log"

# Header observed in practice (18 fields, including `pid`); used ONLY as a
# fallback. Normal reads use the order from the `#Fields:` line at the head of
# the file.
FIELD_BAWAAN = ["date", "time", "action", "protocol", "src-ip", "dst-ip",
                "src-port", "dst-port", "size", "tcpflags", "tcpsyn",
                "tcpack", "tcpwin", "icmptype", "icmpcode", "info", "path",
                "pid"]


def urai_baris_log(baris, urutan_field=None):
    """One pfirewall.log line -> dict ready to store in `penolakan_acl`.

    None for comment lines (starting with '#') and ALLOW lines; as in ufw.py only
    DROPs matter.

    `urutan_field` comes from the '#Fields: ...' line when present; when the file is
    read from the middle (a continuation chunk), FIELD_BAWAAN is assumed.
    """
    # The first line after file creation/rotation can start with hundreds of NUL
    # bytes (see the note above `JALUR_LOG`); stripped before `.split()` so they do
    # not stick to the first column and shift the mapping.
    b = baris.replace("\x00", "").strip()
    if not b or b.startswith("#"):
        return None
    column = b.split()
    urutan = urutan_field or FIELD_BAWAAN
    if len(column) < len(urutan):
        return None
    f = dict(zip(urutan, column))
    if (f.get("action") or "").upper() != "DROP":
        return None

    def ke_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    stamp = "%s %s" % (f.get("date", ""), f.get("time", ""))
    d = {
        "cap_router": stamp[:30],
        "acl": "winfw",
        "aksi": "DROP",
        "proto": (f.get("protocol") or "?").upper(),
        "dari": f.get("src-ip") or "?",
        "port_dari": ke_int(f.get("src-port")),
        "ke": f.get("dst-ip") or "?",
        "port_ke": ke_int(f.get("dst-port")),
        "jumlah": 1,
        "baris": b[:500],
    }
    d["sidik"] = hashlib.sha1(
        ("winfw|" + stamp + "|" + d["dari"] + "|" + d["ke"] + "|"
         + str(f.get("dst-port"))).encode("utf-8")).hexdigest()
    return d


def _baca_entri(jalur, mulai):
    """Read DROP entries from `jalur` starting at byte `mulai`. Returns (entries,
    end_position).

    When `mulai == 0` the `#Fields:` header is read first for the real column order
    (it can change between OS versions; guessing wrong would swap ports and
    addresses). When reading from the middle there is no header, so FIELD_BAWAAN is
    assumed.
    """
    urutan_field = None
    entry = []
    with open(jalur, "r", encoding="utf-8", errors="replace") as fh:
        if mulai == 0:
            for baris in fh:
                if baris.startswith("#Fields:"):
                    urutan_field = baris.split(":", 1)[1].split()
                    break
                if not baris.startswith("#"):
                    break
            fh.seek(0)
        else:
            fh.seek(mulai)
        for baris in fh:
            d = urai_baris_log(baris, urutan_field)
            if d:
                entry.append(d)
        position_end = fh.tell()
    return entry, position_end


def baca_log_potongan(posisi_lama):
    """Read pfirewall.log from the old byte position.

    Same shape as `akseslog.baca_potongan`/`ufwlog.ambil`: (entries, new_position,
    rotated, exists).

    `ada=False` means the file does not exist yet (logging still off). That differs
    from "exists but empty": callers must not report "0 denials" as a result when
    nothing was ever checked.

    On rotation `pfirewall.log.old` is read too. Windows rotates the log when full
    (4 MB): the old file is renamed to `.old` and a new empty one is created. The
    tail of the old file (between the last read position and the rotation point)
    exists only in `.old`; without it each rotation (about every 2 days) leaves a
    gap. Poller dedup (via `sidik`) handles any overlap, and failing to read `.old`
    does not fail reading the new file.
    """
    import os
    jalur = os.path.expandvars(JALUR_LOG)
    if not os.path.exists(jalur):
        return [], posisi_lama or 0, False, False

    size = os.path.getsize(jalur)
    diputar = size < (posisi_lama or 0)

    entry = []
    if diputar and (posisi_lama or 0) > 0:
        path_old = jalur + ".old"
        try:
            if (os.path.exists(path_old)
                    and os.path.getsize(path_old) > (posisi_lama or 0)):
                entry_old, _ = _baca_entri(path_old, posisi_lama or 0)
                entry.extend(entry_old)
        except (PermissionError, OSError):
            # Old tail lost, but the new file is still read: a small gap is much better than
            # a read that stops entirely.
            pass

    position_read = 0 if diputar else (posisi_lama or 0)
    entry_current, posisi_baru = _baca_entri(jalur, position_read)
    entry.extend(entry_current)

    return entry, posisi_baru, diputar, True

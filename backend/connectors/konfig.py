"""Reads device CONFIGURATION: what it is now, and what changed.

Deliberately READ-ONLY. Config backup is the safety net for any ability to change
configuration: until NSM has stored a device's config, a "send change" button would
modify something whose previous state is recorded nowhere. Store first, then change.

It is also valuable on its own: "the router config changed last night, which line
exactly?" has no answer in a manual workflow. RANCID and Oxidized do the same and never
write to devices.

TWO THINGS MUST HAPPEN BEFORE STORING, and neither is cosmetic:

1. SECRETS ARE MASKED. `show running-config` contains enable password hashes, SNMP
   communities, and VPN pre-shared keys. Storing it as-is would copy every device secret
   into `nsm.db`, which is included in backups. A config backup tool that piles up
   secrets is a target, not a safeguard.

2. SELF-CHANGING LINES ARE DROPPED BEFORE COMPARING. `ntp clock-period` and timestamps
   change without anyone touching the device. Compared as-is, NSM would report
   "configuration changed" every hour for untouched devices, and an alert that is always
   on stops being read.
"""
import hashlib
import re


# Config-fetch command per platform. All of them only read.
#
# The values come from the definition files in `backend/perangkat/*.yaml`; the name and
# shape are kept so users (`kesehatan.py`, `report_service/konfig.py`,
# `nsm/pemantau/konfig.py`) did not change. A table in code plus a definition file would be
# two answers to one question, and they never stay equal. The definition file also records
# whether a platform was actually tested (`teruji:`), which a bare table cannot say.
def _dari_definisi(kunci):
    import dialek_perangkat
    return {nama: d.perintah(kunci)
            for nama, d in dialek_perangkat.semua().items()
            if d.perintah(kunci)}


PERINTAH = _dari_definisi("konfigurasi")

# The configuration used when the device is restarted.
#
# This is the difference between "what is in effect now" and "what will be in effect after
# a reboot". A change that was made and tested but never saved is lost silently at the
# next power loss. Verified on the lab devices: a test banner added from the console
# without `write memory` is in the running-config but not in the startup-config.
#
# Read from the definition files like the commands above. A platform without this key does
# not appear here at all, which lets `ambil_startup()` tell "has no such concept" from
# "empty": RouterOS, Junos, and FortiOS do not separate running from saved configuration
# and must never be reported as unsaved.
PERINTAH_STARTUP = _dari_definisi("konfigurasi_startup")

# Lines that change by themselves without anyone editing the config. Dropped before the
# fingerprint is computed so the comparison is honest.
BARIS_BERUBAH_SENDIRI = re.compile(
    r"^\s*(?:"
    r"ntp\s+clock-period"
    r"|!\s*Time:"
    r"|!\s*Last\s+configuration"   # "Last configuration change at ..."
    r"|Current\s+configuration"
    r"|Building\s+configuration"
    # `show startup-config` header: an NVRAM usage report, not configuration. The number
    # changes whenever the content changes, so if compared it would ALWAYS show up as a
    # difference between running and startup and make the whole comparison untrustworthy.
    r"|Using\s+\d+\s+out\s+of\s+\d+\s+bytes"
    r")",
    re.IGNORECASE,
)

# Secrets that must not be stored. Only the VALUE is replaced; command names and structure
# stay intact, because a vanished `snmp-server community` line is a change that must be
# visible.
POLA_RAHASIA = [
    # enable secret 5 $1$xxxx$yyyy   /   enable password 7 08701E1D
    (re.compile(r"^(\s*enable\s+(?:secret|password)\s+\d*\s*).+$", re.I | re.M),
     r"\1<DISAMARKAN>"),
    # username admin privilege 15 secret 5 $1$...
    (re.compile(r"^(\s*username\s+\S+(?:\s+privilege\s+\d+)?\s+(?:secret|password)\s+\d*\s*).+$", re.I | re.M),
     r"\1<DISAMARKAN>"),
    # Example: `snmp-server host 10.0.0.6 version 2c public udp-port 1162`
    #
    # A community string on a Cisco `snmp-server host` line is also a secret, not only on
    # `snmp-server community X`. Whoever used a real community there would have it stored
    # as-is in `nsm.db`, which ends up in backups.
    #
    # `version 3` is deliberately NOT matched: what follows is the SNMPv3 user name, not a
    # secret, and masking it would erase useful information.
    #
    # The v3 line is rejected up front with a lookahead over the whole line, not patched
    # inside the pattern. An optional `(?:version (1|2c))?` group fails on v3, backtracks, and
    # masks the word `version` itself, producing a BROKEN snapshot rather than a safe one.
    #
    # Two lookaheads, and both reject the WHOLE line:
    #     `version 3`    not a community, leave it alone
    #     `<DISAMARKAN>` already masked, leave it alone
    # The second is what makes masking idempotent. Without it a second pass over an already
    # masked line would backtrack past the optional `version 2c` group and mask the word
    # `version`, changing the snapshot fingerprint every time, so NSM would report
    # "configuration changed" for devices nobody touched.
    (re.compile(r"^(?!.*\bversion\s+3\b)(?!.*<DISAMARKAN>)"
                r"(\s*snmp-server\s+host\s+\S+"
                r"(?:\s+vrf\s+\S+)?"
                r"(?:\s+(?:traps|informs))?"
                r"(?:\s+version\s+(?:1|2c))?"
                r"\s+)\S+", re.I | re.M),
     r"\1<DISAMARKAN>"),
    # snmp-server community public RO
    (re.compile(r"^(\s*snmp-server\s+community\s+)\S+", re.I | re.M),
     r"\1<DISAMARKAN>"),
    # crypto isakmp key rahasia address 1.2.3.4
    (re.compile(r"^(\s*crypto\s+isakmp\s+key\s+)\S+", re.I | re.M),
     r"\1<DISAMARKAN>"),
    # password 7 08701E1D  (inside a line vty / interface block)
    (re.compile(r"^(\s*password\s+\d*\s*).+$", re.I | re.M),
     r"\1<DISAMARKAN>"),
    # ppp chap password 7 ...
    (re.compile(r"^(\s*ppp\s+\S+\s+password\s+\d*\s*).+$", re.I | re.M),
     r"\1<DISAMARKAN>"),
    # key-string / pre-shared-key
    (re.compile(r"^(\s*(?:key-string|pre-shared-key)\s+\d*\s*).+$", re.I | re.M),
     r"\1<DISAMARKAN>"),
]


def samarkan(teks):
    """Replace secret values with a marker, keeping the structure.

    Only the VALUE is masked. `snmp-server community <DISAMARKAN> RO` still says SNMP is on
    and with which rights, and if the line ever disappears the loss shows up as a change.
    Dropping the whole line would hide the change most worth noticing.
    """
    for pattern, ganti in POLA_RAHASIA:
        teks = pattern.sub(ganti, teks)
    return teks


def bersihkan(teks):
    """Drop self-changing lines, normalize line endings and trailing whitespace.

    The result is used both to compute the fingerprint AND to store, so what a person
    compares on screen is exactly what the machine compared. Storing one version and
    comparing another is the cheapest way to get two answers to one question.
    """
    line = []
    for b in (teks or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if BARIS_BERUBAH_SENDIRI.match(b):
            continue
        b = b.rstrip()

        # RUNS OF `!` SEPARATORS ARE COLLAPSED INTO ONE.
        #
        # `!` in Cisco IOS is a visual separator, not a command. `show startup-config` writes a
        # different number of them than `show running-config` for identical content, which once
        # made a one-line change look like "7 lines unsaved". The count changes nothing on the
        # device, so it must change nothing in the comparison. One is kept so the config structure
        # stays readable in a diff.
        if b.strip() == "!" and line and line[-1].strip() == "!":
            continue

        line.append(b)
    # Blank lines and separators at the HEAD of the output are dropped. `show running-config`
    # and `show startup-config` begin with different numbers of blank lines and `!` for
    # identical content, and a difference there says nothing about the device. Safe to drop: a
    # `!` before the first command separates nothing.
    while line and (not line[0] or line[0].strip() == "!"):
        line.pop(0)

    # Trailing blank lines are dropped so adding or removing them is not read as a config
    # change.
    while line and not line[-1]:
        line.pop()
    return "\n".join(line)


def sidik(teks):
    """Fingerprint of the config content, used to decide whether a new snapshot is stored."""
    return hashlib.sha256((teks or "").encode("utf-8", "replace")).hexdigest()


def _pola_platform(platform):
    """Extra masking patterns from the platform definition file, already compiled.

    Empty if the platform is unknown or has no `rahasia:` key, and empty means the behavior
    is exactly as before definition files existed.
    """
    if not platform:
        return []
    import dialek_perangkat
    hasil = []
    for r in dialek_perangkat.ambil(platform).rahasia:
        hasil.append((re.compile(r["pola"]), r["ganti"]))
    return hasil


def olah(raw, platform=None):
    """Turn raw device output into `(teks_siap_simpan, sidik_jari)`.

    The order is deliberate: mask FIRST, then clean, then fingerprint. Fingerprinting
    unmasked text would make two configs that are identical after masking look different
    just because the device regenerated a password hash.

    `platform` adds that platform's own masking patterns from its definition file. The
    default None runs only the base patterns.

    Why per-platform: the base patterns in `POLA_RAHASIA` are Cisco-shaped (`enable secret 5
    ...`, `snmp-server community ...`). Neither matches RouterOS `set password=...` or
    FortiOS `set psksecret ENC ...`, so storing another vendor's config with Cisco patterns
    alone would write all its secrets to `nsm.db`, which is included in backups.
    """
    teks = samarkan(raw)
    for pattern, ganti in _pola_platform(platform):
        teks = pattern.sub(ganti, teks)
    teks = bersihkan(teks)
    return teks, sidik(teks)


def beda_baris(old, baru):
    """Change summary: `(jumlah_ditambah, jumlah_dihapus, potongan_diff)`.

    Uses the built-in `difflib`; a simple line diff does not justify an extra dependency.
    """
    import difflib
    a = (old or "").split("\n")
    b = (baru or "").split("\n")
    chunk = list(difflib.unified_diff(a, b, lineterm="", n=2))
    add = sum(1 for x in chunk if x.startswith("+") and not x.startswith("+++"))
    delete = sum(1 for x in chunk if x.startswith("-") and not x.startswith("---"))
    return add, delete, "\n".join(chunk)


def ambil(conn, platform):
    """Fetch the config over an ALREADY connected netmiko session. Takes the open connection
    instead of opening its own, like `akseslog.ambil()` and `flow.ambil()`: one round needs
    one connection for all its commands.
    """
    perintah = PERINTAH.get(platform)
    if not perintah:
        raise ValueError(f"Belum ada perintah pengambil konfigurasi untuk platform '{platform}'")
    return conn.send_command(perintah, read_timeout=60)


def daftar_interface(teks):
    """Interface names that actually exist, read from the config snapshot.

    Used to validate command parameters. A pattern check alone is not enough: `FastEthernet9/9`
    passes any pattern but does not exist on the device, and the router rejects a command for
    a missing interface AFTER half the other commands were already sent. Validating against
    the device's own state replaces guessing.
    """
    hasil = []
    for b in (teks or "").split("\n"):
        match = re.match(r"^interface\s+(\S+)\s*$", b.strip(), re.IGNORECASE)
        if match:
            nama = match.group(1)
            if nama not in hasil:
                hasil.append(nama)
    return hasil


def interface_untuk_ip(teks, ip):
    """Which interface carries this IP address, read from the config snapshot.

    Used by `kirim_perintah.py` to prevent a real class of mistake (see the
    `iface_mati`/`iface_hidup` history in docs/POSTMORTEM-R1.md): sending the `memutus`
    command to the very interface NSM itself uses to reach the device. After the command is
    sent the connection drops mid-way and no reversing command can be sent, because the
    device itself blocked the way back.

    None if the address is not found on any interface (an `ip address` line in an unknown
    format, or simply not this device's address). Callers must treat that as "cannot be
    confirmed", NOT "safe": an incomplete snapshot must not be read as proof of safety.
    """
    current_interface = None
    for line in (teks or "").split("\n"):
        match_iface = re.match(r"^interface\s+(\S+)\s*$", line.strip(), re.IGNORECASE)
        if match_iface:
            current_interface = match_iface.group(1)
            continue
        if current_interface is None:
            continue
        match_ip = re.match(r"^ip address\s+(\S+)\s+\S+", line.strip(), re.IGNORECASE)
        if match_ip and match_ip.group(1) == ip:
            return current_interface
    return None


def ambil_startup(conn, platform):
    """Fetch the config used after the device restarts.

    Returns None if the platform has no such concept, which is different from empty: a
    device that does not separate running from startup must not be reported as having
    unsaved config.

    A device that was never saved answers with an error message instead of a config. That is
    handled here so callers need not know the message text.
    """
    perintah = PERINTAH_STARTUP.get(platform)
    if not perintah:
        return None
    output = conn.send_command(perintah, read_timeout=60)
    if output and "startup-config is not present" in output.lower():
        return ""
    return output


# ACL change detection.
#
# Born from a real event: an ACL line was added to a router directly through its CLI (not
# through NSM) between two consecutive config snapshots. `poll_konfig()` stored the new
# snapshot and computed `baris_tambah`/`baris_hapus`, but those counts do not distinguish
# "ACL changed" from "banner changed". It was only noticed later through a manual
# `show ip access-lists`.
#
# What is looked for here is not "did the config change" (answered by `beda_baris()`) but
# "does the changed part contain access-control definitions", the only kind of change that
# directly alters WHO MAY ENTER rather than a display or a label.
POLA_BARIS_ACL = re.compile(
    r"^[+-]\s*("
    r"ip access-list\s"          # awal blok ACL bernama, Cisco IOS
    r"|access-list\s+\d"
    r"|\s*(permit|deny)\s"  # permit/deny lines INSIDE an ACL block
    r")", re.I)


def deteksi_acl_berubah(potongan_diff):
    """Takes a unified diff (output of `beda_baris()`); True if any ACL line changed.

    Given the DIFF HUNK, not two full configs, because the caller (`poll_konfig()`) already
    calls `beda_baris()` for the counts; re-checking from scratch would compute the same diff
    twice per snapshot.

    ONLY `+`/`-` LINES ARE CHECKED (unified diff context lines start with a space and are
    skipped by the pattern above because `[+-]` requires that prefix): a line present on both
    sides unchanged is irrelevant.

    `permit`/`deny` OUTSIDE ACL blocks (e.g. in a route-map or a VPN crypto ACL) are caught
    as positives too. That is deliberate: both decide which traffic is allowed, and a false
    positive here is far cheaper than a false negative on a rule that really controls access.
    """
    if not potongan_diff:
        return False
    for line in potongan_diff.splitlines():
        if POLA_BARIS_ACL.match(line):
            return True
    return False

"""Identity marker sources: where a device's markers come from.

Deliberately separate from `identitas.py`. This file TOUCHES the outside world
(runs `arp`, opens SNMP, opens SSH); `identitas.py` only weighs what was
obtained. The split is not just tidiness: the verdict logic must be testable
with no device powered on, and each read function here has a parse function that
takes TEXT, so parsing can be tested with recorded output.

EVERYTHING HERE ONLY READS. No command changes device state.

Design: docs/design/TRAFFIC-IDENTITY-FW.md.
"""
import re
import subprocess

import dialek_perangkat

# ---------------------------------------------------------------------------
# MAC: normalize the notation BEFORE comparing.
# ---------------------------------------------------------------------------

def normalkan_mac(teks):
    """Turn any MAC notation into `aa:bb:cc:dd:ee:ff`.

    This matters beyond tidiness. Windows writes MACs with hyphens
    (`02-00-5e-10-00-01`), Linux with colons, Cisco with dots (`0200.5e10.0001`),
    and the letter case varies. Without normalizing, the SAME MAC from two sources
    reads as DIFFERENT.

    The result is not just ugly output: the verdict becomes `bertentangan`
    (contradicting), which BLOCKS the write path. A correct device would be refused
    with a convincing but false reason, and a guard that blocks legitimate work gets
    switched off on day one.
    """
    if not teks:
        return None
    heks = re.sub(r"[^0-9a-fA-F]", "", str(teks))
    if len(heks) != 12:
        return None
    heks = heks.lower()
    return ":".join(heks[i:i + 2] for i in range(0, 12, 2))


# MACs that belong to no one, so they must not be used as markers. They would match
# many devices at once, and a marker matching many devices is the opposite of an
# identity.
def _mac_semu(mac):
    if not mac:
        return True
    if mac == "ff:ff:ff:ff:ff:ff":  # broadcast
        return True
    if mac == "00:00:00:00:00:00":  # empty
        return True
    if mac.startswith("01:00:5e"):          # multicast IPv4
        return True
    if mac.startswith("33:33"):             # multicast IPv6
        return True
    return False


# ---------------------------------------------------------------------------
# Source 1: this machine's own ARP table. ZERO new connections.
# ---------------------------------------------------------------------------

def baca_arp(teks):
    """Parse `arp -a` output into `{ip: mac}`.

    Takes text rather than running the command, so it can be tested with recorded
    output, including odd output that is hard to reproduce on demand.
    """
    hasil = {}
    for line in (teks or "").splitlines():
        m = re.match(r"\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F][0-9a-fA-F][-:]"
                     r"(?:[0-9a-fA-F]{2}[-:]){4}[0-9a-fA-F]{2})\s", line)
        if not m:
            continue
        ip, mac = m.group(1), normalkan_mac(m.group(2))
        if _mac_semu(mac):
            continue
        # The subnet broadcast address (`.255`) sometimes shows up with a real MAC on some
        # systems. It is not a device.
        if ip.endswith(".255"):
            continue
        hasil[ip] = mac
    return hasil


def tabel_arp():
    """This machine's ARP table. `{}` if the command fails.

    Failure is deliberately not raised: a missing ARP table only means one marker
    source is unavailable, which is no reason to abort the whole identity
    collection.
    """
    try:
        # `encoding` + `errors` are REQUIRED, not decoration.
        #
        # `arp` writes in the Windows OEM codepage (cp437/cp850), not utf-8. Without both,
        # one non-ASCII byte kills the subprocess reader thread and `stdout` becomes None
        # WITHOUT any exception reaching here. `baca_arp(None)` then raises, the `except`
        # below swallows it, and this function returns `{}`.
        #
        # The result reads as "empty ARP table": one identity marker source vanishes
        # silently, indistinguishable from a machine that simply has not ARPed anyone.
        #
        # IP addresses and MACs are pure ASCII, so replacing stray bytes with U+FFFD does
        # not break parsing; it keeps the other lines readable.
        keluar = subprocess.run(["arp", "-a"], capture_output=True, text=True,
                                encoding="utf-8", errors="replace",
                                timeout=15)
        return baca_arp(keluar.stdout)
    except Exception:
        return {}


def mac_lokal():
    """MACs of this machine's own network cards, `{ip: mac}`.

    Needed separately from ARP because a machine NEVER ARPs itself. Without this, the
    two closest devices (this machine, registered twice under different addresses)
    would never get a single marker.
    """
    try:
        import psutil
    except ImportError:
        return {}
    hasil = {}
    try:
        for _nama, daftar in psutil.net_if_addrs().items():
            ip = None
            mac = None
            for a in daftar:
                if a.family.name == "AF_INET" and not ip:
                    ip = a.address
                elif a.family.name == "AF_LINK" and not mac:
                    mac = normalkan_mac(a.address)
            if ip and mac and not _mac_semu(mac):
                hasil[ip] = mac
    except Exception:
        return {}
    return hasil


def amati_dari_arp(db):
    """MAC marker for each device, `{device_id: {"mac": ...}}`.

    Stores NOTHING; same shape as `identitas.vonis(terlihat=...)` takes, so judging
    still happens before storing.

    Limited but real value: ARP only reaches devices on directly connected networks.
    That is the point: the WiFi gateway has neither SSH nor SNMP, so without ARP it
    would never have any marker, though it is the plainest example of the problem
    being solved: `192.168.1.1` matches in almost every home.
    """
    from models import Device

    peta = dict(mac_lokal())
    # The local source wins over ARP: for this machine's own addresses the answer is
    # certain, while an ARP row for an own address (if any) can come from any card.
    for ip, mac in tabel_arp().items():
        peta.setdefault(ip, mac)

    visible = {}
    for d in db.query(Device).all():
        mac = peta.get(d.ip_address)
        if mac:
            visible[d.id] = {"mac": mac}
    return visible


# ---------------------------------------------------------------------------
# Source 2: SNMP. One OID, `sysName`.
# ---------------------------------------------------------------------------

def penanda_snmp(d):
    """Marker from SNMP for one device. `{}` if unavailable.

    Only `sysName` is taken, not `sysDescr`. `sysDescr` reads like
    "Linux vm-ubuntu 5.15.0-91-generic ..." and CHANGES with every kernel update; a
    marker that changes without the device changing would produce a `bertentangan`
    verdict on a correct device, right after the security update that deserves
    praise.
    """
    if not d.snmp_user:
        return {}
    try:
        from connectors.snmp import SnmpConnector
        conn = SnmpConnector(
            d.ip_address, user=d.snmp_user,
            auth_pass=d.snmp_auth_pass, priv_pass=d.snmp_priv_pass,
            auth_proto=d.snmp_auth_proto, priv_proto=d.snmp_priv_proto,
            port=d.snmp_port or 161)
        info = conn.get_info() or {}
    except Exception:
        return {}
    # The key is "Hostname (SNMP)", the name `get_info()` uses for display, not the OID
    # name. Written as is here rather than guessed as "sysName", because a wrong key
    # raises no error: it yields an empty marker, which reads as "SNMP unreachable",
    nama = str(info.get("Hostname (SNMP)") or "").strip()
    if not nama or nama == "-":
        return {}
    return {"hostname": nama}


# ---------------------------------------------------------------------------
# Source 3: SSH. Read commands, which differ by device type.
# ---------------------------------------------------------------------------

# Linux. `machine-id` is created once at install time and survives renames and
# address changes: the strongest marker available on Linux.
#
# But it is NOT enough alone, for a reason present in this very lab: a VM cloned
# from another VM carries the same `machine-id`. Two different machines, one twin
# marker. That is why the `sama` verdict requires TWO matching markers, not one.
def perintah_linux(ip):
    """Read commands for Linux. `ip` = the address NSM USES to reach the device.

    The address must be passed in. The first version took the MAC of the card holding
    the default route (`ip route show default`), which is WRONG on multi-homed
    machines. Both lab VMs have two cards: NAT (carries the default route, used by
    the VM to reach the internet) and host-only (used by NSM to reach it). They have
    different MACs and both are legitimate; the question was wrong, not the answer.

    Left alone, the ARP row wins while it exists and nothing shows. But ARP rows are
    `dynamic` and expire; once gone, the NAT card's MAC gets stored, and when ARP
    fills in again the two collide and the verdict becomes `bertentangan`, which
    BLOCKS the write path on a perfectly correct device. A guard that accuses a
    correct device is worse than no guard, because it teaches people to turn it off.

    So the question now is "the MAC of the card holding THIS address", the only
    formulation guaranteed to equal what ARP sees.
    """
    safe = re.sub(r"[^0-9.]", "", str(ip or ""))
    return [
        ("machine_id", "cat /etc/machine-id 2>/dev/null"),
        ("hostname", "hostname"),
        ("mac",
         "K=$(ip -o -4 addr show 2>/dev/null | "
         "awk -v a='%s/' '$4 ~ (\"^\" a) {print $2; exit}'); "
         "[ -n \"$K\" ] && cat /sys/class/net/$K/address 2>/dev/null" % safe),
    ]


# Windows over SSH: the machine name ONLY, MAC deliberately not taken.
#
# Same reason as above, but worse: the machine has a dozen network adapters (Wi-Fi,
# several virtual host-only adapters, Bluetooth, unused ones). No simple Windows
# command reliably answers "the MAC of the card holding this address", and a wrong
# answer here yields `bertentangan` on a correct device.
#
# The MAC is already obtained reliably from another source: the machine's own
# network cards, read via psutil and mapped by address.
PERINTAH_WINDOWS = [
    ("hostname", "hostname"),
]

# Cisco IOS. The serial is the strongest marker on a real device: printed on the
# chassis and unchanged by any configuration.
PERINTAH_CISCO = [
    ("show_version", "show version"),
]


def parse_linux(keluaran):
    """Turn Linux `{label: output}` into clean markers."""
    hasil = {}
    mid = (keluaran.get("machine_id") or "").strip()
    # A valid machine-id is 32 hex characters. Anything else (error messages, an empty
    # file on some systems) is dropped, because a marker holding an error message
    # would be diligently compared as if it were an identity.
    if re.fullmatch(r"[0-9a-fA-F]{32}", mid):
        hasil["machine_id"] = mid.lower()

    nama = (keluaran.get("hostname") or "").strip().splitlines()
    if nama and nama[0]:
        hasil["hostname"] = nama[0].strip()

    mac = normalkan_mac((keluaran.get("mac") or "").strip().split("\n")[0])
    if mac and not _mac_semu(mac):
        hasil["mac"] = mac
    return hasil


def urai_show_version(teks):
    """Take serial, model and IOS version from `show version`.

    Only the SERIAL becomes an identity marker. Model and version are returned for
    display but not compared: the IOS version changes with every upgrade, and an
    upgraded device is still the same device.
    """
    hasil = {}
    t = teks or ""
    m = re.search(r"(?:System serial number|Processor board ID)\s*:?\s*"
                  r"([A-Za-z0-9]+)", t, re.I)
    if m:
        hasil["serial"] = m.group(1).strip()
    m = re.search(r"^[Cc]isco\s+(\S+)\s+\(", t, re.M)
    if m:
        hasil["model"] = m.group(1).strip()
    m = re.search(r"Version\s+([0-9][^,\s]*)", t)
    if m:
        hasil["versi_ios"] = m.group(1).strip()
    return hasil


def penanda_ssh(d):
    """Markers over SSH for one device. `{}` if unavailable.

    ALL commands read. No `configure terminal`, no `write`, nothing that changes
    device state. That must stay true, because this function is what gets called to
    decide whether the device may be written to.
    """
    if not (d.username and (d.password or d.ssh_key_path)):
        return {}
    # HOW markers are collected, not the device BRAND. Lives in the definition files
    # (`kemampuan.identitas`).
    #
    # The old `("linux", "ubuntu", "debian")` list became `alias:` in
    # `perangkat/linux.yaml`, so it applies to every question about that platform, not
    # just this one. Before, a device with platform `ubuntu` had identity markers taken
    # here but its configuration not read elsewhere: two answers for one device, and
    # neither looked wrong.
    method = dialek_perangkat.ambil(d.platform).kemampuan("identitas")
    if method == "cisco":
        daftar = PERINTAH_CISCO
    elif method == "linux":
        daftar = perintah_linux(d.ip_address)
    elif method == "windows":
        daftar = PERINTAH_WINDOWS
    else:
        return {}

    import paramiko
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        # allow_agent/look_for_keys False, same reason as in connectors/ssh.py: the
        # identity used must be certain, not a key that happens to lie in ~/.ssh of the
        # account running this.
        if d.ssh_key_path:
            client.connect(d.ip_address, username=d.username,
                           key_filename=d.ssh_key_path, timeout=12,
                           allow_agent=False, look_for_keys=False)
        else:
            client.connect(d.ip_address, username=d.username,
                           password=d.password, timeout=12,
                           allow_agent=False, look_for_keys=False)
        keluaran = {}
        for label, perintah in daftar:
            _i, o, _e = client.exec_command(perintah, timeout=20)
            keluaran[label] = o.read().decode("utf-8", errors="replace")
    except Exception:
        return {}
    finally:
        try:
            client.close()
        except Exception:
            pass

    if method == "cisco":
        detail = urai_show_version(keluaran.get("show_version", ""))
        # Only the serial is a marker; model and version are not compared.
        return {"serial": detail["serial"]} if detail.get("serial") else {}
    return parse_linux(keluaran)

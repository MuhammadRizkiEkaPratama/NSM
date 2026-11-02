"""Reads ufw firewall rules on Linux devices.

`cek_port_terbuka` only says a port is reachable from here; the rules say why and who
else can reach it (`3306 ALLOW IN from 192.168.56.0/24` is the whole subnet, not just
one host). A rule that ALLOWS a port whose service is currently stopped is invisible to
port checks and opens as soon as the service starts.

READ-ONLY, enforced in two places: this module only runs `ufw status`, and the server's
sudo rules allow only those commands, so `ufw disable` is refused by the system, not
merely never called. A guard that exists only in code disappears when someone writes
new code.
"""
import hashlib
import re

# Full path, not bare `ufw`. The server's sudo rule matches the whole command line, so
# `sudo ufw status verbose` without the path would not match and would be refused with a
# password prompt, which hangs in a non-interactive session.
PERINTAH = ("sudo -n /usr/sbin/ufw status verbose 2>&1; "
            "echo '---PISAH---'; "
            "sudo -n /usr/sbin/ufw status numbered 2>&1")

# "Default: deny (incoming), allow (outgoing), disabled (routed)"
POLA_DEFAULT = re.compile(
    r"^Default:\s*(?P<masuk>\w+)\s*\(incoming\)"
    r"(?:,\s*(?P<keluar>\w+)\s*\(outgoing\))?"
    r"(?:,\s*(?P<rute>\w+)\s*\(routed\))?", re.I)

POLA_LOG = re.compile(r"^Logging:\s*(?P<nilai>.+?)\s*$", re.I)

# "[ 1] 22/tcp                     ALLOW IN    Anywhere"
# "[12] 80/tcp (v6)                DENY IN     2001:db8::/32   # komentar"
POLA_ATURAN = re.compile(
    r"^\[\s*(?P<nomor>\d+)\]\s+"
    r"(?P<ke>.+?)\s{2,}"
    r"(?P<aksi>ALLOW|DENY|REJECT|LIMIT)\s+(?P<arah>IN|OUT|FWD)\s+"
    r"(?P<dari>.+?)\s*$", re.I)


def _bersih(t):
    t = (t or "").strip()
    return t or None


def urai(keluaran):
    """Parse `ufw status` output into a firewall state dict.

    Raises ValueError if the output shows the command itself failed, instead of returning an
    "empty firewall". A disabled firewall and an unreadable one both yield zero rules;
    conflating them would show "no rules" for a machine that is actually locked down.
    """
    if keluaran is None:
        raise ValueError("tidak ada keluaran")

    verbose, _, bernomor = keluaran.partition("---PISAH---")

    merge = verbose + bernomor
    if "a password is required" in merge or "may not run sudo" in merge:
        raise ValueError("nsmro belum diizinkan membaca firewall "
                         "(jalankan firewall/pasang-baca-firewall.sh)")
    if "You need to be root" in merge:
        raise ValueError("ufw ditolak: perintahnya tidak lewat sudo")
    if "command not found" in merge or "No such file" in merge:
        raise ValueError("ufw tidak terpasang di perangkat ini")

    hasil = {"aktif": None, "kebijakan_masuk": None, "kebijakan_keluar": None,
             "kebijakan_rute": None, "logging": None, "aturan": []}

    for line in verbose.splitlines():
        b = line.strip()
        if b.lower().startswith("status:"):
            # Matched exactly, not with `"active" in line`: `inactive` contains `active`, so a
            # disabled firewall was reported as enabled, the worst direction to be wrong.
            nilai = b.split(":", 1)[1].strip().lower()
            hasil["aktif"] = 1 if nilai.startswith("active") else 0
            continue
        m = POLA_DEFAULT.match(b)
        if m:
            hasil["kebijakan_masuk"] = _bersih(m.group("masuk"))
            hasil["kebijakan_keluar"] = _bersih(m.group("keluar"))
            hasil["kebijakan_rute"] = _bersih(m.group("rute"))
            continue
        m = POLA_LOG.match(b)
        if m:
            hasil["logging"] = _bersih(m.group("nilai"))

    if hasil["aktif"] is None:
        raise ValueError("keluaran ufw tidak dikenali")

    for line in bernomor.splitlines():
        m = POLA_ATURAN.match(line.rstrip())
        if not m:
            continue
        ke = m.group("ke").strip()
        dari = m.group("dari").strip()
        komentar = None
        if "#" in dari:
            dari, _, komentar = dari.partition("#")
            dari = dari.strip()
            komentar = _bersih(komentar)
        hasil["aturan"].append({
            "nomor": int(m.group("nomor")),
            "ke": ke[:200],
            "aksi": m.group("aksi").upper(),
            "arah": m.group("arah").upper(),
            "dari": dari[:200],
            "komentar": (komentar or "")[:200] or None,
        })

    # The raw output is stored as EVIDENCE. The parsed rule table can be wrong if ufw's output
    # format changes, and the failure would show up as missing rows, not an error. Raw output
    # cannot be wrong; compare against it if the table is ever doubted.
    hasil["teks"] = keluaran
    hasil["sidik"] = sidik(hasil)
    return hasil


def sidik(keadaan):
    """Fingerprint of the firewall state, to detect CHANGES.

    Rule numbers are deliberately excluded: ufw renumbers the whole list when one rule is
    deleted, so a fingerprint that included them would report "the whole firewall changed"
    for a single deletion, and exaggerated change reports stop being read.
    """
    section = [
        str(keadaan.get("aktif")),
        str(keadaan.get("kebijakan_masuk")),
        str(keadaan.get("kebijakan_keluar")),
        str(keadaan.get("kebijakan_rute")),
    ]
    for a in keadaan.get("aturan", []):
        section.append("|".join([a["aksi"], a["arah"], a["ke"], a["dari"],
                                a.get("komentar") or ""]))
    return hashlib.sha256("\n".join(section).encode("utf-8")).hexdigest()[:16]


def ambil(conn_ssh, timeout=20):
    _in, out, _err = conn_ssh.exec_command(PERINTAH, timeout=timeout)
    return urai(out.read().decode("utf-8", errors="replace"))

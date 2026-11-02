"""Extract OBSERVED values from a configuration snapshot text, per platform.

Returns exactly the same shape that `sot/katalog.py` and `sot/service.py` use:
a `nilai` dict (key -> canonical value, or None if unreadable) plus
`interface`/`vlan`/`rute` lists, so the comparison in `drift/service.py` lines up
two identical structures instead of translating between two.

A `None` value for a key means specifically "this line was not found in the
snapshot". It is NOT the same as an empty string; see `drift/service.py` for how
absence is told apart from "matches" and from "different value".

The regex patterns were verified against a real R1 snapshot, not derived from
generic Cisco documentation. Two surprises: the router prints
`ip domain name lab.local` (three words, no hyphen) rather than the more commonly
documented `ip domain-name` (both forms are supported), and it has `line vty 0 4`,
not `line vty 0 15` as `sot/templates/cisco_ios.j2` assumed. Extraction does not
depend on a particular range; it matches any line starting with `line vty`.
"""
import re


def _baris(teks):
    return teks.split("\n")


def _blok_setelah(baris_semua, cocok):
    """Lines of ONE block (by indentation) that starts at the first line for which
    `cocok(baris)` is True. None if not found.

    Cisco IOS convention: the sub-commands of a block start with ONE space; the
    block ends at the first line without a leading space (usually `!`).
    """
    for i, l in enumerate(baris_semua):
        if cocok(l.rstrip("\r")):
            isi = []
            for l2 in baris_semua[i + 1:]:
                if l2.startswith(" "):
                    isi.append(l2)
                else:
                    break
            return isi
    return None


def _satu(pola, teks, grup=1):
    """Group 1 of the FIRST match of a pattern, or None."""
    m = pola.search(teks)
    return m.group(grup).strip() if m else None


def _semua(pola, teks, grup=1):
    """Group value of ALL matches of a pattern, in order of appearance."""
    return [m.group(grup).strip() for m in pola.finditer(teks)]


# --- File-level patterns (not tied to a particular block) ---
_HOSTNAME = re.compile(r"^hostname\s+(\S+)\s*$", re.MULTILINE)
_DOMAIN = re.compile(r"^ip domain[- ]name\s+(\S+)\s*$", re.MULTILINE)
_TIMEZONE = re.compile(r"^clock timezone\s+(\S+)", re.MULTILINE)
_NTP = re.compile(r"^ntp server\s+(\S+)", re.MULTILINE)
_DNS = re.compile(r"^ip name-server\s+(.+)$", re.MULTILINE)
_LOGGING_HOST = re.compile(r"^logging host\s+(\S+)", re.MULTILINE)
_SNMP_LOKASI = re.compile(r"^snmp-server location\s+(.+?)\s*$", re.MULTILINE)
_SNMP_KONTAK = re.compile(r"^snmp-server contact\s+(.+?)\s*$", re.MULTILINE)
_BANNER = re.compile(r"^banner motd \^C(.*?)\^C", re.MULTILINE | re.DOTALL)
_HTTP_OFF = re.compile(r"^no ip http server\s*$", re.MULTILINE)
_HTTPS_OFF = re.compile(r"^no ip http secure-server\s*$", re.MULTILINE)
_IP_ROUTE = re.compile(r"^ip route\s+(\S+)\s+(\S+)\s+(\S+)", re.MULTILINE)
_VLAN_MULAI = re.compile(r"^vlan\s+(\d+)\s*$", re.MULTILINE)
_ACCESS_LIST_STD = re.compile(r"^ip access-list standard\s+(\S+)\s*$", re.MULTILINE)

# --- In-block patterns (applied to already-extracted block contents) ---
_EXEC_TIMEOUT = re.compile(r"^ exec-timeout\s+(\d+)\s+\d+\s*$", re.MULTILINE)
_ACCESS_CLASS = re.compile(r"^ access-class\s+(\S+)\s+in\s*$", re.MULTILINE)
_TRANSPORT_INPUT = re.compile(r"^ transport input\s+(.+?)\s*$", re.MULTILINE)
_PERMIT_HOST = re.compile(r"^ permit host\s+(\S+)", re.MULTILINE)
_VLAN_NAME = re.compile(r"^ name\s+(\S+)\s*$", re.MULTILINE)
_IF_DESKRIPSI = re.compile(r"^ description\s+(.+?)\s*$", re.MULTILINE)
_IF_IP = re.compile(r"^ ip address\s+(\S+)\s+(\S+)\s*$", re.MULTILINE)
_IF_VLAN = re.compile(r"^ switchport access vlan\s+(\d+)\s*$", re.MULTILINE)
_IF_SHUTDOWN = re.compile(r"^ shutdown\s*$", re.MULTILINE)
_IF_NO_SHUTDOWN = re.compile(r"^ no shutdown\s*$", re.MULTILINE)


def _zona_kanonik(nama_cisco):
    """'WIB' -> 'Asia/Jakarta'. None stays None (line not found).

    Unknown names are returned as is, not forced to None: a device using an
    abbreviation outside the map (e.g. `SGT`) must still show up as DIFFERENT from
    the intent, not vanish into "unreadable" and mask a real drift.
    """
    from sot.katalog import CISCO_KE_ZONA
    if nama_cisco is None:
        return None
    return CISCO_KE_ZONA.get(nama_cisco, nama_cisco)


def _dns_semua(teks):
    """`ip name-server` can appear as one line with several addresses
    (`ip name-server 8.8.8.8 8.8.4.4`) OR as several separate lines. Both forms are
    handled here.
    """
    hasil = []
    for line in _semua(_DNS, teks):
        hasil.extend(line.split())
    return hasil


def _vty_izin(isi_vty, teks_penuh):
    """Addresses permitted via `access-class ... in` on the vty block.

    Two steps: find the ACL NAME from access-class, then find the
    `ip access-list standard <name>` block in the FULL text (the ACL is defined
    outside the vty block) and collect its `permit host` lines.
    """
    if isi_vty is None:
        return None
    name_acl = _satu(_ACCESS_CLASS, "\n".join(isi_vty))
    if not name_acl:
        return []  # vty block without access-class -> genuinely empty
    baris_semua = _baris(teks_penuh)
    content_acl = _blok_setelah(
        baris_semua,
        lambda l: l == "ip access-list standard %s" % name_acl)
    if content_acl is None:
        return None  # access-class points to an ACL that is not found: odd, not "empty"
    return _semua(_PERMIT_HOST, "\n".join(content_acl))


def _ssh_saja(isi_vty):
    if isi_vty is None:
        return None
    nilai = _satu(_TRANSPORT_INPUT, "\n".join(isi_vty))
    if nilai is None:
        return None  # not written -> unreadable, NOT guessed as False
    return nilai.strip() == "ssh"


def _cari_vty(baris_semua):
    return _blok_setelah(baris_semua, lambda l: l.startswith("line vty"))


def _cari_con(baris_semua):
    return _blok_setelah(baris_semua, lambda l: l.startswith("line con"))


def _interface_semua(baris_semua):
    """{interface_name: [block body lines]} for EVERY `interface ...` block."""
    hasil = {}
    i = 0
    n = len(baris_semua)
    while i < n:
        l = baris_semua[i]
        if l.startswith("interface "):
            nama = l[len("interface "):].strip()
            isi = []
            j = i + 1
            while j < n and baris_semua[j].startswith(" "):
                isi.append(baris_semua[j])
                j += 1
            hasil[nama] = isi
            i = j
        else:
            i += 1
    return hasil


def _satu_interface(isi):
    teks = "\n".join(isi)
    shut = _IF_SHUTDOWN.search(teks) is not None
    no_shut = _IF_NO_SHUTDOWN.search(teks) is not None
    # Two lines both state the state (rare, an odd configuration). IOS honors the last
    # one written; it is NOT guessed here: the value is None so the comparison cannot
    # be silently wrong.
    if shut and no_shut:
        shutdown = None
    elif shut:
        shutdown = True
    elif no_shut:
        shutdown = False
    else:
        # Neither present: a documented assumption, not a silent guess. IOS defaults most
        # Ethernet interfaces to no-shutdown. The limit is stated in drift/service.py when
        # results are shown.
        shutdown = False
    ip = _satu(_IF_IP, teks, 1)
    mask = _satu(_IF_IP, teks, 2)
    vlan_txt = _satu(_IF_VLAN, teks)
    return {
        "deskripsi": _satu(_IF_DESKRIPSI, teks),
        "ip": ip,
        "mask": mask,
        "vlan": int(vlan_txt) if vlan_txt else None,
        "shutdown": shutdown,
    }


def _vlan_semua(teks):
    baris_semua = _baris(teks)
    hasil = {}
    i = 0
    n = len(baris_semua)
    while i < n:
        m = _VLAN_MULAI.match(baris_semua[i].rstrip("\r"))
        if m:
            vid = int(m.group(1))
            isi = []
            j = i + 1
            while j < n and baris_semua[j].startswith(" "):
                isi.append(baris_semua[j])
                j += 1
            nama = _satu(_VLAN_NAME, "\n".join(isi))
            hasil[vid] = nama
            i = j
        else:
            i += 1
    return hasil


def cisco_ios(teks):
    """Extract all observed values from ONE `show running-config` snapshot.

    Returns a dict shaped like `sot.service.ambil()`:
    `{"nilai": {...}, "interface": [...], "vlan": [...], "rute": [...]}`.
    """
    baris_semua = _baris(teks)
    isi_vty = _cari_vty(baris_semua)
    isi_con = _cari_con(baris_semua)

    exec_timeout_txt = _satu(_EXEC_TIMEOUT, "\n".join(isi_con)) if isi_con else None

    nilai = {
        "hostname": _satu(_HOSTNAME, teks),
        "domain": _satu(_DOMAIN, teks),
        # Translated BACK to the intent's canonical form ('WIB' -> 'Asia/Jakarta').
        # Without this `zona_waktu` would never match: the intent stores the IANA name,
        # the device writes an abbreviation. The map is single, in `sot/katalog.py`,
        # shared with the renderer.
        "zona_waktu": _zona_kanonik(_satu(_TIMEZONE, teks)),
        "ntp_server": _semua(_NTP, teks) or None,
        "dns_server": _dns_semua(teks) or None,
        "logging_server": _semua(_LOGGING_HOST, teks) or None,
        "snmp_lokasi": _satu(_SNMP_LOKASI, teks),
        "snmp_kontak": _satu(_SNMP_KONTAK, teks),
        "banner_masuk": (_satu(_BANNER, teks) or "").strip() or None,
        "exec_timeout_menit": int(exec_timeout_txt) if exec_timeout_txt else None,
        "vty_izin": _vty_izin(isi_vty, teks),
        "ssh_saja": _ssh_saja(isi_vty),
        "layanan_http_mati": (bool(_HTTP_OFF.search(teks))
                              and bool(_HTTPS_OFF.search(teks))),
    }

    interface = []
    for nama, isi in _interface_semua(baris_semua).items():
        one = _satu_interface(isi)
        one["nama"] = nama
        interface.append(one)

    vlan = [{"vlan_id": vid, "nama": nama}
           for vid, nama in sorted(_vlan_semua(teks).items())]

    rute = [{"tujuan": t, "mask": m, "next_hop": n}
           for t, m, n in _semua_tuple(_IP_ROUTE, teks)]

    return {"nilai": nilai, "interface": interface, "vlan": vlan, "rute": rute}


def _semua_tuple(pola, teks):
    return [m.groups() for m in pola.finditer(teks)]


# Platform -> extractor function. Deliberately closed; see the package docstring
# for why `linux` is absent.
EKSTRAKTOR = {
    "cisco_ios": cisco_ios,
}


def didukung(platform):
    return platform in EKSTRAKTOR


def ekstrak(platform, teks):
    """Run the extractor for the matching platform. Raises KeyError if the platform is
    not supported: callers MUST check `didukung()` first, like
    `sot.render.jalur_template()`.
    """
    return EKSTRAKTOR[platform](teks)

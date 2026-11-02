"""Reads ACL denials from a Cisco router.

Only the router ACL, which ends in `deny ip any any log`, answers "who tried and was
denied"; `ufw` on each server only says what the rules are. Buffered logging must be
enabled on the router, otherwise the messages go only to the console and are lost.

Two caveats when reading the numbers:
1. This is not every attempt. IOS merges similar denials within a window of a few
   minutes into one line with a count, so "1 packet" means at least one.
2. The timestamp is the router's clock, which can be years off if it is not
   synchronized. The read time is stored too, as the only one that can order events
   against other machines' logs. The router timestamp is never overwritten with the
   read time; both are stored as-is and the page shows which one is used.
"""
import re

# %SEC-6-IPACCESSLOGP: list NAME denied tcp 1.2.3.4(1234) -> 5.6.7.8(22), 3 packets
#
# Also matched: IPACCESSLOGDP (icmp, with type/code instead of ports) and IPACCESSLOGRP
# (protocols without ports).
POLA_PORT = re.compile(
    r"%SEC-\d+-IPACCESSLOGP:\s+list\s+(?P<acl>\S+)\s+(?P<aksi>\w+)\s+"
    r"(?P<proto>\w+)\s+(?P<dari>[\d.]+)\((?P<port_dari>\d+)\)\s*->\s*"
    r"(?P<ke>[\d.]+)\((?P<port_ke>\d+)\),\s*(?P<jumlah>\d+)\s+packet")

POLA_TANPA_PORT = re.compile(
    r"%SEC-\d+-IPACCESSLOG(?:DP|RP|NP):\s+list\s+(?P<acl>\S+)\s+(?P<aksi>\w+)\s+"
    r"(?P<proto>\w+)\s+(?P<dari>[\d.]+)\s*->\s*(?P<ke>[\d.]+)"
    r"(?:,\s*(?P<jumlah>\d+)\s+packet)?")

# Timestamp prefix, present when `service timestamps log datetime` is on.
POLA_WAKTU = re.compile(r"^\*?(?P<cap>[A-Z][a-z]{2}\s+\d+\s+[\d:.]+)")


def urai(teks):
    """Turn `show logging` output into a list of denials, each a dict with the keys
    `acl, aksi, proto, dari, port_dari, ke, port_ke, jumlah, cap_router, baris`.

    Unrecognized lines are skipped, not reported as empty denials: the log buffer holds many
    other messages (link flaps, config changes) that would flood the security page.
    """
    hasil = []
    for baris in (teks or "").splitlines():
        baris = baris.strip()
        if "IPACCESSLOG" not in baris:
            continue
        m = POLA_PORT.search(baris) or POLA_TANPA_PORT.search(baris)
        if not m:
            continue
        g = m.groupdict()
        w = POLA_WAKTU.search(baris)
        hasil.append({
            "acl": g.get("acl"),
            "aksi": (g.get("aksi") or "").lower(),
            "proto": (g.get("proto") or "").lower(),
            "dari": g.get("dari"),
            "port_dari": int(g["port_dari"]) if g.get("port_dari") else None,
            "ke": g.get("ke"),
            "port_ke": int(g["port_ke"]) if g.get("port_ke") else None,
            "jumlah": int(g["jumlah"]) if g.get("jumlah") else 1,
            "cap_router": w.group("cap") if w else None,
            "baris": baris[:480],
        })
    return hasil


def sidik(p):
    """Identity key for one denial, used to recognize ones already stored.

    The router timestamp is part of it. Otherwise repeated denials from the same address to
    the same port would count as one event forever, and the repetition is what matters: one
    attempt is a mistake, a hundred is a scan.
    """
    return "|".join(str(p.get(k)) for k in
                    ("cap_router", "acl", "dari", "port_dari", "ke",
                     "port_ke", "proto", "jumlah"))

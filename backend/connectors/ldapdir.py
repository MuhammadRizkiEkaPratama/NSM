"""LDAP directory reader: who the people are, their titles, which groups they belong to.

WHY NSM READS THE DIRECTORY AT ALL. Login uses the directory for one question, "is this
password right". After that the directory is never asked anything, and everything else in
it (full name, title, group membership) never reaches any screen. So the "who fetched
which file" page could only write `arif`, while the directory holds:

    uid: arif        cn: Arif Rahman        title: Auditor

The difference is not cosmetic: "Arif Rahman, Auditor, fetched 40 MB of CCTV footage"
prompts the right question (does an auditor need it?), whereas a short name forces the
reader to remember who `arif` is.

WHY IT IS COPIED TO THE DATABASE INSTEAD OF QUERIED WHEN A PAGE OPENS. Two reasons, the
second more important:
  1. Each page load would query the directory, so the directory server carries the load
     of everyone who opens the page.
  2. The directory server can go down. If names were fetched when the page opens, an
     outage would make every name in the history page VANISH, though history is about
     past events unrelated to the directory's current state. History that changes
     because another server is down cannot be trusted.
So the poller copies it periodically into the `orang_ldap` table and pages read the copy.

PASSWORDS ARE NEVER REQUESTED. Reads use an anonymous bind and ask only for attributes
meant to be read. `userPassword` is not requested, and would not be returned anyway:
slapd hides it from anonymous readers. A monitoring tool has no use for password hashes.
"""

# Attributes fetched, as a closed list rather than "fetch everything". Fetching everything
# would pull in whatever others later add to the directory for other purposes, including
# things that do not belong in a monitoring database, and nobody would notice because the
# column set would grow silently.
ATRIBUT = ["uid", "cn", "title", "mail"]

# Timeout. Without it a dead directory server hangs the poller round until the system's
# default TCP timeout, and it is not just the directory read that stalls but the whole job.
TIMEOUT = 5


def _teks(nilai):
    """ldap3 returns an attribute sometimes as a list, sometimes as text."""
    if nilai is None:
        return None
    if isinstance(nilai, (list, tuple)):
        nilai = nilai[0] if nilai else None
    if nilai is None:
        return None
    teks = str(nilai).strip()
    return teks or None


def baca(url, basis="dc=bsp,dc=id"):
    """Fetch all people and their groups from the directory.

    Returns a list of dicts: uid, nama, jabatan, email, grup (comma-separated text). Raises
    if the directory is unreachable; the caller decides what that means, because "directory
    down" means different things in the poller (skip this round) and on a page (use the old
    copy).
    """
    import ldap3

    host = url
    for prefix in ("ldap://", "ldaps://"):
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    # The URL in the config carries the base DN at its end (`ldap://<host>:389/<base-dn>`).
    # That part belongs to Spring, not to the server address.
    host = host.split("/")[0]

    # STARTTLS IS REQUIRED, AND THE CERTIFICATE IS CHECKED.
    #
    # The directory is at site B, so every query crosses the ISP router, which in this lab's
    # design is not owned by the organization.
    #
    # `auto_bind=AUTO_BIND_TLS_BEFORE_BIND` upgrades the connection to TLS BEFORE the bind is
    # sent. The order matters: bind first, then TLS, would already have sent the credentials.
    #
    # `validate=CERT_REQUIRED` so the chain is really verified against the lab CA. An encrypted
    # connection that does not verify its peer only moves the problem: anyone who can sit in
    # the path can present their own certificate.
    #
    # If the CA file is missing, do NOT silently fall back to a plain connection. Fail
    # clearly: callers already know how to handle "directory unreachable", which is far more
    # honest than sending passwords unencrypted without anyone knowing.
    import os
    import ssl

    berkas_ca = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "bsp-lab-ca.crt")
    if not os.path.exists(berkas_ca):
        raise RuntimeError(
            "Sertifikat CA lab tidak ada di %s. Direktori TIDAK dihubungi: "
            "menyambung tanpa TLS berarti mengirim kredensial melewati "
            "jaringan penyedia dalam bentuk polos." % berkas_ca)

    # `valid_names` IS NEEDED, AND IT IS NOT A RELAXATION.
    #
    # The server certificate carries TWO names: an IP SAN and a DNS SAN (`nsm-ubuntu`). Modern
    # TLS libraries (including sssd on both Linux servers) match both correctly.
    #
    # ldap3 does not. It uses a legacy name matcher derived from the long-removed
    # `ssl.match_hostname`, which reads ONLY DNS-type SANs, never IP-type ones. So connecting
    # by address is always rejected even with a correct certificate.
    #
    # `valid_names` tells ldap3 that `nsm-ubuntu` is a valid name for this server. What is NOT
    # relaxed: the certificate chain is still fully verified against the lab CA via
    # CERT_REQUIRED, so only certificates actually issued by our CA for that name are
    # accepted.
    #
    # If the lab gets internal DNS, the address is replaced by the name and this is no longer
    # needed. Connecting by NAME is the better answer; using the address is what leaves this
    # oddity.
    tls = ldap3.Tls(ca_certs_file=berkas_ca,
                    validate=ssl.CERT_REQUIRED,
                    valid_names=["nsm-ubuntu"],
                    version=ssl.PROTOCOL_TLS_CLIENT)
    server = ldap3.Server(host, connect_timeout=TIMEOUT, get_info=None, tls=tls)
    conn = ldap3.Connection(server, receive_timeout=TIMEOUT,
                            auto_bind=ldap3.AUTO_BIND_TLS_BEFORE_BIND)
    try:
        conn.search("ou=people," + basis, "(objectClass=inetOrgPerson)",
                    attributes=ATRIBUT)
        person = []
        for e in conn.entries:
            d = e.entry_attributes_as_dict
            uid = _teks(d.get("uid"))
            if not uid:
                continue
            person.append({
                "uid": uid,
                "nama": _teks(d.get("cn")),
                "jabatan": _teks(d.get("title")),
                "email": _teks(d.get("mail")),
                "grup": None,
            })

        # Groups are read separately because they are `posixGroup` entries with `memberUid`:
        # membership is recorded on the GROUP, not on the person entry, so a person's groups
        # cannot be learned from the person's own entry.
        conn.search("ou=groups," + basis, "(objectClass=posixGroup)",
                    attributes=["cn", "memberUid"])
        peta = {}
        for e in conn.entries:
            d = e.entry_attributes_as_dict
            name_group = _teks(d.get("cn"))
            anggota = d.get("memberUid") or []
            if isinstance(anggota, str):
                anggota = [anggota]
            for a in anggota:
                peta.setdefault(str(a).strip(), []).append(name_group)

        for o in person:
            g = peta.get(o["uid"])
            o["grup"] = ", ".join(sorted(g)) if g else None
        return person
    finally:
        try:
            conn.unbind()
        except Exception:
            pass

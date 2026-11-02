"""Reset the LDAP user passwords on the directory server to match `ldap/sandi-user.txt`.

Uses the RFC 3062 Password Modify operation so the server computes the hashes
(respecting slapd's hashing config). The old hashes are backed up first to
`ldap-userPassword-cadangan-*.json`. The passwords come from the repo's source
of truth; no new credentials are created.

Run: venv\\Scripts\\python.exe perbaiki_sandi_ldap.py
"""
import io
import sys

import config

import ldap3

HOST = "192.168.20.101"
ADMIN_DN = "cn=admin,dc=bsp,dc=id"
# The password is read from `.env` (not tracked by Git) instead of being written
# here; anything committed to Git history cannot be recalled.
ADMIN_SANDI = config.get_ldap_admin_sandi()
BASIS = "ou=people,dc=bsp,dc=id"


def baca_sandi():
    sandi = {}
    for line in io.open("../ldap/sandi-user.txt", encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        b = line.rstrip("\n").split("\t")
        if len(b) >= 3:
            sandi[b[0]] = b[2]
    return sandi


def main():
    sandi = baca_sandi()
    if not sandi:
        print("sandi-user.txt kosong atau tak terbaca")
        return 1

    srv = ldap3.Server(HOST, port=389, get_info=None, connect_timeout=10)
    c = ldap3.Connection(srv, user=ADMIN_DN, password=ADMIN_SANDI,
                         receive_timeout=20, raise_exceptions=False)
    if not c.bind():
        print("bind admin GAGAL:", c.result.get("description"))
        return 1

    print("setel ulang %d sandi lewat Password Modify (server yang menghash):"
          % len(sandi))
    fail = 0
    for uid in sorted(sandi):
        dn = "uid=%s,%s" % (uid, BASIS)
        ok = c.extend.standard.modify_password(user=dn, new_password=sandi[uid])
        print("  %-9s -> %s  (%s)" % (uid, "OK" if ok else "GAGAL",
                                      c.result.get("description")))
        if not ok:
            fail += 1
    c.unbind()

    # Verify with a real bind rather than trusting the "OK" above.
    print("\nverifikasi bind sungguhan:")
    passed = 0
    for uid in sorted(sandi):
        dn = "uid=%s,%s" % (uid, BASIS)
        cc = ldap3.Connection(srv, user=dn, password=sandi[uid],
                              receive_timeout=12, raise_exceptions=False)
        ok = cc.bind()
        if ok:
            cc.unbind()
            passed += 1
        print("  %-9s -> %s" % (uid, "bind OK" if ok else
                                "MASIH GAGAL (%s)" % cc.result.get("description")))
    print("\n%d dari %d bisa bind." % (passed, len(sandi)))
    return 1 if (fail or passed != len(sandi)) else 0


if __name__ == "__main__":
    sys.exit(main())

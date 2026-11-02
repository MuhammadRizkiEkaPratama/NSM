"""Client for the GNS3 API, used by the topology builder scripts. Building through the API makes the whole topology readable, reviewable code that can be re-run to rebuild the lab. Credentials are never written here; they are read from the machine's GNS3 settings (`gns3_controller.ini` / `gns3_server.ini`) and only used in-process."""
import json
import os
import urllib.error
import urllib.request

INI = os.path.join(os.environ.get("APPDATA", ""), "GNS3", "2.2",
                   "gns3_server.ini")
DASAR = "http://127.0.0.1:3080/v2"


def _kredensial():
    """Read the API user and password from the machine's GNS3 settings."""
    user = sandi = None
    if os.path.exists(INI):
        for baris in open(INI, encoding="utf-8", errors="replace"):
            b = baris.strip()
            if b.startswith("user ") or b.startswith("user="):
                user = b.split("=", 1)[1].strip()
            elif b.startswith("password ") or b.startswith("password="):
                sandi = b.split("=", 1)[1].strip()
    if not user:
        raise RuntimeError(
            "Kredensial API GNS3 tidak ditemukan di %s. "
            "Buka Edit > Preferences > Server untuk melihatnya." % INI)
    return user, sandi or ""


def _pembuka():
    user, sandi = _kredensial()
    p = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    p.add_password(None, DASAR, user, sandi)
    return urllib.request.build_opener(
        urllib.request.HTTPBasicAuthHandler(p))


def panggil(metode, jalur, isi=None, timeout=60):
    """One API request. Raises with the server's message unchanged, since GNS3 errors ("port already used", "adapter not found") are more useful than the HTTP code."""
    data = None if isi is None else json.dumps(isi).encode()
    req = urllib.request.Request(DASAR + jalur, data=data, method=metode)
    req.add_header("Content-Type", "application/json")
    try:
        with _pembuka().open(req, timeout=timeout) as r:
            teks = r.read().decode("utf-8", "replace")
            return json.loads(teks) if teks.strip() else None
    except urllib.error.HTTPError as e:
        pesan = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError("%s %s -> %s %s" % (metode, jalur, e.code, pesan))


def proyek(nama):
    for p in panggil("GET", "/projects"):
        if p["name"] == nama:
            return p
    raise RuntimeError("Proyek %r tidak ada." % nama)


def template(nama):
    for t in panggil("GET", "/templates"):
        if t["name"] == nama:
            return t
    raise RuntimeError("Template %r tidak ada." % nama)

"""Recovers a GNS3 node through the controller API, replacing Cisco `reload in N` for
Dynamips lab devices.

Why not a plain `reload`: on physical gear IOS `reload` reboots and returns with the saved
startup-config. On GNS3/Dynamips, `reload` shuts the emulated machine down PERMANENTLY
(see docs/POSTMORTEM-R1.md). So for devices with `gns3_node` set, `kirim_perintah.py`
never sends `reload in N` to the CLI. Instead, when the device is confirmed unresponsive
after the `memutus` command, this module calls the GNS3 controller API directly (not over
a network path that may be down) to stop and start the node. The effect equals a real
reload (boot from the config saved in its NVRAM file) without the Dynamips flaw, because
the controller, not IOS, powers it off.

The pattern comes from `gns3/hidupkan_ulang_node.py`. It is rewritten here instead of
imported across folders because `gns3/` holds one-off topology scripts, not modules
designed for runtime use; `backend/` stays self-contained.

Does NOT wait for the console to answer, unlike the manual script. This runs inside the
HTTP request of `kirim_perintah.py`, and holding the response until IOS finishes booting
(1-2 minutes) would turn one click into a hanging request. The poller (every 10 seconds)
notices the device coming back on its own.
"""
import json
import os
import urllib.error
import urllib.request

INI = os.path.join(os.environ.get("APPDATA", ""), "GNS3", "2.2",
                   "gns3_server.ini")


def _dasar():
    """GNS3 controller address, configurable via `GNS3_URL` in `.env`.

    It used to be hardcoded to 127.0.0.1, which is wrong once NSM runs on a different machine
    than GNS3 (the nsm-app VM has no GNS3). Setting `GNS3_URL` is also not enough if the
    controller binds only to 127.0.0.1 (the GNS3 default); making it reachable is the lab
    owner's decision, not something this code should change silently.
    """
    try:
        import config
        url = (config._baca().get("GNS3_URL") or "").strip()
    except Exception:
        url = ""
    if not url:
        url = "http://127.0.0.1:3080"
    return url.rstrip("/") + ("" if url.rstrip("/").endswith("/v2") else "/v2")


# Kept as a module name so older code that reads it does not break; the value now comes
# from `_dasar()`.
DASAR = _dasar()


class GagalPulih(Exception):
    pass


def _kredensial():
    """GNS3 API credentials: `.env` first, then the GNS3 server ini file.

    `INI` points to a Windows-only path under `%APPDATA%`. On Linux `APPDATA` is empty, the
    path never exists, and this function would always raise `GagalPulih`. Hence `.env` is
    consulted first, so a machine that does not host GNS3 can still be given credentials.
    """
    try:
        import config
        env = config._baca()
        u = (env.get("GNS3_USER") or "").strip()
        s = (env.get("GNS3_PASSWORD") or "").strip()
        if u:
            return u, s
    except Exception:
        pass

    user = password = None
    if os.path.exists(INI):
        for line in open(INI, encoding="utf-8", errors="replace"):
            b = line.strip()
            if b.startswith("user ") or b.startswith("user="):
                user = b.split("=", 1)[1].strip()
            elif b.startswith("password ") or b.startswith("password="):
                password = b.split("=", 1)[1].strip()
    if not user:
        raise GagalPulih(
            "Kredensial API GNS3 tidak ditemukan. Di mesin tempat GNS3 "
            "terpasang, nilainya ada di %s (Edit > Preferences > Server). "
            "Di mesin LAIN -- mis. nsm-app, yang menjangkau controller lewat "
            "terowongan SSH -- berkas itu memang tidak ada; setel "
            "GNS3_USER dan GNS3_PASSWORD di .env." % INI)
    return user, password or ""


def panggil(metode, jalur, isi=None, timeout=30):
    """One request to the GNS3 controller API. Raises `GagalPulih` with the server's message
    unchanged, same pattern as `gns3/api.py.panggil()`.
    """
    data = None if isi is None else json.dumps(isi).encode()
    # Read at call time, not at import: a module-level `DASAR` freezes at its first value, so
    # changing `GNS3_URL` in `.env` would have no effect until the process restarts.
    base = _dasar()
    req = urllib.request.Request(base + jalur, data=data, method=metode)
    req.add_header("Content-Type", "application/json")
    user, password = _kredensial()
    p = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    p.add_password(None, base, user, password)
    opener = urllib.request.build_opener(
        urllib.request.HTTPBasicAuthHandler(p))
    try:
        with opener.open(req, timeout=timeout) as r:
            teks = r.read().decode("utf-8", "replace")
            return json.loads(teks) if teks.strip() else None
    except urllib.error.HTTPError as e:
        message = e.read().decode("utf-8", "replace")[:300]
        raise GagalPulih("%s %s -> %s %s" % (metode, jalur, e.code, message))
    except urllib.error.URLError as e:
        raise GagalPulih("%s %s -> %s" % (metode, jalur, e))


def pulihkan(nama_node, _panggil=panggil):
    """Stop, then start ONE GNS3 node, by name.

    `_panggil` can be replaced with a fake in tests so they never touch a real GNS3 API (same
    pattern as `_exec`/`_notif` in `penjaga_aksi.py`).

    `POST .../start` on a node that is already `started` does nothing, so this ALWAYS stops
    first and then starts, even if the controller believes the node is running.

    Raises `GagalPulih` if the project or node is not found, or the API call fails (e.g. no
    GNS3 server on this machine). The caller (`kirim_perintah.py`) is already on a path where
    something is wrong, so failures here are logged, not swallowed.
    """
    proyek = [p for p in (_panggil("GET", "/projects") or [])
              if p.get("status") == "opened"]
    if not proyek:
        raise GagalPulih("Tidak ada proyek GNS3 yang sedang terbuka.")
    pid = proyek[0]["project_id"]

    nodes = _panggil("GET", "/projects/%s/nodes" % pid) or []
    node = next((n for n in nodes if n.get("name") == nama_node), None)
    if not node:
        raise GagalPulih("Node %r tidak ditemukan di proyek %r."
                         % (nama_node, proyek[0].get("name")))
    nid = node["node_id"]

    _panggil("POST", "/projects/%s/nodes/%s/stop" % (pid, nid))
    _panggil("POST", "/projects/%s/nodes/%s/start" % (pid, nid))
    return {"proyek": proyek[0].get("name"), "node": nama_node,
            "dihentikan": True, "dinyalakan": True}

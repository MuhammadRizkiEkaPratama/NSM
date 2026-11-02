"""Firewall reports for report_service; re-exported by `report_service/__init__.py`."""
import os
from datetime import datetime, timedelta

from sqlalchemy import desc, func

import config
import dialek
import dialek_perangkat
from models import (
    Device,
    FirewallAturan,
    FirewallPerubahan,
    FirewallSnapshot,
    Flow,
    PenolakanAcl,
    Service,
)

from ._inti import (
    ALAMAT_NSM,
    AMBANG_GIGIH,
    AMBANG_PINDAI,
    LOKASI_ACL_ROUTER,
    POLA_BARIS_IZIN,
    POLA_BLOK_ACL,
    PORT_PINTU_MASUK,
    PORT_SENSITIF,
    _ip_bersih,
    _pelaku_jendela,
    _perubahan_nsm_per_device,
)


def penolakan_acl(db, batas=100):
    """Denied cross-segment attempts, newest first.

    Two sources share one table: router ACL denials (`deny ip any any log`) and
    the `ufw` deny log of Linux servers. The `acl` column tells them apart: the
    literal `"ufw"` means the row came from `/var/log/ufw.log` on a Site A server;
    any other value means a Site B router ACL.

    The `router` field in `daftar` is a legacy name: it now means "the device that
    logged the denial", Cisco or Linux. Kept so existing callers do not break.

    `jumlah` is the IOS count, and IOS aggregates similar denials within a time
    window, so "1" means "at least one"; the page says so.

    `cap_router` (router timestamp) is sent as-is next to NSM's read time `waktu`.
    If the router clock is not synced they differ, and the reader should see that
    instead of a silently chosen value.
    """
    if not dialek.tabel_ada(db, "penolakan_acl"):
        return {"ada_data": False, "daftar": [], "per_asal": [],
                "catatan": "Tabel penolakan belum dibuat."}

    name_device = {d.id: d.name for d in db.query(Device).all()}

    baris = (db.query(PenolakanAcl)
             .order_by(PenolakanAcl.waktu.desc(), PenolakanAcl.id.desc())
             .limit(batas).all())

    # Common service ports that appear as the SOURCE of reply traffic. A row from
    # one of these ports to a random high port (>=1024) is almost certainly a reply
    # or connection teardown, not an inbound attempt (e.g. LDAP SPT=389 -> DPT=53558
    # with ACK/FIN, denied on the return path). Real attacks go the other way:
    # random port -> service port.
    #
    # Intentionally separate from `PORT_SENSITIF` (used by `deteksi_pembobolan()`):
    # the goals are opposite, so do not merge them:
    #   - this list MUST include public ports (80, 443, 8080, 8443, 53, 123, 161),
    #     which reply to clients most often; without them the reply heuristic
    #     fails for web/DNS/NTP traffic.
    #   - `PORT_SENSITIF` MUST exclude those same public ports, or every
    #     legitimate web visitor would be flagged as a breach.
    # When adding a new admin service, review both lists.
    port_service = {22, 23, 25, 53, 80, 110, 123, 143, 161, 389, 443, 636,
                    993, 995, 3306, 3389, 5432, 8080, 8443}
    detail_per_origin = 15

    def _jenis(proto, port_dari, port_ke):
        """Classify one row by its pattern (not a verdict).

        - "balasan": TCP/UDP from a service port to a random high port, i.e. a
          service replying to a client, denied on the return path.
        - "icmp": ICMP (ping/diagnostics).
        - None: a genuine inbound attempt (random port -> service port).
        """
        if (proto or "").upper() == "ICMP":
            return "icmp"
        if port_dari in port_service and port_ke is not None and port_ke >= 1024:
            return "balasan"
        return None

    # ALAMAT_NSM: NSM service checks probe ports that should be closed to prove the
    # firewall blocks them, so their denials show the firewall works, not an attack.

    # Breach: addresses with an established connection to a monitored service port
    # (from `flow_koneksi`, not the deny log). An attacking source that also appears
    # here has a live foothold and is labeled red.
    #
    # Only recent connections (last 3 minutes), matching `deteksi_pembobolan()`.
    # Otherwise a source stays "breached" forever from a long-dead connection and
    # never returns to "blocked". Both page sections must give the same verdict for
    # one source.
    port_service_monitored = {s.port for s in db.query(Service)
                             .filter(Service.port.isnot(None)).all()}
    penetrasi_ip = set()
    if port_service_monitored:
        ambang_penetrasi = datetime.now() - timedelta(minutes=3)
        for (ip_lawan,) in (db.query(Flow.ip_lawan)
                            .filter(Flow.keadaan == "ESTAB",
                                    Flow.waktu >= ambang_penetrasi,
                                    Flow.port_lokal.in_(port_service_monitored))
                            .distinct().all()):
            if ip_lawan:
                penetrasi_ip.add(_ip_bersih(ip_lawan))

    # Grouped by source address, not time: one attempt is a mistake, a hundred from
    # one address is a scan.
    #
    # Fetched newest first so the first row seen per source is the latest (used for
    # `terakhir` and to trim `rincian` to the N newest without re-sorting).
    per_asal = {}
    detail = {}
    for r in (db.query(PenolakanAcl)
              .order_by(PenolakanAcl.waktu.desc(), PenolakanAcl.id.desc())
              .all()):
        k = r.dari or "?"
        a = per_asal.setdefault(k, {"asal": k, "percobaan": 0, "paket": 0,
                                    "tujuan": set(), "terakhir": None,
                                    "n_jinak": 0, "jenis": {}, "port_layanan": {}})
        a["percobaan"] += 1
        a["paket"] += (r.jumlah or 1)
        if r.ke:
            a["tujuan"].add("%s:%s" % (r.ke, r.port_ke or "-"))
        if a["terakhir"] is None:
            a["terakhir"] = r.waktu
        jns = _jenis(r.proto, r.port_dari, r.port_ke)
        if jns:
            a["n_jinak"] += 1
            a["jenis"][jns] = a["jenis"].get(jns, 0) + 1
            if jns == "balasan":
                a["port_layanan"][r.port_dari] = \
                    a["port_layanan"].get(r.port_dari, 0) + 1
        d = detail.setdefault(k, [])
        if len(d) < detail_per_origin:
            d.append({
                "waktu": r.waktu.isoformat() if r.waktu else None,
                "proto": r.proto, "aksi": r.aksi, "acl": r.acl,
                "port_dari": r.port_dari, "ke": r.ke, "port_ke": r.port_ke,
                "jumlah": r.jumlah,
                "jenis": jns,
            })

    def _ringkas(a):
        # The dominant type is set when the majority of rows are reply/ICMP. The 60%
        # threshold keeps a few stray packets from changing the verdict for a source
        # that is actually scanning.
        jinak = a["percobaan"] > 0 and a["n_jinak"] / a["percobaan"] >= 0.6
        jenis_dom = None
        port_layanan = None
        if jinak and a["jenis"]:
            jenis_dom = max(a["jenis"].items(), key=lambda kv: kv[1])[0]
            if jenis_dom == "balasan" and a["port_layanan"]:
                port_layanan = max(a["port_layanan"].items(),
                                   key=lambda kv: kv[1])[0]

        # Three categories, all decided here in Python, not in the browser:
        #   pengecekan : NSM itself, or ICMP/reply traffic. Not an attack; some of it
        #                proves the firewall works.
        #   tembus     : attacking source WITH a live connection to a service port
        #                (cross-checked with flow_koneksi). Red.
        #   diblokir   : genuine inbound attempts the firewall denied. Orange.
        if a["asal"] in ALAMAT_NSM or jinak:
            kategori = "pengecekan"
        elif _ip_bersih(a["asal"]) in penetrasi_ip:
            kategori = "tembus"
        else:
            kategori = "diblokir"

        return {
            "asal": a["asal"], "percobaan": a["percobaan"], "paket": a["paket"],
            "tujuan": sorted(a["tujuan"])[:6],
            "tujuan_jumlah": len(a["tujuan"]),
            "terakhir": a["terakhir"].isoformat() if a["terakhir"] else None,
            "kategori": kategori,
            "lokal": a["asal"] in ALAMAT_NSM,
            # `jenis_jinak` records why a source is "pengecekan" (ICMP vs service reply) so
            # the label is accurate.
            "jenis_jinak": jenis_dom,
            "port_layanan": port_layanan,
            "rincian": detail.get(a["asal"], []),
        }

    summarize_origin = sorted((_ringkas(a) for a in per_asal.values()),
                          key=lambda x: (-x["percobaan"], x["asal"]))

    return {
        "ada_data": bool(baris),
        "catatan": ("Cacahan berasal dari IOS, yang menggabungkan penolakan "
                    "serupa dalam satu jendela waktu — jadi angkanya berarti "
                    "SEDIKITNYA sekian, bukan tepat sekian."),
        "daftar": [{
            "waktu": r.waktu.isoformat() if r.waktu else None,
            "cap_router": r.cap_router,
            "router": name_device.get(r.device_id, "?"),
            "acl": r.acl,
            "aksi": r.aksi,
            "proto": r.proto,
            "dari": r.dari,
            "port_dari": r.port_dari,
            "ke": r.ke,
            "port_ke": r.port_ke,
            "jumlah": r.jumlah,
            "baris": r.baris,
        } for r in baris],
        "per_asal": summarize_origin,
    }


def deteksi_pembobolan(db):
    """Breach detection: did anything actually get in?

    Deny logs (ufw/ACL/winfw) only contain what was blocked, so a breach never
    shows up there. The evidence is established connections: `flow_koneksi` comes
    from `ss -tin` on each device and holds TCP connections live at read time; a
    port closed by the firewall has no ESTAB connections.

    Rule: an ESTAB connection to a sensitive service port (SSH, LDAP, MySQL, ...)
    from an address that is not a registered device = breach. A live connection
    means the firewall let it through (or was bypassed), and an unknown address is
    not a legitimate lab party.

    Not treated as a breach:
    - Public ports (80/443/8080/8443): they serve anyone.
    - Connections from registered devices: legitimate lab traffic.
    - Loopback / the device's own addresses.

    Limitation: `flow_koneksi` is a periodic snapshot (every 60 s), so short-lived
    connections between reads can be missed. "Not detected" does not mean "did not
    happen"; the page says so.
    """
    # Legitimate addresses: every registered device + loopback. `::ffff:` prefixes
    # are stripped so a host cannot slip through by being written differently.
    known = {"127.0.0.1", "::1", "0.0.0.0"}
    name_device = {}
    for d in db.query(Device).all():
        if d.ip_address:
            known.add(_ip_bersih(d.ip_address))
        name_device[d.id] = d.name

    # Monitored service name per (device, port), to show a familiar name instead of
    # just a port number.
    name_service = {}
    for s in db.query(Service).filter(Service.port.isnot(None)).all():
        name_service[(s.device_id, s.port)] = s.nama

    # Only recent connections. `flow_koneksi` accumulates snapshots, so old rows stay
    # after the connection closes. Without a freshness window the detector keeps
    # alarming on breaches already dealt with, and an alarm that never clears stops
    # being trusted. The window is 3 minutes: flows are read every ~60 s, so a live
    # connection is always captured; unseen for 3 rounds means it is gone.
    #
    # Intended effect: once an unauthorized connection is blocked and drops, its
    # card clears within 3 minutes.
    window_alive = timedelta(minutes=3)
    threshold = datetime.now() - window_alive
    baris = (db.query(Flow)
             .filter(Flow.keadaan == "ESTAB",
                     Flow.waktu >= threshold,
                     Flow.port_lokal.in_(list(PORT_SENSITIF.keys())))
             .all())

    merge = {}
    for f in baris:
        asal = _ip_bersih(f.ip_lawan)
        if not asal or asal in known:
            continue
        # A device connecting to itself (between interfaces) is not a breach.
        if asal == _ip_bersih(f.ip_lokal):
            continue
        kunci = (f.device_id, asal, f.port_lokal)
        g = merge.setdefault(kunci, {
            "device_id": f.device_id, "asal": asal, "port": f.port_lokal,
            "terakhir": None, "potret": 0, "proses": None})
        g["potret"] += 1
        if f.waktu and (g["terakhir"] is None or f.waktu > g["terakhir"]):
            g["terakhir"] = f.waktu
        if f.proses and not g["proses"]:
            g["proses"] = f.proses

    temuan = []
    for g in merge.values():
        dev = name_device.get(g["device_id"], "device %s" % g["device_id"])
        port = g["port"]
        layanan = (name_service.get((g["device_id"], port))
                   or PORT_SENSITIF.get(port, "port %s" % port))
        temuan.append({
            "keparahan": "kritis",
            "asal": g["asal"],
            "device": dev,
            "device_id": g["device_id"],
            "port": port,
            "layanan": layanan,
            "proses": g["proses"],
            "potret": g["potret"],
            "terakhir": g["terakhir"].isoformat() if g["terakhir"] else None,
            "judul": ("Host tak terdaftar %s TERHUBUNG ke %s (port %d) di %s"
                      % (g["asal"], layanan, port, dev)),
            "kenapa": ("Ada koneksi HIDUP dari alamat yang tidak dikenal NSM ke "
                       "layanan sensitif ini. Koneksi yang terhubung berarti "
                       "firewall meloloskannya, dan alamat yang tak terdaftar "
                       "berarti ia bukan salah satu pihak sah di lab — dua hal "
                       "yang seharusnya tidak terjadi bersamaan."),
            "saran": [
                "Segera blokir %s di firewall %s: `sudo ufw deny from %s`."
                % (g["asal"], dev, g["asal"]),
                "Periksa sesinya di %s: `sudo ss -tp | grep %s` dan log "
                "layanannya (mis. `sudo journalctl -u ssh` atau `/var/log/"
                "auth.log` untuk SSH)." % (dev, g["asal"]),
                "Kalau ia sempat LOGIN, ganti kredensial layanan itu sekarang — "
                "koneksi yang hidup berarti autentikasinya mungkin sudah lolos.",
                "Kalau %s ternyata perangkat sah, daftarkan di NSM supaya "
                "berhenti ditandai sebagai asing." % g["asal"],
            ],
        })

    # Most severe first, then newest. Everything here is "kritis", so the secondary
    # sort decides: newest events on top.
    temuan.sort(key=lambda t: t["terakhir"] or "", reverse=True)

    return {
        "ada_pembobolan": bool(temuan),
        "jumlah": len(temuan),
        "temuan": temuan,
        "catatan": ("Dibaca dari koneksi TCP yang HIDUP (`flow_koneksi`), bukan "
                    "dari log penolakan — sebab pembobolan menurut definisinya "
                    "tidak muncul di log yang isinya hanya yang diblokir. Ini "
                    "potret tiap 60 detik: ia membuktikan ADANYA koneksi tak "
                    "sah, bukan meniadakannya."),
    }


def _norm_mac(m):
    """Normalize a MAC: lowercase, colon-separated. '08-00-27-..' -> '08:00:27:..'."""
    if not m:
        return None
    return m.strip().lower().replace("-", ":")


def _baca_arp_lokal():
    """{ip: mac} from this machine's ARP table. Fail-safe: {} if unreadable.

    Read locally on the NSM host (uvicorn), not via SSH, as in
    `connectors/lokal.py`. Only valid for the local segment: MACs exist within one
    L2 segment, and hosts across a router show the router's MAC, so they are not
    compared (see `deteksi_spoofing`).
    """
    import re
    import subprocess
    try:
        r = subprocess.run(["arp", "-a"], capture_output=True, text=True,
                           timeout=8, encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return {}
    if r.returncode != 0:
        return {}
    pola = re.compile(r"^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F]{2}(?:[-:][0-9a-fA-F]{2}){5})\s")
    hasil = {}
    for baris in (r.stdout or "").splitlines():
        m = pola.match(baris)
        if m:
            hasil[m.group(1)] = _norm_mac(m.group(2))
    return hasil


def deteksi_spoofing(db):
    """Compare baseline MACs (identity) with MACs seen in ARP.

    If a known device's IP now maps to a MAC other than its registered one,
    something is impersonating it (IP spoofing / ARP poisoning). This is why a
    protected host cannot be imitated by faking the IP alone: the allowlist binds
    IP AND MAC.

    Limitation: MACs only matter within one L2 segment. Hosts across a router
    appear with the router's MAC, so only IPs in the local ARP table (same segment
    as NSM) are compared, avoiding cross-router false positives. MACs can also be
    spoofed; this raises the bar, it is not a wall.
    """
    from models import IdentitasPerangkat
    baseline = {}   # ip -> set(mac)
    for i, d in (db.query(IdentitasPerangkat, Device)
                 .join(Device, Device.id == IdentitasPerangkat.device_id)
                 .filter(IdentitasPerangkat.jenis == "mac").all()):
        if d.ip_address:
            baseline.setdefault(_ip_bersih(d.ip_address), set()).add(
                _norm_mac(i.nilai))
    name_ip = {_ip_bersih(d.ip_address): d.name
               for d in db.query(Device).all() if d.ip_address}

    arp = _baca_arp_lokal()
    arp_terbaca = bool(arp)

    spoofing = []
    for ip, mac_arp in arp.items():
        macs = baseline.get(ip)
        if not macs:
            continue  # not a registered device; out of scope here
        if mac_arp not in macs:
            spoofing.append({
                "ip": ip,
                "nama": name_ip.get(ip, ip),
                "mac_terdaftar": sorted(macs),
                "mac_terlihat": mac_arp,
                "alasan": ("Alamat %s (%s) kini menunjuk ke MAC %s, padahal MAC "
                           "terdaftarnya %s. Ada yang menyamar jadi perangkat "
                           "ini — kemungkinan pemalsuan IP atau peracunan ARP."
                           % (ip, name_ip.get(ip, "?"), mac_arp, ", ".join(sorted(macs)))),
            })

    return {
        "baseline": {ip: sorted(m) for ip, m in baseline.items()},
        "arp": arp,
        "arp_terbaca": arp_terbaca,
        "spoofing": spoofing,
    }


def daftar_dilindungi(db):
    """Addresses that must never be auto-banned (allowlist / never-ban).

    Core auto-ban safeguard so NSM never locks out its own servers. Contains:
      - every device registered in NSM (servers, routers, switches, gateways);
      - NSM's own addresses, listed explicitly so NSM can never cut its own
        monitoring path.

    A new legitimate server is protected by registering it in NSM first. Until
    then it is still safe from auto-ban as long as it is not hostile (see
    `rencana_penjagaan`): normal connections are only flagged for review.
    """
    lindungi = {}
    for d in db.query(Device).all():
        if d.ip_address:
            lindungi[_ip_bersih(d.ip_address)] = d.name
    for ip in ALAMAT_NSM:
        lindungi.setdefault(ip, "NSM (laptop pemantau)")
    return lindungi


def rencana_penjagaan(db, penolakan, pembobolan):
    """Auto-ban decision logic: who is protected, who is a block candidate, automatic vs review.

    Executes nothing; it only decides. Execution (writing firewall rules) is a
    separate path that MUST go through this decision first.

    Two core safeguards:
      1. Allowlist: anything in `daftar_dilindungi()` is never a candidate,
         whatever it does. This prevents locking out own servers, newly
         registered servers, or NSM itself.
      2. Automatic only for clear patterns: scanning (many targets), persistent
         (many attempts), or breach (live connection to a service). An unknown
         host with one normal connection (maybe an unregistered new server) is
         only flagged for one-click review.
    """
    lindungi = daftar_dilindungi(db)
    name_device = {}
    ip_to_device = {}
    location_device = {}
    for d in db.query(Device).all():
        name_device[d.id] = d.name
        location_device[d.id] = d.location
        if d.ip_address:
            ip_to_device[_ip_bersih(d.ip_address)] = d.id

    sort_pattern = {"tembus": 0, "memindai": 1, "gigih": 1, "kecil": 2}
    kandidat = {}

    def tambah(asal, pola, keparahan, alasan, target_ids):
        asal = _ip_bersih(asal)
        if not asal or asal in lindungi:
            return  # allowlisted / empty: never a candidate
        k = kandidat.get(asal)
        if k is None or sort_pattern.get(pola, 3) < sort_pattern.get(k["pola"], 3):
            kandidat[asal] = {"asal": asal, "pola": pola, "keparahan": keparahan,
                              "alasan": alasan,
                              "target_ids": set(t for t in target_ids if t)}
        else:
            k["target_ids"].update(t for t in target_ids if t)

    # 1) Breach (live connection): most severe, automatic.
    for t in (pembobolan or {}).get("temuan", []):
        tambah(t.get("asal"), "tembus", "kritis",
               "Punya koneksi HIDUP ke %s di %s"
               % (t.get("layanan"), t.get("device")),
               [t.get("device_id")])

    # 2) Patterns from the deny log: only 'diblokir' (real attacks; 'pengecekan'
    #    and protected hosts are already excluded).
    for a in (penolakan or {}).get("per_asal", []):
        if a.get("kategori") != "diblokir":
            continue
        target_ids = []
        for tuj in (a.get("tujuan") or []):
            ip = _ip_bersih(str(tuj).split(":")[0])
            if ip in ip_to_device:
                target_ids.append(ip_to_device[ip])
        if a.get("tujuan_jumlah", 0) >= AMBANG_PINDAI:
            tambah(a["asal"], "memindai", "tinggi",
                   "Memindai %d tujuan berbeda" % a["tujuan_jumlah"], target_ids)
        elif a.get("percobaan", 0) >= AMBANG_GIGIH:
            tambah(a["asal"], "gigih", "tinggi",
                   "%d percobaan berulang" % a["percobaan"], target_ids)
        else:
            tambah(a["asal"], "kecil", "sedang",
                   "%d percobaan, %d tujuan"
                   % (a.get("percobaan", 0), a.get("tujuan_jumlah", 0)), target_ids)

    # MAC binding: baseline (identity) vs live ARP on the local segment.
    spoof = deteksi_spoofing(db)
    mac_base = spoof.get("baseline", {})  # ip -> [registered mac]
    mac_arp = spoof.get("arp", {})  # ip -> mac currently seen

    hasil = []
    for k in kandidat.values():
        auto = k["pola"] in ("tembus", "memindai", "gigih")
        # If any target is at a site guarded by a router ACL (not just the device's own
        # ufw), also offer an ACL block: that is the real entry point to the site (see
        # `ubah_acl_router.py`). `LOKASI_ACL_ROUTER` is a closed list on purpose, like
        # `ubah_acl_router.ROUTER_ACL`.
        acl_router_id = None
        for i in k["target_ids"]:
            r = LOKASI_ACL_ROUTER.get(location_device.get(i))
            if r is not None:
                acl_router_id = r
                break
        hasil.append({
            "asal": k["asal"],
            "pola": k["pola"],
            "keparahan": k["keparahan"],
            "alasan": k["alasan"],
            "aksi_saran": "blokir-otomatis" if auto else "tinjau",
            "target": [name_device.get(i, "device %s" % i)
                       for i in sorted(k["target_ids"])],
            "target_ids": sorted(k["target_ids"]),
            "perintah": "sudo ufw insert 1 deny from %s" % k["asal"],
            # Attacker MAC if seen in local ARP: enables MAC-based blocking and flags
            # impersonation of a registered IP.
            "mac": mac_arp.get(k["asal"]),
            # Relevant ACL router ID, or None if this attack targets no ACL-guarded site.
            "acl_router_id": acl_router_id,
        })
    _uk = {"kritis": 0, "tinggi": 1, "sedang": 2}
    hasil.sort(key=lambda x: (0 if x["aksi_saran"] == "blokir-otomatis" else 1,
                              _uk.get(x["keparahan"], 9)))

    return {
        # Each protected host carries its registered MAC: the allowlist binds IP and
        # MAC, so faking the IP alone cannot impersonate a trusted host (see `spoofing`).
        "dilindungi": [{"ip": ip, "nama": nm, "mac": mac_base.get(ip, [])}
                       for ip, nm in sorted(lindungi.items())],
        "kandidat": hasil,
        "jumlah_auto": sum(1 for x in hasil if x["aksi_saran"] == "blokir-otomatis"),
        "jumlah_tinjau": sum(1 for x in hasil if x["aksi_saran"] == "tinjau"),
        # Impersonation warning: a registered IP whose MAC changed in ARP.
        "spoofing": spoof.get("spoofing", []),
        "arp_terbaca": spoof.get("arp_terbaca", False),
        "catatan": ("Host DILINDUNGI tidak pernah diban otomatis apa pun "
                    "perilakunya — inilah yang mencegah salah tanda mengunci "
                    "server sendiri. Auto hanya untuk pola jelas (memindai, "
                    "gigih, tembus); host asing dengan koneksi wajar hanya "
                    "ditinjau. Allowlist mengikat IP+MAC, jadi memalsukan IP "
                    "tidak cukup untuk meniru host tepercaya. Ini keputusan, "
                    "BUKAN eksekusi."),
    }


def firewall_riwayat(db, batas=20):
    """Firewall changes made through NSM, including rejected ones.

    Rejections are shown on purpose: an attempt to block NSM's own address is
    worth knowing about, and a success-only list would leave no trace of it.

    Compare with `firewall_snapshot`, which records ALL changes, including ones
    made directly on the server. A rule in the snapshot with no matching row here
    means someone changed the firewall outside NSM.
    """
    peta = dict((d.id, d.name) for d in db.query(Device).all())
    baris = (db.query(FirewallPerubahan)
             .order_by(FirewallPerubahan.id.desc())
             .limit(batas).all())
    return [{
        "waktu": r.waktu.isoformat() if r.waktu else None,
        "device": peta.get(r.device_id, "?"),
        "aksi": r.aksi,
        "ip_sasaran": r.ip_sasaran,
        "menit": r.menit,
        "alasan": r.alasan,
        "oleh": r.oleh,
        "hasil": r.hasil,
        # Rejections and rollbacks are flagged to tell them apart from changes that
        # actually happened.
        "berhasil": r.hasil == "BERHASIL",
        "bukti": (r.bukti or "")[:600] or None,
    } for r in baris]


def firewall_semua(db):
    """Firewall state per device, with its rules.

    Three states that must not be confused, all producing an empty rule list:

        aktif=1, no rules     -> firewall on, default policy decides. With
                                 `deny incoming` the host is fully closed.
        aktif=0               -> firewall OFF. The host is open.
        never read            -> NSM knows nothing.

    Treating them alike shows the same empty table for a locked-down host and a
    wide-open one, so each device carries its own `keadaan`.
    """
    hasil = []
    # `platform in (linux, lokal)`: Windows Firewall on the NSM host
    # (`platform == "lokal"`) is read by `poll_firewall_lokal()` in the same shape
    # (one FirewallSnapshot per device), so no special case is needed here.
    for d in (db.query(Device)
              # Devices whose firewall runs on the host itself: `ufw` on Linux, `netsh` on the
              # NSM host. The list comes from the device definition files, not hardcoded names.
              .filter(Device.platform.in_(
                  dialek_perangkat.platform_dengan("firewall", "ufw", "netsh")))
              .order_by(Device.id).all()):
        snap = (db.query(FirewallSnapshot)
                .filter(FirewallSnapshot.device_id == d.id)
                .order_by(FirewallSnapshot.id.desc())
                .first())

        if snap is None:
            # The message differs per platform: Linux needs sudo, the NSM host needs no
            # privileges (netsh runs as a normal user), so mentioning sudo there would mislead.
            summarize_empty = (
                "Belum pernah terbaca. Akun pemantau butuh izin sudo "
                "terbatas di perangkat ini (firewall/pasang-baca-firewall.sh)."
            ) if dialek_perangkat.ambil(d.platform).firewall == "ufw" else (
                "Belum pernah terbaca. Menunggu putaran poller berikutnya "
                "(job firewall_lokal)."
            )
            hasil.append({
                "device_id": d.id, "device": d.name, "ip": d.ip_address,
                "platform": d.platform,
                "keadaan": "belum_terbaca",
                "ringkas": summarize_empty,
                "aktif": None, "aturan": [], "jumlah_aturan": 0,
                "kebijakan_masuk": None, "kebijakan_keluar": None,
                "logging": None, "waktu": None, "riwayat": 0,
            })
            continue

        aturan = (db.query(FirewallAturan)
                  .filter(FirewallAturan.snapshot_id == snap.id)
                  .order_by(FirewallAturan.nomor).all())

        if not snap.aktif:
            keadaan = "mati"
            ringkas = ("Firewall MATI. Semua port yang ada layanannya bisa "
                       "dihubungi siapa pun yang bisa menjangkau alamat ini.")
        elif not aturan:
            keadaan = "tanpa_aturan"
            ringkas = ("Firewall menyala tanpa satu pun aturan. Yang berlaku "
                       "seluruhnya kebijakan bawaan: masuk "
                       + str(snap.kebijakan_masuk) + ".")
        else:
            keadaan = "aktif"
            ringkas = None

        # How many times the rules have changed; distinguishes "always been this way"
        # from "just changed by someone".
        riwayat = (db.query(func.count(FirewallSnapshot.id))
                   .filter(FirewallSnapshot.device_id == d.id).scalar() or 0)

        hasil.append({
            "device_id": d.id, "device": d.name, "ip": d.ip_address,
            "platform": d.platform,
            "keadaan": keadaan,
            "ringkas": ringkas,
            "aktif": int(snap.aktif or 0),
            "kebijakan_masuk": snap.kebijakan_masuk,
            "kebijakan_keluar": snap.kebijakan_keluar,
            "logging": snap.logging,
            "waktu": snap.waktu.isoformat() if snap.waktu else None,
            "jumlah_aturan": snap.jumlah_aturan or 0,
            # history-1 because the first snapshot is the initial read, not a change;
            # otherwise every newly monitored device would look recently modified.
            "riwayat": max(0, riwayat - 1),
            "aturan": [{
                "nomor": a.nomor, "ke": a.ke, "aksi": a.aksi,
                "arah": a.arah, "dari": a.dari, "komentar": a.komentar,
                # Rules open to anyone are flagged. Not a verdict (SSH open to the whole lab may
                # be intended), but these rows deserve a look first.
                "terbuka_luas": (a.dari or "").lower().startswith("anywhere"),
            } for a in aturan],
        })
    return hasil


def _hitung_baris_acl(teks_konfig):
    """Count of permit/deny lines across all named ACL blocks in one Cisco config
    snapshot. `remark` is skipped: it is documentation, not a rule.

    There is no structured table for Cisco ACLs (unlike ufw/Windows in
    `firewall_aturan`). Counted from the raw `teks` of config snapshots already
    saved every 15 minutes: no new device read and no extra table to keep in sync.
    """
    if not teks_konfig:
        return 0
    total = 0
    for _nama, content in POLA_BLOK_ACL.findall(teks_konfig):
        for baris in content.splitlines():
            if POLA_BARIS_IZIN.match(baris):
                total += 1
    return total


def peta_lapis_firewall(db):
    """Summary of the three firewall layers in the lab, one card per layer.

    Answers "which firewalls does NSM use, where, protecting what" at the top of
    the page.

    Rule counts per layer come from different sources on purpose (see each
    layer's comment): the three firewalls are stored through three different
    paths, and forcing one shape here would hide that.
    """
    from models import KonfigSnapshot

    # --- Layer 1: ufw, each Linux server ---
    linux_snap_ids = [s.id for s in (
        db.query(FirewallSnapshot.id)
        .join(Device, Device.id == FirewallSnapshot.device_id)
        .filter(Device.platform.in_(
            dialek_perangkat.platform_dengan("firewall", "ufw")))
        .filter(FirewallSnapshot.id.in_(
            db.query(func.max(FirewallSnapshot.id))
            .filter(FirewallSnapshot.device_id.in_(
                db.query(Device.id).filter(Device.platform.in_(
                    dialek_perangkat.platform_dengan("firewall", "ufw")))))
            .group_by(FirewallSnapshot.device_id)
        )).all())]
    count_ufw = (db.query(func.count(FirewallAturan.id))
               .filter(FirewallAturan.snapshot_id.in_(linux_snap_ids)).scalar()
               if linux_snap_ids else 0)
    n_linux = db.query(Device).filter(
        Device.platform.in_(dialek_perangkat.platform_dengan("firewall", "ufw")),
        Device.aktif != 0).count()
    rejection_ufw = (db.query(func.count(PenolakanAcl.id))
                      .filter(PenolakanAcl.acl == "ufw").scalar() or 0)

    # --- Layer 2: router R2 ACL, the only entry to Site B ---
    router_b = db.query(Device).filter(Device.ip_address == "192.168.20.1").first()
    count_acl = 0
    drift_acl = []
    if router_b is not None:
        snapshot_last = (db.query(KonfigSnapshot)
                           .filter(KonfigSnapshot.device_id == router_b.id)
                           .order_by(desc(KonfigSnapshot.waktu)).first())
        if snapshot_last is not None:
            count_acl = _hitung_baris_acl(snapshot_last.teks)
            if snapshot_last.acl_berubah:
                drift_acl.append(snapshot_last.waktu.isoformat()
                                 if snapshot_last.waktu else None)
    rejection_router = (db.query(func.count(PenolakanAcl.id))
                        .filter(~PenolakanAcl.acl.in_(("ufw", "winfw"))).scalar() or 0)

    # --- Layer 3: Windows Firewall on the NSM host ---
    laptop = db.query(Device).filter(Device.platform.in_(
        dialek_perangkat.platform_dengan("firewall", "netsh"))).first()
    count_winfw = 0
    winfw_readable = False
    if laptop is not None:
        snap_laptop = (db.query(FirewallSnapshot)
                       .filter(FirewallSnapshot.device_id == laptop.id)
                       .order_by(FirewallSnapshot.id.desc()).first())
        if snap_laptop is not None:
            winfw_readable = True
            count_winfw = snap_laptop.jumlah_aturan or 0
    rejection_winfw = (db.query(func.count(PenolakanAcl.id))
                       .filter(PenolakanAcl.acl == "winfw").scalar() or 0)
    # Windows Firewall deny logging is OFF by default, unlike ufw and router ACLs.
    # Zero deny rows does not mean nothing was denied; LogBlocked may never have
    # been enabled. This is checked, not guessed.
    #
    # Row count alone answers the wrong question: `penolakan_winfw > 0` means "was
    # ever logged", not "is still logged", so one old row would keep the green badge
    # on forever. Typical failure: the poller runs as a normal account,
    # `pfirewall.log` is readable only by Administrators, every read fails, and the
    # page keeps showing a frozen count that looks like current state.
    #
    # `posisi_log.diperbarui` serves as "last successful read": the poller sets it
    # only after a read completes (`poller.py`, after deny rows are added). When a
    # read raises, the transaction rolls back and the timestamp does not advance.
    from connectors.winfw import JALUR_LOG as _JALUR_WINFW
    from models import PosisiLog

    winfw_readable_at = None
    if laptop is not None:
        winfw_readable_at = (
            db.query(func.max(PosisiLog.diperbarui))
            .filter(PosisiLog.device_id == laptop.id,
                    PosisiLog.jalur == _JALUR_WINFW).scalar())

    # The threshold is derived from the read interval, not a fixed number: three
    # missed rounds means reading has stopped, while one late round is not reported
    # as a failure.
    _batas_macet = config.get_firewall_interval() * 3
    winfw_macet = False
    if winfw_readable_at is not None:
        winfw_macet = (datetime.now() - winfw_readable_at).total_seconds() > _batas_macet
    elif rejection_winfw > 0:
        # Rows exist but no successful read is recorded. The rows came from somewhere,
        # so this is "stalled", not "never enabled".
        winfw_macet = True

    # The green badge only shows while reading is still running.
    winfw_log_active = rejection_winfw > 0 and not winfw_macet

    # Cause + recovery command, computed here so the page can point straight to the fix.
    #
    # Why actually open the file instead of `os.access(R_OK)`: on Windows
    # `os.access` checks the read-only attribute, NOT the ACL, and says "allowed"
    # for files the ACL denies. Only a real read is reliable. Cheap (1 byte) and
    # only run when already stalled.
    winfw_cause = None
    winfw_recovery = None
    if winfw_macet:
        path_log = os.path.expandvars(_JALUR_WINFW)
        exists_file = os.path.exists(path_log)
        can_read = False
        if exists_file:
            try:
                with open(path_log, "rb") as _fh:
                    _fh.read(1)
                can_read = True
            except (PermissionError, OSError):
                can_read = False
        if exists_file and not can_read:
            winfw_cause = (
                "NSM tidak boleh membaca berkas log firewall Windows. Ini "
                "hampir selalu terjadi setelah log penuh (4 MB) lalu Windows "
                "membuat berkas BARU dengan izin bawaan (hanya Administrator) — "
                "izin baca yang pernah diberikan ikut hilang bersama berkas lama.")
            import getpass
            dom = os.environ.get("USERDOMAIN", "")
            usr = getpass.getuser()
            account = (dom + "\\" + usr) if dom else usr
            folder = os.path.dirname(path_log)
            # Grant on the FOLDER with (OI)(CI) inheritance so the permission survives log
            # rotation, unlike a single-file grant that breaks each time the log rolls over.
            # Run as Administrator.
            winfw_recovery = (
                'icacls "%s" /grant "%s:(OI)(CI)R"' % (folder, account))

    return [
        {
            "lapis": "ufw", "nama": "ufw (tiap server Linux)",
            "letak": str(n_linux) + " server Linux di lab",
            "melindungi": "Host itu sendiri, per perangkat",
            "jumlah_aturan": count_ufw,
            "mencatat_penolakan": True,
            "penolakan_tercatat": rejection_ufw,
            "drift": [],
        },
        {
            "lapis": "acl_router",
            "nama": "ACL router (" + (router_b.name if router_b else "R2") + ")",
            "letak": "R2, FastEthernet0/1 arah masuk",
            "melindungi": "Seluruh Lokasi B (192.168.20.0/24)",
            "jumlah_aturan": count_acl,
            "mencatat_penolakan": True,
            "penolakan_tercatat": rejection_router,
            "drift": drift_acl,
        },
        {
            "lapis": "winfw", "nama": "Windows Firewall (laptop)",
            "letak": laptop.name if laptop else "Laptop tempat NSM berjalan",
            "melindungi": "Laptop itu sendiri",
            "jumlah_aturan": count_winfw,
            "mencatat_penolakan": winfw_log_active,
            "penolakan_tercatat": rejection_winfw,
            "drift": [],
            "terbaca": winfw_readable,
            # The two fields below let the badge distinguish "never enabled" from "used to
            # work, now stopped". The deny count is still sent as-is; the page just stops
            # presenting it as current state.
            "pembacaan_macet": winfw_macet,
            "terbaca_terakhir": (winfw_readable_at.isoformat()
                                 if winfw_readable_at else None),
            # Concrete cause + copyable recovery command when the stall is a read-permission
            # problem; None otherwise.
            "sebab": winfw_cause,
            "pemulihan": winfw_recovery,
        },
    ]


def acl_drift(db, ambang_hari=30):
    """Cisco routers whose ACL was changed directly via CLI, outside NSM.

    Snapshots with a `FirewallPerubahan` row whose `hasil` is
    BERHASIL/BERHASIL_TANPA_BUKTI for the same device in the window
    (previous snapshot, this snapshot] are NOT reported as drift: NSM itself made
    that change (via `blokir_acl()`/`buka_blokir_acl()` in `ubah_acl_router.py`).
    Only ACL changes with no NSM record explaining them are reported.

    Only a router whose LATEST snapshot has `acl_berubah=1` is reported; older
    snapshots stay in the normal config history but should not keep raising a
    warning on the Firewall page once a newer snapshot exists.
    """
    from models import KonfigSnapshot

    kandidat = []  # (device, latest snapshot, previous snapshot)
    for d in (db.query(Device)
              # Devices whose access rules are router ACLs.
              .filter(Device.platform.in_(
                  dialek_perangkat.platform_dengan("firewall", "acl")))
              .order_by(Device.id).all()):
        terakhir = (db.query(KonfigSnapshot)
                    .filter(KonfigSnapshot.device_id == d.id)
                    .order_by(desc(KonfigSnapshot.waktu))
                    .first())
        if terakhir is None or not terakhir.acl_berubah:
            continue
        previous = (db.query(KonfigSnapshot)
                      .filter(KonfigSnapshot.device_id == d.id,
                              KonfigSnapshot.waktu < terakhir.waktu)
                      .order_by(desc(KonfigSnapshot.waktu))
                      .first())
        kandidat.append((d, terakhir, previous))

    if not kandidat:
        return []

    per_device = _perubahan_nsm_per_device(db, [d.id for d, _t, _s in kandidat])

    hasil = []
    for d, terakhir, previous in kandidat:
        actor = _pelaku_jendela(
            per_device.get(d.id),
            previous.waktu if previous else None,
            terakhir.waktu)
        if actor is not None:
            continue  # explained by NSM itself; not drift
        hasil.append({
            "device_id": d.id, "device": d.name, "ip": d.ip_address,
            "waktu": terakhir.waktu.isoformat() if terakhir.waktu else None,
            "baris_tambah": terakhir.baris_tambah,
            "baris_hapus": terakhir.baris_hapus,
        })
    return hasil


def _urai_ke(ke):
    """'22/tcp' -> (22, 'tcp'). '80' -> (80, None). 'Apache Full' -> (None, None).

    ufw application profile names ('Apache Full', 'OpenSSH') deliberately give
    None rather than a guessed port, so no finding rests on a guess.
    """
    if not ke:
        return (None, None)
    teks = str(ke).strip()
    proto = None
    if "/" in teks:
        teks, proto = teks.split("/", 1)
        proto = proto.strip().lower()
    teks = teks.strip()
    if not teks.isdigit():
        return (None, proto)
    return (int(teks), proto)


def _jaringan(dari):
    """'192.168.56.0/24' -> network object. 'Anywhere' -> all of IPv4.

    Returns None when unparseable, meaning "unknown", not "no match". Checks below
    skip rows with unparsed addresses instead of treating them as matches.
    """
    import ipaddress
    if not dari:
        return None
    teks = str(dari).strip()
    if teks.lower().startswith("anywhere"):
        # 'Anywhere (v6)' lands here too. IPv6 is not compared with IPv4 below since
        # ipaddress refuses to mix them, which is correct.
        if "v6" in teks.lower():
            return None
        return ipaddress.ip_network("0.0.0.0/0")
    try:
        return ipaddress.ip_network(teks, strict=False)
    except ValueError:
        return None


def firewall_temuan(db):
    """Firewall rule quality findings per device.

    Same shape as config compliance findings (severity, title, why, evidence) so
    the page renders one format for both.
    """
    hasil = []
    for d in (db.query(Device)
              .filter(Device.platform.in_(
                  dialek_perangkat.platform_dengan("firewall", "ufw")))
              .order_by(Device.id).all()):
        snap = (db.query(FirewallSnapshot)
                .filter(FirewallSnapshot.device_id == d.id)
                .order_by(FirewallSnapshot.id.desc())
                .first())
        if snap is None:
            continue

        aturan = (db.query(FirewallAturan)
                  .filter(FirewallAturan.snapshot_id == snap.id)
                  .order_by(FirewallAturan.nomor).all())

        temuan = []

        # --- 1) Open to anyone ---
        # Not an automatic verdict: port 80 on a web server IS for everyone. Severity
        # depends on the port: a way into the host, or a service meant to be public.
        for a in aturan:
            if (a.aksi or "").upper() != "ALLOW":
                continue
            jar = _jaringan(a.dari)
            if jar is None or jar.prefixlen != 0:
                continue
            port, proto = _urai_ke(a.ke)
            gate = PORT_PINTU_MASUK.get(port)
            temuan.append({
                "keparahan": "tinggi" if gate else "sedang",
                "judul": (("Port " + str(a.ke) + " (" + gate + ") terbuka untuk siapa saja")
                          if gate else
                          ("Port " + str(a.ke) + " terbuka untuk siapa saja")),
                "kenapa": (
                    ("Ini pintu masuk ke mesinnya sendiri, bukan layanan yang "
                     "dilayani ke publik. Siapa pun yang bisa menjangkau alamat "
                     "ini boleh mencoba masuk, dan satu-satunya yang tersisa "
                     "sebagai penjaga adalah sandinya.")
                    if gate else
                    ("Terbuka untuk siapa saja bisa saja memang disengaja — "
                     "port web memang begitu. Yang perlu diputuskan: apakah "
                     "layanan di port ini memang untuk semua orang.")),
                "bukti": "aturan #" + str(a.nomor) + ": " + str(a.ke)
                         + " ALLOW dari " + str(a.dari),
                "nomor": a.nomor,
            })

        # --- 2) Duplicate rules ---
        # Identical match criteria, so the second never adds anything. Low severity: it
        # opens nothing new, it just makes the list longer than needed, and long lists
        # stop being read.
        visible = {}
        for a in aturan:
            kunci = ((a.ke or "").lower(), (a.aksi or "").upper(),
                     (a.arah or "").upper(), (a.dari or "").lower())
            if kunci in visible:
                temuan.append({
                    "keparahan": "rendah",
                    "judul": "Aturan #" + str(a.nomor) + " kembar dengan #"
                             + str(visible[kunci]),
                    "kenapa": ("Kriteria cocoknya sama persis, jadi yang kedua "
                               "tidak pernah menambah apa pun."),
                    "bukti": str(a.ke) + " " + str(a.aksi) + " dari " + str(a.dari),
                    "nomor": a.nomor,
                })
            else:
                visible[kunci] = a.nomor

        # --- 3) Rules shadowed by an earlier rule ---
        # Rule #7 "3306 from 192.168.20.101" adds nothing if #2 already says "3306 from
        # 192.168.20.0/24" (a shadowed rule).
        for i, a in enumerate(aturan):
            if (a.aksi or "").upper() != "ALLOW":
                continue
            jar_a = _jaringan(a.dari)
            port_a = _urai_ke(a.ke)
            if jar_a is None or port_a[0] is None:
                continue
            for b in aturan[:i]:
                if (b.aksi or "").upper() != "ALLOW":
                    continue
                if (b.arah or "").upper() != (a.arah or "").upper():
                    continue
                if _urai_ke(b.ke) != port_a:
                    continue
                jar_b = _jaringan(b.dari)
                if jar_b is None or jar_b.version != jar_a.version:
                    continue
                # Broader OR equal; exact duplicates were already caught above, so only broader
                # ones here.
                if jar_b.prefixlen < jar_a.prefixlen and jar_a.subnet_of(jar_b):
                    temuan.append({
                        "keparahan": "rendah",
                        "judul": "Aturan #" + str(a.nomor)
                                 + " sudah tercakup aturan #" + str(b.nomor),
                        "kenapa": ("Aturan #" + str(b.nomor) + " sudah "
                                   "mengizinkan seluruh " + str(b.dari)
                                   + ", dan " + str(a.dari) + " ada di dalamnya. "
                                   "Menghapus yang lebih sempit tidak mengubah "
                                   "apa pun yang bisa lewat."),
                        "bukti": "#" + str(a.nomor) + " " + str(a.ke) + " dari "
                                 + str(a.dari) + "  <=  #" + str(b.nomor)
                                 + " dari " + str(b.dari),
                        "nomor": a.nomor,
                    })
                    break

        # --- 4) Monitored services with no opening ---
        # The reverse of the checks above, and the one that predicts breakage: a
        # monitored service whose port is not allowed from anywhere reads as "service
        # down" when the firewall is the cause.
        if snap.aktif and aturan:
            port_terbuka = set()
            for a in aturan:
                if (a.aksi or "").upper() != "ALLOW":
                    continue
                p, _ = _urai_ke(a.ke)
                if p is not None:
                    port_terbuka.add(p)
            layanan = (db.query(Service)
                       .filter(Service.device_id == d.id).all())
            for s in layanan:
                if s.port and s.port not in port_terbuka:
                    temuan.append({
                        "keparahan": "sedang",
                        "judul": "Layanan " + str(s.nama) + " dipantau di port "
                                 + str(s.port) + ", tetapi tidak ada aturan yang "
                                 "mengizinkannya",
                        "kenapa": ("Kalau layanan ini nanti terbaca mati, "
                                   "sebabnya bisa jadi firewall — bukan "
                                   "layanannya. Perbedaan itu tidak terlihat "
                                   "dari halaman Layanan, karena keduanya "
                                   "menghasilkan gejala yang sama persis."),
                        "bukti": "port " + str(s.port) + " tidak ada di "
                                 + str(len(port_terbuka)) + " port yang diizinkan",
                        "nomor": None,
                    })

        cacah = {"tinggi": 0, "sedang": 0, "rendah": 0}
        for t in temuan:
            cacah[t["keparahan"]] = cacah.get(t["keparahan"], 0) + 1

        hasil.append({
            "device_id": d.id,
            "device": d.name,
            "jumlah_aturan": len(aturan),
            "cacah": cacah,
            "temuan": temuan,
            # Stated, not hidden: a page listing three finding types without mentioning the
            # fourth it cannot check would read as if it checked everything.
            "tak_terperiksa": (
                "Aturan yang tidak pernah kena lalu lintas tidak bisa diperiksa "
                "NSM: `ufw status` tidak menyediakan pencacah, dan angkanya "
                "hanya ada di `iptables -L -n -v` yang menuntut izin sudo baru "
                "di tiap server."),
        })
    return hasil

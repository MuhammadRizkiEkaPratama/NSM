"""Device discovery: scan a subnet, identify hosts, and OFFER them -- never add them.

A monitor that auto-adds whatever it sees lets anyone who can plug in an IP
add load to it (every device pinged every five seconds, forever). Scan
results therefore never go into `devices`; they go into their own offers
table, and only a human action moves them. Because the platform is already
identified, an approved device produces data right away.

Discovery runs in two layers, because `connectors/snmp.py` is SNMPv3-only
and requires credentials (`_identitas()` raises if `user` is empty), which
an untouched subnet does not have yet:

    1. ICMP + TCP   -> no credentials. Answers "what is here".
    2. SNMP         -> only when credentials are given. Answers "what is it".

Hosts that pass layer 1 but not layer 2 are still offered, with an empty
platform. Ping, TCP and service checks are vendor-neutral; only config reads
and the write path are unavailable.

No commands are ever sent to devices from this file.
"""
import ipaddress

import dialek_perangkat
from connectors.snmp import OID_SYS_OBJECT_ID

# sysObjectID is the only OID discovery queries, deliberately. It asks "what
# are you", not "how are you"; every extra query is extra traffic to devices
# whose owners may not have asked to be scanned.
__all__ = ["OID_SYS_OBJECT_ID", "PORT_BAWAAN", "BATAS_ALAMAT", "PindaiDitolak",
           "Temuan", "alamat_dalam", "kenali", "pindai"]

# Ports probed. Few, deliberately: a full port scan is a security scanner's
# job and looks like an attack to the target. These four answer how the
# device can be managed.
PORT_BAWAAN = (22, 80, 443, 161)

# Max addresses per scan (about a /22). The exact value is arbitrary; having a
# limit is what matters. Without it, a typo like `10.0.0.0/8` instead of
# `10.0.0.0/24` means 16M addresses and NSM flooding its own network for hours
# with no way to stop it from the UI.
BATAS_ALAMAT = 1024


class PindaiDitolak(Exception):
    """Scan request rejected. The message is meant for humans."""


class Temuan:
    """One responding address. Plain data; no database access."""

    def __init__(self, ip, hidup=False, rtt_ms=None, port_terbuka=(),
                 sysobjectid=None, platform=None, catatan=""):
        self.ip = ip
        self.hidup = hidup
        self.rtt_ms = rtt_ms
        self.port_terbuka = list(port_terbuka)
        self.sysobjectid = sysobjectid
        self.platform = platform
        self.catatan = catatan

    @property
    def dikenali(self):
        return bool(self.platform)

    def sebagai_dict(self):
        return {
            "ip": self.ip,
            "hidup": self.hidup,
            "rtt_ms": self.rtt_ms,
            "port_terbuka": list(self.port_terbuka),
            "sysobjectid": self.sysobjectid,
            "platform": self.platform,
            "keterangan_platform": (
                dialek_perangkat.ambil(self.platform).keterangan
                if self.platform else ""),
            "catatan": self.catatan,
        }

    def __repr__(self):
        return "<Temuan %s hidup=%s platform=%s port=%s>" % (
            self.ip, self.hidup, self.platform, self.port_terbuka)


def alamat_dalam(jaringan, batas=BATAS_ALAMAT, izinkan_publik=False):
    """Return the list of addresses to scan, or raise `PindaiDitolak`.

    All three rejections happen before any packet is sent:

    1. Not a valid network: typos are rejected, not silently turned into a
       different scan.
    2. Too large: see `BATAS_ALAMAT`.
    3. Not a private range: scanning public addresses looks hostile to the
       target, and the liability falls on the source network's owner. Can be
       overridden with `izinkan_publik=True`, which must be deliberate and is
       never the default.
    """
    try:
        jar = ipaddress.ip_network(str(jaringan).strip(), strict=False)
    except ValueError as e:
        raise PindaiDitolak(
            "%r bukan jaringan yang sah: %s" % (jaringan, e)) from e

    if not izinkan_publik and not (jar.is_private or jar.is_loopback
                                   or jar.is_link_local):
        raise PindaiDitolak(
            "%s bukan rentang alamat pribadi. Memindai alamat publik dari "
            "jaringan ini terlihat sebagai pemindaian bermusuhan di sisi "
            "penerimanya, dan yang menanggungnya pemilik jaringan ini. Kalau "
            "memang disengaja, nyatakan `izinkan_publik`." % jar)

    # Check the size BEFORE building the address list. Materializing `hosts()`
    # for `10.0.0.0/8` creates ~16.7M address objects plus strings just to call
    # `len()` and then reject; a guard that does the excessive work itself is no
    # guard.
    if jar.num_addresses > batas + 2:
        raise PindaiDitolak(
            "%s berisi %d alamat, melebihi batas %d. Persempit rentangnya, "
            "atau naikkan batasnya dengan sengaja."
            % (jar, jar.num_addresses, batas))

    # `hosts()` already drops network and broadcast addresses for prefixes that
    # have them, and returns the single address for a /32.
    alamat = [str(a) for a in jar.hosts()] or [str(jar.network_address)]

    # Re-checked after dropping network/broadcast so the caller's limit applies to
    # the number actually scanned.
    if len(alamat) > batas:
        raise PindaiDitolak(
            "%s berisi %d alamat yang bisa dipindai, melebihi batas %d. "
            "Persempit rentangnya, atau naikkan batasnya dengan sengaja."
            % (jar, len(alamat), batas))
    return alamat


def kenali(sysobjectid):
    """sysObjectID -> platform name, or None if no definition exists.

    Deliberately thin wrapper over `dialek_perangkat`: the match table lives in
    the device definition files, so a new vendor needs only a new YAML file.
    """
    return dialek_perangkat.dari_sysobjectid(sysobjectid)


def _sysobjectid(ip, snmp):
    """Query sysObjectID on one address. Returns None if there is no answer.

    Silent on failure by design: hosts that do not answer SNMP are normal on an
    unknown subnet. Raising would stop the scan at the first non-SNMPv3 address.
    """
    from connectors.snmp import SnmpConnector
    try:
        c = SnmpConnector(ip, **snmp)
        hasil = c.ambil_oid([OID_SYS_OBJECT_ID])
        value = (hasil or {}).get(OID_SYS_OBJECT_ID)
        return str(value) if value else None
    except Exception:
        return None


def pindai(jaringan, ports=PORT_BAWAAN, batas=BATAS_ALAMAT,
           izinkan_publik=False, snmp=None):
    """Scan one network and return only live `Temuan` entries.

    `snmp` is an SNMPv3 credential dict (`user`, `auth_pass`, ...) or None. None
    skips layer 2 entirely, so all results have an empty platform.

    Does not touch the database, so the network part can be tested without a
    database and the database part without a network.
    """
    from connectors.icmp import ping_banyak
    from connectors.tcp import cek_port_banyak

    alamat = alamat_dalam(jaringan, batas=batas, izinkan_publik=izinkan_publik)

    # Layer 1a: who answers. Batched, not sequential; see
    # `connectors/icmp.py ping_banyak()`.
    ping_map = ping_banyak(alamat)
    hidup = [ip for ip in alamat if (ping_map.get(ip) or (False, None))[0]]
    if not hidup:
        return []

    # Layer 1b: probe ports only on hosts that answered; probing dead hosts just
    # waits for timeouts.
    port_map = cek_port_banyak(hidup, list(ports)) if ports else {}

    hasil = []
    for ip in hidup:
        t = Temuan(ip, hidup=True,
                   rtt_ms=(ping_map.get(ip) or (False, None))[1],
                   port_terbuka=port_map.get(ip) or [])
        if snmp:
            t.sysobjectid = _sysobjectid(ip, snmp)
            t.platform = kenali(t.sysobjectid)
            if t.sysobjectid and not t.platform:
                t.catatan = ("menjawab SNMP tetapi sysObjectID %s belum punya "
                             "berkas definisi" % t.sysobjectid)
            elif not t.sysobjectid:
                t.catatan = "tidak menjawab SNMPv3 dengan kredensial yang diberikan"
        else:
            t.catatan = "kredensial SNMP tidak diberikan, platform tidak ditanyakan"
        hasil.append(t)
    return hasil


# ---------------------------------------------------------------------------
# Storage, and the only path into the `devices` table
# ---------------------------------------------------------------------------
STATUS = ("baru", "disetujui", "diabaikan")


def simpan(db, temuan, tenant_id=None):
    """Save scan results to `perangkat_ditemukan` and return a summary.

    Never touches the `devices` table. Known addresses are updated, not added
    again, and two columns are treated specially:

      * `pertama_terlihat` is never overwritten, so "since when has this been on
        the network" is not lost on every scan.
      * `status` is never reset to `baru`. Human decisions persist: ignored
        addresses do not reappear in the queue, and addresses that already
        became devices are not offered twice.
    """
    from datetime import datetime

    import models

    baru = diperbarui = 0
    for t in temuan:
        line = (db.query(models.PerangkatDitemukan)
                 .filter(models.PerangkatDitemukan.ip_address == t.ip,
                         models.PerangkatDitemukan.tenant_id == tenant_id)
                 .first())
        if line is None:
            line = models.PerangkatDitemukan(
                ip_address=t.ip, tenant_id=tenant_id, status="baru",
                pertama_terlihat=datetime.now())
            db.add(line)
            baru += 1
        else:
            diperbarui += 1

        line.terakhir_terlihat = datetime.now()
        line.rtt_ms = t.rtt_ms
        line.port_terbuka = ",".join(str(p) for p in t.port_terbuka) or None
        line.catatan = (t.catatan or "")[:500] or None

        # Only overwrite sysObjectID and platform when this scan actually got an
        # answer. A scan without SNMP credentials must not erase a platform that was
        # identified earlier.
        if t.sysobjectid:
            line.sysobjectid = t.sysobjectid
        if t.platform:
            line.platform = t.platform

    db.commit()
    return {"baru": baru, "diperbarui": diperbarui, "total": len(temuan)}


def daftar(db, status="baru", tenant_id=None):
    """Offers awaiting a decision. `status=None` returns all of them."""
    import models

    q = db.query(models.PerangkatDitemukan)
    if tenant_id is not None:
        q = q.filter(models.PerangkatDitemukan.tenant_id == tenant_id)
    if status:
        q = q.filter(models.PerangkatDitemukan.status == status)
    return q.order_by(models.PerangkatDitemukan.ip_address).all()


def abaikan(db, finding_id):
    """Mark an offer as not our device. The decision persists."""
    import models

    line = db.get(models.PerangkatDitemukan, finding_id)
    if line is None:
        raise ValueError("temuan %r tidak ada" % finding_id)
    if line.status == "disetujui":
        raise ValueError(
            "temuan %r sudah jadi device #%s; hapus device-nya kalau memang "
            "mau dibatalkan" % (finding_id, line.device_id))
    line.status = "diabaikan"
    db.commit()
    return line


def setujui(db, finding_id, nama, device_type="server", platform=None):
    """Turn an offer into a device. The ONLY path into `devices`.

    The device is created with `aktif=0`. Approving means "this is ours", not
    "start monitoring now": an immediately active device would be pinged and
    raise incidents before its credentials and thresholds are set, producing
    false alarms. Activation is a separate step on the device page, where
    credentials and thresholds are configured.
    """
    import models

    line = db.get(models.PerangkatDitemukan, finding_id)
    if line is None:
        raise ValueError("temuan %r tidak ada" % finding_id)
    if line.status == "disetujui":
        raise ValueError("temuan %r sudah jadi device #%s"
                         % (finding_id, line.device_id))

    # An address that already has a device must not get a second one; two rows
    # would mean two partial histories for one machine.
    already = (db.query(models.Device)
             .filter(models.Device.ip_address == line.ip_address).first())
    if already is not None:
        raise ValueError("alamat %s sudah terdaftar sebagai device #%s (%s)"
                         % (line.ip_address, already.id, already.name))

    d = models.Device(
        name=nama,
        ip_address=line.ip_address,
        device_type=device_type,
        platform=platform or line.platform or None,
        tenant_id=line.tenant_id,
        aktif=0,  # see docstring
    )
    db.add(d)
    db.flush()  # so `d.id` exists before linking

    line.status = "disetujui"
    line.device_id = d.id
    db.commit()
    return d

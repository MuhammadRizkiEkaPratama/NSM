"""Syslog receiver: lets NSM hear device events instead of only polling.

Devices push events such as:

    %LINK-3-UPDOWN: Interface FastEthernet1/1, changed state to down
    %SYS-5-CONFIG_I: Configured from console by vty0 (192.168.56.1)

The first arrives immediately, not at the next ping; the second tells who
changed the config and from where.

Design: `urai()` and `sidik_templat()` are pure functions (no socket, no DB),
so they can be tested with real messages and a parse error never crashes the
receiver.

Port 1514, not 514: ports below 1024 need privileges on Linux, and `nsm-app`
runs as the unprivileged user `nsmapp`. Running a parser of unauthenticated
network input as root is a bad trade. Point Cisco devices at it with:

    logging host 192.168.56.156 transport udp port 1514

If 514 is ever required, use `AmbientCapabilities=CAP_NET_BIND_SERVICE` in the
systemd unit or a firewall port redirect, not root.

Syslog is unauthenticated UDP, so anyone on the network can pose as a router:

  * `device_id` is a guess from the sender address, which is stored as
    `alamat` so it can be re-checked;
  * unknown senders are still stored (`device_id` NULL); they are worth seeing;
  * syslog never triggers automated device actions directly. It is evidence
    and a trigger for checks; decisions still go through `pagar_otomasi`,
    which verifies the real state first.

Run (test):
    venv\\Scripts\\python.exe syslog_terima.py --dengar
Test parsing without network:
    venv\\Scripts\\python.exe syslog_terima.py --contoh
"""
import hashlib
import re
import socket
import sys
import threading
from datetime import datetime

PORT_BAWAAN = 1514
UKURAN_MAKS = 8192  # RFC 5426 recommends accepting at least 2048; generous

# RFC 3164 severity. Lower means more severe.
NAMA_SEVERITY = {
    0: "emergency", 1: "alert", 2: "critical", 3: "error",
    4: "warning", 5: "notice", 6: "info", 7: "debug",
}

# Messages with severity <= this become human-visible events. 5 (notice) keeps
# the most needed Cisco events: %LINK-3-UPDOWN, %OSPF-5-ADJCHG, and CONFIG_I.
AMBANG_PENTING = 5

# `<190>` at message start: PRI = facility*8 + severity.
_PRI = re.compile(r"^<(\d{1,3})>")

# Cisco tag: %FACILITY-SEVERITY-MNEMONIC
_TAG_CISCO = re.compile(r"(%[A-Z0-9_]+-\d-[A-Z0-9_]+)")

# Unix-style tag: "sshd[1234]:" or "kernel:"
_TAG_UNIX = re.compile(r"^([A-Za-z0-9_./-]{1,32})(?:\[\d+\])?:")

# RFC 3164 header after PRI: "MMM  D HH:MM:SS HOSTNAME ".
#
# Must be stripped before anything else; otherwise:
#   1. the hostname leaks into the template, so the same event on R1 and R2
#      gets different template fingerprints;
#   2. Unix-style tags (`sshd[2211]:`) never match, since `_TAG_UNIX` anchors
#      at the start of the string.
#
# The hostname is not stored: the sender chooses it and can spoof it. The
# socket address, already in `alamat`, is what is trusted.
_KEPALA_3164 = re.compile(
    r"^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+(\S+)\s+")

# RFC 5424 header: "1 2026-08-23T08:12:01Z HOSTNAME APP PROCID MSGID ".
_KEPALA_5424 = re.compile(
    r"^1\s+\S+T\S+\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(?:-\s+)?")

# Parts normalized when fingerprinting templates. Order matters: IPs must come
# before plain numbers, or an IP splits into four numbers and different
# messages can share a fingerprint.
_NORMALISASI = [
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<IP>"),
    (re.compile(r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b"), "<MAC>"),
    (re.compile(r"\b[A-Za-z]+(?:Ethernet|-?[Ee]th)\d+(?:/\d+)*\b"), "<IF>"),
    (re.compile(r"\b\d+\b"), "<N>"),
]


def buang_stempel_cisco(teks):
    """Strip the sequence number and timestamp that IOS inserts itself.

    Handled forms:

        123: *Aug 22 22:17:18.158 UTC: %CDP-4-...   clock not authoritative
         45: .Aug 23 01:27:28.791 UTC: %SYS-5-...   authoritative, NTP not synced
          9:  Aug 23 01:27:28.791 UTC: %SYS-5-...   authoritative and synced

    If left in, the same message from devices with different clock markers gets
    different template fingerprints, and Drain3 mining (which does not use the
    `<N>` normalization) produces duplicate patterns.

    A named function so `pola_log.py` applies exactly the same rules when mining
    stored messages; two copies of the rules would drift apart and show up as
    false "new patterns".
    """
    teks = re.sub(r"^\d+:\s*", "", teks)
    return re.sub(
        r"^[*.]?[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?"
        r"(?:\s+[A-Za-z]{2,5})?:\s*", "", teks)


def urai(data, alamat, sekarang=None):
    """Parse one syslog datagram into a dict. Pure function.

    Always returns a dict and never raises on odd input: one malformed message
    must not crash the receiver. Unparseable messages are stored as-is with
    `facility`/`severity` NULL, since they are often the most unusual ones.
    """
    if isinstance(data, bytes):
        teks = data.decode("utf-8", errors="replace")
    else:
        teks = str(data)
    teks = teks.strip("\x00").strip()

    hasil = {
        "waktu": sekarang or datetime.now(),
        "alamat": alamat,
        "facility": None,
        "severity": None,
        "tag": None,
        "pesan": teks,
    }

    m = _PRI.match(teks)
    if m:
        try:
            pri = int(m.group(1))
            if 0 <= pri <= 191:
                hasil["facility"] = pri // 8
                hasil["severity"] = pri % 8
        except ValueError:
            pass
        teks = teks[m.end():]

    # The sender's timestamp is deliberately not used as `waktu`. Lab device clocks
    # drift (NTP is one of the things NSM monitors), so the receiver's clock is used
    # as the single source.
    teks = teks.lstrip()

    # Strip the header (timestamp + hostname) so tag and template are clean.
    # See `_KEPALA_3164` for what breaks otherwise.
    mh = _KEPALA_5424.match(teks) or _KEPALA_3164.match(teks)
    if mh:
        teks = teks[mh.end():]

    # Cisco inserts its own sequence number and timestamp after the RFC 3164 header:
    #
    #     123: *Aug 22 22:17:18.158 UTC: %CDP-4-DUPLEX_MISMATCH: ...
    #
    # All of it is stripped, including fractional seconds and the time zone suffix;
    # otherwise the timestamp pollutes the template.
    teks = re.sub(r"^\d+:\s*", "", teks)
    teks = buang_stempel_cisco(teks)

    mc = _TAG_CISCO.search(teks)
    if mc:
        hasil["tag"] = mc.group(1)[:64]
    else:
        mu = _TAG_UNIX.match(teks)
        if mu:
            hasil["tag"] = mu.group(1)[:64]

    hasil["pesan"] = teks.strip() or "(kosong)"
    hasil["sidik_templat"] = sidik_templat(hasil["pesan"])
    return hasil


def templat(pesan):
    """Message shape with variable parts replaced by placeholders.

    "Interface FastEthernet1/1, changed state to down"
      -> "Interface <IF>, changed state to down"

    The same event on different interfaces yields the same template, which makes
    "this pattern has never been seen" answerable.
    """
    t = pesan or ""
    for pattern, replace in _NORMALISASI:
        t = pattern.sub(replace, t)
    return t


def sidik_templat(pesan):
    return hashlib.sha1(templat(pesan).encode("utf-8")).hexdigest()[:40]


def penting(hasil):
    """Whether this message should become a human-visible event."""
    s = hasil.get("severity")
    if s is None:
        # Unparsed -> treat as visible. Messages not shaped like normal syslog are the
        # most unusual ones.
        return True
    return s <= AMBANG_PENTING


class Penerima:
    """UDP socket + parse + store. Kept separate from `urai()` so parsing can be
    tested without a network.
    """

    def __init__(self, port=PORT_BAWAAN, simpan=None, alamat_ikat="0.0.0.0"):
        self.port = port
        self.alamat_ikat = alamat_ikat
        self.simpan = simpan or (lambda h: None)
        self._sock = None
        self._jalan = False
        self._utas = None
        self.diterima = 0
        self.gagal = 0

    def mulai(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.alamat_ikat, self.port))
        self._sock.settimeout(1.0)
        self._jalan = True
        self._utas = threading.Thread(target=self._putar, daemon=True,
                                      name="syslog")
        self._utas.start()
        return self

    def _putar(self):
        while self._jalan:
            try:
                data, origin = self._sock.recvfrom(UKURAN_MAKS)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                h = urai(data, origin[0])
                self.simpan(h)
                self.diterima += 1
            except Exception:
                # One malformed message must not crash the receiver. Failures are counted, not
                # printed: syslog can arrive thousands of times per minute and printing each
                # error would flood the log.
                self.gagal += 1

    def berhenti(self):
        self._jalan = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._utas:
            self._utas.join(timeout=3)


CONTOH = [
    b"<187>Aug 23 08:12:01 R1 %LINK-3-UPDOWN: Interface FastEthernet1/1, "
    b"changed state to down",
    b"<189>Aug 23 08:12:03 R1 %SYS-5-CONFIG_I: Configured from console by "
    b"vty0 (192.168.56.1)",
    b"<190>Aug 23 08:12:05 R2 %OSPF-5-ADJCHG: Process 1, Nbr 192.168.20.1 on "
    b"FastEthernet0/0 from FULL to DOWN, Neighbor Down: Interface down",
    b"<38>Aug 23 08:12:09 ldap sshd[2211]: Failed password for invalid user "
    b"admin from 192.168.56.9 port 51234 ssh2",
    b"pesan tanpa PRI dan tanpa bentuk syslog sama sekali",
]


def _contoh():
    print("=" * 74)
    print("URAI CONTOH PESAN SUNGGUHAN (tanpa jaringan, tanpa basis data)")
    print("=" * 74)
    for c in CONTOH:
        h = urai(c, "192.168.56.60")
        print("\n  %s" % c.decode()[:78])
        print("    facility=%s severity=%s (%s) penting=%s"
              % (h["facility"], h["severity"],
                 NAMA_SEVERITY.get(h["severity"], "?"), penting(h)))
        print("    tag     = %s" % h["tag"])
        print("    templat = %s" % templat(h["pesan"])[:76])
    return 0


def _dengar(port):
    print("mendengar syslog UDP di 0.0.0.0:%d  (Ctrl+C berhenti)" % port)
    p = Penerima(port=port, simpan=lambda h: print(
        "  [%s] %-14s %-22s %s" % (h["waktu"].strftime("%H:%M:%S"),
                                   h["alamat"], h["tag"] or "-",
                                   h["pesan"][:60]))).mulai()
    try:
        while True:
            p._utas.join(0.5)
    except KeyboardInterrupt:
        print("\nditerima %d, gagal %d" % (p.diterima, p.gagal))
    finally:
        p.berhenti()
    return 0


if __name__ == "__main__":
    if "--dengar" in sys.argv:
        sys.exit(_dengar(PORT_BAWAAN))
    sys.exit(_contoh())

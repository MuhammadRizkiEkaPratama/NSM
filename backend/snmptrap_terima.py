r"""SNMP trap receiver. Events that are PUSHED, not polled.

Syslog already captures most events, but SNMP traps still cover two cases: devices that
speak only SNMP (UPS, printers, some cheap switches) and events Cisco sends as traps
without logging them to syslog (depending on `snmp-server enable traps`).

Runs as its own thread, not a scheduled job: traps arrive at any time. pysnmp 7 is fully
asyncio while the poller uses a `BlockingScheduler` with no event loop, so this receiver
runs its OWN event loop in a separate thread; sharing the poller's main thread would
deadlock both.

Port 1162, not 162, same as syslog on 1514: ports below 1024 need privileges, and a process
reading raw unauthenticated network data is the last one that should run as root.

Cisco devices are pointed at it with:

    snmp-server host <ip-nsm> version 2c <community> udp-port 1162
    snmp-server enable traps

Trust level is the same as syslog: SNMPv2c is unauthenticated (the community string is sent
in clear), so a trap is EVIDENCE and a trigger for checks, never a trigger for direct action
on a device.

Traps go into the same `syslog_pesan` table with a `tag` prefixed `TRAP:`, because both
answer "what did the device report" and two tables would make every page, correlation and
pattern-mining step do its work twice.

Run manually (test):
    venv\Scripts\python.exe snmptrap_terima.py --dengar
"""
import asyncio
import sys
import threading
from datetime import datetime

PORT_BAWAAN = 1162

# Traps default to severity 4 (warning). Not 3: routine traps like `linkUp` are far more common
# than problems and would flood the page.
SEVERITY_BAWAAN = 4

# OIDs with a clear meaning mapped to readable names. Deliberately short; unknown OIDs are stored as-is.
ARTI_OID = {
    "1.3.6.1.6.3.1.1.5.1": "coldStart",
    "1.3.6.1.6.3.1.1.5.2": "warmStart",
    "1.3.6.1.6.3.1.1.5.3": "linkDown",
    "1.3.6.1.6.3.1.1.5.4": "linkUp",
    "1.3.6.1.6.3.1.1.5.5": "authenticationFailure",
}

TRAP_GAWAT = {"linkDown", "coldStart", "authenticationFailure"}


def _severity(nama):
    """linkDown is more serious than linkUp, so "recovered" is not treated like "broken"."""
    if nama in TRAP_GAWAT:
        return 3
    return SEVERITY_BAWAAN


def bentuk_pesan(oid_trap, varbinds):
    """Turn a trap into one readable line of text.

    Shaped like a syslog line so template mining treats both the same way.
    """
    nama = ARTI_OID.get(str(oid_trap), str(oid_trap))
    section = []
    for o, v in varbinds or []:
        so = str(o)
        if so.startswith("1.3.6.1.6.3.1.1.4."):   # snmpTrapOID/UpTime
            continue
        section.append("%s=%s" % (so, v))
    tail = (" " + " ".join(section)) if section else ""
    return "TRAP:%s%s" % (nama, tail), nama


class PenerimaTrap:
    """pysnmp trap socket in a thread with its own event loop."""

    def __init__(self, port=PORT_BAWAAN, simpan=None, alamat_ikat="0.0.0.0",
                 community="public"):
        self.port = port
        self.alamat_ikat = alamat_ikat
        self.community = community
        self.simpan = simpan or (lambda h: None)
        self.diterima = 0
        self.gagal = 0
        self._loop = None
        self._utas = None
        self._mesin = None

    # The signature MUST match what pysnmp 7 calls: (snmpEngine, stateReference, contextEngineId,
    # contextName, varBinds, cbCtx). Missing `state_ref` makes every trap fail inside pysnmp,
    # so even the `self.gagal` counter stays at zero.
    def _pada_trap(self, mesin, state_ref, konteks_id, konteks_nama,
                   varbinds, cbctx):
        try:
            oid_trap = None
            for o, v in varbinds:
                if str(o).startswith("1.3.6.1.6.3.1.1.4.1"):
                    oid_trap = v
                    break
            pesan, nama = bentuk_pesan(oid_trap, varbinds)

            # The sender address comes from the pysnmp execution context.
            #
            # pysnmp 7 renamed the method to snake_case (`get_execution_context`, not the
            # `getExecutionContext` seen in older pysnmp 4/5 examples). With the old name, the broad
            # `except` swallowed the AttributeError and every trap was stored with address "?".
            alamat = "?"
            try:
                info = mesin.observer.get_execution_context(
                    "rfc3412.receiveMessage:request")
                alamat = str(info["transportAddress"][0])
            except Exception:
                pass

            from syslog_terima import sidik_templat
            self.simpan({
                "waktu": datetime.now(),
                "alamat": alamat,
                "facility": None,
                "severity": _severity(nama),
                "tag": ("TRAP:" + nama)[:64],
                "pesan": pesan,
                "sidik_templat": sidik_templat(pesan),
            })
            self.diterima += 1
        except Exception:
            # One malformed trap must not take the receiver down; it is counted, not printed (same as syslog).
            self.gagal += 1

    def _putar(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            from pysnmp.carrier.asyncio.dgram import udp
            from pysnmp.entity import config as snmp_cfg, engine
            from pysnmp.entity.rfc3413 import ntfrcv

            self._mesin = engine.SnmpEngine()
            snmp_cfg.add_transport(
                self._mesin, udp.DOMAIN_NAME,
                udp.UdpTransport().open_server_mode(
                    (self.alamat_ikat, self.port)))
            snmp_cfg.add_v1_system(self._mesin, "nsm-area", self.community)
            ntfrcv.NotificationReceiver(self._mesin, self._pada_trap)
            self._mesin.transport_dispatcher.job_started(1)
            self._mesin.transport_dispatcher.run_dispatcher()
        except Exception as e:
            print("[snmptrap] penerima berhenti: %s" % str(e)[:160])

    def mulai(self):
        self._utas = threading.Thread(target=self._putar, daemon=True,
                                      name="snmptrap")
        self._utas.start()
        return self

    def berhenti(self):
        try:
            if self._mesin is not None:
                self._mesin.transport_dispatcher.job_finished(1)
                self._mesin.transport_dispatcher.close_dispatcher()
        except Exception:
            pass


def _dengar(port):
    print("mendengar SNMP trap UDP di 0.0.0.0:%d  (Ctrl+C berhenti)" % port)
    p = PenerimaTrap(port=port, simpan=lambda h: print(
        "  [%s] %-14s %-22s %s" % (h["waktu"].strftime("%H:%M:%S"),
                                   h["alamat"], h["tag"], h["pesan"][:60]))
    ).mulai()
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
    print("Bentuk pesan trap (tanpa jaringan):")
    for oid, vb in (("1.3.6.1.6.3.1.1.5.3", [("1.3.6.1.2.1.2.2.1.1", "2")]),
                    ("1.3.6.1.6.3.1.1.5.4", []),
                    ("1.3.6.1.4.1.9.9.999", [])):
        pesan, nama = bentuk_pesan(oid, vb)
        print("  %-24s severity=%d  %s" % (nama, _severity(nama), pesan))
    sys.exit(0)

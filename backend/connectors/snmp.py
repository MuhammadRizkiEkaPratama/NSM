"""SNMP v3 connector: the standard way to read network device statistics.

Why SNMP alongside SSH: an SSH read needs a TCP connection, key exchange,
login and a command (1-2 s plus device CPU). SNMP is one UDP request and one
reply with no per-request login, which is why Zabbix, LibreNMS, PRTG and
Cacti use it for periodic data.

Why v3, not v2c: v2c relies on a community string sent in plaintext. v3
offers noAuthNoPriv, authNoPriv and authPriv (authentication + encryption);
NSM uses authPriv.

Version note: pysnmp 7.x only provides an asyncio API; the synchronous
`getCmd()` from pysnmp 4.x used by most online examples no longer exists.
The NSM poller is synchronous, so each call is wrapped in `asyncio.run()`
inside this class.
"""
import asyncio
import time

from connectors.base import BaseConnector

# --- OIDs (data addresses on the device) ---
# Standard OIDs, identical on Cisco, Linux, MikroTik, etc.
OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"  # system description
OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"  # uptime
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"  # hostname

# Device type as reported by the device itself.
#
# Unlike the OIDs above, which ask about the state of a known device, this
# asks for its identity; the answer points into the vendor's OID branch:
#
#     .1.3.6.1.4.1.9.1.222      -> Cisco
#     .1.3.6.1.4.1.14988.1      -> MikroTik
#
# Used by `penemuan.py` to match newly discovered devices to definition files
# in `backend/perangkat/`, as LibreNMS does: a typed name can be wrong, this
# value comes from the device.
OID_SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"

OID_IF_DESCR = "1.3.6.1.2.1.2.2.1.2"  # interface name (e.g. eth0)
OID_IF_OPER = "1.3.6.1.2.1.2.2.1.8"  # status: 1=up, 2=down
OID_IF_IN_32 = "1.3.6.1.2.1.2.2.1.10"  # bytes in  (32-bit counter)
OID_IF_OUT_32 = "1.3.6.1.2.1.2.2.1.16"  # bytes out (32-bit counter)
OID_IF_IN_64 = "1.3.6.1.2.1.31.1.1.1.6"  # bytes in  (64-bit counter)
OID_IF_OUT_64 = "1.3.6.1.2.1.31.1.1.1.10"  # bytes out (64-bit counter)

# 64-bit counters are preferred: a 32-bit counter wraps at ~4.29 billion
# bytes, about 34 s on a 1 Gbps link, so it can wrap twice between 30 s polls
# without detection. Devices without 64-bit counters fall back to 32-bit.

STATUS_IF = {1: "up", 2: "down", 3: "testing", 4: "unknown",
             5: "dormant", 6: "notPresent", 7: "lowerLayerDown"}


def _protokol_auth(nama):
    from pysnmp.hlapi.v3arch.asyncio import (
        usmHMACSHAAuthProtocol, usmHMACMD5AuthProtocol,
        usmHMAC192SHA256AuthProtocol, usmNoAuthProtocol,
    )
    return {
        "SHA": usmHMACSHAAuthProtocol,
        "SHA256": usmHMAC192SHA256AuthProtocol,
        "MD5": usmHMACMD5AuthProtocol,  # legacy, avoid if possible
        "NONE": usmNoAuthProtocol,
    }.get((nama or "SHA").upper(), usmHMACSHAAuthProtocol)


def _protokol_priv(nama):
    from pysnmp.hlapi.v3arch.asyncio import (
        usmAesCfb128Protocol, usmDESPrivProtocol, usmNoPrivProtocol,
    )
    return {
        "AES": usmAesCfb128Protocol,
        "DES": usmDESPrivProtocol,  # legacy, avoid if possible
        "NONE": usmNoPrivProtocol,
    }.get((nama or "AES").upper(), usmAesCfb128Protocol)


class SnmpConnector(BaseConnector):
    def __init__(self, ip_address, user=None, auth_pass=None, priv_pass=None,
                 auth_proto="SHA", priv_proto="AES", port=161, timeout=2, retries=1):
        super().__init__(ip_address)
        self.user = user
        self.auth_pass = auth_pass
        self.priv_pass = priv_pass
        self.auth_proto = auth_proto
        self.priv_proto = priv_proto
        self.port = port
        self.timeout = timeout
        self.retries = retries

    # ------------------------------------------------------------------
    # Async section (internal use only)
    # ------------------------------------------------------------------
    def _identitas(self):
        from pysnmp.hlapi.v3arch.asyncio import UsmUserData
        if not self.user:
            raise ValueError("Kredensial SNMP belum diisi untuk device ini")
        return UsmUserData(
            self.user,
            authKey=self.auth_pass or None,
            privKey=self.priv_pass or None,
            authProtocol=_protokol_auth(self.auth_proto),
            privProtocol=_protokol_priv(self.priv_proto),
        )

    async def _get(self, mesin, oids):
        from pysnmp.hlapi.v3arch.asyncio import (
            get_cmd, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity,
        )
        destination = await UdpTransportTarget.create(
            (self.ip_address, self.port), timeout=self.timeout, retries=self.retries)
        error, error_status, _, hasil = await get_cmd(
            mesin, self._identitas(), destination, ContextData(),
            *[ObjectType(ObjectIdentity(o)) for o in oids],
        )
        if error:
            raise RuntimeError(str(error))
        if error_status:
            raise RuntimeError(f"SNMP menolak permintaan: {error_status.prettyPrint()}")
        return {str(nama): value for nama, value in hasil}

    async def _walk(self, mesin, oid_dasar):
        """Walk one OID subtree. Returns {index: value}.

        Used for interface tables: each interface has an index shared across
        several subtrees.
        """
        from pysnmp.hlapi.v3arch.asyncio import (
            walk_cmd, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity,
        )
        destination = await UdpTransportTarget.create(
            (self.ip_address, self.port), timeout=self.timeout, retries=self.retries)
        hasil = {}
        async for error, error_status, _, line in walk_cmd(
            mesin, self._identitas(), destination, ContextData(),
            ObjectType(ObjectIdentity(oid_dasar)),
            lexicographicMode=False,  # stop once outside the subtree
        ):
            if error:
                raise RuntimeError(str(error))
            if error_status:
                raise RuntimeError(f"SNMP menolak permintaan: {error_status.prettyPrint()}")
            for nama, value in line:
                teks = str(nama)
                if not teks.startswith(oid_dasar):
                    continue
                index = teks[len(oid_dasar):].lstrip(".")
                hasil[index] = value
        return hasil

    async def _walk_aman(self, mesin, oid_utama, oid_cadangan):
        """Walk the primary OID; fall back if it is empty OR rejected.

        Old devices lack the 64-bit counter table: some return nothing, others an
        error (e.g. genErr). Errors are treated as "unsupported" too, so those
        devices fall back to 32-bit counters instead of failing entirely.
        """
        try:
            hasil = await self._walk(mesin, oid_utama)
            if hasil:
                return hasil
        except Exception:
            pass
        return await self._walk(mesin, oid_cadangan)

    async def _bandwidth_async(self):
        from pysnmp.hlapi.v3arch.asyncio import SnmpEngine
        mesin = SnmpEngine()
        try:
            nama = await self._walk(mesin, OID_IF_DESCR)
            enter = await self._walk_aman(mesin, OID_IF_IN_64, OID_IF_IN_32)
            keluar = await self._walk_aman(mesin, OID_IF_OUT_64, OID_IF_OUT_32)

            hasil = {}
            for index, label in nama.items():
                name_iface = str(label)
                if name_iface in ("lo", "lo0", "Null0"):
                    continue  # loopback: traffic to itself
                if index not in enter and index not in keluar:
                    continue
                hasil[name_iface] = {
                    "in_octets": float(enter[index]) if index in enter else None,
                    "out_octets": float(keluar[index]) if index in keluar else None,
                }
            return hasil
        finally:
            mesin.close_dispatcher()

    async def _info_async(self):
        from pysnmp.hlapi.v3arch.asyncio import SnmpEngine
        mesin = SnmpEngine()
        try:
            base = await self._get(mesin, [OID_SYS_NAME, OID_SYS_DESCR, OID_SYS_UPTIME])
            nama = await self._walk(mesin, OID_IF_DESCR)
            status = await self._walk(mesin, OID_IF_OPER)

            line = []
            for index, label in sorted(nama.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
                code = int(status[index]) if index in status else None
                line.append(f"{str(label):<18} {STATUS_IF.get(code, '-')}")

            kutu = base.get(OID_SYS_UPTIME)
            uptime = "-"
            if kutu is not None:
                # sysUpTime is in hundredths of a second since boot
                second = int(kutu) // 100
                hari, remaining = divmod(second, 86400)
                jam, remaining = divmod(remaining, 3600)
                menit = remaining // 60
                uptime = f"{hari} hari {jam} jam {menit} menit"

            return {
                "Hostname (SNMP)": str(base.get(OID_SYS_NAME, "-")),
                "Keterangan Sistem": str(base.get(OID_SYS_DESCR, "-")),
                "Uptime": uptime,
                "Interface": "\n".join(line) if line else "(tidak ada)",
            }
        finally:
            mesin.close_dispatcher()

    async def _cek_async(self):
        from pysnmp.hlapi.v3arch.asyncio import SnmpEngine
        mesin = SnmpEngine()
        try:
            await self._get(mesin, [OID_SYS_UPTIME])
        finally:
            mesin.close_dispatcher()

    # ------------------------------------------------------------------
    # Sync section (used by the poller and main.py)
    # ------------------------------------------------------------------
    def check_reachable(self):
        """Up/down according to SNMP.

        Unlike ping, this proves the SNMP service answers and the credentials are
        valid. NSM's official up/down status still comes from ICMP; this is used to
        test the SNMP connection.
        """
        start = time.time()
        try:
            asyncio.run(self._cek_async())
            return True, round((time.time() - start) * 1000, 2)
        except Exception:
            return False, None

    def get_bandwidth(self):
        return asyncio.run(self._bandwidth_async())

    def get_info(self):
        return asyncio.run(self._info_async())

    def ambil_oid(self, oids):
        """Fetch several OIDs at once. Returns {oid: text_value}.

        Raw values only, no parsing. `get_info()` returns display-ready device
        state; `penemuan.py` needs single raw values for matching, from devices
        that may not answer.

        Unanswered OIDs are omitted from the result, which is distinct from an
        answered empty value.
        """
        return asyncio.run(self._oid_async(oids))

    async def _oid_async(self, oids):
        from pysnmp.hlapi.v3arch.asyncio import SnmpEngine
        mesin = SnmpEngine()
        try:
            hasil = await self._get(mesin, list(oids))
        finally:
            mesin.close_dispatcher()
        return {k: str(v) for k, v in (hasil or {}).items() if v is not None}

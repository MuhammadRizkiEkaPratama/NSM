"""Block/unblock an IP in the router ACL (see docs/design/AUTO-BAN.md).

Separate from `kirim_perintah.py` on purpose: that file uses `reload in N` as a
safety net, which suits rare, supervised config changes but not frequent
temporary blocks. `reload in` cannot stack (a second candidate resets the
first timer) and, if it fires, reboots the whole router and cuts off Location B.

A temporary block here is an EEM applet (`event timer countdown`) installed on
the router itself: it counts down, removes ONE specific ACL line, then deletes
itself, so the block stays temporary even if NSM is down. Verified on IOS
12.4(13b) ENTSERVICESK9.

Two layers of protection: this file checks permission, picks a safe sequence
number and refuses forbidden targets; `penjaga_aksi.py` applies a broader
allowlist again at execution time.

Sequence numbers 1-9 sit below the first real rule (10), so they are free unless
NSM used them. A free one is chosen automatically, re-read from the device on
every call. The block goes above `permit tcp any any established` so packets
with a forged ACK flag cannot slip past the ACL.

Default is `sungguhan=False`: return the plan without touching the device.
"""
import re
from datetime import datetime

import config
import dialek_perangkat
import identitas
from models import Device, FirewallPerubahan, KonfigSnapshot

MENIT_MIN = 1
MENIT_MAKS = 1440

# Loaded from `.env` (`ALAMAT_DILINDUNGI` + `ALAMAT_NSM`). This module still
# performs its own check before touching the router; only the source of the
# values is shared, not the check.
DILARANG = config.get_alamat_dilindungi()

# Routers that have an ACL block path, and their ACL details. Loaded from `.env`
# (`ROUTER_ACL`, JSON). Closed and empty by default: adding a router is an explicit
# decision, and empty means ACL blocking is never offered.
#
# `interface` is used only for a sanity check (the ACL is attached there in the
# latest snapshot); this file never changes interface-to-ACL bindings.
#
# `lokasi` must match the protected devices' `Device.location` exactly; it is used
# by `report_service.rencana_penjagaan()` via `LOKASI_ACL_ROUTER`.
ROUTER_ACL = config.get_router_acl()

# Sequence gap reserved for NSM, always below any real rule (re-verified on every call).
SEQ_MIN, SEQ_MAKS = 1, 9

_POLA_BARIS_ACL = re.compile(r"^\s*(\d+)\s+(.+?)(?:\s+\(\d+ matches?\))?\s*$")


class Ditolak(Exception):
    """Request rejected before anything is sent to the device."""


def _sah_ipv4(ip):
    from ubah_firewall import sah_ipv4
    return sah_ipv4(ip)


def _nama_applet(ip):
    """`192.168.56.151` -> `NSM-ACL-192-168-56-151` (a valid EEM applet name)."""
    return "NSM-ACL-" + ip.replace(".", "-")


def periksa_izin(db, device_id, ip=None, menit=None, _periksa_ip=False,
                 _periksa_menit=False):
    """May NSM insert/delete ACL lines on this router?

    Two separate flags (`_periksa_ip`/`_periksa_menit`) instead of `TIDAK_DIBERI`
    because the only callers are `blokir()`/`buka()` in this file.
    """
    d = db.query(Device).filter(Device.id == device_id).first()
    if d is None:
        raise Ditolak("Perangkat %r tidak ada." % device_id)

    # Based on `kemampuan.firewall: acl` in the definition file, not a vendor name.
    # Not the only gate: `ROUTER_ACL` below must also list the device, since "technically
    # possible" and "known safe" are separate conditions.
    if dialek_perangkat.ambil(d.platform).firewall != "acl":
        can = dialek_perangkat.platform_dengan("firewall", "acl")
        raise Ditolak(
            "Perangkat %s berplatform %r. Blokir ACL baru ada untuk perangkat "
            "yang memblokir lewat ACL router (%s)."
            % (d.name, d.platform, ", ".join(can)))

    if device_id not in ROUTER_ACL:
        raise Ditolak(
            "%s belum terdaftar di ROUTER_ACL — belum ada ACL yang "
            "diketahui aman disisipi NSM di perangkat ini." % d.name)

    if d.aktif == 0:
        raise Ditolak(
            "Perangkat %s sedang DIJEDA%s. Perangkat yang dijeda tidak "
            "dipantau, jadi mengubah ACL-nya berarti mengubah sesuatu yang "
            "tidak sedang diawasi siapa pun."
            % (d.name, " (%s)" % d.jeda_alasan if d.jeda_alasan else ""))

    if not (d.username and (d.password or d.ssh_key_path)):
        raise Ditolak("Perangkat %s tidak punya kredensial SSH di NSM." % d.name)

    cfg = ROUTER_ACL[device_id]

    # Is the ACL still attached to the expected interface? Checked against the latest
    # snapshot, because the router config can change behind our back.
    snap = (db.query(KonfigSnapshot)
            .filter(KonfigSnapshot.device_id == device_id)
            .order_by(KonfigSnapshot.id.desc())
            .first())
    if snap is None:
        raise Ditolak(
            "NSM belum pernah berhasil membaca konfigurasi %s, jadi ia "
            "tidak tahu keadaan ACL yang sedang diubahnya." % d.name)
    teks = snap.teks or ""
    if ("ip access-list extended %s" % cfg["acl"]) not in teks:
        raise Ditolak(
            "ACL %r tidak ditemukan di potret konfigurasi terakhir %s. "
            "Konfigurasi router mungkin sudah berubah — periksa ulang "
            "sebelum melanjutkan." % (cfg["acl"], d.name))
    if ("ip access-group %s in" % cfg["acl"]) not in teks:
        raise Ditolak(
            "ACL %r tidak (lagi) terpasang di interface %s milik %s." %
            (cfg["acl"], cfg["interface"], d.name))

    if _periksa_ip:
        if not isinstance(ip, str) or not _sah_ipv4(ip):
            raise Ditolak("%r bukan alamat IPv4 yang sah." % ip)
        if ip in DILARANG:
            raise Ditolak(
                "%s ada di daftar yang tidak boleh diblokir. Memblokirnya "
                "memutus pemantauan NSM atau hubungan antar lokasi, dan "
                "akibatnya baru terlihat setelah ada yang mengeluh." % ip)
        if ip == d.ip_address:
            raise Ditolak(
                "%s adalah alamat perangkat itu sendiri." % ip)

    if _periksa_menit:
        if (isinstance(menit, bool) or not isinstance(menit, int)
                or menit < MENIT_MIN or menit > MENIT_MAKS):
            raise Ditolak(
                "Lama blokir harus %d-%d menit, dapat %r." %
                (MENIT_MIN, MENIT_MAKS, menit))

    allowed, verdict, why = identitas.boleh_ditulisi(db, device_id)
    if not allowed:
        raise Ditolak("Identitas %s belum memenuhi syarat (vonis: %s). %s" %
                      (d.name, verdict, why))

    return d, cfg


def _sambung(d):
    from netmiko import ConnectHandler
    return ConnectHandler(device_type=d.platform, host=d.ip_address,
                          username=d.username, password=d.password,
                          timeout=20)


def _baca_acl(conn, acl_nama):
    """`show access-list <name>` -> sorted [(seq:int, line:str), ...].

    Re-read on every call; sequence numbers can change if someone edits the ACL outside NSM.
    """
    keluar = conn.send_command("show access-list %s" % acl_nama)
    hasil = []
    for line in keluar.splitlines():
        m = _POLA_BARIS_ACL.match(line)
        if m:
            hasil.append((int(m.group(1)), m.group(2).strip()))
    return sorted(hasil)


def _pilih_seq_aman(acl_terbaca):
    """Pick a sequence number in SEQ_MIN..SEQ_MAKS not used in the live ACL. Raises Ditolak if the gap is full."""
    used = {seq for seq, _ in acl_terbaca}
    for candidate in range(SEQ_MIN, SEQ_MAKS + 1):
        if candidate not in used:
            return candidate
    raise Ditolak(
        "Celah sequence number %d-%d untuk blokir ACL sudah penuh (%d ban "
        "aktif sekaligus). Tunggu salah satu kedaluwarsa dulu." %
        (SEQ_MIN, SEQ_MAKS, SEQ_MAKS - SEQ_MIN + 1))


def _catat(db, device_id, aksi, ip, menit, alasan, oleh, hasil, bukti):
    """Same pattern as `ubah_firewall._catat`: one shared audit table (`FirewallPerubahan`)."""
    try:
        db.add(FirewallPerubahan(
            device_id=device_id, waktu=datetime.now(), aksi=aksi,
            ip_sasaran=str(ip) if ip else None,
            menit=menit if isinstance(menit, int) and not isinstance(menit, bool)
            else None,
            alasan=(str(alasan)[:400] if alasan else None),
            oleh=str(oleh or "?"), hasil=hasil,
            bukti=(str(bukti)[:4000] if bukti else None)))
        db.commit()
    except Exception:
        db.rollback()


def _terjangkau_router(d):
    """Does a NEW SSH session to the router still work? An old session survives a bad ACL, so it must be new."""
    try:
        c = _sambung(d)
        try:
            out = c.send_command("show clock")
            return bool(out.strip())
        finally:
            c.disconnect()
    except Exception:
        return False


def _terjangkau_lokasi_b(cfg):
    """Can NSM still reach the real service at Location B?

    Proves the new block did not cut legitimate traffic. Uses TCP, not ping: other
    ACL rules permit ICMP, so ping would always succeed.
    """
    import socket
    try:
        with socket.create_connection(
                (cfg["contoh_host_lokasi"], cfg["port_uji"]), timeout=6):
            return True
    except OSError:
        return False


def blokir(db, device_id, ip, menit, alasan, oleh, sungguhan=False):
    """Insert `deny ip host {ip} any log` in the router ACL, with an EEM applet that
    removes it after `menit` minutes.

    Order matters:
        1. check permission
        2. read the real ACL, pick a seq
        3. insert ACL line + EEM applet (one send_config_set)
        4. verify the router is reachable (new session)
        5. verify Location B is reachable (TCP, from NSM)
        6. if either fails, roll back immediately (remove line + applet)

    If rollback also fails, the EEM applet from step 3 is the last safety net: the
    router lifts the block itself after `menit` minutes.
    """
    d, cfg = periksa_izin(db, device_id, ip=ip, menit=menit,
                          _periksa_ip=True, _periksa_menit=True)

    plan = {
        "device": d.name, "device_id": d.id, "ip_sasaran": ip, "menit": menit,
        "alasan": alasan, "oleh": oleh, "acl": cfg["acl"],
        "sungguhan": False, "hasil": "RENCANA", "bukti": None,
        "waktu": datetime.now(),
    }
    if not sungguhan:
        plan["catatan"] = (
            "Belum dikirim. Perangkat tidak disentuh sama sekali. "
            "Panggil lagi dengan sungguhan=True untuk benar-benar mengirim.")
        return plan

    if not alasan or not str(alasan).strip():
        message = "Alasan wajib diisi untuk perubahan sungguhan."
        _catat(db, device_id, "ACL_BLOKIR", ip, menit, alasan, oleh,
               "DITOLAK_NSM", message)
        raise Ditolak(message)

    second = menit * 60
    nama_applet = _nama_applet(ip)

    c = _sambung(d)
    try:
        acl_before = _baca_acl(c, cfg["acl"])
        seq = _pilih_seq_aman(acl_before)

        line_config = [
            "ip access-list extended %s" % cfg["acl"],
            " %d deny ip host %s any log" % (seq, ip),
            "event manager applet %s" % nama_applet,
            " event timer countdown time %d" % second,
            ' action 1.0 cli command "enable"',
            ' action 2.0 cli command "configure terminal"',
            ' action 3.0 cli command "ip access-list extended %s"' % cfg["acl"],
            ' action 4.0 cli command "no %d"' % seq,
            # "exit" (not "end") leaves only the ACL submode, staying in config mode.
            # global config mode. DITEMUKAN 18 Agustus 2026 lewat uji live
            # With "end" the next action would run in EXEC mode, where "no event manager applet"
            # (a config-mode command) fails silently and the applet would not delete itself.
            ' action 5.0 cli command "exit"',
            ' action 6.0 cli command "no event manager applet %s"' % nama_applet,
            ' action 7.0 cli command "end"',
        ]
        text_send = c.send_config_set(line_config)
    finally:
        c.disconnect()

    plan["sungguhan"] = True
    plan["bukti"] = text_send
    plan["seq"] = seq

    router_ok = _terjangkau_router(d)
    location_b_ok = _terjangkau_lokasi_b(cfg) if router_ok else False

    if not (router_ok and location_b_ok):
        cause = ("router tidak menjawab sesi SSH baru" if not router_ok
                else "Lokasi B (%s:%d) tidak lagi terjangkau dari NSM" %
                     (cfg["contoh_host_lokasi"], cfg["port_uji"]))
        # Roll back immediately. The EEM applet remains as the last safety net.
        cancelled = False
        try:
            c2 = _sambung(d)
            try:
                c2.send_config_set([
                    "ip access-list extended %s" % cfg["acl"],
                    " no %d" % seq,
                    "no event manager applet %s" % nama_applet,
                ])
                cancelled = True
            finally:
                c2.disconnect()
        except Exception:
            pass

        if cancelled:
            plan["hasil"] = "DIBATALKAN"
            plan["catatan"] = (
                "Setelah baris ACL dipasang, %s. Baris BERHASIL dibatalkan."
                % cause)
            _catat(db, device_id, "ACL_BLOKIR", ip, menit, alasan, oleh,
                   "DIBATALKAN", text_send + "\n\n" + plan["catatan"])
        else:
            # If this rollback also fails, the ACL line and applet are still on the router.
            # Recording "cancelled" would be a lie (`ban_aktif` empty while the router blocks),
            # so record success: `send_config_set` already succeeded, the applet is installed
            # and will lift the block on its own.
            plan["hasil"] = "BERHASIL_TANPA_BUKTI"
            plan["catatan"] = (
                "Baris ACL TERPASANG di router, tapi %s, dan pembatalan "
                "otomatis juga gagal (kemungkinan sebab yang sama). Applet "
                "EEM '%s' sudah terpasang SEBELUM kegagalan ini terjadi, "
                "jadi baris ACL akan tetap terhapus sendiri dalam %d menit "
                "walau tidak ada yang campur tangan." %
                (cause, nama_applet, menit))
            _catat(db, device_id, "ACL_BLOKIR", ip, menit, alasan, oleh,
                   "BERHASIL_TANPA_BUKTI",
                   text_send + "\n\n" + plan["catatan"])
        return plan

    plan["hasil"] = "BERHASIL"
    plan["catatan"] = (
        "Baris ACL 'deny ip host %s any log' terpasang di sequence %d ACL "
        "%s (router %s), DI ATAS 'permit tcp any any established' — "
        "menutup celah spoofing-ACK yang tidak tertutup blokir di device "
        "tujuan. Applet EEM '%s' akan menghapusnya sendiri dalam %d menit, "
        "tidak bergantung NSM tetap hidup." %
        (ip, seq, cfg["acl"], d.name, nama_applet, menit))
    _catat(db, device_id, "ACL_BLOKIR", ip, menit, alasan, oleh, "BERHASIL",
          text_send)
    return plan


def buka(db, device_id, ip, oleh, sungguhan=False):
    """Lift an ACL block before its EEM applet fires.

    The line to delete is found by matching text in the live ACL, not by a remembered
    sequence number. If it is already gone (e.g. the applet fired first), that is not a failure.
    """
    d, cfg = periksa_izin(db, device_id)

    hasil = {"device": d.name, "device_id": d.id, "ip_sasaran": ip,
             "oleh": oleh, "acl": cfg["acl"], "sungguhan": False,
             "hasil": "RENCANA", "bukti": None, "waktu": datetime.now()}
    if not sungguhan:
        hasil["catatan"] = "Belum dikirim. Perangkat tidak disentuh."
        return hasil

    nama_applet = _nama_applet(ip)
    target_text = "deny ip host %s any log" % ip

    c = _sambung(d)
    try:
        acl_now = _baca_acl(c, cfg["acl"])
        seq_cocok = [seq for seq, teks in acl_now if teks == target_text]

        perintah = ["ip access-list extended %s" % cfg["acl"]]
        for seq in seq_cocok:
            perintah.append(" no %d" % seq)
        # Also remove the applet if present, unconditionally: `no event manager applet`
        # on a missing name fails silently in IOS.
        perintah.append("no event manager applet %s" % nama_applet)

        text_send = c.send_config_set(perintah)
    finally:
        c.disconnect()

    hasil["sungguhan"] = True
    hasil["bukti"] = text_send
    hasil["hasil"] = "BERHASIL"
    hasil["baris_dihapus"] = len(seq_cocok)
    _catat(db, device_id, "ACL_BUKA", ip, None, None, oleh, "BERHASIL",
          text_send)
    return hasil

"""The only file in NSM allowed to change firewall rules. Twin of `kirim_perintah.py`.

Three layers of protection, none to be relied on alone:
    1. this file                checks permission, refuses forbidden targets
    2. `nsm-ubah-firewall`      on the server, with its own policy
    3. sudo rule                allows only file 2

Layer 1 can be bypassed by new Python code; layer 2 cannot, so the forbidden
address list lives in both places.

Every block has a time limit by design: a permanent automatic block eventually
blocks something important and nobody dares remove it. Self-expiring blocks force
permanent decisions to be made by a human.

Default is `sungguhan=False`: return the plan without touching the device.
"""
import re
from datetime import datetime

import config
import dialek_perangkat
from models import Device, FirewallPerubahan, FirewallSnapshot


class Ditolak(Exception):
    """Request rejected before anything is sent to the device."""


# Addresses that must not be blocked. Loaded from `.env` (`ALAMAT_DILINDUNGI` +
# `ALAMAT_NSM`).
#
# `firewall/nsm-ubah-firewall` on each server keeps its own list on purpose: it runs
# in another process on another machine and must survive losing this file.
DILARANG = config.get_alamat_dilindungi()

MENIT_MIN = 1
MENIT_MAKS = 1440

POLA_IP = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")

JALUR = "/usr/local/sbin/nsm-ubah-firewall"

# Marker for "parameter not provided".
#
# Not `None`: `None` is a value the caller sent, and it is invalid. Using
# `if ip is not None:` to skip validation let `blokir(ip=None)` pass every check
# and open an SSH connection before failing.
TIDAK_DIBERI = object()


def sah_ipv4(ip):
    m = POLA_IP.match((ip or "").strip())
    if not m:
        return False
    return all(0 <= int(b) <= 255 for b in m.groups())


def periksa_izin(db, device_id, ip=TIDAK_DIBERI, menit=TIDAK_DIBERI):
    """May NSM change this device's firewall? Raises Ditolak.

    Checked BEFORE the connection opens so a refusal never leaves a half-done session.
    """
    d = db.query(Device).filter(Device.id == device_id).first()
    if d is None:
        raise Ditolak("Perangkat %r tidak ada." % device_id)

    # A capability, not a vendor: `kemampuan.firewall: ufw` in `perangkat/linux.yaml`.
    # Other ufw devices only need one line in their definition file.
    if dialek_perangkat.ambil(d.platform).firewall != "ufw":
        # The message names the applicable platforms, derived from the definition files
        # rather than typed, so it cannot go stale.
        can = dialek_perangkat.platform_dengan("firewall", "ufw")
        raise Ditolak(
            "Perangkat %s berplatform %r. Pengubahan firewall lewat NSM baru "
            "ada untuk perangkat yang memblokir dengan ufw (%s)."
            % (d.name, d.platform, ", ".join(can)))

    # `== 0`, not `is False`: the column is an SQLite INTEGER and `0 is False` is False in Python.
    if d.aktif == 0:
        raise Ditolak(
            "Perangkat %s sedang DIJEDA%s. Perangkat yang dijeda tidak "
            "dipantau, jadi mengubah firewallnya berarti mengubah sesuatu "
            "yang tidak sedang diawasi siapa pun."
            % (d.name, " (%s)" % d.jeda_alasan if d.jeda_alasan else ""))

    if not (d.username and (d.password or d.ssh_key_path)):
        raise Ditolak(
            "Perangkat %s tidak punya kredensial SSH di NSM." % d.name)

    # A disabled firewall blocks nothing; writing the rule would "succeed" with no effect
    # while the page reports the address as blocked.
    snap = (db.query(FirewallSnapshot)
            .filter(FirewallSnapshot.device_id == device_id)
            .order_by(FirewallSnapshot.id.desc())
            .first())
    if snap is None:
        raise Ditolak(
            "NSM belum pernah berhasil membaca firewall %s, jadi ia tidak "
            "tahu keadaan yang sedang diubahnya." % d.name)
    if not snap.aktif:
        raise Ditolak(
            "Firewall di %s sedang MATI. Aturan yang ditulis ke firewall mati "
            "tidak menolak apa pun, tetapi akan terlihat seperti berhasil."
            % d.name)

    if ip is not TIDAK_DIBERI:
        if not isinstance(ip, str) or not sah_ipv4(ip):
            raise Ditolak("%r bukan alamat IPv4 yang sah." % ip)
        if ip in DILARANG:
            raise Ditolak(
                "%s ada di daftar yang tidak boleh diblokir. Memblokirnya "
                "memutus pemantauan NSM atau hubungan antar server, dan "
                "akibatnya baru terlihat setelah ada yang mengeluh." % ip)
        if ip == d.ip_address:
            raise Ditolak(
                "%s adalah alamat perangkat itu sendiri. Memblokirnya di "
                "dirinya sendiri tidak melakukan apa pun yang diinginkan "
                "siapa pun." % ip)

    if menit is not TIDAK_DIBERI:
        # `isinstance(True, int)` is True in Python, so bool is rejected separately:
        # `blokir(..., menit=True)` would otherwise read as 1 minute.
        if (isinstance(menit, bool) or not isinstance(menit, int)
                or menit < MENIT_MIN or menit > MENIT_MAKS):
            raise Ditolak(
                "Lama blokir harus %d-%d menit, dapat %r. Blokir tanpa batas "
                "yang dipasang mesin akan tetap ada lama setelah alasannya "
                "terlupakan." % (MENIT_MIN, MENIT_MAKS, menit))

    return d


def _catat(db, device_id, aksi, ip, menit, alasan, oleh, hasil, bukti):
    """Write one history row. A logging failure must not break the action.

    If logging fails after the block is already on the device, raising would make the
    caller think the block did not happen.
    """
    try:
        db.add(FirewallPerubahan(
            device_id=device_id, waktu=datetime.now(), aksi=aksi,
            ip_sasaran=str(ip) if ip is not TIDAK_DIBERI else None,
            menit=menit if isinstance(menit, int) and not isinstance(menit, bool)
            else None,
            alasan=(str(alasan)[:400] if alasan else None),
            oleh=str(oleh or "?"), hasil=hasil,
            bukti=(str(bukti)[:4000] if bukti else None)))
        db.commit()
    except Exception:
        db.rollback()


def _sambung(d):
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    opsi = {"timeout": 20, "allow_agent": False, "look_for_keys": False}
    if d.ssh_key_path:
        c.connect(d.ip_address, username=d.username,
                  key_filename=d.ssh_key_path, **opsi)
    else:
        c.connect(d.ip_address, username=d.username, password=d.password,
                  **opsi)
    return c


def _jalankan(c, argumen, timeout=30):
    perintah = "sudo -n %s %s" % (JALUR, " ".join(str(a) for a in argumen))
    _in, out, err = c.exec_command(perintah, timeout=timeout)
    keluar = out.channel.recv_exit_status()
    teks = out.read().decode("utf-8", "replace")
    error = err.read().decode("utf-8", "replace")
    return keluar, (teks + error).strip()


def _masih_terjangkau(d):
    """Does the device still serve NSM after the rule change?

    Not a ping check: a bad rule can pass ICMP while cutting SSH. Only opening a
    NEW session and running a command proves it; an existing TCP connection stays
    alive even if new rules forbid new connections.
    """
    try:
        c = _sambung(d)
        try:
            _i, o, _e = c.exec_command("hostname", timeout=15)
            return bool(o.read().decode().strip())
        finally:
            c.close()
    except Exception:
        return False


def blokir(db, device_id, ip, menit, alasan, oleh, sungguhan=False):
    """Block an address on the device for a limited time.

    Returns a dict with the plan or result. `sungguhan=False` (default) does not
    touch the device.

    Order matters:
        1. check permission              (no connection yet)
        2. send the block command        (the server installs its own unblock timer)
        3. verify still reachable        (new SSH session)
        4. on failure, unblock at once

    Step 4 exists because the server timer only fires after `menit` minutes, too long
    to wait when we already know something is wrong.
    """
    try:
        d = periksa_izin(db, device_id, ip=ip, menit=menit)
    except Ditolak as e:
        # Refusals are logged, but only for real requests.
        #
        # Someone trying to block NSM's own address is worth knowing about. Plans
        # (`sungguhan=False`) are not logged because the page calls them on every form fill,
        # which would bury the real entries.
        if sungguhan:
            _catat(db, device_id, "BLOKIR", ip, menit, alasan, oleh,
                   "DITOLAK_NSM", str(e))
        raise

    plan = {
        "device": d.name,
        "device_id": d.id,
        "ip_sasaran": ip,
        "menit": menit,
        "alasan": alasan,
        "oleh": oleh,
        "perintah": "sudo %s blokir %s %d" % (JALUR, ip, menit),
        "sungguhan": False,
        "hasil": "RENCANA",
        "bukti": None,
        "waktu": datetime.now(),
    }
    if not sungguhan:
        plan["catatan"] = (
            "Belum dikirim. Perangkat tidak disentuh sama sekali. "
            "Panggil lagi dengan sungguhan=True untuk benar-benar mengirim.")
        return plan

    if not alasan or not str(alasan).strip():
        message = "Alasan wajib diisi untuk perubahan sungguhan."
        _catat(db, device_id, "BLOKIR", ip, menit, alasan, oleh,
               "DITOLAK_NSM", message)
        raise Ditolak(message)

    c = _sambung(d)
    try:
        keluar, teks = _jalankan(c, ["blokir", ip, menit])
    finally:
        c.close()

    plan["sungguhan"] = True
    plan["bukti"] = teks

    if keluar != 0:
        plan["hasil"] = "DITOLAK_SERVER"
        plan["catatan"] = (
            "Server menolak permintaannya. Aturan firewall TIDAK berubah.")
        _catat(db, device_id, "BLOKIR", ip, menit, alasan, oleh,
               "DITOLAK_SERVER", teks)
        return plan

    if not _masih_terjangkau(d):
        # Unblock at once; the server timer would only do it after `menit` minutes.
        cancelled = False
        try:
            c2 = _sambung(d)
            try:
                keluar2, _text2 = _jalankan(c2, ["buka", ip])
                cancelled = (keluar2 == 0)
            finally:
                c2.close()
        except Exception:
            pass

        if cancelled:
            plan["hasil"] = "DIBATALKAN"
            plan["catatan"] = (
                "Setelah blokir dipasang, perangkat TIDAK lagi bisa dihubungi "
                "NSM. Blokirnya BERHASIL dibatalkan.")
            _catat(db, device_id, "BLOKIR", ip, menit, alasan, oleh,
                   "DIBATALKAN", teks + "\n\n" + plan["catatan"])
        else:
            # If this rollback also fails (usually the same cause, e.g. SSH cannot open), the
            # block is still on the device. Recording "cancelled" would misreport the device
            # state, so record success: the server's `systemd timer` is already verified
            # installed (the wrapper checks it before replying), so the block will expire anyway.
            plan["hasil"] = "BERHASIL_TANPA_BUKTI"
            plan["catatan"] = (
                "Blokir TERPASANG di perangkat, tapi NSM tidak bisa "
                "membuktikan perangkat masih terjangkau SESUDAHNYA, dan "
                "pembatalan otomatis juga gagal (kemungkinan sebab yang "
                "sama). Jaring server (timer buka-sendiri) SUDAH TERBUKTI "
                "terpasang sebelum ini, jadi blokir akan tetap terbuka "
                "sendiri dalam %d menit walau tidak ada yang campur "
                "tangan." % menit)
            _catat(db, device_id, "BLOKIR", ip, menit, alasan, oleh,
                   "BERHASIL_TANPA_BUKTI", teks + "\n\n" + plan["catatan"])
        return plan

    plan["hasil"] = "BERHASIL"
    plan["catatan"] = (
        "Alamat %s diblokir di %s selama %d menit, dan perangkat terbukti "
        "masih melayani NSM sesudahnya. Blokirnya akan membuka sendiri."
        % (ip, d.name, menit))
    _catat(db, device_id, "BLOKIR", ip, menit, alasan, oleh, "BERHASIL", teks)
    return plan


def buka(db, device_id, ip, oleh, sungguhan=False):
    """Unblock before the time limit expires."""
    try:
        d = periksa_izin(db, device_id, ip=ip)
    except Ditolak as e:
        if sungguhan:
            _catat(db, device_id, "BUKA", ip, None, None, oleh,
                   "DITOLAK_NSM", str(e))
        raise

    hasil = {
        "device": d.name, "device_id": d.id, "ip_sasaran": ip,
        "oleh": oleh, "perintah": "sudo %s buka %s" % (JALUR, ip),
        "sungguhan": False, "hasil": "RENCANA", "bukti": None,
        "waktu": datetime.now(),
    }
    if not sungguhan:
        hasil["catatan"] = "Belum dikirim. Perangkat tidak disentuh."
        return hasil

    c = _sambung(d)
    try:
        keluar, teks = _jalankan(c, ["buka", ip])
    finally:
        c.close()

    hasil["sungguhan"] = True
    hasil["bukti"] = teks
    hasil["hasil"] = "BERHASIL" if keluar == 0 else "GAGAL"
    _catat(db, device_id, "BUKA", ip, None, None, oleh, hasil["hasil"], teks)
    return hasil

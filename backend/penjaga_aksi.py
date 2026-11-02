"""Auto-ban execution: block and unblock IPs.

WRITE PATH. This is the only module that changes device firewalls/ACLs from
NSM. It opens a write path specifically for auto-ban, with its own
safeguards; the other read-only guards stay in place.

Two mechanisms, and one IP can have both at once:
`blokir()`/`buka_blokir()` -- ufw on the target Linux device.
`blokir_acl()`/`buka_blokir_acl()` -- ACL on the router.
They are deliberately separate `BanAktif` rows (keyed on `ip`+`device_id`,
not `ip` alone). With one row per IP, blocking the same address on both
layers (defense in depth) would treat the second attempt as "already
banned" and the second layer would never be installed.
`buka_blokir_apa_pun()` and `kedaluwarsa()` handle both, choosing by device
platform (`linux` -> ufw, `cisco_ios` -> ACL).

The core safeguard sits at the execution point, not in the caller:
`blokir()` checks the allowlist itself even though `rencana_penjagaan`
already filtered it. A caller that forgets the check could lock NSM out of
its own servers, the costliest failure for a security tool.

Execution is delegated to `ubah_firewall` / `ubah_acl_router`; tests inject
a fake executor via `_exec`, so the allowlist can be tested without SSH.

Bans are temporary: `waktu_kedaluwarsa` defaults to `BAN_MENIT` minutes, so
a mistaken ban lifts itself after the window (like fail2ban).
`kedaluwarsa()`, called by a poller job, lifts expired bans.
"""
import ipaddress
from datetime import datetime, timedelta

import config
import dialek_perangkat
import notifikasi
import report_service
import ubah_acl_router
import ubah_firewall
from models import BanAktif, Device

# How long an auto-ban lasts before the server lifts it by itself.
# `ubah_firewall` takes MINUTES (1-1440); the server-side wrapper schedules
# the unblock, so bans stay temporary even if NSM restarts.
#
# Single source of truth: `BAN_SEMENTARA` (NSM's `waktu_kedaluwarsa`) is always
# derived from `BAN_MENIT` (sent to the server). Change only `BAN_MENIT`;
# separate values would let NSM's records drift from when the server actually
# unblocks.
BAN_MENIT = 60
BAN_SEMENTARA = timedelta(minutes=BAN_MENIT)


class DitolakPengaman(Exception):
    """Block refused by a safeguard (allowlist / invalid IP). Not a technical error;
    callers should display it, not swallow it.
    """


def _sah_ip(ip):
    try:
        ipaddress.ip_address(ip)
        return True
    except (ValueError, TypeError):
        return False


def _periksa_pengaman(db, ip):
    """Raise DitolakPengaman if `ip` must not be blocked. Returns the cleaned IP."""
    ip = report_service._ip_bersih(ip)
    if not _sah_ip(ip):
        raise DitolakPengaman("Alamat tidak sah: %r" % ip)
    dilindungi = report_service.daftar_dilindungi(db)
    if ip in dilindungi:
        raise DitolakPengaman(
            "%s ada di allowlist (%s) — host terdaftar/NSM tidak pernah "
            "diblokir. Kalau ia memang perlu diblokir, keluarkan dulu dari "
            "daftar perangkat." % (ip, dilindungi[ip]))
    return ip


def _kirim_notifikasi_blokir(db, ban, nama_device):
    """Notify this device's subscribers that NSM just blocked an IP.

    Uses the same generic endpoint as device up/down alerts
    (`/internal/notifikasi-device`, see `notifikasi.titip_ke_java`), so no new
    Java endpoint is needed.

    Pure best-effort, unlike `notifikasi.proses_antrean`: failures are NOT
    retried. The block itself is already recorded in `FirewallPerubahan` and the
    audit log; email only adds visibility. Failures are printed to the poller log.
    """
    if not config.get_notif_enabled():
        return
    try:
        cfg = config.get_notif_config()
        subject = "[NSM] %s diblokir di firewall %s" % (ban.ip, nama_device)
        kedaluwarsa = (ban.waktu_kedaluwarsa.strftime("%d %B %Y, %H:%M:%S")
                      if ban.waktu_kedaluwarsa else "permanen")
        content = (
            "<p>NSM memblokir alamat <b>%s</b> di firewall <b>%s</b>.</p>"
            % (notifikasi._esc(ban.ip), notifikasi._esc(nama_device))
            + notifikasi._tabel_html([
                ("Pola", notifikasi._esc(ban.pola)),
                ("Alasan", notifikasi._esc(ban.alasan)),
                ("Oleh", notifikasi._esc(ban.oleh)),
                ("Berlaku sampai", kedaluwarsa),
            ])
            + "<p>Blokir ini SEMENTARA — server membukanya sendiri saat "
              "waktunya habis, walau NSM sedang mati.</p>")
        notifikasi.titip_ke_java(cfg, subject, content, nama_device, ban.device_id)
    except Exception as e:
        print("[ban] notifikasi blokir %s gagal dikirim (dilewati): %s"
              % (ban.ip, e))


def blokir(db, ip, device_id=None, alasan="", pola="manual", oleh="auto",
           _exec=None, _notif=None):
    """Block `ip` on the firewall of `device_id`. Raises DitolakPengaman if forbidden.

    Delegates execution to `ubah_firewall.blokir`, the only sanctioned path for
    firewall changes: the `nsm-ubah-firewall` server wrapper (via sudo),
    temporary blocks the server lifts itself, a reachability check with
    auto-revert if NSM locks itself out, and auditing to `FirewallPerubahan`.
    This module adds one more layer on top: a wider allowlist (all registered
    devices, `daftar_dilindungi`), not just the addresses in
    `ubah_firewall.DILARANG`.

    After the ban is written, subscribers are emailed (see
    `_kirim_notifikasi_blokir`); that is best-effort and never makes `blokir()`
    report failure, since the firewall has already changed.

    Idempotent (an active ban is not written twice). `_exec` replaces the
    executor and `_notif` the notifier, for tests.
    """
    ip = _periksa_pengaman(db, ip)  # top layer: wide allowlist, before anything else
    if not device_id:
        return {"ok": False, "error": "Device target tidak diketahui."}

    # Idempotency key is (ip, device_id), not ip alone, so the same IP can still
    # be blocked on ANOTHER device (e.g. the router ACL layer while the ufw layer
    # on the target server is already active). See the module docstring.
    exists = (db.query(BanAktif)
           .filter(BanAktif.ip == ip, BanAktif.device_id == device_id,
                   BanAktif.aktif == 1).first())
    if exists:
        return {"ok": True, "sudah_diban": True, "ban_id": exists.id}

    run = _exec or ubah_firewall.blokir
    alasan_final = alasan or ("auto-ban (%s)" % pola)
    try:
        r = run(db, device_id, ip, BAN_MENIT, alasan_final, oleh,
                     sungguhan=True)
    except ubah_firewall.Ditolak as e:
        # Refused by the `ubah_firewall` Python/server layer: treat it like our own
        # safeguard, as an answer rather than an error.
        raise DitolakPengaman(str(e))
    except Exception as e:
        # Not a refusal: a technical failure (e.g. a transient SSH error, common on
        # Dynamips labs). Returned as a structured answer instead of raised, so one
        # failing candidate does not abort the whole `poll_auto_ban` round for other
        # candidates on healthy devices. This candidate is retried next round.
        return {"ok": False, "error": "Gagal menghubungi perangkat: %s" % e}
    # "BERHASIL_TANPA_BUKTI" is treated the same as "BERHASIL": the change did
    # reach the device, only the post-change verification/revert failed (usually
    # transient SSH). Not recording BanAktif here would make NSM lose track of a
    # ban that is actually active on the device.
    if r.get("hasil") not in ("BERHASIL", "BERHASIL_TANPA_BUKTI"):
        return {"ok": False, "error": r.get("catatan") or r.get("hasil"),
                "detail": r.get("bukti")}

    ban = BanAktif(ip=ip, device_id=device_id, alasan=alasan_final, pola=pola,
                   oleh=oleh, waktu_ban=datetime.now(),
                   waktu_kedaluwarsa=datetime.now() + BAN_SEMENTARA, aktif=1)
    db.add(ban)
    db.commit()

    nama_device = (db.query(Device.name).filter(Device.id == device_id).scalar()
                  or ("device %s" % device_id))
    try:
        (_notif or _kirim_notifikasi_blokir)(db, ban, nama_device)
    except Exception:
        # Extra safety net: `_kirim_notifikasi_blokir` already swallows its own
        # errors; this only guards against a fake `_notif` (tests) raising. A
        # notification must never make a successful block report failure.
        pass

    return {"ok": True, "ban_id": ban.id,
            "kedaluwarsa": ban.waktu_kedaluwarsa.isoformat()}


def unblock(db, ip, device_id=None, oleh="auto", _exec=None):
    """Unblock `ip` via `ubah_firewall.buka` and mark the ban inactive.

    `device_id` narrows it to ONE ban when the same IP has several active bans
    (ufw + ACL, see the module docstring). Without it (legacy behavior, kept for
    callers that do not know the device), the most recent ban for this IP is
    lifted.
    """
    ip = report_service._ip_bersih(ip)
    q = db.query(BanAktif).filter(BanAktif.ip == ip, BanAktif.aktif == 1)
    if device_id is not None:
        q = q.filter(BanAktif.device_id == device_id)
    ban = q.order_by(BanAktif.waktu_ban.desc()).first()
    if not ban:
        return {"ok": True, "tidak_ada_ban": True}
    run = _exec or ubah_firewall.buka
    try:
        r = run(db, ban.device_id, ip, oleh, sungguhan=True)
    except ubah_firewall.Ditolak as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        # Not a refusal: a technical failure (e.g. SSH unreachable). `kedaluwarsa()`
        # calls this in a loop over all expired bans; raising would let one
        # unreachable device abort the whole loop and leave bans on healthy devices
        # in place. Returned as a structured answer; this ban is retried next round.
        return {"ok": False, "error": "Gagal menghubungi perangkat: %s" % e}
    if r.get("hasil") not in ("BERHASIL", None):
        return {"ok": False, "error": r.get("catatan") or r.get("hasil")}
    ban.aktif = 0
    ban.waktu_buka = datetime.now()
    db.commit()
    return {"ok": True, "ban_id": ban.id}


def block_acl(db, ip, device_id=None, alasan="", pola="manual", oleh="auto",
               menit=BAN_MENIT, _exec=None, _notif=None):
    """Block `ip` in the router ACL of `device_id`.

    Same design as `blokir()` (ufw): the wide allowlist is checked at the
    execution point (`_periksa_pengaman`), execution is delegated to
    `ubah_acl_router.blokir`, and the result is recorded as a `BanAktif` row
    deliberately SEPARATE from any ufw ban for the same IP (keyed on
    `ip`+`device_id`), so blocking on both layers does not count as "already
    banned". `menit` is separate from the global `BAN_MENIT` because an ACL
    block may have a different duration than a ufw block for the same IP.
    """
    ip = _periksa_pengaman(db, ip)
    if not device_id:
        return {"ok": False, "error": "Device target tidak diketahui."}

    exists = (db.query(BanAktif)
           .filter(BanAktif.ip == ip, BanAktif.device_id == device_id,
                   BanAktif.aktif == 1).first())
    if exists:
        return {"ok": True, "sudah_diban": True, "ban_id": exists.id}

    run = _exec or ubah_acl_router.blokir
    alasan_final = alasan or ("auto-ban ACL (%s)" % pola)
    try:
        r = run(db, device_id, ip, menit, alasan_final, oleh,
                     sungguhan=True)
    except ubah_acl_router.Ditolak as e:
        raise DitolakPengaman(str(e))
    except Exception as e:
        # Same reasoning as the ufw `blokir()` above; see the comment there.
        return {"ok": False, "error": "Gagal menghubungi perangkat: %s" % e}
    # "BERHASIL_TANPA_BUKTI" is treated the same as "BERHASIL": the change did
    # reach the device, only the post-change verification/revert failed (usually
    # transient SSH). Not recording BanAktif here would make NSM lose track of a
    # ban that is actually active on the device.
    if r.get("hasil") not in ("BERHASIL", "BERHASIL_TANPA_BUKTI"):
        return {"ok": False, "error": r.get("catatan") or r.get("hasil"),
                "detail": r.get("bukti")}

    ban = BanAktif(ip=ip, device_id=device_id, alasan=alasan_final, pola=pola,
                   oleh=oleh, waktu_ban=datetime.now(),
                   waktu_kedaluwarsa=datetime.now() + timedelta(minutes=menit),
                   aktif=1)
    db.add(ban)
    db.commit()

    nama_device = (db.query(Device.name).filter(Device.id == device_id).scalar()
                  or ("device %s" % device_id))
    try:
        (_notif or _kirim_notifikasi_blokir)(db, ban, nama_device)
    except Exception:
        pass

    return {"ok": True, "ban_id": ban.id,
            "kedaluwarsa": ban.waktu_kedaluwarsa.isoformat()}


def unblock_acl(db, ip, device_id, oleh="auto", _exec=None):
    """Unblock an ACL ban. Unlike `buka_blokir()` (ufw), `device_id` is REQUIRED:
    one IP can be banned on several devices, so there is no safe "most recent
    ban for this IP" to guess.
    """
    ip = report_service._ip_bersih(ip)
    ban = (db.query(BanAktif)
           .filter(BanAktif.ip == ip, BanAktif.device_id == device_id,
                   BanAktif.aktif == 1).first())
    if not ban:
        return {"ok": True, "tidak_ada_ban": True}
    run = _exec or ubah_acl_router.buka
    try:
        r = run(db, device_id, ip, oleh, sungguhan=True)
    except ubah_acl_router.Ditolak as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": "Gagal menghubungi perangkat: %s" % e}
    if r.get("hasil") not in ("BERHASIL", None):
        return {"ok": False, "error": r.get("catatan") or r.get("hasil")}
    ban.aktif = 0
    ban.waktu_buka = datetime.now()
    db.commit()
    return {"ok": True, "ban_id": ban.id}


def unblock_any(db, ip, device_id=None, oleh="auto", _exec=None,
                        _exec_acl=None):
    """Single entry point to lift a ban of ANY kind, chosen by device platform
    (`linux` -> ufw, `cisco_ios` -> ACL).

    Without `device_id`, lifts ALL active bans for this IP (ufw and ACL alike),
    not just the first one found. Callers that only know the IP (e.g. the older
    UI "Unblock" button, or `kedaluwarsa()`) thus clear every active layer.
    """
    if device_id is not None:
        device = db.query(Device).filter(Device.id == device_id).first()
        # This device's block mechanism, from its definition file.
        if (device is not None
                and dialek_perangkat.ambil(device.platform).firewall == "acl"):
            return unblock_acl(db, ip, device_id, oleh=oleh, _exec=_exec_acl)
        return unblock(db, ip, device_id=device_id, oleh=oleh, _exec=_exec)

    ip_clean = report_service._ip_bersih(ip)
    bans = (db.query(BanAktif)
            .filter(BanAktif.ip == ip_clean, BanAktif.aktif == 1).all())
    if not bans:
        return {"ok": True, "tidak_ada_ban": True}
    hasil = [unblock_any(db, ip, device_id=b.device_id, oleh=oleh,
                                 _exec=_exec, _exec_acl=_exec_acl)
             for b in bans]
    return {"ok": all(h.get("ok") for h in hasil), "hasil": hasil}


def kedaluwarsa(db, _exec=None, _exec_acl=None):
    """Lift all TEMPORARY bans that have expired. Returns the count.

    Called by a poller job. Permanent bans (`waktu_kedaluwarsa` None) are
    skipped. Most ufw bans are already lifted by the server wrapper and ACL bans
    by their EEM applet; this is an extra safety net that also syncs NSM's
    `ban_aktif` records with the actual server/router state.
    """
    sekarang = datetime.now()
    habis = (db.query(BanAktif)
             .filter(BanAktif.aktif == 1,
                     BanAktif.waktu_kedaluwarsa.isnot(None),
                     BanAktif.waktu_kedaluwarsa < sekarang).all())
    dibuka = 0
    for ban in habis:
        r = unblock_any(db, ban.ip, device_id=ban.device_id,
                                oleh="kedaluwarsa", _exec=_exec,
                                _exec_acl=_exec_acl)
        if r.get("ok"):
            dibuka += 1
    return dibuka


def daftar_ban_aktif(db):
    """Currently active bans, newest first, for display.

    Includes `device_id` and `jenis` ("ufw"/"acl"): the UI "Unblock" button
    needs both to lift the RIGHT ban when one IP has several active bans.
    """
    line = (db.query(BanAktif)
             .filter(BanAktif.aktif == 1)
             .order_by(BanAktif.waktu_ban.desc()).all())
    devices = {d.id: d for d in db.query(Device).all()}
    hasil = []
    for b in line:
        d = devices.get(b.device_id)
        hasil.append({
            "ip": b.ip, "device": d.name if d else None,
            "device_id": b.device_id,
            # Mechanism name from the definition file. Defaults to "ufw" for devices that
            # no longer exist: old ban rows may point to deleted devices, and changing
            # their label would change the meaning of existing history.
            "jenis": (dialek_perangkat.ambil(d.platform).firewall or "ufw")
                     if d else "ufw",
            "alasan": b.alasan, "pola": b.pola, "oleh": b.oleh,
            "waktu_ban": b.waktu_ban.isoformat() if b.waktu_ban else None,
            "kedaluwarsa": (b.waktu_kedaluwarsa.isoformat()
                            if b.waktu_kedaluwarsa else None),
        })
    return hasil

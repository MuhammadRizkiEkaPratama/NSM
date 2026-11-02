"""Stage 5: dead service -> restart over SSH + sudo.

Medium risk. Operational: the wrapper `/usr/local/sbin/nsm-restart-layanan` is
installed on `.103` and `.105`, and `nsmro` may run THAT FILE ONLY via sudo,
not `systemctl`. The kill switch `config.get_pemulih_layanan_aktif()` is still
off by default and `PAGAR_DAFTAR_PUTIH` must be filled separately.

Double allowlist: `Service.unit_systemd` AND `PAGAR_DAFTAR_PUTIH`. A NULL
`unit_systemd` means the service is not mapped and is never a candidate. The
operator fills it once per service that is safe to restart; "Login NSM" itself
must never have one, since restarting it would cut NSM's own admin access.

Two phases, as in stage 4: a restart takes time before the service answers
again, so verifying immediately would always report "not yet".
"""
from datetime import datetime, timedelta

from sqlalchemy import select, desc

import pagar_otomasi
from pemulih import rollback
from models import Device, Service, ServiceEvent, PagarTindakan

KATEGORI = "pemulih"
KUNCI = "layanan_restart"

BATAS_TUNGGU_VERIFIKASI_DETIK = 90

# Calls the WRAPPER, not raw `systemctl`. `nsmro` has no sudo for `systemctl`
# (see `pasang-restart-layanan.sh` step 5), only for ONE file that holds the list
# of units that may be touched. Even if this module had a bug that sent an
# arbitrary unit name (`ssh`, `slapd`, `mysql`), the server would refuse, not this
# code. Same rule as `pagar_otomasi.py`: checked at the point of execution.
_JALUR_PEMBUNGKUS = "/usr/local/sbin/nsm-restart-layanan"
_PERINTAH_RESTART = "sudo " + _JALUR_PEMBUNGKUS + " restart {unit}"


class GagalEksekusi(Exception):
    pass


def _jalankan_ssh(device, perintah, timeout=20):
    """One command over SSH with the `nsmro` account and this device's private key.
    Never called directly by `coba_restart()`; always via the injected `_exec`
    parameter, as in `penjaga_aksi.py`.
    """
    import paramiko
    cl = paramiko.SSHClient()
    cl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        if device.ssh_key_path:
            cl.connect(device.ip_address, username="nsmro",
                      key_filename=device.ssh_key_path, timeout=timeout,
                      allow_agent=False, look_for_keys=False)
        else:
            raise GagalEksekusi("device %s tidak punya ssh_key_path." % device.name)
        _stdin, stdout, stderr = cl.exec_command(perintah, timeout=timeout)
        keluar = stdout.read().decode("utf-8", "replace")
        error = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        if code != 0:
            raise GagalEksekusi("exit %d: %s" % (code, error.strip() or keluar.strip()))
        return keluar
    finally:
        cl.close()


def _sedang_down(db, service_id):
    """True if NSM considers the service DEAD, read from `service_events`, not the last
    raw check.
    Reading the last `service_checks` row would let one brief failure (a timeout, a
    single TCP reset) restart a healthy service and cut live user sessions.
    `service_events` only gets a DOWN row after consecutive failures reach
    `SERVICE_DOWN_THRESHOLD`, the same threshold NSM uses to notify humans.
    Recovery (DOWN -> UP) is recorded without a threshold, so phase 2 is not slowed.
    """
    ev = db.execute(
        select(ServiceEvent).where(ServiceEvent.service_id == service_id)
        .order_by(desc(ServiceEvent.timestamp), desc(ServiceEvent.id)).limit(1)
    ).scalars().first()
    return ev is not None and ev.event_type == "DOWN"


def cari_kandidat(db):
    """[(device, service), ...] -- layanan yang SUDAH dipetakan
    (`unit_systemd` terisi) DAN sedang down sekarang."""
    hasil = []
    for s in db.execute(
        select(Service).where(Service.unit_systemd.isnot(None))
    ).scalars().all():
        if _sedang_down(db, s.id):
            d = db.get(Device, s.device_id)
            if d is not None and d.aktif == 1:
                hasil.append((d, s))
    return hasil


def coba_restart(db, device, service, oleh="pemulih_layanan", sekarang=None, _exec=None):
    """Phase 1: gate -> run `systemctl restart` via the wrapper -> record the action.
    No verification; see `verifikasi_tertunda()`.
    `_exec(device, command) -> str` can be injected for tests; the default
    `_jalankan_ssh` is real SSH and no official test calls it.
    """
    # Gate 1b conditions for services are computed from this device's own
    # `PagarTindakan` history (restart limit per 24 h), so nothing needs to be passed
    # via `bukti`. Written out so it does not read as an oversight.
    kep = pagar_otomasi.putuskan(db, device.id, KATEGORI, KUNCI,
                                 oleh=oleh, sekarang=sekarang, bukti={})
    if not kep.izin:
        return kep

    # Not for rollback (stage 5 has no such concept). Pure bookkeeping, so
    # `verifikasi_tertunda()` knows exactly which service_id to recheck instead of
    # sweeping all of the device's services, which may be down for unrelated reasons.
    rollback.simpan_state_sebelum(db, kep.tindakan_id, {"service_id": service.id})

    run = _exec or _jalankan_ssh
    perintah = _PERINTAH_RESTART.format(unit=service.unit_systemd)
    try:
        run(device, perintah)
    except GagalEksekusi as e:
        pagar_otomasi.record_verification(
            db, kep.tindakan_id, False, bukti="Gagal menjalankan '%s': %s" % (perintah, e))
        return kep

    # Command SENT does not mean service HEALTHY; that is phase 2.
    return kep


def verifikasi_tertunda(db, sekarang=None, batas_detik=BATAS_TUNGGU_VERIFIKASI_DETIK):
    """Phase 2: service answers healthy -> success. Past the deadline without health ->
    failure (NO rollback; see `pemulih/__init__.py`: the prior state was already
    dead, so there is nothing sensible to restore).
    """
    sekarang = sekarang or datetime.now()
    pending = db.execute(
        select(PagarTindakan).where(
            PagarTindakan.kategori == KATEGORI,
            PagarTindakan.kunci == KUNCI,
            PagarTindakan.keputusan == pagar_otomasi.IZIN,
            PagarTindakan.status_verifikasi.is_(None),
        )
    ).scalars().all()

    verified = 0
    for t in pending:
        state = rollback.ambil_state_sebelum(db, t.id)
        service_id = state.get("service_id") if state else None
        if service_id is None:
            continue
        s = db.get(Service, service_id)
        if s is None:
            continue

        if not _sedang_down(db, s.id):
            pagar_otomasi.record_verification(
                db, t.id, True, bukti="Layanan '%s' menjawab sehat lagi sesudah direstart." % s.nama)
            verified += 1
            continue

        if sekarang - t.waktu >= timedelta(seconds=batas_detik):
            bukti = "Masih tidak sehat %d detik sesudah restart." % batas_detik
            pagar_otomasi.record_verification(db, t.id, False, bukti=bukti)
            _eskalasi(db, t.device_id, "Layanan '%s' dicoba direstart otomatis" % s.nama, bukti)
            verified += 1
    return verified


def _eskalasi(db, device_id, ringkas, alasan):
    try:
        import notifikasi_berjenjang
        notifikasi_berjenjang.eskalasi_segera(db, device_id, ringkas, alasan)
    except Exception as e:
        print("[pemulih:layanan] gagal eskalasi notifikasi (dilewati): %s" % e)

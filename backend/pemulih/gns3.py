"""Stage 4: dead GNS3 node -> restart through the controller API.

Lowest risk of the four recoverers.

Two phases, because a Dynamips node takes 1-2 minutes to boot and verifying
right after `pulihkan()` would always report "not recovered".
  Phase 1 (`coba_pulihkan`)       detect -> guardrail -> call API -> record the
                                  action. Does not wait for the boot.
  Phase 2 (`verifikasi_tertunda`) next poller round, check pending actions:
                                  recovered -> success; past the deadline
                                  without recovery -> failure.

No rollback here: the "before" state is the dead state being fixed (see
`pemulih/__init__.py`).
"""
from datetime import datetime, timedelta

from sqlalchemy import select, desc

import pagar_otomasi
from connectors import gns3_pemulihan
from models import Device, DeviceEvent, PagarTindakan

KATEGORI = "pemulih"
KUNCI = "gns3_restart"

# Enough for a Dynamips boot (1-2 min measured) plus slack for the poller to
# record the new status.
BATAS_TUNGGU_VERIFIKASI_DETIK = 180


def _sedang_down(db, device_id):
    """True if NSM considers the device DEAD, read from `device_events`, not raw pings.

    `status_logs` holds EVERY ping, including a single lost packet; `DOWN_THRESHOLD`
    only gates when a `device_events` row is written (default 5 consecutive
    failures). Reading `status_logs` would let one lost packet reboot a healthy
    router: automation must not trust more easily than a human would.
    Using `device_events` also gives the recoverer the same definition of "dead" as
    the diagnosis panel. Recovery (DOWN -> UP) is recorded without a threshold, so
    phase 2 is not slowed down.
    """
    ev = db.execute(
        select(DeviceEvent).where(DeviceEvent.device_id == device_id)
        .order_by(desc(DeviceEvent.timestamp), desc(DeviceEvent.id)).limit(1)
    ).scalars().first()
    return ev is not None and ev.event_type == "DOWN"


def cari_kandidat(db):
    """Devices with a `gns3_node` that are actively monitored and currently down."""
    hasil = []
    for d in db.execute(
        select(Device).where(Device.gns3_node.isnot(None), Device.aktif == 1)
    ).scalars().all():
        if _sedang_down(db, d.id):
            hasil.append(d)
    return hasil


def coba_pulihkan(db, device, oleh="pemulih_gns3", sekarang=None, _panggil=None):
    """Phase 1: guardrail gate, then call the GNS3 API if allowed.
    `_panggil` is passed to `gns3_pemulihan.pulihkan()` so tests never touch a real
    GNS3 server. Returns `pagar_otomasi.Keputusan`; if `.izin` is False nothing is
    called.
    """
    kep = pagar_otomasi.putuskan(db, device.id, KATEGORI, KUNCI,
                                 oleh=oleh, sekarang=sekarang)
    if not kep.izin:
        return kep

    kwargs = {} if _panggil is None else {"_panggil": _panggil}
    try:
        hasil = gns3_pemulihan.pulihkan(device.gns3_node, **kwargs)
    except gns3_pemulihan.GagalPulih as e:
        # Failed to CALL the API itself (GNS3 server not running, etc.): a known failure
        # already, no need to wait for phase 2.
        pagar_otomasi.record_verification(
            db, kep.tindakan_id, False,
            bukti="Gagal memanggil API GNS3: %s" % e)
        return kep

    # A successful call does not mean recovered; that is phase 2.
    return kep


def verifikasi_tertunda(db, sekarang=None,
                        batas_detik=BATAS_TUNGGU_VERIFIKASI_DETIK):
    """Phase 2: check ALL `gns3_restart` actions that were allowed but not yet verified.
    Recovered -> success. Past the deadline without recovery -> failure (the rate
    limit holds back further attempts if this keeps happening).
    Returns the number just verified, for the poller's summary log.
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
        if t.device_id is None:
            continue
        if not _sedang_down(db, t.device_id):
            pagar_otomasi.record_verification(
                db, t.id, True, bukti="Device menjawab lagi sesudah dipulihkan.")
            verified += 1
            continue
        if sekarang - t.waktu >= timedelta(seconds=batas_detik):
            bukti = ("Masih tidak menjawab %d detik sesudah dipulihkan."
                    % batas_detik)
            pagar_otomasi.record_verification(db, t.id, False, bukti=bukti)
            _eskalasi(db, t.device_id, "Node GNS3 dicoba dipulihkan otomatis", bukti)
            verified += 1
    return verified


def _eskalasi(db, device_id, ringkas, alasan):
    # Imported inside the function to avoid a circular import (`notifikasi_berjenjang`
    # must not know about `pemulih`); a send failure must not undo the verification
    # already recorded above.
    try:
        import notifikasi_berjenjang
        notifikasi_berjenjang.eskalasi_segera(db, device_id, ringkas, alasan)
    except Exception as e:
        print("[pemulih:gns3] gagal eskalasi notifikasi (dilewati): %s" % e)

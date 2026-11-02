"""Stage 6: interface down although intent says up -> bring it up.

Medium risk. Reuses the `iface_hidup` catalog entry in `connectors/perintah.py`
via `kirim_perintah.kirim()`, which already carries all the guards (identity
must match, never shut NSM's own interface, GNS3 awareness). This module opens no
device connection itself: it only decides (via the guardrail) and calls `kirim()`.

Candidates come from `drift.service.bandingkan()` (stage 2), so there is one
config extraction/normalization logic (`drift/ekstrak.py`) for the project.

Verification is synchronous: `kirim()` re-reads the config in the same SSH
session, and `terkirim=True` with `berubah=True` counts as success.

Rollback is prepared but never triggered automatically. The prior state
(`shutdown=True`) is saved via `pemulih.rollback` and `batalkan()` can shut the
interface again, but nothing detects that bringing it up caused a new problem,
and an automatic rollback without such a signal would cause flapping.
"""
import dialek_perangkat
import kirim_perintah
import pagar_otomasi
from drift import service as drift_svc
from pemulih import rollback

KATEGORI = "pemulih"
KUNCI = "interface_up"


def cari_kandidat(db):
    """[(device, nama_interface), ...] -- interface yang intent bilang
    HARUS hidup (shutdown=False) tapi potret terbaru menunjukkan
    shutdown=True. Hanya device cisco_ios yang didukung `drift.ekstrak`
    (sama seperti Tahap 2 -- lihat `drift/__init__.py`)."""
    from models import Device
    hasil = []
    # Devices whose interfaces can be re-enabled through NSM. The real limit is
    # `drift.ekstrak`, which knows only one config shape and is still enforced by
    # `r["didukung"]` below; here we ask about write capability from the definition files.
    for d in db.query(Device).filter(
            Device.platform.in_(
                dialek_perangkat.platform_dengan("firewall", "acl")),
            Device.aktif == 1).all():
        r = drift_svc.bandingkan(db, d.id)
        if not (r.get("didukung") and r.get("punya_intent") and r.get("punya_potret")):
            continue
        for iface in r.get("interface", []):
            for m in iface.get("medan", []):
                if (m["medan"] == "shutdown" and m["intended"] is False
                        and m["observed"] is True):
                    hasil.append((d, iface["kunci"]))
    return hasil


def coba_nyalakan(db, device, nama_interface, oleh="pemulih_interface", sekarang=None):
    """Guardrail gate -> save state -> real `kirim_perintah.kirim('iface_hidup')` ->
    verify from the `kirim()` result itself.
    Returns `pagar_otomasi.Keputusan`; if `.izin` is False no command is sent.
    """
    # `bukti` carries the interface name so gate 1b can check whether it was shut down
    # deliberately according to the latest config snapshot. Without it the question is
    # unanswerable and the guardrail refuses, so it is required, not optional.
    kep = pagar_otomasi.putuskan(db, device.id, KATEGORI, KUNCI,
                                 oleh=oleh, sekarang=sekarang,
                                 bukti={"interface": nama_interface})
    if not kep.izin:
        return kep

    rollback.simpan_state_sebelum(
        db, kep.tindakan_id,
        {"device_id": device.id, "interface": nama_interface, "shutdown": True})

    try:
        hasil = kirim_perintah.kirim(
            db, device.id, "iface_hidup", {"interface": nama_interface},
            oleh=oleh, sungguhan=True)
    except kirim_perintah.Ditolak as e:
        bukti = "Ditolak penjaga: %s" % e
        pagar_otomasi.record_verification(db, kep.tindakan_id, False, bukti=bukti)
        _eskalasi(db, device.id,
                 "Interface %s dicoba dinyalakan otomatis" % nama_interface, bukti)
        return kep

    succeed = bool(hasil.get("terkirim")) and bool(hasil.get("berubah"))
    bukti = ("Terkirim & berubah (baris +%s/-%s)."
            % (hasil.get("baris_bertambah"), hasil.get("baris_berkurang"))
            if succeed else
            "terkirim=%s, berubah=%s, galat=%s"
            % (hasil.get("terkirim"), hasil.get("berubah"), hasil.get("galat")))
    pagar_otomasi.record_verification(db, kep.tindakan_id, succeed, bukti=bukti)
    rollback.simpan_state_sesudah(db, kep.tindakan_id, {
        "terkirim": hasil.get("terkirim"), "berubah": hasil.get("berubah"),
        "reload_masih_terpasang": hasil.get("reload_masih_terpasang"),
    })
    # Escalate IMMEDIATELY on failure. Verification is synchronous, so a failure is
    # final and there is no deadline to wait for as in gns3.py/layanan.py/konfig.py.
    # (This module has no `verifikasi_tertunda()`, which is where the others hook in.)
    if not succeed:
        _eskalasi(db, device.id,
                 "Interface %s dicoba dinyalakan otomatis" % nama_interface, bukti)
    return kep


def _eskalasi(db, device_id, ringkas, alasan):
    try:
        import notifikasi_berjenjang
        notifikasi_berjenjang.eskalasi_segera(db, device_id, ringkas, alasan)
    except Exception as e:
        print("[pemulih:interface] gagal eskalasi notifikasi (dilewati): %s" % e)


def batalkan(db, tindakan_id, oleh="pemulih_interface"):
    """Roll one `interface_up` action back to shutdown. Not called automatically
    anywhere (see the module docstring); available to a human or a future
    orchestrator with a stronger signal.
    """
    def _kembalikan(state):
        hasil = kirim_perintah.kirim(
            db, state["device_id"], "iface_mati", {"interface": state["interface"]},
            oleh=oleh, sungguhan=True)
        if not hasil.get("terkirim"):
            raise RuntimeError("gagal mematikan ulang: %s" % hasil.get("galat"))
        return {"terkirim": True, "berubah": hasil.get("berubah")}

    return rollback.kembalikan(db, tindakan_id, _kembalikan)

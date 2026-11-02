"""Shared rollback bookkeeping for remediators that have a meaningful "revert".

Not every remediator has rollback. For `gns3.py` and `layanan.py` the
previous state is the broken state being fixed, so "revert" would mean
"revert to down". Failures there are handled by rate limits and
verification (`status_verifikasi=False`) instead.

Remediators with a meaningful rollback:

    interface.py   previous state = shutdown or not. Shutting an interface
                   back down after a wrong "enable" decision is reasonable.
    konfig.py      previous state = observed snapshot before the fix was
                   sent. `kembalikan()` does not build inverse commands; it
                   calls the existing `kirim_perintah.putuskan(..., 'batalkan')`,
                   which lets `reload in N` expire (or calls `gns3_pemulihan`
                   for GNS3 nodes) so the device itself restores its
                   startup-config. See `kirim_perintah.putuskan()` for details.

State is free-form JSON owned by each remediator. This module only
guarantees that it is stored intact on the same `PagarTindakan` row as the
decision that allowed the action, and that the rollback result
(success/failure) is recorded honestly.
"""
import json

from models import PagarTindakan
from sot import katalog


def simpan_state_sebelum(db, tindakan_id, state):
    """Store the state snapshot BEFORE the action runs. Call right after
    `pagar_otomasi.putuskan()` allows it and before the first command is sent;
    state recorded after the action starts is no longer "before".
    """
    line = db.get(PagarTindakan, tindakan_id)
    if line is None:
        raise katalog.Ditolak("tindakan pagar id=%s tidak ditemukan." % tindakan_id)
    line.state_sebelum = json.dumps(state, ensure_ascii=False)
    db.commit()


def simpan_state_sesudah(db, tindakan_id, state):
    """Store the state snapshot AFTER the action (and verification), so what
    happened can be reviewed without reconnecting to the device.
    """
    line = db.get(PagarTindakan, tindakan_id)
    if line is None:
        raise katalog.Ditolak("tindakan pagar id=%s tidak ditemukan." % tindakan_id)
    line.state_sesudah = json.dumps(state, ensure_ascii=False)
    db.commit()


def ambil_state_sebelum(db, tindakan_id):
    """Return `state_sebelum` as a dict, or None if it was never stored (e.g.
    remediators without a rollback concept).
    """
    line = db.get(PagarTindakan, tindakan_id)
    if line is None or not line.state_sebelum:
        return None
    return json.loads(line.state_sebelum)


def kembalikan(db, tindakan_id, fungsi_kembalikan):
    """Run `fungsi_kembalikan(state_sebelum_dict)` and record the result.

    `fungsi_kembalikan` belongs to the caller (e.g. `interface.py`/`konfig.py`);
    this module only reads state, calls it, and records. An exception from it is
    recorded as a FAILED rollback (`rollback_dilakukan=False`) instead of
    propagating: "the fix failed AND the way back failed" is the most critical
    state in the system and must be recorded, not left in a traceback.

    Raises `katalog.Ditolak` only when there is no `state_sebelum` to restore;
    that is a caller error, not a rollback failure.
    """
    state = ambil_state_sebelum(db, tindakan_id)
    if state is None:
        raise katalog.Ditolak(
            "tindakan id=%s tidak punya state_sebelum tersimpan -- tidak "
            "ada yang bisa dikembalikan." % tindakan_id)

    line = db.get(PagarTindakan, tindakan_id)
    try:
        bukti = fungsi_kembalikan(state)
        line.rollback_dilakukan = True
        line.state_sesudah = json.dumps(
            {"rollback": "berhasil", "bukti": bukti}, ensure_ascii=False)
    except Exception as e:
        line.rollback_dilakukan = False
        line.state_sesudah = json.dumps(
            {"rollback": "gagal", "galat": str(e)}, ensure_ascii=False)
    db.commit()
    return line.rollback_dilakukan

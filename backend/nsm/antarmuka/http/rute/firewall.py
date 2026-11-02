"""Firewall routes: three-layer state, and the block/unblock path."""
from fastapi import APIRouter, Depends

import report_service
from nsm.antarmuka.http import wiring

router = APIRouter(tags=["firewall"])


def _daftar_ban_aktif(db):
    """Active bans, fail-safe: [] if the table does not exist yet (`migrate_ban` not run), so the
    Firewall page does not die over one new feature.
    """
    try:
        import penjaga_aksi
        return penjaga_aksi.daftar_ban_aktif(db)
    except Exception:
        return []


@router.get("/firewall")
def firewall_semua(period: str = "24h", db=Depends(wiring.beri_sesi)):
    """Firewall rules of each Linux device, with their state.
    READ-ONLY. No endpoint changes firewall rules, and any addition must require explicit
    per-change approval (same pattern as `kirim_perintah.py` for router configuration).
    `period` is accepted but unused: the LATEST state is shown, not a time range.
    """
    _rejection = report_service.penolakan_acl(db)
    _pembobolan = report_service.deteksi_pembobolan(db)
    return {"device": report_service.firewall_semua(db),
            "riwayat": report_service.firewall_riwayat(db),
            # Rule quality, not just content; one page needs one request.
            "temuan": report_service.firewall_temuan(db),
            # Router ACL denials, answering the same security question as the rules from the other side.
            "penolakan": _rejection,
            # BREACH DETECTION: did anything actually get through, read from LIVE connections
            # (`flow_koneksi`) rather than from the denial log, which contains only what was blocked.
            "pembobolan": _pembobolan,
            # Guard plan (auto-ban stage 1, docs/design/AUTO-BAN.md): the allowlist that is never banned,
            # and hostile-host candidates classified as auto-ban vs review. A decision, not an execution.
            "penjagaan": report_service.rencana_penjagaan(
                db, _rejection, _pembobolan),
            # Bans currently in effect. Empty until something is blocked via the 1-click button or auto.
            "ban_aktif": _daftar_ban_aktif(db),
            # Routers whose ACL was changed directly via CLI, outside NSM (see `report_service.acl_drift()`).
            # Shown on the Firewall page, the natural place for "did access control change without NSM knowing".
            "acl_drift": report_service.acl_drift(db),
            # Three-layer map: one card per firewall used by NSM, with location, what it protects, and rule count.
            "peta_lapis": report_service.peta_lapis_firewall(db)}


@router.post("/firewall/blokir")
def firewall_blokir(isi: dict, db=Depends(wiring.beri_sesi)):
    """Block one IP on a device's firewall (1-click or auto).
    REJECTS allowlisted IPs; the safeguard lives in `penjaga_aksi.blokir` itself, not in the
    caller. `DitolakPengaman` is returned as an answer (not a 500) because the page must show it.
    """
    import penjaga_aksi
    try:
        return penjaga_aksi.blokir(
            db, isi.get("ip"), device_id=isi.get("device_id"),
            alasan=isi.get("alasan", ""), pola=isi.get("pola", "manual"),
            oleh=isi.get("oleh", "?"))
    except penjaga_aksi.DitolakPengaman as e:
        return {"ok": False, "ditolak": True, "pesan": str(e)}


@router.post("/firewall/blokir-acl")
def firewall_blokir_acl(isi: dict, db=Depends(wiring.beri_sesi)):
    """Block one IP on a router ACL, the second layer for location B, separate from
    `/firewall/blokir` (ufw). See `penjaga_aksi.blokir_acl` for why both can be active together.
    """
    import penjaga_aksi
    try:
        return penjaga_aksi.block_acl(
            db, isi.get("ip"), device_id=isi.get("device_id"),
            alasan=isi.get("alasan", ""), pola=isi.get("pola", "manual"),
            oleh=isi.get("oleh", "?"))
    except penjaga_aksi.DitolakPengaman as e:
        return {"ok": False, "ditolak": True, "pesan": str(e)}


@router.post("/firewall/buka-blokir")
def firewall_buka_blokir(isi: dict, db=Depends(wiring.beri_sesi)):
    """Unblock one IP: ufw, ACL, or both.
    `device_id` is OPTIONAL: if given, only the ban on that device is lifted (ufw/ACL chosen from
    its platform); otherwise ALL active bans for the IP are lifted, since one IP can have both.
    """
    import penjaga_aksi
    return penjaga_aksi.unblock_any(
        db, isi.get("ip"), device_id=isi.get("device_id"),
        oleh=isi.get("oleh", "?"))

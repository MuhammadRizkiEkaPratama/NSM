"""Identity (LDAP) reports for report_service; re-exported by `report_service/__init__.py`."""
from datetime import datetime
from models import (OrangLdap)



def direktori_ldap(db):
    """Full contents of the LDAP directory copy (`orang_ldap`) for the LDAP
    Management page; unlike `_peta_orang`, not just for decorating history rows.

    Read-only by design: the page cannot modify, add, or delete anything in LDAP.
    It only reads the copy the poller syncs into `orang_ldap` (see `OrangLdap` in
    models.py and `sinkron_ldap()` in poller.py). Write support would need LDAP
    write credentials on the primary lab instance and has deliberately not been
    designed.

    `usia_menit` is included so the reader knows this is a copy, not live state
    (same reason `diperbarui` exists on the model).
    """
    orang = (db.query(OrangLdap).order_by(OrangLdap.uid).all())
    sekarang = datetime.now()
    hasil = []
    for o in orang:
        usia = None
        if o.diperbarui:
            usia = round((sekarang - o.diperbarui).total_seconds() / 60)
        hasil.append({
            "uid": o.uid,
            "nama": o.nama,
            "jabatan": o.jabatan,
            "email": o.email,
            "grup": [g.strip() for g in (o.grup or "").split(",") if g.strip()],
            "diperbarui": o.diperbarui.isoformat() if o.diperbarui else None,
            "usia_menit": usia,
        })

    oldest = min((o["usia_menit"] for o in hasil if o["usia_menit"] is not None),
                default=None)
    return {
        "orang": hasil,
        "total": len(hasil),
        # Stalest copy across all entries. If large, the poller has not synced for a
        # while (e.g. `.101` unreachable) and the page says so instead of silently
        # showing old data.
        "salinan_tertua_menit": oldest,
    }

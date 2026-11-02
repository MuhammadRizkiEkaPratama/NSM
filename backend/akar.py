"""Separates cause from effect when several things fail at once.

A failing service is judged an EFFECT if any of these holds, checked in order:
    1. the device it runs on is down (a dead machine explains more than a
       dead service, so it is checked first)
    2. a service it needs is failing (e.g. E-Canteen without its database,
       sssd without the directory)
    3. a device it needs is down
Otherwise it is a CAUSE and worth waking someone for.

Effects are not hidden: they are shown under their cause, because the
dependency list is written by hand and will sometimes be wrong. Resolution
repeats until nothing changes, with a round cap so an accidental cycle
(A needs B, B needs A) terminates instead of hanging.
"""
from sqlalchemy import select

import models

# Round cap: a chain deeper than 8 almost certainly means a cycle. Stop with a
# partial result rather than hang.
BATAS_PUTARAN = 8


def _peta_ketergantungan(db):
    """{layanan_id: [(pada_layanan_id, pada_device_id, alasan), ...]}"""
    hasil = {}
    for r in db.execute(select(models.LayananBergantung)).scalars():
        hasil.setdefault(r.layanan_id, []).append(
            (r.pada_layanan_id, r.pada_device_id, r.alasan))
    return hasil


def nilai(db, layanan_turun, device_turun, peta=None):
    """Split failing services into causes and effects.

    `layanan_turun`: {layanan_id: device_id} for failing services.
    `device_turun`: set of device_ids that are DOWN.
    Returns {layanan_id: {"vonis": "sebab"|"akibat", "karena": sentence,
    "karena_layanan": id|None, "karena_device": id|None}}.

    Pure: it only reads the dependency map, so it can be tested with synthetic data.
    """
    if peta is None:
        peta = _peta_ketergantungan(db)

    vonis = {sid: {"vonis": "sebab", "karena": None,
                   "karena_layanan": None, "karena_device": None}
             for sid in layanan_turun}

    for _ in range(BATAS_PUTARAN):
        changed = False
        for sid, did in layanan_turun.items():
            if vonis[sid]["vonis"] == "akibat":
                continue

            if did in device_turun:
                vonis[sid] = {"vonis": "akibat",
                              "karena": "perangkat tempatnya berjalan sedang mati",
                              "karena_layanan": None, "karena_device": did}
                changed = True
                continue

            for at_sid, at_did, alasan in peta.get(sid, []):
                if at_sid is not None and at_sid in layanan_turun:
                    vonis[sid] = {"vonis": "akibat",
                                  "karena": alasan or "layanan yang dibutuhkannya jatuh",
                                  "karena_layanan": at_sid,
                                  "karena_device": None}
                    changed = True
                    break
                if at_did is not None and at_did in device_turun:
                    vonis[sid] = {"vonis": "akibat",
                                  "karena": alasan or "perangkat yang dibutuhkannya mati",
                                  "karena_layanan": None,
                                  "karena_device": at_did}
                    changed = True
                    break
        if not changed:
            break

    return vonis


def ringkas(vonis):
    """One-sentence summary for the page header; empty when everything is healthy."""
    sebab = [s for s, v in vonis.items() if v["vonis"] == "sebab"]
    akibat = [s for s, v in vonis.items() if v["vonis"] == "akibat"]
    if not vonis:
        return ""
    if not akibat:
        return "%d layanan bermasalah, tidak ada yang saling terkait." % len(sebab)
    return ("%d sebab, %d ikut terdampak. Perbaiki yang bertanda SEBAB lebih "
            "dulu — yang lain kemungkinan pulih sendiri." % (len(sebab), len(akibat)))

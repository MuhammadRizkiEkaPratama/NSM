"""Seed the Source of Truth from the state that is ACTUALLY running.

Why this exists: NSM's drift detection worked (config snapshots, many
findings) but the Source of Truth it compares against was nearly empty.
`intent_nilai` had only 6 rows (all for R1), and `intent_interface`,
`intent_vlan`, and `intent_rute` had none, for 11 monitored devices. Drift
detection without a complete intent reports "configuration changed" rather
than "configuration VIOLATES intent", which decides whether findings are
actionable. This is data-entry work, not a code defect.

Approach: intent is NOT invented. It is derived from the latest configuration
snapshot NSM already took from the device ("bootstrap intent from reality,
then a human reviews"). On day one the most sensible intent is the state its
operator currently considers correct; after seeding, EVERY change reads as
drift.

Three guards:
1. Never overwrite. Keys already declared by a human are left alone;
   re-seeding from a snapshot would erase that decision without asking.
2. Never seed empty values. A key absent from the config (e.g. an unset
   `zona_waktu`) is SKIPPED, not declared empty. "Not declared" and
   "deliberately empty" differ, and mixing them yields false violations forever.
3. Record provenance. `diubah_oleh` is `benih_intent:<snapshot time>`, so
   "decided by a person" is distinguishable from "whatever was running when seeded".

Only platforms supported by the drift extractor (Cisco IOS) can be seeded.
Linux snapshots hold SECURITY POSTURE (sshd_config, listening ports), not
intent catalog keys, so seeding from them would give wrong conclusions.

Run (report only, changes nothing):
    venv\\Scripts\\python.exe benih_intent.py
Write for real:
    venv\\Scripts\\python.exe benih_intent.py --tulis
"""
import sys

from sqlalchemy import desc, select

import database
import models
from drift import ekstrak
from sot import katalog, service as sot_svc

OLEH = "benih_intent"


def potret_terakhir(db, device_id):
    return db.execute(
        select(models.KonfigSnapshot)
        .where(models.KonfigSnapshot.device_id == device_id)
        .order_by(desc(models.KonfigSnapshot.waktu))
        .limit(1)
    ).scalars().first()


def _bersih(nilai):
    keluar = {}
    for k, v in (nilai or {}).items():
        if v is None:
            continue
        if isinstance(v, (list, dict, str)) and len(v) == 0:
            continue
        keluar[k] = v
    return keluar


def benihkan(db, d, tulis=False):
    hasil = {"device": d.name, "platform": d.platform, "lewat": None,
             "nilai": 0, "interface": 0, "vlan": 0, "rute": 0, "dipertahankan": []}

    if not ekstrak.didukung(d.platform):
        hasil["lewat"] = ("platform '%s' tidak didukung ekstraktor drift"
                          % d.platform)
        return hasil

    s = potret_terakhir(db, d.id)
    if s is None or not (s.teks or "").strip():
        hasil["lewat"] = "belum ada potret konfigurasi"
        return hasil
    hasil["potret"] = str(s.waktu)[:19]

    observed = ekstrak.ekstrak(d.platform, s.teks or "")
    oleh = "%s:%s" % (OLEH, str(s.waktu)[:19])

    already = {b.kunci for b in db.execute(
        select(models.IntentNilai)
        .where(models.IntentNilai.device_id == d.id)).scalars().all()}
    prospective = _bersih(observed.get("nilai"))
    baru = {k: v for k, v in prospective.items() if k not in already}
    hasil["dipertahankan"] = sorted(already & set(prospective))
    # Validated ONE BY ONE, not as a batch: validating the whole set rejected the
    # entire device when a single key failed. A rejected value is not junk, it is a
    # finding: Cisco `exec_timeout 0` means CLI sessions NEVER expire, and the
    # catalog rejects it because nobody should intend that. Dropping it silently
    # would hide a real security weakness.
    hasil["ditolak"] = []
    valid = {}
    for k, v in baru.items():
        try:
            katalog.periksa_parsial(d.platform, {k: v})
            valid[k] = v
        except katalog.Ditolak as e:
            hasil["ditolak"].append("%s=%r (%s)" % (k, v, str(e)[:70]))
    if valid:
        if tulis:
            sot_svc.simpan_nilai(db, d.id, valid, oleh=oleh)
        hasil["nilai"] = len(valid)

    # For repeating categories, seed only if still EMPTY. Merging partially would
    # mix human intent with whatever happened to be running, indistinguishably.
    for kategori, model, simpan in (
        ("interface", models.IntentInterface, sot_svc.simpan_interface),
        ("vlan", models.IntentVlan, sot_svc.simpan_vlan),
        ("rute", models.IntentRute, sot_svc.simpan_rute),
    ):
        exists = db.execute(select(model).where(model.device_id == d.id)
                         ).scalars().all()
        daftar = observed.get(kategori) or []
        if exists:
            hasil["dipertahankan"].append("%s (%d baris sudah ada)"
                                          % (kategori, len(exists)))
            continue
        if not daftar:
            continue
        if tulis:
            simpan(db, d.id, daftar, oleh=oleh)
        hasil[kategori] = len(daftar)

    return hasil


def main(tulis=False):
    db = database.SessionLocal()
    try:
        print("=" * 72)
        print("PAKET 0 - BENIHKAN SOURCE OF TRUTH DARI POTRET KONFIGURASI")
        print("mode: %s" % ("MENULIS" if tulis else "LAPORAN SAJA"))
        print("=" * 72)
        total = {"nilai": 0, "interface": 0, "vlan": 0, "rute": 0}
        temuan = []
        for d in db.execute(
            select(models.Device).where(models.Device.aktif == True)  # noqa: E712
        ).scalars().all():
            h = benihkan(db, d, tulis=tulis)
            if h["lewat"]:
                print("\n- %-26s LEWAT: %s" % (d.name, h["lewat"]))
                continue
            print("\n- %-26s (potret %s)" % (d.name, h.get("potret")))
            print("    nilai %d  interface %d  vlan %d  rute %d"
                  % (h["nilai"], h["interface"], h["vlan"], h["rute"]))
            if h["dipertahankan"]:
                print("    DIPERTAHANKAN (tidak ditimpa): %s"
                      % ", ".join(str(x) for x in h["dipertahankan"]))
            for reject in h.get("ditolak") or []:
                print("    [TEMUAN] kenyataan melanggar katalog: %s" % reject)
            for k in total:
                total[k] += h[k]
            for t in h.get("ditolak") or []:
                temuan.append("%s: %s" % (d.name, t))

        print("\n" + "=" * 72)
        print("TOTAL %s: nilai %d, interface %d, vlan %d, rute %d"
              % ("DITULIS" if tulis else "AKAN DITULIS",
                 total["nilai"], total["interface"], total["vlan"], total["rute"]))
        if temuan:
            print()
            print("TEMUAN KEAMANAN (kenyataan melanggar katalog, %d):" % len(temuan))
            for t in temuan:
                print("  - %s" % t)
        if not tulis:
            print("Tambahkan --tulis untuk benar-benar menyimpannya.")
        print("=" * 72)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(tulis="--tulis" in sys.argv))

"""Evaluate stored config snapshots against the compliance catalog.

    python nilai_kepatuhan.py                   show results, do not save
    python nilai_kepatuhan.py --jalankan        save to `konfig_temuan`
    python nilai_kepatuhan.py --jalankan --ulang-semua
                                                re-evaluate ALL snapshots (after the rule catalog changes)

The poller also evaluates each new snapshot itself. Safe to run while the poller is up: it
only READS `konfig_snapshots` and writes `konfig_temuan`, never touching devices.
"""
import sys
from datetime import datetime

from database import SessionLocal
from models import Device, KonfigSnapshot, KonfigTemuan
from connectors import kepatuhan


def nilai_potret(db, potret, platform, simpan=True):
    """Evaluate one snapshot and return the list of results."""
    hasil = kepatuhan.nilai(potret.teks, platform)
    if not simpan:
        return hasil
    for h in hasil:
        old = (db.query(KonfigTemuan)
                .filter(KonfigTemuan.snapshot_id == potret.id,
                        KonfigTemuan.aturan_id == h["aturan_id"])
                .first())
        if old is None:
            old = KonfigTemuan(snapshot_id=potret.id,
                                device_id=potret.device_id,
                                aturan_id=h["aturan_id"])
            db.add(old)
        old.hasil = h["hasil"]
        old.keparahan = h["keparahan"]
        old.baris_bukti = h["baris_bukti"]
        old.nomor_baris = h["nomor_baris"]
        old.dinilai = datetime.now()
    return hasil


def main():
    run = "--jalankan" in sys.argv
    retry = "--ulang-semua" in sys.argv
    db = SessionLocal()
    try:
        print("=" * 74)
        print("PENILAIAN KEPATUHAN KONFIGURASI"
              + ("" if run else "  (uji coba, tidak menyimpan)"))
        print("=" * 74)

        platform = {d.id: d.platform for d in db.query(Device).all()}
        nama = {d.id: d.name for d in db.query(Device).all()}
        potret = (db.query(KonfigSnapshot)
                  .order_by(KonfigSnapshot.id).all())
        if not potret:
            print("  Belum ada satu potret konfigurasi pun.")
            return 0

        print(f"  {len(potret)} potret, {len(kepatuhan.KATALOG)} aturan di katalog")
        print()
        print("  %-4s %-20s %-19s %8s %8s %8s %8s"
              % ("#", "perangkat", "waktu", "tinggi", "sedang", "rendah", "patuh"))
        print("  " + "-" * 82)

        for p in potret:
            already = (db.query(KonfigTemuan)
                     .filter(KonfigTemuan.snapshot_id == p.id).count())
            if already and not retry and run:
                print("  %-4s %-20s %-19s   sudah dinilai, dilewati"
                      % (p.id, nama.get(p.device_id, "?")[:20],
                         p.waktu.strftime("%d/%m %H:%M:%S")))
                continue
            hasil = nilai_potret(db, p, platform.get(p.device_id), simpan=run)
            r = kepatuhan.ringkas(hasil)
            print("  %-4s %-20s %-19s %8d %8d %8d %8d"
                  % (p.id, nama.get(p.device_id, "?")[:20],
                     p.waktu.strftime("%d/%m %H:%M:%S"),
                     r[kepatuhan.TINGGI], r[kepatuhan.SEDANG],
                     r[kepatuhan.RENDAH], r["patuh"]))
        if run:
            db.commit()

        # Findings of each device's LATEST snapshot, in detail (what the compliance page shows).
        print()
        print("  TEMUAN PADA POTRET TERAKHIR TIAP PERANGKAT")
        print("  " + "-" * 82)
        last = {}
        for p in potret:
            last[p.device_id] = p
        for did, p in last.items():
            hasil = kepatuhan.nilai(p.teks, platform.get(did))
            temuan = [h for h in hasil if h["hasil"] == kepatuhan.TEMUAN]
            temuan.sort(key=lambda h: kepatuhan.URUTAN_KEPARAHAN[h["keparahan"]])
            print(f"\n  {nama.get(did, '?')} (potret #{p.id}, "
                  f"{p.waktu.strftime('%d %b %H:%M')})")
            if not temuan:
                print("    tidak ada temuan")
            for h in temuan:
                a = kepatuhan.PETA_KATALOG[h["aturan_id"]]
                bukti = ""
                if h["baris_bukti"]:
                    bukti = f"   baris {h['nomor_baris']}: {h['baris_bukti'][:44]}"
                print("    [%-6s] %-44s%s" % (h["keparahan"], a["judul"][:44], bukti))

        if not run:
            print()
            print("  Tidak ada yang disimpan. Tambahkan --jalankan.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

r"""Re-mask stored configuration snapshots saved before the SNMP pattern was fixed.

    py samarkan_ulang_potret.py              dry run, writes nothing
    py samarkan_ulang_potret.py --jalankan   writes to the database

Why: `POLA_RAHASIA` only caught `snmp-server community X`, so a community string at the end
of a line such as `snmp-server host <ip> version 2c <community> udp-port 1162` was never
masked. The pattern is fixed, but only for NEW snapshots. Old ones still hold the raw line
(and the database goes into backups), and the next snapshot of the same device would be
masked, so the comparison would show a configuration change that never happened.

Editing stored history is acceptable here because the text should have been masked from the
start; afterwards the snapshot says exactly the same about the device minus one secret value.
The scope is strict: EVERY changed line is checked, and if any is not an `snmp-server host`
line the whole run aborts without writing anything.

Updated: `teks` + `sidik` and `teks_startup` + `sidik_startup`, always together, because
`poll_konfig()` detects changes by comparing the fingerprint. `baris_tambah`, `baris_hapus`
and `acl_berubah` are deliberately untouched: they are computed between consecutive
snapshots, and the line changes identically in ALL of them.
"""
import difflib
import os
import re
import sys
import time

import database
import models
from connectors import konfig

# Lines ALLOWED to change. Anything else aborts the whole run.
DIIZINKAN = re.compile(r"^\s*snmp-server\s+host\s+", re.I)

# A backup must be newer than this. The exact number does not matter, only that a bound exists.
UMUR_BACKUP_MAKS_JAM = 24


def backup_terbaru():
    """(path, age_hours) of the latest backup, or (None, None) if there is none."""
    import config
    folder = config.get_backup_dir()
    if not os.path.isdir(folder):
        return None, None
    zips = [os.path.join(folder, b) for b in os.listdir(folder)
            if b.endswith(".zip")]
    if not zips:
        return None, None
    baru = max(zips, key=os.path.getmtime)
    return baru, (time.time() - os.path.getmtime(baru)) / 3600.0


def samarkan_saja(teks, platform):
    """Run ONLY the masking stage of `konfig.olah()`, without `bersihkan()`.

    `olah()` runs masking, platform patterns, then cleaning. The cleaning rules were added
    later, so running them here would apply today's rules to history recorded under
    yesterday's rules. That rewrites history instead of masking a secret.
    """
    hasil = konfig.samarkan(teks)
    for pattern, replace in konfig._pola_platform(platform):
        hasil = pattern.sub(replace, hasil)
    return hasil


def periksa(lama, platform):
    """(new_text, changed_lines) or (None, None) if nothing changed."""
    baru = samarkan_saja(lama, platform)
    if baru == lama:
        return None, None
    changed = [b for b in difflib.unified_diff(
        lama.splitlines(), baru.splitlines(), lineterm="", n=0)
        if b.startswith(("+", "-")) and not b.startswith(("+++", "---"))]
    return baru, changed


def main():
    run = "--jalankan" in sys.argv
    print("=" * 74)
    print("SAMARKAN ULANG POTRET KONFIGURASI  %s"
          % ("MENULIS" if run else "LIHAT SAJA (tambahkan --jalankan untuk menulis)"))
    print("=" * 74)

    if run:
        jalur, age = backup_terbaru()
        if jalur is None:
            print("\nBERHENTI: tidak ada backup sama sekali di folder backup.")
            print("Jalankan `py backup_nsm.py` lebih dulu.")
            return 1
        print("\nBackup terbaru: %s  (%.1f jam lalu)" % (os.path.basename(jalur), age))
        if age > UMUR_BACKUP_MAKS_JAM:
            print("BERHENTI: backup terbaru sudah lebih dari %d jam."
                  % UMUR_BACKUP_MAKS_JAM)
            print("Jalankan `py backup_nsm.py` lebih dulu -- skrip ini menulis")
            print("ke riwayat lab, dan riwayat tanpa jalan pulang bukan riwayat.")
            return 1

    db = database.SessionLocal()
    try:
        baris = (db.query(models.KonfigSnapshot, models.Device)
                 .join(models.Device,
                       models.Device.id == models.KonfigSnapshot.device_id)
                 .order_by(models.KonfigSnapshot.id).all())
        print("\nPotret diperiksa: %d" % len(baris))

        plan = []
        ditolak = []

        for s, d in baris:
            for kol_text, kol_fingerprint in (("teks", "sidik"),
                                        ("teks_startup", "sidik_startup")):
                lama = getattr(s, kol_text)
                if not lama:
                    continue
                baru, changed = periksa(lama, d.platform)
                if baru is None:
                    continue
                nakal = [b for b in changed if not DIIZINKAN.match(b[1:])]
                if nakal:
                    ditolak.append((s.id, kol_text, nakal))
                else:
                    plan.append((s, kol_text, kol_fingerprint, baru, len(changed)))

        # Abort the whole run rather than skip one line: if any snapshot changes outside the allowed
        # lines, the script's assumption is wrong and it must not write partially.
        if ditolak:
            print("\nBERHENTI: %d potret akan berubah DI LUAR baris "
                  "`snmp-server host`." % len(ditolak))
            for sid, kol, nakal in ditolak[:5]:
                print("  potret #%s kolom %s:" % (sid, kol))
                for b in nakal[:4]:
                    print("      %s" % b[:96])
            print("\nTidak ada satu baris pun ditulis. Periksa dulu kenapa")
            print("penyamarannya menyentuh baris lain.")
            return 1

        if not plan:
            print("\nTidak ada yang perlu diubah. Semua potret sudah tersamar.")
            return 0

        print("\nYang akan diubah:")
        print("  %-6s %-26s %-14s %s" % ("id", "perangkat", "kolom", "baris"))
        print("  " + "-" * 62)
        peta = {d.id: d.name for _s, d in baris}
        for s, kol, _ks, _baru, n in plan:
            print("  %-6s %-26s %-14s %d" % (s.id, peta.get(s.device_id, "?")[:26], kol, n))

        example = plan[0]
        old_line = [b for b in difflib.unified_diff(
            getattr(example[0], example[1]).splitlines(), example[3].splitlines(),
            lineterm="", n=0) if b.startswith(("+", "-"))
            and not b.startswith(("+++", "---"))]
        print("\nContoh perubahan (potret #%s):" % example[0].id)
        for b in old_line[:4]:
            print("  %s" % b[:96])

        if not run:
            print("\n" + "=" * 74)
            print("TIDAK ADA YANG DITULIS. Jalankan lagi dengan --jalankan")
            print("sesudah memastikan daftar di atas memang yang kamu maksud.")
            print("=" * 74)
            return 0

        for s, kol_text, kol_fingerprint, baru, _n in plan:
            setattr(s, kol_text, baru)
            setattr(s, kol_fingerprint, konfig.sidik(baru))
        db.commit()
        print("\n%d kolom diperbarui." % len(plan))

        # Re-verified from the database, not assumed.
        db.expire_all()
        remaining = 0
        for s, d in (db.query(models.KonfigSnapshot, models.Device)
                     .join(models.Device,
                           models.Device.id == models.KonfigSnapshot.device_id).all()):
            for kol in ("teks", "teks_startup"):
                t = getattr(s, kol)
                if t and samarkan_saja(t, d.platform) != t:
                    remaining += 1
        if remaining:
            print("PERINGATAN: masih ada %d kolom yang belum tersamar." % remaining)
            return 1
        print("Diperiksa ulang: tidak ada lagi potret yang belum tersamar.")
        print("\nJALANKAN BACKUP LAGI (see docs/BACKUP.md) -- isi basis data berubah.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

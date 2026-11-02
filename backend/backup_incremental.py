"""Incremental NSM backup: one parent archive that is OVERWRITTEN each round,
plus weekly and monthly copies. See `docs/design/INCREMENTAL-BACKUP.md` for the
full design and measurements.

This is separate from `backup_nsm.py` (daily full backup), which is unchanged
and still runs. The old method must stay in place and proven until the new one
has been shown to restore correctly (see `uji_pulih_incremental.py`).

Design:
    TABEL_INCREMENTAL  large append-only time-series tables. Each round dumps
                       only the new rows (`id > last position`, not a time
                       column; see the comment on TABEL_INCREMENTAL) and
                       appends them to the accumulated file in the parent.
    All other tables   full dump every time. They can be UPDATED, not just
                       appended to, so a time-based incremental would
                       silently miss their changes.

    induk.zip           single file, overwritten every round
    induk-mingguan.zip  copy of the parent, refreshed when >= 7 days old
    induk-bulanan.zip   copy of the parent, refreshed when >= 30 days old

`induk.zip` alone is one restore point (the latest state). The weekly and
monthly copies give several restore points without the storage cost of the
old 14-copy full-backup rotation (about 320 MB per location vs. 3 files).

Manual run:
    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\activate
    python backup_incremental.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime

import config
import database
import sandi_backup
from backup_nsm import _berkas_kredensial, _buang, find_tool, ukuran_mb

# (table, marker_column). Only LARGE append-only time-series tables belong here:
# once written, a row never changes. Tables that can be UPDATED (devices,
# device_events, ...) are excluded on purpose.
#
# Kept separate from `pangkas_data.TABEL`: that list answers "how long to
# retain", this one "what needs incremental backup". `penolakan_acl` is
# append-only and never pruned by time, so it appears only here.
#
# Why `id` and not a time column: for `status_logs`, `bandwidth_samples`, and
# `service_checks` the time is `datetime.now()` at write, which is safe. But
# `akses_web`, `flow_koneksi`, and `penolakan_acl` store the EVENT time from the
# source log, and MySQL can record a row minutes after that time when the poller
# is catching up on a large log. A row with `waktu` before the cut can be
# committed AFTER a round runs; the next round's `waktu > old_cut` filter then
# skips it forever.
#
# `id` (MySQL auto-increment) is assigned at commit, so `id <= new_id` read
# BEFORE the dump always means "every committed row so far". An uncommitted row
# cannot already have an id <= new_id (the counter never goes back), so a row
# that commits during the cutoff simply joins the next round.
TABEL_INCREMENTAL = [
    ("status_logs", "id"),
    ("bandwidth_samples", "id"),
    ("service_checks", "id"),
    ("akses_web", "id"),
    ("flow_koneksi", "id"),
    ("penolakan_acl", "id"),
]

NAMA_INDUK = "induk.zip"
NAMA_META = "induk.meta.json"
HARI_MINGGUAN = 7
HARI_BULANAN = 30

gagal = []


def log(teks):
    print(teks)


def _folder_induk():
    return os.path.join(config.get_backup_dir(), "incremental")


def _baca_meta(folder):
    jalur = os.path.join(folder, NAMA_META)
    if not os.path.exists(jalur):
        return None
    with open(jalur, encoding="utf-8") as f:
        return json.load(f)


def _tulis_meta(folder, meta):
    jalur = os.path.join(folder, NAMA_META)
    with open(jalur, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def _dump_tabel(kerja, user, sandi, nama_db, host, port,
                nama_tabel, nama_berkas, where=None, dengan_skema=True):
    tool = find_tool("mysqldump.exe", config.get_mysqldump_path())
    if not tool:
        gagal.append("mysqldump tidak ditemukan")
        return None
    cnf = _berkas_kredensial(user, sandi, host, port)
    keluar = os.path.join(kerja, nama_berkas)
    try:
        perintah = [tool, f"--defaults-extra-file={cnf}",
                   "--single-transaction", "--set-gtid-purged=OFF",
                   "--skip-masking-policies", "--no-tablespaces",
                   "--skip-routines", "--skip-events"]
        if not dengan_skema:
            perintah += ["--no-create-info", "--skip-add-drop-table",
                        "--skip-comments"]
        if where:
            perintah += ["--where=" + where]
        perintah += [nama_db, nama_tabel]
        with open(keluar, "wb") as f:
            p = subprocess.run(perintah, stdout=f, stderr=subprocess.PIPE,
                               timeout=300)
        if p.returncode != 0:
            message = p.stderr.decode("utf-8", "replace")[:200].strip()
            gagal.append(f"{nama_tabel}: {message}")
            log(f"  [GAGAL] {nama_tabel}: {message}")
            _buang(keluar)
            return None
        return keluar
    finally:
        try:
            os.unlink(cnf)
        except OSError:
            pass


def _klausa_where(kolom, titik_lama, titik_baru, bootstrap):
    """Build the WHERE clause for one dump round, bounded ABOVE by `titik_baru` and
    BELOW by the old position.

    `kolom` is always `id` (see TABEL_INCREMENTAL), so the points are max-id
    integers and are written without quotes.

    The upper bound is required: `titik_baru` is recorded BEFORE the dump runs,
    but mysqldump takes seconds to tens of seconds, so rows arriving in that
    window would land in this round AND the next (which filters `> titik_lama`),
    giving duplicate primary keys on restore. With both bounds each round is an
    adjacent window: (a, b], then (b, c], with no gap and no overlap.
    """
    if bootstrap:
        return f"{kolom} <= {titik_baru}"
    return f"{kolom} > {titik_lama} AND {kolom} <= {titik_baru}"


def _id_maksimum(nama_db, tabel):
    from sqlalchemy import text
    db = database.SessionLocal()
    try:
        hasil = db.execute(text(f"SELECT MAX(id) FROM `{tabel}`")).scalar()
        return int(hasil) if hasil is not None else 0
    finally:
        db.close()


def _dump_semua_tabel_lain(kerja, user, sandi, nama_db, host, port):
    """Full dump of every `nsm` table NOT in TABEL_INCREMENTAL, in one mysqldump call
    (they are small). The table list is read from `information_schema` at run
    time, so a newly added table is backed up in full by default instead of being
    silently missed.
    """
    from sqlalchemy import text
    db = database.SessionLocal()
    try:
        semua = [r[0] for r in db.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = :db"), {"db": nama_db}).all()]
    finally:
        db.close()
    name_incr = {t for t, _ in TABEL_INCREMENTAL}
    other = sorted(set(semua) - name_incr)
    if not other:
        return None, []
    tool = find_tool("mysqldump.exe", config.get_mysqldump_path())
    if not tool:
        gagal.append("mysqldump tidak ditemukan")
        return None, other
    cnf = _berkas_kredensial(user, sandi, host, port)
    keluar = os.path.join(kerja, "_lain_full.sql")
    try:
        perintah = [tool, f"--defaults-extra-file={cnf}",
                   "--single-transaction", "--set-gtid-purged=OFF",
                   "--skip-masking-policies", "--no-tablespaces",
                   "--skip-routines", "--skip-events",
                   nama_db] + other
        with open(keluar, "wb") as f:
            p = subprocess.run(perintah, stdout=f, stderr=subprocess.PIPE,
                               timeout=300)
        if p.returncode != 0:
            message = p.stderr.decode("utf-8", "replace")[:200].strip()
            gagal.append("tabel lain (full): " + message)
            log("  [GAGAL] tabel lain: " + message)
            _buang(keluar)
            return None, other
        return keluar, other
    finally:
        try:
            os.unlink(cnf)
        except OSError:
            pass


def _gabungkan_ke_induk(folder, kerja_baru, bootstrap):
    """Core of "overwrite, don't append": open the OLD parent (if any), append the
    new delta to each incremental table's accumulated file, REPLACE the files of
    the full-every-time tables, then rewrite induk.zip from scratch in the same
    location.

    `kerja_baru` holds only this round's dump results (delta for incremental
    tables, full for the others), not the accumulation.
    """
    jalur_induk = os.path.join(folder, NAMA_INDUK)
    akumulasi = tempfile.mkdtemp(prefix="induk_gabung_")
    try:
        if not bootstrap and os.path.exists(jalur_induk):
            with zipfile.ZipFile(jalur_induk) as z:
                z.extractall(akumulasi)

        for nama in os.listdir(kerja_baru):
            source = os.path.join(kerja_baru, nama)
            destination = os.path.join(akumulasi, nama)
            table_incr = any(nama == f"{t}.sql" for t, _ in TABEL_INCREMENTAL)
            if table_incr and not bootstrap and os.path.exists(destination):
                with open(destination, "a", encoding="utf-8") as keluar, \
                     open(source, encoding="utf-8") as enter:
                    keluar.write("\n")
                    shutil.copyfileobj(enter, keluar)
            else:
                shutil.copy2(source, destination)

        file_new = os.path.join(folder, NAMA_INDUK + ".baru")
        with zipfile.ZipFile(file_new, "w", zipfile.ZIP_DEFLATED) as z:
            for nama in sorted(os.listdir(akumulasi)):
                z.write(os.path.join(akumulasi, nama), nama)

        # Atomic replace: write to `.baru` first, then overwrite the real name. If the
        # process dies mid-zip (power loss), the OLD parent stays intact.
        os.replace(file_new, jalur_induk)
        return jalur_induk
    finally:
        shutil.rmtree(akumulasi, ignore_errors=True)


def _salin_terjadwal(folder, jalur_induk, nama_sub, hari_ambang, meta_induk):
    sub = os.path.join(folder, nama_sub)
    os.makedirs(sub, exist_ok=True)
    meta_path = os.path.join(sub, "meta.json")
    terakhir = None
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            terakhir = datetime.fromisoformat(json.load(f)["terakhir"])
    sekarang = datetime.now()
    if terakhir and (sekarang - terakhir).days < hari_ambang:
        return None
    destination = os.path.join(sub, f"induk-{nama_sub}.zip")
    shutil.copy2(jalur_induk, destination)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"terakhir": sekarang.isoformat()}, f, indent=2)
    log(f"  Salinan {nama_sub} diperbarui: {ukuran_mb(destination):.1f} MB")
    return destination


def main():
    start = datetime.now()
    print("=" * 70)
    print(f"BACKUP INCREMENTAL NSM  {start:%d %B %Y %H:%M:%S}")
    print("=" * 70)

    if not database.PAKAI_MYSQL:
        log("BERHENTI: backup incremental hanya untuk MySQL (NSM sedang "
            "memakai SQLite). Jalankan backup_nsm.py biasa.")
        return 1

    folder = _folder_induk()
    os.makedirs(folder, exist_ok=True)
    meta = _baca_meta(folder)
    bootstrap = meta is None
    position_old = (meta or {}).get("posisi", {})

    if bootstrap:
        log("Belum ada induk sebelumnya -- BOOTSTRAP (dump penuh sekali, "
            "putaran berikutnya baru benar-benar incremental).")
    else:
        log("Posisi id terakhir: " +
            ", ".join(f"{t}={position_old.get(t, 0)}" for t, _ in TABEL_INCREMENTAL))

    env = database.ENV
    user_nsm = env.get("NSM_DB_USER", "nsm_app")
    password_nsm = env.get("NSM_DB_PASS", "")
    db_nsm = env.get("NSM_DB_NAME", "nsm")
    host_nsm = env.get("NSM_DB_HOST", "")
    port_nsm = env.get("NSM_DB_PORT", "3306")

    position_new = {}
    with tempfile.TemporaryDirectory(prefix="backup_incr_") as kerja:
        log("\nMengumpulkan tabel INCREMENTAL:")
        for tabel, kolom in TABEL_INCREMENTAL:
            id_old = position_old.get(tabel, 0)
            id_new = _id_maksimum(db_nsm, tabel)
            position_new[tabel] = id_new
            where = _klausa_where(kolom, id_old, id_new, bootstrap)
            hasil = _dump_tabel(
                kerja, user_nsm, password_nsm, db_nsm, host_nsm, port_nsm,
                tabel, f"{tabel}.sql", where=where,
                dengan_skema=bootstrap)
            if hasil:
                n = sum(1 for _ in open(hasil, encoding="utf-8", errors="replace")
                       if _.startswith("INSERT INTO"))
                log(f"  {tabel:<20} {ukuran_mb(hasil):6.2f} MB  "
                    f"({n} baris baru)" if not bootstrap else
                    f"  {tabel:<20} {ukuran_mb(hasil):6.2f} MB  (penuh, bootstrap)")

        log("\nTabel LAIN (full setiap kali -- bisa berubah, bukan cuma bertambah):")
        _result_other, list_other = _dump_semua_tabel_lain(
            kerja, user_nsm, password_nsm, db_nsm, host_nsm, port_nsm)
        if _result_other:
            log(f"  {len(list_other)} tabel ({', '.join(list_other[:6])}"
               f"{'…' if len(list_other) > 6 else ''})  "
               f"{ukuran_mb(_result_other):.2f} MB")

        log("\nAkun & audit (Java, tetap full setiap kali):")
        from backup_nsm import backup_mysql, export_audit_csv
        # `terbatas=True` is REQUIRED here, for the same reason as in `backup_nsm.py`.
        # Without it mysqldump runs `SHOW EVENTS`, which needs the `EVENT` privilege
        # that `nsm_app` does not have (and should not: the backup account needs no
        # administrative rights). That single denial aborts the WHOLE dump, so the
        # `nsm_auth` database (accounts, password hashes, roles, notification
        # subscriptions) silently goes missing from the backup.
        #
        # The server has zero scheduled events, so nothing real is skipped. Granting
        # `EVENT` would also "fix" it but is the wrong fix: widening an account's access
        # to copy something that does not exist.
        backup_mysql(kerja, terbatas=True)
        export_audit_csv(kerja)

        if not os.listdir(kerja):
            log("\nTidak ada satu pun berkas berhasil dibuat -- berhenti.")
            return 1

        jalur_induk = _gabungkan_ke_induk(folder, kerja, bootstrap)

    _tulis_meta(folder, {
        "posisi": position_new,
        "diperbarui": datetime.now().isoformat(),
        "bootstrap_pada": (meta or {}).get("bootstrap_pada")
                          or (start.isoformat() if bootstrap else None),
    })

    log(f"\nInduk diperbarui: {NAMA_INDUK}  {ukuran_mb(jalur_induk):.1f} MB")

    log("\nMemeriksa salinan berkala:")
    _salin_terjadwal(folder, jalur_induk, "mingguan", HARI_MINGGUAN, meta)
    _salin_terjadwal(folder, jalur_induk, "bulanan", HARI_BULANAN, meta)

    folder_secondary = config.get_backup_dir2()
    if folder_secondary:
        sandi = sandi_backup.frasa_sandi()
        destination_base = os.path.join(folder_secondary, "incremental")
        os.makedirs(destination_base, exist_ok=True)
        for label, source in [("induk", jalur_induk)]:
            if not os.path.exists(source):
                continue
            try:
                if sandi:
                    destination = os.path.join(destination_base, f"{label}.zip.enc")
                    sandi_backup.enkripsi(source, destination, sandi)
                    log(f"  {label}.zip.enc disalin terenkripsi ke lokasi kedua")
                else:
                    destination = os.path.join(destination_base, f"{label}.zip")
                    shutil.copy2(source, destination)
                    log(f"  [PERINGATAN] {label}.zip disalin TANPA ENKRIPSI")
                    gagal.append(f"{label}: salinan kedua belum dienkripsi")
            except Exception as e:
                gagal.append(f"{label}: salinan kedua gagal ({e})")
                log(f"  [GAGAL] {label} ke lokasi kedua: {e}")
    else:
        log("  Lokasi kedua belum diatur (BACKUP_DIR2 di .env).")

    old = round((datetime.now() - start).total_seconds(), 1)

    # Write the manifest here too. The Backup page's history table is built from
    # `manifest.log`; without this it would freeze silently, showing stale rows
    # while real backups keep running. A stale history is more misleading than an
    # empty one.
    try:
        from backup_nsm import tulis_manifest as _tulis_manifest
        _tulis_manifest(config.get_backup_dir(), NAMA_INDUK, start, not gagal)
    except Exception as e:                          # noqa: BLE001
        log(f"  [PERINGATAN] manifest.log tidak bisa ditulis: {e}")

    # Report to NSM from here, not through a separate scheduled task.
    #
    # The Backup monitor page on nsm-app (Linux) cannot inspect `C:\...` folders,
    # so it shows the REPORT sent by this machine; a report older than 26 hours is
    # marked stale and the page turns unhealthy. Calling it here guarantees the
    # report reflects the backup that just ran (a separate task could run before
    # the backup and report yesterday's state with today's timestamp), and creating
    # a new scheduled task would need admin rights.
    try:
        import lapor_backup
        lapor_backup.lapor(cetak=False)
        log("  Laporan keadaan backup dikirim ke NSM.")
    except Exception as e:                          # noqa: BLE001
        gagal.append(f"laporan ke NSM gagal terkirim ({e})")
        log(f"  [GAGAL] laporan ke NSM: {e}")

    print("\n" + "=" * 70)
    if gagal:
        print(f"SELESAI DENGAN CATATAN ({old} dtk): {'; '.join(gagal)}")
    else:
        print(f"SUKSES ({old} dtk), tanpa kendala.")
    print("=" * 70)
    return 1 if gagal else 0


if __name__ == "__main__":
    sys.exit(main())

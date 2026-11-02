"""Automatic NSM backup, run by Windows Task Scheduler daily at 02:00.

What is backed up:
  1. nsm.sql       devices, ping history, UP/DOWN transitions, bandwidth
                   (MySQL database `nsm` on 192.168.56.103)
  2. nsm_auth.sql  accounts, audit log, blocked IPs (MySQL on this machine)
  3. audit_logs    CSV copy, human-readable, opens in Excel

Item 1 used to be the SQLite file `nsm.db`. After the data moved to MySQL,
copying that file still SUCCEEDED while storing no new rows, so the real
database is dumped now. `backup_sqlite()` below is only used if NSM is moved
back to SQLite.

Everything is packed into ONE dated .zip, copied to a second location if
configured, and backups beyond the retention count are deleted.

Three things are done carefully:

* Copying nsm.db while the poller writes. A plain copy can capture a
  half-written transaction (it looks fine and is broken when needed). The
  official SQLite backup API (`sqlite3.Connection.backup`) is safe with an
  active writer.

* The MySQL password never appears on the command line, where anyone listing
  processes could read it. A temporary `--defaults-extra-file` is used and
  deleted right after.

* A partial failure is not a total failure. If mysqldump is missing, the
  SQLite backup is still completed and reported as-is. A half backup is far
  more useful than none.

Manual run:
    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\activate
    python backup_nsm.py
"""
import csv
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime

import config
import database
import sandi_backup

DIR = os.path.dirname(os.path.abspath(__file__))
DB_SQLITE = os.path.join(DIR, "nsm.db")
AWALAN = "nsm-backup-"

catatan = []
gagal = []


def log(teks):
    print(teks)
    catatan.append(teks)


def periksa_lokasi_kedua(folder_utama, folder_kedua):
    """(real, message): is the second location REALLY a second copy?

    The whole design rests on "a backup on the same disk as the data is not a
    backup", so the second location points at a cloud-sync folder to move the
    files off the machine. This check exists because that folder may be a plain
    folder on the SAME disk: no sync client installed, no account signed in, the
    encrypted files are ordinary local files, and the machine has one physical
    disk. The copy is real as a file but not as protection; if the disk dies, the
    VM, the database, and both backups go together.

    The danger is the BELIEF that a second copy exists. This check does not stop
    the backup; it only refuses to stay silent.
    """
    if not folder_kedua:
        return False, ("Lokasi kedua belum diatur. Seluruh backup hanya ada "
                       "di satu tempat.")
    try:
        a = os.path.splitdrive(os.path.abspath(folder_utama))[0].upper()
        b = os.path.splitdrive(os.path.abspath(folder_kedua))[0].upper()
    except Exception:
        return True, "Lokasi kedua tidak bisa diperiksa; dianggap terpisah."

    if a and b and a == b:
        message = ("Lokasi kedua ada di DISK YANG SAMA (%s) dengan lokasi "
                 "utama. Ini bukan salinan kedua: kalau disk itu mati, "
                 "keduanya hilang bersamaan." % a)
        if "onedrive" in folder_kedua.lower() and not _onedrive_hidup():
            message += (" Jalurnya menyebut OneDrive, tetapi OneDrive TIDAK "
                      "terpasang/berjalan di mesin ini -- jadi tidak ada satu "
                      "berkas pun yang benar-benar terunggah.")
        return False, message
    return True, "Lokasi kedua berada di disk yang berbeda (%s vs %s)." % (a, b)


def _onedrive_hidup():
    jalur = [
        os.path.join(os.environ.get("ProgramFiles", ""),
                     "Microsoft OneDrive", "OneDrive.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Microsoft", "OneDrive", "OneDrive.exe"),
    ]
    if not any(j and os.path.exists(j) for j in jalur):
        return False
    try:
        import subprocess
        # `encoding` and `errors` are required, and the `or ""` below hides their
        # absence: with a non-English `tasklist` locale, `stdout` becomes None, `or ""`
        # turns it into an empty string, and the answer becomes "not running", so the
        # backup would run exactly while the files are syncing.
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq OneDrive.exe"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20)
        return "OneDrive.exe" in (r.stdout or "")
    except Exception:
        return False


def ukuran_mb(path):
    try:
        return os.path.getsize(path) / 1024 / 1024
    except OSError:
        return 0.0


# ---------------------------------------------------------------------------
# 1. SQLite — salinan aman + pemeriksaan integritas
# ---------------------------------------------------------------------------
def backup_sqlite(tujuan):
    if not os.path.exists(DB_SQLITE):
        gagal.append("nsm.db tidak ditemukan")
        log(f"  [GAGAL] {DB_SQLITE} tidak ditemukan")
        return None

    source = sqlite3.connect(DB_SQLITE)
    copy_of = sqlite3.connect(tujuan)
    try:
        with copy_of:
            source.backup(copy_of)          # aman walau poller sedang menulis
    finally:
        source.close()
        copy_of.close()

    check = sqlite3.connect(tujuan)
    try:
        hasil = check.execute("PRAGMA integrity_check").fetchone()[0]
        count_device = check.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
        count_log = check.execute("SELECT COUNT(*) FROM status_logs").fetchone()[0]
        count_ev = check.execute("SELECT COUNT(*) FROM device_events").fetchone()[0]
    finally:
        check.close()

    if hasil != "ok":
        gagal.append(f"integritas nsm.db: {hasil}")
        log(f"  [GAGAL] pemeriksaan integritas: {hasil}")
        return None

    log(f"  nsm.db      OK  {ukuran_mb(tujuan):.1f} MB  "
        f"(device={count_device}, status_logs={count_log:,}, event={count_ev})")
    return tujuan


def _berkas_kredensial(user, sandi, host, port):
    f = tempfile.NamedTemporaryFile("w", suffix=".cnf", delete=False,
                                    encoding="utf-8")
    f.write("[client]\n")
    f.write(f"user={user}\n")
    if sandi:
        f.write(f"password={sandi}\n")
    f.write(f"host={host}\nport={port}\n")
    f.close()
    return f.name


def _buang(jalur):
    try:
        if jalur and os.path.exists(jalur):
            os.unlink(jalur)
    except OSError:
        pass


def find_tool(nama, dari_config):
    if dari_config and os.path.exists(dari_config):
        return dari_config
    location = shutil.which(nama)
    if location:
        return location
    # Common MySQL install locations on Windows
    for pattern in (r"C:\Program Files\MySQL",):
        if not os.path.isdir(pattern):
            continue
        for root_cause, _dirs, file in os.walk(pattern):
            if nama in file:
                return os.path.join(root_cause, nama)
    return None


def backup_mysql(folder, user=None, sandi=None, nama_db=None,
                 host=None, port=None, label=None, terbatas=False):
    if user is None:
        user, sandi, nama_db, host, port = config.get_mysql_config()
    tool = find_tool("mysqldump.exe", config.get_mysqldump_path())
    if not tool:
        gagal.append("mysqldump tidak ditemukan")
        log("  [LEWAT] mysqldump tidak ditemukan — dump MySQL dilewati.")
        log("          Isi MYSQLDUMP_PATH di .env atau tambahkan MySQL ke PATH.")
        return None

    cnf = _berkas_kredensial(user, sandi, host, port)
    keluar = os.path.join(folder, f"{label or nama_db}.sql")
    try:
        with open(keluar, "wb") as f:
            proses = subprocess.run(
                [tool, f"--defaults-extra-file={cnf}",
                 "--single-transaction",
                 # Required for a restorable dump. With GTID enabled, mysqldump emits
                 # `SET @@GLOBAL.GTID_PURGED=...`; restoring to the SAME server then fails with
                 # ERROR 3546 (the GTID set overlaps `@@GLOBAL.GTID_EXECUTED`), and restoring to
                 # the same server is the most likely scenario. The statement only helps when
                 # this server is a replication source; in this single-machine lab it is purely
                 # an obstacle.
                 "--set-gtid-purged=OFF",
                 # Required for the `nsm` dump to be accepted. mysqldump 9.7 also copies
                 # "masking policies" from the `mysql` schema. `nsm_app` deliberately has rights
                 # only on the `nsm` database, so that request is denied
                 # (`SELECT command denied ... column_masking_policy`) and the WHOLE dump fails.
                 # The fix is not to grant access to the `mysql` schema but to stop asking for
                 # something unused: there are no masking policies.
                 #
                 # Same principle for two more privileges that are deliberately not granted:
                 # `--no-tablespaces` (listing tablespaces needs the server-wide PROCESS
                 # privilege, which would let the monitoring account see everyone's queries) and
                 # `--skip-events` (`SHOW EVENTS` needs EVENT). The NSM schema is created by
                 # SQLAlchemy and has no tablespaces, events, or stored routines, so nothing is
                 # lost.
                 "--skip-masking-policies",
                 "--no-tablespaces",
                 "--routines" if not terbatas else "--skip-routines",
                 "--events" if not terbatas else "--skip-events",
                 "--databases", nama_db],
                stdout=f, stderr=subprocess.PIPE, timeout=300,
            )
        if proses.returncode != 0:
            message = proses.stderr.decode(errors="replace").strip()[:200]
            gagal.append(f"mysqldump gagal: {message}")
            log(f"  [GAGAL] mysqldump: {message}")
            _buang(keluar)
            return None
        if os.path.getsize(keluar) < 1024:
            gagal.append(f"{label or nama_db}.sql terlalu kecil "
                         f"({os.path.getsize(keluar)} byte)")
            log(f"  [GAGAL] {label or nama_db}.sql cuma "
                f"{os.path.getsize(keluar)} byte — tidak memuat satu tabel pun")
            _buang(keluar)
            return None

        # Every live table must be present in the dump. A dump that is complete for
        # yesterday's schema is incomplete for today's (for example, tables added by a
        # migration after the last backup). Nothing outside shows it: exit code 0,
        # plausible size, manifest SUCCESS; only a restore test reveals it.
        #
        # This is NOT a total failure. A dump with 36 of 38 tables is worth keeping, so
        # the file is kept and only the verdict changes: the backup is PARTIAL and the
        # manifest names the missing tables.
        less = _tabel_hilang_dari_dump(keluar, nama_db, cnf)
        if less:
            gagal.append("%s.sql tidak memuat %d tabel: %s"
                         % (label or nama_db, len(less), ", ".join(less)))
            log("  [BOLONG] %s.sql tidak memuat %d tabel yang hidup: %s"
                % (label or nama_db, len(less), ", ".join(less)))
            log("           Jalankan lagi backup ini; kalau tetap kurang, "
                "periksa hak akses akun backup atas tabel tersebut.")

        log(f"  {label or nama_db}.sql  OK  {ukuran_mb(keluar):.2f} MB")
        return keluar
    except subprocess.TimeoutExpired:
        gagal.append("mysqldump kehabisan waktu")
        log("  [GAGAL] mysqldump kehabisan waktu (300 detik)")
        return None
    finally:
        try:
            os.unlink(cnf)
        except OSError:
            pass


def _tabel_hilang_dari_dump(jalur_dump, nama_db, cnf):
    """Live tables that have no `CREATE TABLE` in the dump file.

    The live table list comes from `mysql.exe`, not SQLAlchemy: this runs from a
    scheduled task, and the ORM is kept out of the backup path (one dependency
    fewer where failure matters most).

    The tool is looked up here, not passed in by the caller: a caller once passed
    `mysqldump.exe`, which does not accept `-e "SELECT ..."`, and the completeness
    check silently stopped checking.

    Returns [] when the check itself cannot run, after saying so. A failure to
    MEASURE must not accuse a backup that was never checked, and it must not be
    answered with an unexplained "zero tables missing".
    """
    try:
        import periksa_dump
        tool = find_tool("mysql.exe", config.get_mysql_path())
        if not tool:
            log("  [CATATAN] mysql.exe tidak ditemukan; kelengkapan dump "
                "tidak diperiksa kali ini")
            return []
        r = subprocess.run(
            [tool, f"--defaults-extra-file={cnf}", "-N", "-B", "-e",
             "SELECT table_name FROM information_schema.tables "
             f"WHERE table_schema='{nama_db}' AND table_type='BASE TABLE'"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        if r.returncode != 0 or not r.stdout.strip():
            log("  [CATATAN] daftar tabel hidup tidak terbaca; kelengkapan "
                "dump tidak diperiksa kali ini")
            return []
        alive = {b.strip() for b in r.stdout.splitlines() if b.strip()}
        missing, berlebih = periksa_dump.bandingkan(jalur_dump, alive)
        if berlebih:
            log("  [CATATAN] %d tabel ada di dump tetapi sudah tidak hidup: %s"
                % (len(berlebih), ", ".join(berlebih)))
        return missing
    except Exception as e:                      # noqa: BLE001
        log("  [CATATAN] pemeriksaan kelengkapan dump gagal dijalankan: %s"
            % e)
        return []


def export_audit_csv(folder):
    """audit_logs -> CSV. The .sql dump is for restoring; the CSV is for humans."""
    user, sandi, nama_db, host, port = config.get_mysql_config()
    tool = find_tool("mysql.exe", config.get_mysql_path())
    if not tool:
        gagal.append("mysql.exe tidak ditemukan")
        log("  [LEWAT] mysql.exe tidak ditemukan — export audit CSV dilewati.")
        return None

    cnf = _berkas_kredensial(user, sandi, host, port)
    keluar = os.path.join(folder, "audit_logs.csv")
    try:
        proses = subprocess.run(
            [tool, f"--defaults-extra-file={cnf}", "--batch", "--raw",
             nama_db, "-e", "SELECT * FROM audit_logs ORDER BY id"],
            capture_output=True, timeout=300,
        )
        if proses.returncode != 0:
            message = proses.stderr.decode(errors="replace").strip()[:200]
            gagal.append(f"export audit gagal: {message}")
            log(f"  [GAGAL] export audit: {message}")
            return None

        teks = proses.stdout.decode("utf-8", errors="replace")
        baris = [b for b in teks.split("\n") if b.strip() != ""]
        with open(keluar, "w", newline="", encoding="utf-8-sig") as f:
            penulis = csv.writer(f)
            for b in baris:
                penulis.writerow([
                    column.replace("\\n", "\n").replace("\\t", "\t")
                    for column in b.rstrip("\r").split("\t")
                ])
        count = max(0, len(baris) - 1)
        log(f"  audit_logs.csv  OK  {count:,} baris")
        return keluar
    except subprocess.TimeoutExpired:
        gagal.append("export audit kehabisan waktu")
        log("  [GAGAL] export audit kehabisan waktu")
        return None
    finally:
        try:
            os.unlink(cnf)
        except OSError:
            pass


def rotasi(folder, simpan):
    if not os.path.isdir(folder):
        return
    # `.enc` files are included, not only `.zip`. Since the second copy is
    # encrypted its name ends in `.zip.enc`; a filter that accepts only `.zip` would
    # silently stop rotation there (no error, old backups pile up until the cloud
    # quota fills, which then blocks the NEXT backup).
    file = sorted(
        [f for f in os.listdir(folder)
         if f.startswith(AWALAN) and (f.endswith(".zip") or f.endswith(".zip.enc"))]
    )
    discard = file[:-simpan] if len(file) > simpan else []
    for b in discard:
        try:
            os.remove(os.path.join(folder, b))
            log(f"  rotasi: {b} dihapus")
        except OSError as e:
            log(f"  rotasi: gagal menghapus {b} ({e})")


def tulis_manifest(folder, nama_zip, mulai, sukses):
    old = (datetime.now() - mulai).total_seconds()
    status = "SUKSES" if sukses else ("SEBAGIAN" if nama_zip else "GAGAL")
    baris = (f"{mulai:%Y-%m-%d %H:%M:%S}  {status:<9} {nama_zip or '-':<32} "
             f"{old:6.1f} dtk  {'; '.join(gagal) if gagal else 'tanpa kendala'}")
    try:
        with open(os.path.join(folder, "manifest.log"), "a",
                  encoding="utf-8") as f:
            f.write(baris + "\n")
    except OSError:
        pass
    return baris


def main():
    mulai = datetime.now()
    stamp = mulai.strftime("%Y%m%d_%H%M%S")
    folder_utama = config.get_backup_dir()
    folder_kedua = config.get_backup_dir2()
    simpan = config.get_backup_keep()

    print("=" * 70)
    print(f"BACKUP NSM  {mulai:%d %B %Y %H:%M:%S}")
    print("=" * 70)
    os.makedirs(folder_utama, exist_ok=True)

    with tempfile.TemporaryDirectory() as work:
        log("Mengumpulkan data:")

        if database.PAKAI_MYSQL:
            env = database.ENV
            backup_mysql(work,
                         user=env.get("NSM_DB_USER"),
                         sandi=env.get("NSM_DB_PASS"),
                         nama_db=env.get("NSM_DB_NAME", "nsm"),
                         host=env.get("NSM_DB_HOST"),
                         port=env.get("NSM_DB_PORT", "3306"),
                         terbatas=True)
            log("  (nsm.db tidak lagi ikut: sejak 12 Agustus ia bukan basis "
                "data yang dipakai, hanya salinan riwayat sebelum pindah)")
        else:
            backup_sqlite(os.path.join(work, "nsm.db"))

        # ACCOUNTS and AUDIT owned by Spring, in the MySQL on this machine.
        #
        # `terbatas=True` is required: mysqldump runs `SHOW EVENTS` by default, which
        # needs the `EVENT` privilege that `nsm_app` lacks (and should lack: the backup
        # account needs no administrative rights). That single denial aborted the whole
        # `nsm_auth` dump, silently dropping accounts, password hashes, roles, and
        # notification subscriptions from the archive. `nsm_auth` has zero events,
        # routines, and triggers, so nothing real is skipped. Granting `EVENT` would also
        # work but is the wrong fix: widening an account's access to copy something that
        # does not exist.
        backup_mysql(work, terbatas=True)
        export_audit_csv(work)

        content = os.listdir(work)
        if not content:
            log("  tidak ada satu pun berkas berhasil dibuat")
            baris = tulis_manifest(folder_utama, None, mulai, False)
            print("\n" + baris)
            return 1

        nama_zip = f"{AWALAN}{stamp}.zip"
        path_zip = os.path.join(folder_utama, nama_zip)
        with zipfile.ZipFile(path_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for file in content:
                z.write(os.path.join(work, file), file)
        log(f"\nDibungkus: {nama_zip}  {ukuran_mb(path_zip):.1f} MB  "
            f"({len(content)} berkas)")

    # Second copy: the point of "a backup on the same disk is not a backup".
    # ENCRYPTED when the passphrase is set, and CHECKED rather than assumed; see
    # `periksa_lokasi_kedua()`.
    real_secondary, message_secondary = periksa_lokasi_kedua(folder_utama,
                                                        folder_kedua)
    if not real_secondary:
        # Recorded, but does NOT fail the backup.
        #
        # This machine has one disk and the owner knowingly accepted that no second disk
        # is available. Marking every night PARTIAL for a state that will not change
        # would make the backup status meaningless (alarm fatigue). The backup itself
        # succeeded: complete, encrypted, and shown to be restorable. What is missing is
        # a place to put it, which is a standing condition to remember, not a failure to
        # report repeatedly. The Health page shows it once; see `kesehatan._backup()`.
        log("")
        log("  [CATATAN LOKASI KEDUA] " + message_secondary)
        log("  Backup ini TETAP berhasil; yang kurang tempat menaruhnya.")

    if folder_kedua:
        try:
            os.makedirs(folder_kedua, exist_ok=True)
            sandi = sandi_backup.frasa_sandi()
            if sandi:
                tujuan = os.path.join(folder_kedua, nama_zip + ".enc")
                n = sandi_backup.enkripsi(path_zip, tujuan, sandi)
                log(f"Disalin TERENKRIPSI ke lokasi kedua: {folder_kedua}")
                log(f"  {nama_zip}.enc  {n / 1024 / 1024:.2f} MB  AES-256-GCM")
            else:
                # Copied as-is, but stated plainly. A plaintext copy moving to a place we do not
                # control, with no warning, is the most common way secrets leave unnoticed.
                tujuan = os.path.join(folder_kedua, nama_zip)
                shutil.copy2(path_zip, tujuan)
                log(f"Disalin ke lokasi kedua: {folder_kedua}")
                log("  PERINGATAN: TANPA ENKRIPSI. Berkas ini memuat "
                    "kredensial perangkat.")
                log("  Atur `nsm.backup-passphrase` di application.properties "
                    "untuk menguncinya.")
                gagal.append("salinan kedua belum dienkripsi")
            rotasi(folder_kedua, simpan)
        except Exception as e:
            gagal.append(f"salinan kedua gagal: {e}")
            log(f"  [GAGAL] salinan kedua: {e}")
    else:
        log("Lokasi kedua belum diatur (BACKUP_DIR2 di .env) — "
            "backup hanya ada di satu disk.")

    rotasi(folder_utama, simpan)

    sukses = not gagal
    baris = tulis_manifest(folder_utama, nama_zip, mulai, sukses)
    print()
    print("=" * 70)
    print(baris)
    print("=" * 70)
    return 0 if sukses else 2  # 2 = partial success, not a total failure


if __name__ == "__main__":
    sys.exit(main())

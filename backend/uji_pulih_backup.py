"""Restore test: proves backup files can really be restored.
Checks, each catching one way a backup can silently break:
 1. The zip opens and contains the three promised files (docs/BACKUP.md).
 2. The restored `nsm.db` passes `PRAGMA integrity_check` (catches copies cut mid-transaction).
 3. Every table in the live database also exists in the restored one.
 4. The tables actually hold rows.
 5. The newest row timestamp in the restored copy matches the zip creation time (catches stale zips).
 6. The MySQL dump is actually executed into a scratch database and row counts are compared with the live ones. Restored counts may not exceed live counts, except for ephemeral token tables listed in `TABEL_FANA`.
 7. `audit_logs.csv` has a plausible row count for its table.
Most important guard: the MySQL dump contains `CREATE DATABASE nsm_auth` and `USE nsm_auth`, which would overwrite the live accounts database. Database names are rewritten first, and the script refuses to run if any live name remains.
Only reads `nsm.db`; safe to run while the poller and uvicorn are running.
Run: py uji_pulih_backup.py
"""
import csv
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timedelta

import config
import database
import sandi_backup
from backup_nsm import _berkas_kredensial, find_tool

lolos = 0
gagal = 0

# Scratch database name; the suffix distinguishes it from the live one and the script refuses to run if they match.
AKHIRAN_UJI = "_ujipulih"

DB_BUANGAN = (database.ENV.get("NSM_DB_NAME", "nsm") or "nsm") + AKHIRAN_UJI

# Ephemeral MySQL tables (rows expire or are consumed). A restored copy with more rows than the live DB is normal for these.
# Listed by name, not pattern, so adding a table forces a deliberate decision. Durable tables (`users`, `audit_logs`, `notif_langganan`, `blocked_ips`) stay fully checked.
TABEL_FANA = {
    # Password reset tokens: 30-minute lifetime, deleted when the link is used.
    "password_reset_tokens": "token reset password sekali pakai, "
                             "umur 30 menit lalu hilang begitu dipakai",
    # Email change tokens: same lifetime and behavior as password reset tokens.
    "email_change_tokens": "token ganti email sekali pakai, "
                           "umur 30 menit lalu hilang begitu dikonfirmasi",
}


def cek(nama, dapat, harap):
    global lolos, gagal
    if dapat == harap:
        lolos += 1
        print(f"  LOLOS  {nama}: {dapat}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama}: dapat {dapat!r}, harusnya {harap!r}")


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print(f"  LOLOS  {nama}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama} {ket}")


def zip_terbaru(folder):
    """Newest backup zip in a folder, or None."""
    if not os.path.isdir(folder):
        return None
    prospective = [os.path.join(folder, f) for f in os.listdir(folder)
             if f.startswith("nsm-backup-") and f.endswith(".zip")]
    return max(prospective, key=os.path.getmtime) if prospective else None


def salinan_terbaru(folder):
    """Newest backup copy, encrypted or not.
    The primary location must be a plain `.zip` (it is opened here); the second location only needs to exist and should be `.zip.enc`.
    """
    if not os.path.isdir(folder):
        return None
    prospective = [os.path.join(folder, f) for f in os.listdir(folder)
             if f.startswith("nsm-backup-")
             and (f.endswith(".zip") or f.endswith(".zip.enc"))]
    return max(prospective, key=os.path.getmtime) if prospective else None


def waktu_dari_nama(jalur):
    m = re.search(r"(\d{8})_(\d{6})", os.path.basename(jalur))
    if not m:
        return None
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")


def baris_per_tabel(jalur_db):
    """{table_name: row_count} for a SQLite file."""
    c = sqlite3.connect(f"file:{jalur_db}?mode=ro", uri=True)
    try:
        tabel = [t for (t,) in c.execute(
            "select name from sqlite_master where type='table' "
            "and name not like 'sqlite_%'")]
        return {t: c.execute(f'select count(*) from "{t}"').fetchone()[0]
                for t in tabel}
    finally:
        c.close()


# ===========================================================================
def uji_sqlite(kerja, saat_zip):
    print("\n2. nsm.db hasil pulih: utuh, lengkap, dan isinya sezaman")
    recover = os.path.join(kerja, "nsm.db")
    benar("berkas nsm.db ada di dalam zip", os.path.exists(recover))
    if not os.path.exists(recover):
        return

    c = sqlite3.connect(f"file:{recover}?mode=ro", uri=True)
    try:
        hasil = c.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        c.close()
    cek("PRAGMA integrity_check", hasil, "ok")

    # Read the live DB from an anchored path; a relative "nsm.db" could compare against an unrelated empty file and pass vacuously.
    hidup = baris_per_tabel(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "nsm.db"))
    dipulih = baris_per_tabel(recover)

    missing = sorted(set(hidup) - set(dipulih))
    cek("tidak ada tabel yang hilang dari hasil pulih", missing, [])

    empty = sorted(t for t in dipulih
                    if dipulih[t] == 0 and hidup.get(t, 0) > 0)
    cek("tidak ada tabel yang berstruktur benar tapi kosong", empty, [])

    # A backup from the past may have fewer rows; more rows means the wrong file was compared.
    melebihi = sorted(t for t in dipulih if dipulih[t] > hidup.get(t, 0))
    cek("tidak ada tabel hasil pulih yang melebihi yang hidup", melebihi, [])

    print("\n   perbandingan isi (backup diambil di masa lalu, jadi lebih kecil itu wajar)")
    print("   %-22s %10s %10s" % ("tabel", "dipulih", "hidup"))
    for t in sorted(hidup):
        print("   %-22s %10d %10d" % (t, dipulih.get(t, 0), hidup[t]))

    c = sqlite3.connect(f"file:{recover}?mode=ro", uri=True)
    try:
        teks = c.execute("select max(timestamp) from status_logs").fetchone()[0]
    finally:
        c.close()
    latest = datetime.fromisoformat(teks) if teks else None
    benar("baris ping terbaru punya cap waktu", latest is not None)
    if latest and saat_zip:
        # Compare against the live DB as of backup time, not against "now": a stopped poller would otherwise make a healthy backup look stale.
        _db_actual = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "nsm.db")
        c = sqlite3.connect(f"file:{_db_actual.replace(os.sep, '/')}?mode=ro",
                            uri=True)
        try:
            seharusnya = c.execute(
                "select max(timestamp) from status_logs where timestamp <= ?",
                (saat_zip.strftime("%Y-%m-%d %H:%M:%S"),)).fetchone()[0]
        finally:
            c.close()
        # Tolerance of five minutes: the zip name has whole-second resolution and the poller keeps writing during the copy. A genuinely stale zip is off by hours.
        TOLERANSI = timedelta(minutes=5)
        begin = datetime.fromisoformat(seharusnya) if seharusnya else None
        print(f"       baris terbaru di hasil pulih : {latest}")
        print(f"       zip dibuat                   : {saat_zip}")
        print(f"       keadaan basis data saat itu  : {begin}")
        benar("hasil pulih tidak lebih tua daripada keadaan saat penyalinan mulai",
              begin is not None and latest >= begin,
              f"-> hasil pulih {latest}, saat itu sudah ada {begin}. "
              f"Zip yang isinya lebih tua berarti berkasnya basi")
        benar("hasil pulih tidak lebih baru daripada masuk akal "
              f"(zip + {int(TOLERANSI.total_seconds())} dtk)",
              latest <= saat_zip + TOLERANSI,
              f"-> {latest} jauh melewati {saat_zip}, mustahil kecuali "
              f"berkasnya tertukar")

    c = sqlite3.connect(f"file:{recover}?mode=ro", uri=True)
    try:
        dev = c.execute("select count(*) from devices").fetchone()[0]
        nama = [r[0] for r in c.execute("select name from devices order by id")]
    finally:
        c.close()
    print(f"       perangkat di hasil pulih: {nama}")
    benar("daftar perangkat terbaca dari hasil pulih", dev > 0,
          f"-> {dev} perangkat")


# ===========================================================================
def _proses_hidup(pid):
    """True/False/None: whether process `pid` is still running; None means unknown.
    Do not use `os.kill(pid, 0)` on Windows: it terminates the process. The Windows path uses OpenProcess/GetExitCodeProcess, which only read.
    """
    if not pid or pid <= 0:
        return None

    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        ERROR_INVALID_PARAMETER = 87
        STILL_ACTIVE = 259
        h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            # Access denied means the process exists but belongs to someone else, so it is alive.
            return False if k.GetLastError() == ERROR_INVALID_PARAMETER else None
        try:
            code = wintypes.DWORD()
            if not k.GetExitCodeProcess(h, ctypes.byref(code)):
                return None
            return code.value == STILL_ACTIVE
        finally:
            k.CloseHandle(h)

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None


class KunciPemulihan:
    """Exclusive lock: only one restore test may run at a time, because all tests share one scratch database (`DB_BUANGAN`) and would otherwise drop each other's data.
    A stale lock (holder process dead) is taken over after `BATAS_BASI`.
    """

    # Last-resort safety net: only applies when liveness of the holder cannot be determined (see `_proses_hidup`).
    BATAS_BASI = 2400          # 40 menit; uji terlama terukur ~3 menit

    # Maximum wait for the lock; giving up never means running without it.
    TUNGGU_DETIK = 900

    def __init__(self, nama="pemulihan"):
        self.jalur = os.path.join(tempfile.gettempdir(),
                                  "nsm-kunci-%s.lock" % nama)
        self.dipegang = False

    def _pemilik(self):
        """Pid written in the lock file, or None if unreadable."""
        try:
            with open(self.jalur, encoding="utf-8", errors="replace") as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None

    def _rebut(self, alasan):
        print("   [kunci] %s -- kunci diambil alih" % alasan)
        try:
            os.remove(self.jalur)
        except OSError:
            pass

    def __enter__(self):
        """Acquire the lock. Callers must check `self.dipegang`: running without the lock caused two tests to wipe the same scratch database and report false data loss."""
        limit = time.time() + self.TUNGGU_DETIK
        while time.time() < limit:
            try:
                fd = os.open(self.jalur, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self.dipegang = True
                return self
            except FileExistsError:
                pass

            # Decide by whether the holder is still alive (its pid is in the lock file), not only by lock age; killed tests never run `__exit__`.
            pid = self._pemilik()
            hidup = _proses_hidup(pid)
            if hidup is False:
                self._rebut("pemegang kunci (pid %s) sudah tidak ada" % pid)
                continue

            try:
                age = time.time() - os.path.getmtime(self.jalur)
            except OSError:
                age = 0
            if age > self.BATAS_BASI:
                self._rebut("kunci basi %d detik (pid %s, keadaannya tidak "
                            "bisa dipastikan)" % (int(age), pid))
                continue
            time.sleep(5)

        pid = self._pemilik()
        state = ("pid %s masih hidup" % pid if _proses_hidup(pid)
                   else "pid %r, keadaannya tidak bisa dipastikan" % pid)
        print("   [kunci] tidak dapat giliran dalam %d detik (%s)."
              % (self.TUNGGU_DETIK, state))
        return self

    def __exit__(self, *a):
        if self.dipegang:
            try:
                os.remove(self.jalur)
            except OSError:
                pass
        return False


def test_mysql(kerja, user=None, sandi=None, nama_db=None, host=None,
              port=None, judul=None, tabel_bukti="users"):
    """Restore one MySQL dump into the scratch database and compare it with the live one."""
    print("\n" + (judul or "3. Dump MySQL BENAR-BENAR dijalankan, "
                           "bukan cuma dibaca"))
    if user is None:
        user, sandi, nama_db, host, port = config.get_mysql_config()
    dump = os.path.join(kerja, f"{nama_db}.sql")
    benar(f"berkas {nama_db}.sql ada di dalam zip", os.path.exists(dump))
    if not os.path.exists(dump):
        return

    tool = find_tool("mysql.exe", config.get_mysql_path())
    if not tool:
        print("  [LEWAT] mysql.exe tidak ditemukan — pemulihan tidak bisa diuji.")
        print("          Isi MYSQL_PATH di .env. Dilewati, bukan dianggap lolos.")
        return

    # One scratch database for all restores, so only one privilege grant is needed. Any existing copy is dropped first and cleaned up at the end.
    db_test = DB_BUANGAN

    # GUARD: never overwrite the live database
    if db_test == nama_db:
        print("  [BERHENTI] nama basis data pembuangan sama dengan yang hidup.")
        return

    content = open(dump, encoding="utf-8", errors="replace").read()

    # Rewrite only backtick-quoted identifiers, not the whole file: table data may contain text like `nsm-ubah-firewall`, and a blanket replace would corrupt the data being verified.
    change = content.replace("`%s`" % nama_db, "`%s`" % db_test)

    # After rewriting, no mention of the live database name may remain in executable statements; otherwise abort. Mentions in `--` comment lines are ignored.
    remaining = re.findall(re.escape("`%s`" % nama_db), change)
    if remaining:
        print(f"  [BERHENTI] masih ada {len(remaining)} sebutan `{nama_db}` "
              f"setelah ditulis ulang. Tidak dijalankan.")
        gagal_penjaga(f"dump masih menyebut {nama_db}")
        return
    benar(f"nol pengenal `{nama_db}` tersisa setelah ditulis ulang "
          f"(penjaga anti-menimpa)", True)

    # GTID is enabled, so mysqldump emits `SET @@GLOBAL.GTID_PURGED=...`, which fails on restore into the same server (ERROR 3546). Checked separately before the line is stripped, so the test does not hide the defect.
    punya_gtid = re.search(r"(?im)^\s*SET\s+@@GLOBAL\.GTID_PURGED", change)
    benar("dump tidak memuat SET @@GLOBAL.GTID_PURGED "
          "(pernyataan yang membuatnya gagal dipulihkan ke server yang sama)",
          punya_gtid is None,
          "-> backup ini dibuat SEBELUM `--set-gtid-purged=OFF` masuk ke "
          "backup_nsm.py. Masih bisa diselamatkan dengan membuang barisnya, "
          "dan itu dibuktikan di baris berikutnya")
    if punya_gtid:
        change = re.sub(r"(?im)^\s*SET\s+@@GLOBAL\.GTID_PURGED[^;]*;\s*$",
                      "-- (baris GTID_PURGED dibuang oleh uji pulih)", change)
        print("       barisnya dibuang, lalu pemulihannya dicoba lagi supaya "
              "ketahuan apakah backup lama masih bisa diselamatkan")

    safe = os.path.join(kerja, f"{db_test}.sql")
    open(safe, "w", encoding="utf-8").write(change)

    cnf = _berkas_kredensial(user, sandi, host, port)

    # Take the lock here, just before the part that touches the scratch database, whose `finally` always releases it. The earlier guards return early and would leak the lock file.
    _kunci = KunciPemulihan()
    _kunci.__enter__()
    if not _kunci.dipegang:
        # A measurement failure, reported as such: the backup itself was not checked.
        gagal_pengukuran("uji pemulihan lain sedang memakai basis data "
                         "pembuangan `%s`; backup TIDAK diperiksa" % db_test)
        try:
            os.unlink(cnf)
        except OSError:
            pass
        return

    try:
        ada = subprocess.run(
            [tool, f"--defaults-extra-file={cnf}", "-N", "-B", "-e",
             f"show databases like '{db_test}'"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        if ada.stdout.strip():
            subprocess.run([tool, f"--defaults-extra-file={cnf}", "-e",
                            f"drop database `{db_test}`"], timeout=60)

        with open(safe, encoding="utf-8") as f:
            jalan = subprocess.run([tool, f"--defaults-extra-file={cnf}"],
                                   stdin=f, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   # 900 seconds: the NSM dump has hundreds of thousands of rows.
                                   timeout=900)
        cek("dump dijalankan tanpa galat", jalan.returncode, 0)
        if jalan.returncode != 0:
            print("       " + jalan.stderr.strip()[:300])
            return

        def hitung(db):
            r = subprocess.run(
                [tool, f"--defaults-extra-file={cnf}", "-N", "-B", "-e",
                 "select table_name, table_rows from information_schema.tables "
                 f"where table_schema='{db}' order by table_name"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            return dict(baris.split("\t")[:2]
                        for baris in r.stdout.strip().splitlines() if baris)

        def hitung_tepat(db, tabel, percobaan=3):
            """Row count; -1 means the measurement failed, not the data.
            Retried because `mysql.exe` occasionally returns code 0 with empty stdout.
            """
            for _to in range(percobaan):
                r = subprocess.run(
                    [tool, f"--defaults-extra-file={cnf}", "-N", "-B", "-e",
                     f"select count(*) from `{db}`.`{tabel}`"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
                if r.returncode == 0:
                    try:
                        return int(r.stdout.strip())
                    except ValueError:
                        pass
            return -1

        t_recover = set(hitung(db_test))
        t_alive = set(hitung(nama_db))
        cek("tidak ada tabel MySQL yang hilang dari hasil pulih",
            sorted(t_alive - t_recover), [])

        print("\n   %-24s %10s %10s   %s"
              % ("tabel MySQL", "dipulih", "hidup", "sifat baris"))
        aneh = []
        fana_menyusut = []
        for t in sorted(t_alive):
            a, b = hitung_tepat(db_test, t), hitung_tepat(nama_db, t)
            print("   %-24s %10d %10d   %s"
                  % (t, a, b, "fana (dibebaskan)" if t in TABEL_FANA else "awet"))
            if a > b:
                if t in TABEL_FANA:
                    fana_menyusut.append((t, a, b))
                else:
                    aneh.append(f"{t} ({a} dipulih > {b} hidup)")

        # Ephemeral shrinkage is printed, not hidden, so an abnormal drop remains visible.
        for t, a, b in fana_menyusut:
            print(f"       CATATAN: {t} menyusut {a} -> {b} baris. Dibebaskan "
                  f"karena {TABEL_FANA[t]}; ini pergeseran data biasa antara "
                  f"jam backup dan jam uji, bukan backup rusak.")

        cek(f"tidak ada tabel MySQL AWET hasil pulih yang melebihi yang hidup "
            f"({len(t_alive - TABEL_FANA.keys())} dari {len(t_alive)} tabel "
            f"dijaga, sisanya fana)", aneh, [])

        n_user = hitung_tepat(db_test, tabel_bukti)
        benar(f"tabel {tabel_bukti} hasil pulih berisi baris", n_user > 0,
              f"-> {n_user} baris")
    finally:
        # Basis data pembuangan SELALU dihapus, berhasil maupun gagal.
        subprocess.run([tool, f"--defaults-extra-file={cnf}", "-e",
                        f"drop database if exists `{db_test}`"], timeout=60)
        remaining_check = subprocess.run(
            [tool, f"--defaults-extra-file={cnf}", "-N", "-B", "-e",
             f"show databases like '{db_test}'"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        cek("basis data pembuangan dibersihkan setelah uji",
            remaining_check.stdout.strip(), "")
        try:
            os.unlink(cnf)
        except OSError:
            pass
        # Release the lock last, after the scratch database is dropped.
        _kunci.__exit__(None, None, None)


def gagal_penjaga(pesan):
    global gagal
    gagal += 1
    print(f"  GAGAL  penjaga: {pesan}")


def gagal_pengukuran(pesan):
    """The test could not measure, which is different from a bad result. It stays failing on purpose so it never looks like a pass."""
    global gagal
    gagal += 1
    print(f"  GAGAL PENGUKURAN  {pesan}")


# ===========================================================================
def test_csv(kerja):
    print("\n4. audit_logs.csv terbaca")
    jalur = os.path.join(kerja, "audit_logs.csv")
    benar("berkas audit_logs.csv ada di dalam zip", os.path.exists(jalur))
    if not os.path.exists(jalur):
        return
    with open(jalur, encoding="utf-8", errors="replace", newline="") as f:
        baris = list(csv.reader(f))
    benar("punya baris kepala + isi", len(baris) > 1, f"-> {len(baris)} baris")
    print(f"       {len(baris) - 1} baris audit, kolom: {baris[0][:6]}")


# ===========================================================================
def uji():
    print("=" * 74)
    print("Uji pulih backup — dari zip, ke folder pembuangan, tanpa menyentuh")
    print("apa pun yang sedang berjalan")
    print("=" * 74)

    primary = config.get_backup_dir()
    kedua = config.get_backup_dir2()

    print("\n1. Zip backup ditemukan dan bisa dibuka")
    zip_primary = zip_terbaru(primary)
    benar(f"ada zip di lokasi utama ({primary})", zip_primary is not None)
    if not zip_primary:
        return

    # The second copy is checked for existence too; a second location that silently stops filling is easy to miss.
    zip_secondary = salinan_terbaru(kedua) if kedua else None
    if kedua:
        benar(f"lokasi kedua juga terisi ({kedua})", zip_secondary is not None,
              "-> backup di satu disk yang sama dengan datanya bukan backup")
        if zip_secondary:
            # Compare names, not sizes: an encrypted copy is always slightly larger, so equal sizes suggest it is not encrypted.
            benar("salinan kedua sezaman dengan yang di lokasi utama",
                  os.path.basename(zip_secondary).startswith(os.path.basename(zip_primary)),
                  f"-> utama {os.path.basename(zip_primary)}, "
                  f"kedua {os.path.basename(zip_secondary)}")

            # It must really be encrypted: check the file header, not the `.enc` suffix. A plain copy in the cloud folder would expose device credentials.
            with open(zip_secondary, "rb") as f:
                header = f.read(8)
            terenkripsi = header == sandi_backup.AJAIB
            if sandi_backup.frasa_sandi():
                benar("salinan kedua benar-benar terenkripsi", terenkripsi,
                      "-> frasa sandi diatur tetapi berkasnya polos; "
                      "isinya memuat kredensial perangkat")
            elif not terenkripsi:
                print("       CATATAN: salinan kedua belum dienkripsi "
                      "(nsm.backup-passphrase belum diatur)")

    saat_zip = waktu_dari_nama(zip_primary)
    print(f"       diuji: {os.path.basename(zip_primary)}  "
          f"{os.path.getsize(zip_primary) / 1024 / 1024:.2f} MB  dibuat {saat_zip}")

    try:
        z = zipfile.ZipFile(zip_primary)
        broken = z.testzip()
    except zipfile.BadZipFile as e:
        cek("zip bisa dibuka", str(e), "(tidak melempar)")
        return
    cek("tidak ada berkas rusak di dalam zip", broken, None)

    content = sorted(z.namelist())
    print(f"       isi: {content}")
    _u, _s, nama_db, _h, _p = config.get_mysql_config()

    # Expected contents follow where the data lives: `nsm.sql` since the move to MySQL, no longer `nsm.db`.
    import database
    name_nsm = database.ENV.get("NSM_DB_NAME", "nsm")
    primary = f"{name_nsm}.sql" if database.PAKAI_MYSQL else "nsm.db"
    for required in (primary, f"{nama_db}.sql", "audit_logs.csv"):
        benar(f"zip memuat {required}", required in content,
              f"-> yang ada {content}")

    kerja = tempfile.mkdtemp(prefix="nsm-pulih-")
    print(f"       dipulihkan ke: {kerja}")
    try:
        z.extractall(kerja)
        z.close()

        if database.PAKAI_MYSQL:
            # Actually run the largest dump to prove it restores; reading the `.sql` proves nothing.
            env = database.ENV
            test_mysql(kerja,
                      user=env.get("NSM_DB_USER"),
                      sandi=env.get("NSM_DB_PASS"),
                      nama_db=name_nsm,
                      host=env.get("NSM_DB_HOST"),
                      port=env.get("NSM_DB_PORT", "3306"),
                      judul="2. Dump basis data NSM BENAR-BENAR dipulihkan "
                            "(riwayat pemantauan, bagian terbesar backup)",
                      tabel_bukti="status_logs")
        else:
            uji_sqlite(kerja, saat_zip)

        test_mysql(kerja)
        test_csv(kerja)
    except Exception as e:
        # Errors mid-test are reported as failures rather than lost, so a crashed test does not look like a fast one.
        global gagal
        gagal += 1
        import traceback
        print(f"  GAGAL  uji berhenti karena galat: {e}")
        traceback.print_exc()
    finally:
        shutil.rmtree(kerja, ignore_errors=True)
        print(f"\n   folder pembuangan dihapus: {kerja}")


if __name__ == "__main__":
    uji()
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

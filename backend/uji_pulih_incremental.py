"""Restore test for incremental backups: does the real `induk.zip` restore, and do row counts match the live database exactly?
Unlike `uji_backup_incremental.py` (synthetic data, no MySQL), this restores the real zip with the real `mysql.exe` into a scratch database, never the live one; the script aborts if the names match.
Run:
    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\python.exe uji_pulih_incremental.py
"""
import os
import subprocess
import sys
import tempfile
import zipfile

import config
import database
from backup_incremental import TABEL_INCREMENTAL, _folder_induk, NAMA_INDUK, _baca_meta
from backup_nsm import find_tool, _berkas_kredensial
from uji_pulih_backup import AKHIRAN_UJI

lolos = 0
gagal_n = 0


def benar(nama, syarat, ket=""):
    global lolos, gagal_n
    if syarat:
        lolos += 1
        print("  LOLOS  %s" % nama)
    else:
        gagal_n += 1
        print("  GAGAL  %s %s" % (nama, ket))


def main():
    print("=" * 74)
    print("UJI PULIH: induk.zip (backup incremental) vs basis data hidup")
    print("=" * 74)

    if not database.PAKAI_MYSQL:
        print("[LEWAT] NSM sedang memakai SQLite, bukan MySQL.")
        return 0

    path_parent = os.path.join(_folder_induk(), NAMA_INDUK)
    benar("induk.zip ada di disk", os.path.exists(path_parent))
    if not os.path.exists(path_parent):
        return 1

    env = database.ENV
    user = env.get("NSM_DB_USER", "nsm_app")
    password = env.get("NSM_DB_PASS", "")
    name_db = env.get("NSM_DB_NAME", "nsm")
    host = env.get("NSM_DB_HOST", "")
    port = env.get("NSM_DB_PORT", "3306")
    # Same scratch name and lock as `uji_pulih_backup.py`: two restore tests must not run at the same time.
    from uji_pulih_backup import DB_BUANGAN, KunciPemulihan
    db_test = DB_BUANGAN

    # GUARD: never overwrite the live database.
    if db_test == name_db:
        print("[BERHENTI] nama basis data pembuangan sama dengan yang hidup.")
        return 1

    tool = find_tool("mysql.exe", config.get_mysql_path())
    if not tool:
        print("[LEWAT] mysql.exe tidak ditemukan -- pemulihan tidak bisa diuji.")
        return 0

    # Take the lock after both guards; their early returns would otherwise leave the lock file behind.
    _kunci = KunciPemulihan()
    _kunci.__enter__()
    if not _kunci.dipegang:
        print("[GAGAL PENGUKURAN] uji pemulihan lain sedang memakai basis "
              "data pembuangan `%s`; backup incremental TIDAK diperiksa."
              % db_test)
        return 1

    cnf = _berkas_kredensial(user, password, host, port)
    work = tempfile.mkdtemp(prefix="uji_pulih_incr_")
    try:
        with zipfile.ZipFile(path_parent) as z:
            z.extractall(work)
        content_zip = set(os.listdir(work))
        print("\n1. ISI induk.zip")
        for t, _k in TABEL_INCREMENTAL:
            benar("%s.sql ada di dalam induk" % t, f"{t}.sql" in content_zip)
        benar("_lain_full.sql (tabel kecil) ada di dalam induk",
              "_lain_full.sql" in content_zip)

        # Accounts and audit (`nsm_auth`) are checked too: they cannot be rebuilt, and losing them means nobody can log in.
        benar("nsm_auth.sql (akun & peran) ada di dalam induk",
              "nsm_auth.sql" in content_zip,
              "-> akun, hash sandi, dan peran TIDAK ikut tercadangkan")
        benar("audit_logs.csv (jejak audit) ada di dalam induk",
              "audit_logs.csv" in content_zip)

        print("\n2. Basis data pembuangan disiapkan bersih")
        subprocess.run([tool, f"--defaults-extra-file={cnf}", "-e",
                        f"drop database if exists `{db_test}`; "
                        f"create database `{db_test}`"],
                       timeout=60, capture_output=True)
        benar("basis data pembuangan `%s` dibuat" % db_test, True)

        print("\n3. SEMUA berkas SQL di induk dijalankan, dalam urutan yang "
              "benar")
        urutan = ["_lain_full.sql"] + [f"{t}.sql" for t, _k in TABEL_INCREMENTAL]
        all_ok = True
        for nama in urutan:
            jalur = os.path.join(work, nama)
            if not os.path.exists(jalur):
                continue
            with open(jalur, encoding="utf-8", errors="replace") as f:
                p = subprocess.run(
                    [tool, f"--defaults-extra-file={cnf}", "-D", db_test],
                    stdin=f, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
            ok = p.returncode == 0
            benar("  %-24s dijalankan tanpa galat" % nama, ok,
                  "-> %s" % p.stderr.strip()[:200] if not ok else "")
            all_ok = all_ok and ok

        if not all_ok:
            print("\n[BERHENTI] ada berkas yang gagal dijalankan -- "
                  "perbandingan baris dilewati (tidak berarti apa-apa "
                  "kalau pemulihannya sendiri sudah gagal).")
            return 1

        print("\n4. JUMLAH BARIS pembuangan HARUS SAMA dengan yang hidup "
              "PADA SAAT POSISI id")
        print("   (bukan 'sekarang' -- `nsm` basis data hidup terus "
              "bertambah baris SELAMA")
        print("    uji ini berjalan, jadi dibandingkan per `id <= posisi`, "
              "persis apa yang")
        print("    ditangkap induk.zip -- lihat _klausa_where()/"
              "_id_maksimum() di backup_incremental.py)")

        meta = _baca_meta(_folder_induk())
        posisi = (meta or {}).get("posisi", {})
        benar("induk.meta.json ada dan punya 'posisi' per tabel",
              bool(posisi), "-> meta=%r" % meta)

        def hitung(db, tabel, kolom=None, sampai=None, percobaan=3):
            """Row count; returns -1 if the measurement itself failed.
            Retried up to `percobaan` times because `mysql.exe` occasionally exits 0 with empty stdout. A failed measurement must not be reported as data loss.
            """
            for to in range(1, percobaan + 1):
                r = subprocess.run(
                    [tool, f"--defaults-extra-file={cnf}", "-N", "-B", "-e",
                     f"select count(*) from `{db}`.`{tabel}` "
                     + (f"where {kolom} <= {sampai}" if sampai is not None else "")],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
                if r.returncode == 0:
                    try:
                        return int(r.stdout.strip())
                    except ValueError:
                        print("     [percobaan %d/%d] keluaran tak terduga %r"
                              % (to, percobaan, r.stdout))
                else:
                    print("     [percobaan %d/%d] galat mysql: %s"
                          % (to, percobaan, r.stderr.strip()[:160]))
            return -1

        for tabel, kolom in TABEL_INCREMENTAL:
            # `asli` is bounded to the same id position used when `backup_incremental.py` dumped; comparing against "now" would always differ on a live, growing database.
            limit = posisi.get(tabel)
            original = hitung(name_db, tabel, kolom, limit)
            recover = hitung(db_test, tabel)
            if original < 0 or recover < 0:
                # Do not report a row difference here: the measurement failed, not the backup.
                sisi = "basis data HIDUP" if original < 0 else "basis data pulih"
                benar("%-20s TIDAK BISA DIUKUR" % tabel, False,
                      "-> gagal mencacah di %s setelah 3 percobaan; "
                      "ini kegagalan ALAT UKUR, bukan bukti data hilang. "
                      "Jalankan ulang uji ini sebelum menyimpulkan apa pun."
                      % sisi)
            else:
                benar("%-20s asli(id<=%s)=%-8d pulih=%-8d" %
                      (tabel, limit, original, recover),
                      original == recover,
                      "-> SELISIH %d baris" % (original - recover))

        print("\n5. Pembuangan dibersihkan")
        subprocess.run([tool, f"--defaults-extra-file={cnf}", "-e",
                        f"drop database `{db_test}`"],
                       timeout=60, capture_output=True)
        benar("basis data pembuangan dihapus setelah uji", True)
    finally:
        try:
            os.unlink(cnf)
        except OSError:
            pass
        import shutil
        shutil.rmtree(work, ignore_errors=True)
        # Last, after everything is cleaned up (see `uji_pulih_backup.KunciPemulihan`).
        _kunci.__exit__(None, None, None)

    print()
    print("=" * 74)
    print("HASIL: %d lolos, %d gagal" % (lolos, gagal_n))
    print("=" * 74)
    return 1 if gagal_n else 0


if __name__ == "__main__":
    sys.exit(main())

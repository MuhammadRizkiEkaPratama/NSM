"""Measurement tool (not a backup tool): how big is an incremental backup of NSM compared with a full backup?
Read-only: writes no backup, deletes nothing, does not touch binlogs or database rows; temp files are removed afterward.
Measures, after compression:
  1. FULL: everything, every time.
  2. INCR-WAKTU: only rows newer than a cutoff (NSM data is mostly append-only).
  3. INCR-BINLOG: MySQL binary log size over the same range.
Run:
    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\python.exe ukur_incremental.py [jumlah_hari]
"""
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta

import config
from database import SessionLocal
from sqlalchemy import text

# Time-series tables and their time columns, from the same list `pangkas_data.py` uses; copying it here would let one silently fall behind.
from pangkas_data import TABEL as TABEL_WAKTU


def mb(byte):
    return byte / 1024.0 / 1024.0


def _kredensial():
    """MySQL host/user/password read from the existing DATABASE_URL."""
    from sqlalchemy.engine import make_url
    u = make_url(config.get_database_url() if hasattr(config, "get_database_url")
                 else os.environ.get("DATABASE_URL", ""))
    return u


def dump_mysql(basis, tujuan, where_per_tabel=None, hanya_tabel=None):
    """Run mysqldump. `where_per_tabel` is a dict {table: WHERE clause}.
    The password goes through `--defaults-extra-file`, not the command line, so it is not visible in the process list (same as `backup_nsm.py`).
    """
    from database import engine
    u = engine.url
    file_cnf = tempfile.NamedTemporaryFile("w", suffix=".cnf",
                                             delete=False, encoding="utf-8")
    file_cnf.write("[client]\nuser=%s\npassword=%s\nhost=%s\nport=%s\n"
                     % (u.username, u.password, u.host, u.port or 3306))
    file_cnf.close()
    try:
        # `mysqldump` is often not on PATH on Windows; the finder is reused from `backup_nsm.py`.
        from backup_nsm import find_tool
        tool = find_tool("mysqldump.exe", config.get_mysqldump_path())
        if not tool:
            raise RuntimeError("mysqldump tidak ditemukan di mesin ini")
        perintah = [tool, "--defaults-extra-file=" + file_cnf.name,
                    "--no-tablespaces", "--skip-lock-tables"]
        if where_per_tabel:
            # mysqldump accepts only one --where, so tables with different clauses run one at a time and the output is concatenated.
            with open(tujuan, "wb") as keluar:
                for table, klausa in where_per_tabel.items():
                    p = subprocess.run(
                        perintah + ["--where=" + klausa, u.database, table],
                        capture_output=True)
                    if p.returncode != 0:
                        print("   [lewat] %s: %s" % (table,
                              p.stderr.decode("utf-8", "replace")[:90].strip()))
                        continue
                    keluar.write(p.stdout)
        else:
            with open(tujuan, "wb") as keluar:
                p = subprocess.run(perintah + [u.database], capture_output=True)
                if p.returncode != 0:
                    raise RuntimeError(p.stderr.decode("utf-8", "replace")[:300])
                keluar.write(p.stdout)
    finally:
        os.unlink(file_cnf.name)
    return os.path.getsize(tujuan)


def zip_ukuran(sumber, tujuan_zip):
    """Compress and return the resulting size. Compression ratio is the core of the comparison: monitoring data is very repetitive."""
    with zipfile.ZipFile(tujuan_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(sumber, os.path.basename(sumber))
    return os.path.getsize(tujuan_zip)


def ukur_binlog(hari):
    """Total size of MySQL binary logs written in the last `hari` days, with an estimated compressed size.
    Read over SSH with only `ls`/`du`/`gzip -c | wc -c`: nothing is moved, deleted or flushed. `PURGE` and `--delete-master-logs` are deliberately never used because replication from .104 to .101 depends on the same binlogs.
    """
    try:
        import paramiko
    except ImportError:
        return None
    d = None
    db = SessionLocal()
    try:
        from models import Device
        d = db.query(Device).filter(Device.ip_address == "192.168.56.104").first()
    finally:
        db.close()
    if d is None:
        return None

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        if d.ssh_key_path:
            c.connect(d.ip_address, username=d.username,
                      key_filename=d.ssh_key_path, timeout=20,
                      allow_agent=False, look_for_keys=False)
        else:
            c.connect(d.ip_address, username=d.username, password=d.password,
                      timeout=20, allow_agent=False, look_for_keys=False)
    except Exception as e:
        print("   [lewat] tidak bisa SSH ke server MySQL: %s" % str(e)[:80])
        return None

    try:
        perintah = (
            "sudo -n find /var/log/mysql -name 'mysql-bin.0*' -mtime -%d "
            "-printf '%%s\\n' 2>/dev/null | awk '{s+=$1} END {print s+0}'; "
            "sudo -n bash -c \"cat \\$(find /var/log/mysql -name 'mysql-bin.0*' "
            "-mtime -%d) 2>/dev/null | gzip -c | wc -c\"" % (hari, hari))
        _i, out, _e = c.exec_command(perintah, timeout=180)
        line = out.read().decode("utf-8", "replace").split()
        if len(line) < 2 or line[0] == "0":
            # Not a bug: the `nsmro` account is deliberately limited to three sudo commands, and reading /var/log/mysql is not one of them. Measure manually with an admin account:
            #   sudo find /var/log/mysql -name 'mysql-bin.0*' -mtime -1 \
            #        -print0 | xargs -0 cat | gzip -c | wc -c
            print("   [lewat] `nsmro` tidak berhak membaca /var/log/mysql "
                  "(sudo-nya sengaja dibatasi 3 perintah).")
            print("           Ukur manual dengan akun admin -- lihat "
                  "docs/design/INCREMENTAL-BACKUP.md untuk angka 20 Agustus 2026.")
            return None
        return int(line[0]), int(line[1])
    finally:
        c.close()


def main():
    hari = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    cut = datetime.now() - timedelta(days=hari)

    print("=" * 74)
    print("UKUR: FULL vs INCREMENTAL  (jendela %d hari terakhir)" % hari)
    print("Titik potong: %s" % cut.strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 74)
    print("Skrip ini hanya MEMBACA. Tidak ada backup yang ditulis/dihapus.")

    work = tempfile.mkdtemp(prefix="ukur_incr_")
    hasil = {}
    try:
        # ---------- 1. FULL ----------
        print("\n1. FULL (seperti sekarang: seluruh isi, tiap kali)")
        f_sql = os.path.join(work, "full.sql")
        n = dump_mysql(None, f_sql)
        z = zip_ukuran(f_sql, os.path.join(work, "full.zip"))
        hasil["full"] = (n, z)
        print("   SQL mentah : %8.1f MB" % mb(n))
        print("   sesudah zip: %8.1f MB   (rasio %.1f:1)" % (mb(z), n / max(z, 1)))
        os.unlink(f_sql)

        print("\n2. INCREMENTAL lewat RENTANG WAKTU (hanya baris baru)")
        where = {}
        db = SessionLocal()
        try:
            for table, column, _simpan, _note in TABEL_WAKTU:
                where[table] = "%s >= '%s'" % (
                    column, cut.strftime("%Y-%m-%d %H:%M:%S"))
                try:
                    count = db.execute(text(
                        "SELECT COUNT(*) FROM %s WHERE %s" % (table, where[table])
                    )).scalar()
                    total = db.execute(text(
                        "SELECT COUNT(*) FROM %s" % table)).scalar()
                    print("   %-20s %8s baris baru  dari %8s total"
                          % (table, count, total))
                except Exception as e:
                    print("   %-20s [lewat] %s" % (table, str(e)[:60]))
                    where.pop(table, None)
        finally:
            db.close()

        i_sql = os.path.join(work, "incr.sql")
        n2 = dump_mysql(None, i_sql, where_per_tabel=where)
        z2 = zip_ukuran(i_sql, os.path.join(work, "incr.zip"))
        hasil["incr_waktu"] = (n2, z2)
        print("   SQL mentah : %8.1f MB" % mb(n2))
        print("   sesudah zip: %8.1f MB" % mb(z2))
        os.unlink(i_sql)

        print("\n3. INCREMENTAL lewat BINLOG (cara standar literatur MySQL)")
        b = ukur_binlog(hari)
        if b:
            hasil["binlog"] = b
            print("   binlog mentah : %8.1f MB" % mb(b[0]))
            print("   sesudah gzip  : %8.1f MB" % mb(b[1]))
        else:
            print("   tidak terukur (lihat pesan di atas)")

        # ---------- RINGKASAN ----------
        print("\n" + "=" * 74)
        print("RINGKASAN -- yang benar-benar memakan disk (sesudah dikompres)")
        print("=" * 74)
        fz = hasil["full"][1]
        print("  %-34s %9.1f MB   %s" % ("FULL (dipakai sekarang)", mb(fz), "1,0x"))
        iz = hasil["incr_waktu"][1]
        print("  %-34s %9.1f MB   %s" % ("INCREMENTAL per rentang waktu",
              mb(iz), "%.2fx" % (iz / max(fz, 1))))
        if "binlog" in hasil:
            bz = hasil["binlog"][1]
            print("  %-34s %9.1f MB   %s" % ("INCREMENTAL lewat binlog",
                  mb(bz), "%.2fx" % (bz / max(fz, 1))))
        print()
        print("  Hemat per hari kalau pindah ke incremental-waktu: %.1f MB "
              "(%.0f%%)" % (mb(fz - iz), 100.0 * (fz - iz) / max(fz, 1)))
        keep = config.get_backup_keep()
        print("  Dengan BACKUP_KEEP=%d dan DUA lokasi salinan, selisih "
              "setahun\n  kira-kira %.1f GB." % (
                  keep, mb(fz - iz) * 365 * 2 / 1024.0))
    finally:
        for remaining in os.listdir(work):
            try:
                os.unlink(os.path.join(work, remaining))
            except OSError:
                pass
        os.rmdir(work)
        print("\n(berkas sementara dibersihkan)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

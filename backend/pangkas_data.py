"""Delete old rows from tables that grow without bound.

Only repeated raw data (the result of each check round) is pruned. Event
records are NEVER pruned: `device_events` (when a device went down and
recovered, and why) and `service_events` (the same for services, with the
diagnosis snapshot). Outage history therefore survives pruning of old pings.

Retention is 35 days, not 30: the longest Report period is 30 days, and pruning
exactly at 30 would make `jeda.py` read the missing rows at the window edge as
"NSM was not monitoring" and shrink the availability denominator.

Usage:
    python pangkas_data.py              dry run, show what would be deleted
    python pangkas_data.py --jalankan   actually delete
    python pangkas_data.py --jalankan --vacuum   also shrink the database file

Stop the poller and uvicorn first, as with migrations: deleting tens of
thousands of rows holds the write lock long enough to fail the next ping round.
`--vacuum` rewrites the whole database file to return free space to the
filesystem; it needs free disk equal to the file size and can take minutes, so
it is never automatic.
"""
import os
import sys
from datetime import datetime, timedelta

from sqlalchemy import text

import database
import dialek

import config
import rollup
from database import SessionLocal, engine, JALUR_DB

# (table name, time column, days retained, short note)
# Days can be overridden in .env (e.g. SIMPAN_HARI_STATUS_LOGS=60); retention is
# an operational decision, like POLL_INTERVAL.
TABEL = [
    ("status_logs", "timestamp", 35,
     "hasil ping tiap putaran"),
    ("bandwidth_samples", "timestamp", 35,
     "counter lalu lintas tiap interface"),
    ("service_checks", "timestamp", 35,
     "hasil pemeriksaan layanan tiap putaran"),
    ("akses_web", "waktu", 35,
     "baris access log Apache yang sudah dibaca"),
    # 35, not 14: this table is shown next to `akses_web` (kept 35 days) on a page
    # with a "30 days" button. With 14 days the two would silently cover different
    # windows on the same screen.
    ("flow_koneksi", "waktu", 35,
     "potret koneksi TCP; disamakan 35 hari agar sejendela dengan akses_web"),
]

# Tables deliberately NOT in the list above, written out so the omission reads as
# a decision rather than an oversight.
TIDAK_DIPANGKAS = {
    "device_events": "riwayat gangguan device, inti dari halaman Report",
    "service_events": "riwayat gangguan layanan beserta potret diagnosanya",
    "devices": "daftar perangkat",
    "services": "daftar layanan",
    "posisi_log": "penanda posisi baca access log, cuma satu baris per device",
    "konfig_snapshots": ("riwayat konfigurasi perangkat. Hanya bertambah saat "
                         "konfigurasinya BERUBAH, jadi tabelnya tetap kecil "
                         "sendiri; dan membuangnya berarti membuang satu-satunya "
                         "salinan konfigurasi lama yang dipunyai NSM"),
    "nama_alamat": ("singgahan nama DNS, satu baris per alamat. Membuangnya "
                    "hanya memaksa pencarian ulang yang memakan 4-9 detik per "
                    "alamat"),
    # The hourly rollup is the only surviving copy of long history once raw rows are
    # pruned, so it is never pruned (about 52,000 rows per year for six devices).
    "status_rollup_jam": ("ringkasan per jam yang menggantikan status_logs "
                          "setelah baris mentahnya dibuang. Menyusut 600x, "
                          "jadi tidak pernah jadi masalah ruang. Memangkasnya "
                          "berarti membuang riwayat yang tabel ini ada untuk "
                          "menyelamatkannya"),
}


def save_day(nama, bawaan):
    """Read the retention days from .env, falling back to the default if the value is
    not sensible.
    """
    kunci = "SIMPAN_HARI_" + nama.upper()
    value = os.getenv(kunci) or config._baca().get(kunci)
    try:
        day = int(str(value).strip())
        # Below 7 days is dangerous: the 7-day Report period would lose its own data,
        # which would look like a fault.
        return day if day >= 7 else bawaan
    except (TypeError, ValueError):
        return bawaan


def boleh_pangkas_status_logs(db, batas):
    """May `status_logs` rows older than `batas` be deleted?
    Returns (allowed: bool, up_to_hour: datetime|None, old_count: int).

    Rule: SUMMARIZE FIRST, THEN DELETE. Long history lives in `status_rollup_jam`;
    deleting raw rows not yet summarized destroys the very data meant to be saved,
    and pruning would still report success.
    A separate function so the decision can be tested without deleting anything.
    """
    old_age = db.execute(
        text("SELECT COUNT(*) FROM status_logs WHERE timestamp < :b"),
        {"b": batas}).scalar() or 0
    if not old_age:
        return True, rollup.jam_terakhir_diringkas(db), 0
    until_hour = rollup.jam_terakhir_diringkas(db)
    return (until_hour is not None and until_hour >= batas), until_hour, old_age


def ukuran_mb(db):
    """NSM data size in MB, wherever it is stored."""
    if dialek._mysql(db):
        from sqlalchemy import text
        n = db.execute(text(
            "SELECT SUM(data_length + index_length) / 1024 / 1024 "
            "FROM information_schema.tables WHERE table_schema = DATABASE()"
        )).scalar()
        return float(n or 0)
    return os.path.getsize(JALUR_DB) / 1024 / 1024


def ada_tabel(db, nama):
    return dialek.tabel_ada(db, nama)


def main():
    run = "--jalankan" in sys.argv
    vacuum = "--vacuum" in sys.argv
    db = SessionLocal()
    total_discard = 0
    skipped = []
    try:
        if run:
            last = db.execute(
                text("SELECT MAX(timestamp) FROM status_logs")).scalar()
            if last:
                if isinstance(last, str):
                    last = datetime.fromisoformat(last)
                if (datetime.now() - last) < timedelta(seconds=20):
                    # Name the database actually in use (not the retired `nsm.db`), so nobody checks
                    # a file that nothing writes to.
                    print("BERHENTI. Poller masih menulis ke %s."
                          % database.keterangan())
                    print("Matikan poller dan uvicorn lebih dulu, lalu ulangi.")
                    return 1

        # Size is read from the SAME path the `engine` above uses, so the reported MB
        # comes from the database whose rows were actually deleted.
        size_begin = ukuran_mb(db)
        print("=" * 74)
        print("PEMANGKASAN DATA MENTAH" + ("" if run else "  (uji coba, tidak mengubah apa pun)"))
        print("=" * 74)
        print(f"  {database.keterangan()}")
        print(f"  ukuran data sekarang: {size_begin:.1f} MB")
        print()
        print(f"  {'Tabel':<20}{'simpan':>8}{'total':>10}{'dibuang':>10}{'sisa':>10}")
        print("  " + "-" * 66)

        for nama, column, bawaan, _note in TABEL:
            if not ada_tabel(db, nama):
                print(f"  {nama:<20}{'-':>8}{'belum ada':>10}")
                continue
            day = save_day(nama, bawaan)
            batas = datetime.now() - timedelta(days=day)

            # GUARD: summarize first, then delete. If raw rows not yet in the hourly rollup
            # would be deleted, the table is skipped, not just warned about.
            # Also checked in the dry run; otherwise the dry run would not predict what the
            # real run does.
            if nama == "status_logs" and ada_tabel(db, "status_rollup_jam"):
                allowed, until_hour, _old_age = boleh_pangkas_status_logs(db, batas)
                if not allowed:
                    print(f"  {nama:<20}{str(day) + ' hr':>8}"
                          f"{'DILEWATI':>10}")
                    print(f"      Ringkasan per jam baru sampai "
                          f"{until_hour or 'belum ada sama sekali'},")
                    print(f"      sementara yang mau dibuang sampai {batas}.")
                    print(f"      Membuang baris mentah yang belum sempat")
                    print(f"      diringkas menghancurkan riwayat yang justru")
                    print(f"      hendak diselamatkan, dan tidak bisa dikembalikan.")
                    print(f"      Jalankan `python bangun_rollup.py --jalankan`")
                    print(f"      lebih dulu, lalu ulangi pemangkasan.")
                    skipped.append(nama)
                    continue
            total = db.execute(text(f"SELECT COUNT(*) FROM {nama}")).scalar() or 0
            old = db.execute(
                text(f"SELECT COUNT(*) FROM {nama} WHERE {column} < :b"),
                {"b": batas}).scalar() or 0
            print(f"  {nama:<20}{str(day) + ' hr':>8}{total:>10,}"
                  f"{old:>10,}{total - old:>10,}")
            if run and old:
                # Delete in batches, not one huge DELETE: a single transaction removing 100k rows
                # holds the write lock for seconds and grows the WAL file.
                sisa = old
                while sisa > 0:
                    n = db.execute(
                        text(f"DELETE FROM {nama} WHERE rowid IN ("
                             f"SELECT rowid FROM {nama} WHERE {column} < :b "
                             f"LIMIT 5000)"),
                        {"b": batas}).rowcount
                    db.commit()
                    if not n:
                        break
                    sisa -= n
                total_discard += old

        print()
        for nama, alasan in TIDAK_DIPANGKAS.items():
            print(f"  tidak dipangkas: {nama:<16} {alasan}")

        if not run:
            print()
            print("  Tidak ada yang diubah. Tambahkan --jalankan untuk membuang,")
            print("  dan --vacuum kalau ukuran berkasnya ikut mau dikecilkan.")
            return 0

        print()
        print(f"  {total_discard:,} baris dibuang.")
        if skipped:
            # Mentioned again at the end so a run that skipped something does not read as
            # fully successful.
            print()
            print(f"  DILEWATI: {', '.join(skipped)} — ringkasan per jam belum")
            print("  mengejar batas pemangkasan. Baris mentahnya SENGAJA tidak")
            print("  dibuang, karena membuangnya berarti menghancurkan riwayat")
            print("  yang belum sempat diselamatkan. Jalankan lebih dulu:")
            print("      python bangun_rollup.py --jalankan")

        if vacuum and not dialek._mysql(db):
            print("  VACUUM berjalan, berkas ditulis ulang. Bisa satu-dua menit...")
            db.close()
            with engine.connect() as connection:
                connection.exec_driver_sql("VACUUM")
            size_end = os.path.getsize(JALUR_DB) / 1024 / 1024
            print(f"  ukuran nsm.db: {size_begin:.1f} MB -> {size_end:.1f} MB")
        elif vacuum:
            # `VACUUM` is SQLite. The InnoDB equivalent, `OPTIMIZE TABLE`, copies the whole
            # table and blocks writes (minutes on a 500k-row table).
            # Deliberately not automatic: InnoDB reuses freed space itself, so compaction is
            # rarely needed and should be a conscious decision taken when monitoring may stop.
            print("  --vacuum DILEWATI: basis datanya MySQL.")
            print("  Padanannya `OPTIMIZE TABLE` mengunci penulisan selama")
            print("  tabelnya disalin, dan poller akan berhenti mencatat")
            print("  selama itu. InnoDB memakai ulang ruang bekas hapusan")
            print("  sendiri, jadi ini hampir tidak pernah diperlukan.")
        elif not dialek._mysql(db):
            print("  Ukuran berkas belum mengecil: ruang bekas hapusan disimpan")
            print("  SQLite untuk dipakai ulang. Tambahkan --vacuum kalau mau")
            print("  ruangnya benar-benar dikembalikan ke disk.")
        else:
            print("  Ruang bekas hapusan dipakai ulang InnoDB sendiri; ukuran")
            print("  di disk tidak langsung mengecil, dan itu memang wajar.")
        print()
        print("  Nyalakan lagi poller dan uvicorn.")
        return 0
    finally:
        try:
            db.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())

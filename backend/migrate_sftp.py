"""Add tables `transfer_berkas` and `sesi_sftp`, plus the SFTP service on .103.

Safe to run repeatedly: existing tables are skipped and an already registered
service is not duplicated.

    python migrate_sftp.py
"""
import os
import sqlite3

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

TABEL = {
    "transfer_berkas": """
        CREATE TABLE transfer_berkas (
            id         INTEGER PRIMARY KEY,
            device_id  INTEGER REFERENCES devices(id),
            waktu      DATETIME,
            pid        INTEGER,
            pengguna   VARCHAR,
            ip_klien   VARCHAR,
            aksi       VARCHAR,
            jalur      VARCHAR,
            jalur_baru VARCHAR,
            byte_baca  FLOAT DEFAULT 0,
            byte_tulis FLOAT DEFAULT 0
        )
    """,
    "sesi_sftp": """
        CREATE TABLE sesi_sftp (
            id         INTEGER PRIMARY KEY,
            device_id  INTEGER REFERENCES devices(id),
            pid        INTEGER,
            pengguna   VARCHAR,
            ip_klien   VARCHAR,
            mulai      DATETIME,
            diperbarui DATETIME
        )
    """,
}

# The page filters by time ("who fetched what today", "volume per user").
# Without indexes every page load scans the whole table, which feels fast while
# data is small and then degrades gradually.
INDEKS = [
    ("idx_transfer_waktu", "transfer_berkas(waktu)"),
    ("idx_transfer_pengguna", "transfer_berkas(pengguna, waktu)"),
    ("idx_sesi_pid", "sesi_sftp(device_id, pid)"),
]


def main():
    if not os.path.exists(DB):
        print("BERHENTI: %s tidak ada." % DB)
        raise SystemExit(1)

    db = sqlite3.connect(DB)
    ada = set(r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"))

    for nama, sql in TABEL.items():
        if nama in ada:
            print("  lewat  tabel %s sudah ada" % nama)
        else:
            db.execute(sql)
            print("  BUAT   tabel %s" % nama)

    for nama, target in INDEKS:
        db.execute("CREATE INDEX IF NOT EXISTS %s ON %s" % (nama, target))
    print("  indeks siap (%d)" % len(INDEKS))

    # SFTP service on testUbuntu.
    #
    # Registered as a regular `services` row with `jenis='sftp'`, not a new column
    # on `devices`. The poller selects web logs by `jenis='http'`, so this row never
    # reaches the Apache reader, and any other SFTP host only needs one more row
    # here, no code change.
    dev = db.execute(
        "SELECT id FROM devices WHERE ip_address = '192.168.56.103'").fetchone()
    if dev is None:
        print("  lewat  device .103 tidak ada, layanan SFTP tidak didaftarkan")
    else:
        already = db.execute(
            "SELECT id FROM services WHERE device_id = ? AND jenis = 'sftp'",
            (dev[0],)).fetchone()
        if already:
            print("  lewat  layanan SFTP sudah terdaftar (id %d)" % already[0])
        else:
            db.execute(
                "INSERT INTO services (device_id, nama, jenis, port, aktif, "
                "log_akses, timeout_detik) VALUES (?,?,?,?,?,?,?)",
                (dev[0], "Server Berkas SFTP", "sftp", 22, 1,
                 "/var/log/auth.log", 5))
            print("  BUAT   layanan 'Server Berkas SFTP' di device %d" % dev[0])

    db.commit()
    db.close()
    print("\nSelesai.")


if __name__ == "__main__":
    main()

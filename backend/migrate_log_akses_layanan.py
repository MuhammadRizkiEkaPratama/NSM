"""Migration: each HTTP service names its own access log.

WHY
---
NSM used ONE global access log path (`ACCESS_LOG` in config, default
`/var/log/apache2/access.log`). That is right while one machine serves one web
service, and silently wrong once it serves two.

`.103` runs TWO web services, both registered in NSM:

    #4  Web Server BSP   http :80     <- Apache log, READ
    #5  E-Canteen v2     http :8080   <- Spring Boot, NEVER READ

E-Canteen is the service people actually use most, yet its traffic was never
recorded, and nothing on screen says so: the Traffic page looks normal. The shape of
the error is not a wrong number but a correct number for a narrower question than
the reader assumes.

WHY IN `services`, NOT `devices` OR CONFIG
------------------------------------------
Because the LOG belongs to the SERVICE, not the machine. One machine can run Apache,
Nginx, and three Spring Boot apps, each with its own log in a different place.
Storing it in `devices` would force one answer to a question with many answers.
Registering a new HTTP service then makes its log readable without changing code.

NULL MEANS "USE THE DEFAULT PATH FROM CONFIG"
---------------------------------------------
Existing services get nothing and their behavior does NOT change. A migration that
changes the behavior of services it never mentions is the fastest way to make people
afraid to run migrations.

ONLY ADDS two columns, then fills two rows that are already known:

    services.log_akses     access log path of that service
    akses_web.service_id   which service served this request

No existing row is changed or removed. Safe to re-run. Run with the poller and
uvicorn STOPPED:

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\activate
    python migrate_log_akses_layanan.py
"""
import os
import sqlite3

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

# Known log path for each service. Only filled when the column is still empty, so a
# value you changed yourself is not overwritten.
ISIAN = {
    "Web Server BSP": "/var/log/apache2/access.log",
    "E-Canteen v2":   "/opt/ecanteen/logs/access.log",
}

conn = sqlite3.connect(DB, timeout=20)
cur = conn.cursor()
cur.execute("PRAGMA busy_timeout=20000")

punya = [r[1] for r in cur.execute("PRAGMA table_info(services)").fetchall()]
if "log_akses" in punya:
    print("- kolom services.log_akses sudah ada")
else:
    cur.execute("ALTER TABLE services ADD COLUMN log_akses VARCHAR")
    print("- kolom services.log_akses ditambahkan")

# Second column: each `akses_web` row names the service that served it.
#
# Without it, two access logs on one machine produce rows sitting together under the
# same `device_id` with no way to tell them apart, and "how much E-Canteen traffic"
# could only be answered by guessing from the path, although `/` can be served by
# both.
#
# OLD rows are left NULL on purpose, not guessed backwards: nobody knew which service
# owned them when they were written, and a guess would make never-known data look like
# measured data.
punya_aw = [r[1] for r in cur.execute("PRAGMA table_info(akses_web)").fetchall()]
if "service_id" in punya_aw:
    print("- kolom akses_web.service_id sudah ada")
else:
    cur.execute("ALTER TABLE akses_web ADD COLUMN service_id INTEGER")
    print("- kolom akses_web.service_id ditambahkan")

print("\nMengisi jalur log yang sudah diketahui:")
for nama, jalur in ISIAN.items():
    baris = cur.execute(
        "SELECT id, log_akses FROM services WHERE nama = ?", (nama,)).fetchone()
    if baris is None:
        print(f"  {nama}: layanan tidak ada, dilewati")
        continue
    sid, lama = baris
    if lama:
        print(f"  {nama}: sudah terisi ({lama}), TIDAK ditimpa")
        continue
    cur.execute("UPDATE services SET log_akses = ? WHERE id = ?", (jalur, sid))
    print(f"  {nama}: -> {jalur}")

conn.commit()

print("\nKeadaan seluruh layanan HTTP sesudah migrasi:")
for sid, nama, port, jalur in cur.execute(
        "SELECT id, nama, port, log_akses FROM services "
        "WHERE jenis = 'http' ORDER BY id"):
    print(f"  #{sid} {nama:<18} :{port:<6} {jalur or '(pakai bawaan config)'}")

print("\nTabel lama (harus utuh):")
for t in ("devices", "services", "akses_web", "posisi_log", "status_logs"):
    try:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} baris")
    except sqlite3.OperationalError:
        print(f"  {t}: belum ada")

conn.close()
print("\nMigrasi selesai.")
print("\nCATATAN: menambah kolom saja belum membuat NSM membaca log E-Canteen.")
print("Log-nya belum ada di .103 — Tomcat harus disuruh menulisnya dulu.")

"""Migration: `ssh_key_path` column on the devices table.

Lets a device be accessed with an SSH KEY instead of a password.

Device passwords are stored as-is in `nsm.db`, and `nsm.db` goes into the
nightly backup zip that is copied to cloud storage, so usable login
credentials leave the machine every day. With a key, the database stores only
the file PATH; the secret stays on the host and is never copied.

Caveat: the private key file has no passphrase, because the poller runs
unattended. So this is not "no secrets on disk" but "the secret is not inside
the file copied to the cloud every night", plus it can be revoked by removing
one line from authorized_keys without changing the account password.

Safe to run repeatedly. Run with the poller and uvicorn STOPPED:

    cd C:\\\\Users\\\\<user>\\\\NSM\\\\backend
    venv\\\\Scripts\\\\activate
    python migrate_ssh_key.py
"""
import os
import sqlite3

# Path is pinned to this file's folder, not the current working directory.
# With a relative path, running from the wrong folder raises NO error: SQLite
# silently creates a new empty database there. See `database.py`.
DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

conn = sqlite3.connect(DB, timeout=20)
cur = conn.cursor()
cur.execute("PRAGMA busy_timeout=20000")

punya = {r[1] for r in cur.execute("PRAGMA table_info(devices)").fetchall()}

if "ssh_key_path" in punya:
    print("- kolom 'devices.ssh_key_path' sudah ada, lewati")
else:
    cur.execute("ALTER TABLE devices ADD COLUMN ssh_key_path VARCHAR")
    print("- kolom 'devices.ssh_key_path' ditambahkan")

conn.commit()

print("\nStruktur devices:")
for r in cur.execute("PRAGMA table_info(devices)").fetchall():
    print("   ", r[1], r[2])

print("\nDevice yang ada (kolom baru masih kosong, itu wajar):")
for r in cur.execute("select id, name, ip_address, platform, "
                     "case when password is not null and password != '' "
                     "then 'password' else '-' end, "
                     "coalesce(ssh_key_path,'-') from devices order by id"):
    print("   id=%-3s %-22s %-16s %-10s login=%-9s kunci=%s" % r)

# Existing data is not touched; printed as proof.
print("\nTabel lain (harus utuh):")
for t in ("status_logs", "device_events", "bandwidth_samples",
          "services", "service_checks", "service_events"):
    try:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} baris")
    except sqlite3.OperationalError:
        print(f"  {t}: belum ada")

conn.close()
print("\nMigrasi selesai.")

"""Add the Cisco router (GNS3) to the devices table.

Run once, with the server (poller/uvicorn) STOPPED so the DB is not locked:

    python add_cisco_router.py

Safe to rerun: skipped if the IP already exists.
"""
import os
import sqlite3

# Path is pinned to this file's folder, not the current working directory.
# With a relative path, running from the wrong folder raises NO error: SQLite
# silently creates a new empty database there and you just see "zero rows".
# Full rationale is in `database.py`.
DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

# CREDENTIALS ARE READ FROM `.env`, NEVER WRITTEN HERE.
#
# This file is tracked by Git, and Git history is permanent and spreads: one
# `push` is enough to carry a router password somewhere unintended, and
# deleting it later does not remove the commit that contained it.
#
# The script is run by hand, so if a value is missing from `.env` it STOPS
# with a message naming what is missing, instead of silently storing an empty
# password. A device with an empty password looks added successfully, then
# fails when used, far from the cause.
_USER = os.environ.get("DEVICE_SSH_USER") or ""
_SANDI = os.environ.get("DEVICE_SSH_PASS") or ""
if not (_USER and _SANDI):
    try:
        import config
        _USER = _USER or config.get_ssh_user()
        _SANDI = _SANDI or config.get_ssh_pass()
    except Exception:
        pass
if not (_USER and _SANDI):
    raise SystemExit(
        "DEVICE_SSH_USER / DEVICE_SSH_PASS belum diisi.\n"
        "Isi di backend/.env (lihat .env.contoh), atau setel sebagai variabel\n"
        "lingkungan sebelum menjalankan skrip ini."
    )

DEVICE = {
    "name": "Router Cisco GNS3",
    "ip_address": "192.168.56.60",
    "device_type": "router",  # dashboard category
    "platform": "cisco_ios",  # netmiko device_type string
    "username": _USER,
    "password": _SANDI,
    "location": "Lab GNS3",
}

conn = sqlite3.connect(DB)
cur = conn.cursor()

cur.execute("SELECT id FROM devices WHERE ip_address = ?", (DEVICE["ip_address"],))
row = cur.fetchone()
if row:
    print(f"- device dengan IP {DEVICE['ip_address']} sudah ada (id {row[0]}), lewati")
else:
    cur.execute(
        "INSERT INTO devices (name, ip_address, device_type, platform, username, password, location) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            DEVICE["name"], DEVICE["ip_address"], DEVICE["device_type"],
            DEVICE["platform"], DEVICE["username"], DEVICE["password"], DEVICE["location"],
        ),
    )
    conn.commit()
    print(f"- router ditambahkan sebagai id {cur.lastrowid}")

print("\nIsi tabel devices sekarang:")
for r in cur.execute("SELECT id, name, ip_address, device_type, platform FROM devices").fetchall():
    print("  ", r)

conn.close()

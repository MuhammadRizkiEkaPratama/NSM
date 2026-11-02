"""Add the testUbuntu VM (host-only) to the devices table.

Run with the server (poller/uvicorn) STOPPED so the DB is not locked:

    python add_testubuntu.py

Safe to rerun: skipped if the IP already exists.

Note: the "Detail" (SSH) button needs OpenSSH server inside testUbuntu. If it
is missing, run INSIDE testUbuntu:
    sudo apt update && sudo apt install -y openssh-server
    sudo systemctl enable --now ssh
Without it the device still shows UP (ping works), but Detail fails with
"Connection refused".
"""
import os
import sqlite3

# Path is pinned to this file's folder, not the current working directory.
# With a relative path, running from the wrong folder raises NO error: SQLite
# silently creates a new empty database there and you just see "zero rows".
# Full rationale is in `database.py`.
DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

DEVICE = {
    "name": "VM testUbuntu",
    "ip_address": "192.168.56.103",  # testUbuntu host-only IP (from `ip a`)
    "device_type": "server",  # server -> gets a Detail button on the dashboard
    "platform": "linux",  # netmiko device_type string
    "username": "doni",
    "password": "ExampleLabPass123",
    "location": "VirtualBox (host-only)",
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
    print(f"- testUbuntu ditambahkan sebagai id {cur.lastrowid}")

print("\nIsi tabel devices sekarang:")
for r in cur.execute("SELECT id, name, ip_address, device_type, platform FROM devices").fetchall():
    print("  ", r)

conn.close()

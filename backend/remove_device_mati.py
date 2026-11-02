"""Delete the 'Device Mati' device (192.168.1.250) and its status history.

Run with the poller/uvicorn stopped so the database is not locked:
    python remove_device_mati.py
"""
import os
import sqlite3

# Path is anchored to this file's folder, not the current directory: with a
# relative path SQLite would silently create an empty database elsewhere. See `database.py`.
DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

IP = "192.168.1.250"

conn = sqlite3.connect(DB)
cur = conn.cursor()

cur.execute("SELECT id, name FROM devices WHERE ip_address = ?", (IP,))
row = cur.fetchone()
if not row:
    print(f"- tidak ada device dengan IP {IP}, tidak ada yang dihapus")
else:
    dev_id, name = row
    cur.execute("DELETE FROM status_logs WHERE device_id = ?", (dev_id,))
    cur.execute("DELETE FROM devices WHERE id = ?", (dev_id,))
    conn.commit()
    print(f"- '{name}' (id {dev_id}) dihapus beserta riwayat status-nya")

print("\nIsi tabel devices sekarang:")
for r in cur.execute("SELECT id, name, ip_address, device_type, platform FROM devices").fetchall():
    print("  ", r)

conn.close()

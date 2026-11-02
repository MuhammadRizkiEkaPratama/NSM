"""Migration: email notifications when an important device has a problem.

Two new columns:
  devices.penting                 0/1, default 0 (no notifications)
  device_events.notif_terkirim    when the email for that event was sent

The marker lives on the EVENT row, not on the device, so one outage is never sent
twice. With the marker on the device, a poller that died and restarted could resend
the email for the same outage.

Every device starts with penting = 0. Nothing is sent until you mark devices in the
dashboard; this is deliberate, because an alert tool that sounds for everything
quickly turns into noise.

Safe to re-run. Run with the poller and uvicorn STOPPED:

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\activate
    python migrate_notifikasi.py
"""
import os
import sqlite3

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "nsm.db")

conn = sqlite3.connect(DB)
cur = conn.cursor()


def tambah(tabel, nama, tipe, ekstra=""):
    column = {r[1] for r in cur.execute(f"PRAGMA table_info({tabel})").fetchall()}
    if nama in column:
        print(f"- {tabel}.{nama} sudah ada, lewati")
        return False
    cur.execute(f"ALTER TABLE {tabel} ADD COLUMN {nama} {tipe} {ekstra}".strip())
    print(f"- {tabel}.{nama} ditambahkan")
    return True


tambah("devices", "penting", "INTEGER", "DEFAULT 0")
tambah("device_events", "notif_terkirim", "DATETIME")

n = cur.execute("UPDATE devices SET penting = 0 WHERE penting IS NULL").rowcount
if n:
    print(f"- {n} device yang nilainya kosong diisi penting = 0")

# Old events must not trigger an email flood when the feature is switched on. All of
# them are marked as already sent, so notifications only apply to outages that happen
# AFTER this.
sudah = cur.execute(
    "UPDATE device_events SET notif_terkirim = CURRENT_TIMESTAMP "
    "WHERE notif_terkirim IS NULL"
).rowcount
print(f"- {sudah} kejadian lama ditandai 'sudah terkirim' "
      f"(supaya tidak membanjiri kotak masuk saat fitur dinyalakan)")

conn.commit()

print("\nStatus device:")
for r in cur.execute(
    "SELECT id, name, ip_address, aktif, penting FROM devices ORDER BY id"
).fetchall():
    print(f"   {r[0]}. {r[1]:20} {r[2]:16} "
          f"{'aktif ' if r[3] else 'dijeda'}  "
          f"notifikasi {'MENYALA' if r[4] else 'mati'}")

conn.close()
print("\nMigrasi selesai. Belum ada device yang mengirim notifikasi — "
      "tandai sendiri lewat tombol lonceng di dashboard.")

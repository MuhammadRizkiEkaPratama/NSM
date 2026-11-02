from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from sqlalchemy import desc
from models import (DeviceEvent, PosisiLog)


def status_terakhir(db, device_id):
    """Latest event for the device, or None if it has none."""
    return (
        db.query(DeviceEvent)
        .filter(DeviceEvent.device_id == device_id)
        .order_by(desc(DeviceEvent.timestamp), desc(DeviceEvent.id))
        .first()
    )


# Flat copy of the device fields used by network work.
# Worker threads must not touch SQLAlchemy Device objects: sessions are not
# thread-safe, and with expire_on_commit a field access after a commit silently
# issues a SELECT from the worker thread. Only plain strings and numbers cross
# into threads.
Sasaran = namedtuple("Sasaran", [
    "id", "name", "ip_address", "platform",
    "username", "password", "ssh_key_path",
    "snmp_user", "snmp_auth_pass", "snmp_priv_pass",
    "snmp_auth_proto", "snmp_priv_proto", "snmp_port",
])


def sasaran(d):
    """Flat copy of a Device for use in worker threads."""
    return Sasaran(*(getattr(d, nama) for nama in Sasaran._fields))


# Max devices read concurrently. Deliberately lower than the ping/port-check
# concurrency: each read is a full SSH session, some lab VMs have little RAM, and
# sshd's default MaxStartups is 10 unauthenticated sessions.
PEKERJA_BACA = 8


def kerjakan_bersamaan(daftar, kerja, pekerja=PEKERJA_BACA):
    """Run `kerja(x)` for each x concurrently and return `[(x, output, error)]` in input order.
    Errors are returned, not raised, so one failing device cannot stop the others.
    `kerja` must not touch the database.
    """
    if not daftar:
        return []

    def bungkus(x):
        try:
            return x, kerja(x), None
        except Exception as e:
            return x, None, e

    with ThreadPoolExecutor(max_workers=min(len(daftar), pekerja)) as pool:
        return list(pool.map(bungkus, daftar))


def posisi_log(db, device_id, jalur):
    # `order_by` is required: the table was once not unique per (device, file), and an
    # unordered `.first()` could pick a stale row, rewinding the read position
    # (duplicate rows) or skipping log lines. The unique index now prevents duplicates;
    # the ordering is a second layer of defense.
    p = (db.query(PosisiLog)
         .filter(PosisiLog.device_id == device_id, PosisiLog.jalur == jalur)
         .order_by(PosisiLog.diperbarui.desc(), PosisiLog.id.desc())
         .first())
    if p is None:
        p = PosisiLog(device_id=device_id, jalur=jalur, posisi=0,
                      ukuran_terakhir=0, diperbarui=datetime.now())
        db.add(p)
        db.flush()
    return p

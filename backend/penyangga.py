"""Local buffer: NSM keeps recording even when its database is unreachable.

Since NSM's data moved to MySQL, "database unreachable" is a real state, and
a monitor hits it exactly when it is most needed: network trouble often cuts
the database connection too. A monitor that stops recording during an outage
is useless, so the MySQL move and this buffer go together.

The easy thing to miss: when MySQL is down the poller loses not only where
to WRITE but also where to READ its device and service list. Without a copy
it stops working entirely. So `devices` and `services` are mirrored into the
buffer on every successful round, along with each device's LAST STATUS row:
the poller detects outages from status CHANGES, and without the previous
state the first buffered round would log false transitions.

The schema is identical to MySQL by design. Writers do not need to know
where they write, and draining the buffer into MySQL uses the same
`pindah_data.salin_semua()` as migrating `nsm.db` to MySQL. Code that only
runs during outages is the least tested; sharing the everyday path makes it
trustworthy.

IDs are not carried over. Rows born in the buffer start at `id` 1, which
already exists in MySQL, so on drain the `id` is dropped and MySQL assigns a
new one. `device_id` and `service_id` stay correct because the mirrored
reference tables use the same IDs.
"""
import os
import time

from sqlalchemy import delete, func, insert, inspect, select
from sqlalchemy.dialects import sqlite as _sqlite

import database
import models
import pindah_data

# Reference tables: COPIED INTO the buffer, never sent back.
#
# MySQL owns their content. Sending them back on drain would overwrite changes
# made via the web UI during the outage (e.g. a paused device would resume).
ACUAN = ("devices", "services")

# Tables whose rows are born in the buffer and must be moved to MySQL.
# Taken from the foreign-key-safe order, minus the reference tables.
HASIL = tuple(t for t in pindah_data.URUTAN if t not in ACUAN)

# How long to treat MySQL as "down" before retrying. Without this backoff
# every poller round pays the full connection timeout, which is as bad as
# stopping.
JEDA_COBA_LAGI = 30.0

_gagal_sejak = None
_coba_berikutnya = 0.0


def berkas_ada():
    return os.path.exists(database.JALUR_PENYANGGA)


def siapkan():
    """Ensure the buffer has every table AND every column. Cheap when complete.

    `create_all` only creates MISSING tables; it never adds columns to existing
    ones. `penyangga.db` is long-lived while the models keep growing, so a
    migration that adds a column (e.g. `konfig_snapshots.acl_berubah`) updates
    MySQL and `nsm.db` but not the buffer. On drain, the `SELECT` then fails
    with `no such column`, which blocks the entire backlog indefinitely.

    Missing columns are therefore added here once, when detected, as NULLABLE
    without a default: values only pass through before reaching MySQL, where the
    real schema applies.
    """
    database.Base.metadata.create_all(database.engine_penyangga)
    _selaraskan_kolom()


def _selaraskan_kolom():
    """Add model columns missing from the buffer's tables. Idempotent."""
    ins = inspect(database.engine_penyangga)
    md = database.Base.metadata
    exists_table = set(ins.get_table_names())
    dial = _sqlite.dialect()
    with database.engine_penyangga.begin() as p:
        for nama, table in md.tables.items():
            if nama not in exists_table:
                continue  # create_all already made it complete
            kol_exists = {c["name"] for c in ins.get_columns(nama)}
            for kol in table.columns:
                if kol.name in kol_exists:
                    continue
                tipe = kol.type.compile(dialect=dial)
                # Column and table names come from our own models, not external input,
                # but identifiers are still quoted for hygiene.
                p.exec_driver_sql(
                    'ALTER TABLE "%s" ADD COLUMN "%s" %s' % (nama, kol.name, tipe))
                print("  [penyangga] kolom disamakan: %s.%s (%s)"
                      % (nama, kol.name, tipe))


def mysql_hidup():
    """Try to connect once. Never raises."""
    try:
        with database.engine.connect() as k:
            k.execute(select(1))
        return True
    except Exception:
        return False


def sesi():
    """Return (session, ke_penyangga).

    While MySQL is healthy this is just `SessionLocal()` with no extra cost; the
    check only runs after a failure.
    """
    global _gagal_sejak, _coba_berikutnya

    if _gagal_sejak is not None and time.time() < _coba_berikutnya:
        siapkan()
        return database.SessionPenyangga(), True

    if not database.PAKAI_MYSQL:
        return database.SessionLocal(), False

    if mysql_hidup():
        if _gagal_sejak is not None:
            _gagal_sejak = None
        return database.SessionLocal(), False

    if _gagal_sejak is None:
        _gagal_sejak = time.time()
    _coba_berikutnya = time.time() + JEDA_COBA_LAGI
    siapkan()
    return database.SessionPenyangga(), True


def lama_terputus():
    """Seconds MySQL has been unreachable. None when healthy."""
    if _gagal_sejak is None:
        return None
    return time.time() - _gagal_sejak


def cermin_acuan(db):
    """Copy devices, services, and each device's last status into the buffer.

    Called from poller rounds that SUCCESSFULLY wrote to MySQL. The cost is
    small (a few dozen rows) and paid while healthy, not during an outage when
    there is nowhere to fetch it from.
    """
    siapkan()
    md = database.Base.metadata

    with database.engine_penyangga.begin() as p:
        for nama in ACUAN:
            table = md.tables[nama]
            line = [dict(r._mapping) for r in db.execute(select(table))]
            p.execute(delete(table))
            if line:
                p.execute(insert(table), line)

        # Last status row per device. The poller only needs the LATEST state, not the
        # history, so one row per device is copied.
        sl = md.tables["status_logs"]
        last = db.execute(
            select(func.max(sl.c.id)).group_by(sl.c.device_id)).scalars().all()
        p.execute(delete(sl))
        batas_cermin = 0
        if last:
            line = [dict(r._mapping) for r in
                     db.execute(select(sl).where(sl.c.id.in_(last)))]
            if line:
                p.execute(insert(sl), line)
                batas_cermin = max(r["id"] for r in line)

        # This boundary separates the mirror copy from the backlog.
        #
        # Mirrored rows already exist in MySQL. If they were sent on drain, every
        # outage would leave a duplicate per device, and duplicates in `status_logs`
        # skew availability (the denominator grows without new measurements).
        #
        # Rows born in the buffer always have higher IDs, since SQLite continues from
        # the highest existing value, so one number separates the two.
        #
        # Stored in a separate table NOT registered in the models, so it is never
        # carried into MySQL.
        p.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS cermin_batas "
            "(tabel TEXT PRIMARY KEY, id_maks INTEGER)")
        p.exec_driver_sql(
            "INSERT INTO cermin_batas (tabel, id_maks) VALUES ('status_logs', ?) "
            "ON CONFLICT(tabel) DO UPDATE SET id_maks = excluded.id_maks",
            (batas_cermin,))


_cermin_berikutnya = 0.0

# The reference mirror is refreshed every 5 minutes, not every round.
#
# Its content (devices, services) rarely changes while the poller runs every
# 5 seconds; mirroring each round would mean 17,280 writes a day. Trade-off:
# the buffer's device list can lag up to 5 minutes, so a device added just
# before an outage is not monitored during it.
JEDA_CERMIN = 300.0


def rawat(db, dipenyangga):
    """Called every poller round. Never raises.

    When healthy: refresh the reference mirror occasionally, then drain the
    backlog. While buffering: do nothing, since there is nowhere to read from or
    send to.

    Never raises because failed maintenance must not stop monitoring: a failed
    mirror at worst costs readiness for the NEXT outage, while crashing the
    poller round would cost monitoring TODAY.
    """
    global _cermin_berikutnya
    if dipenyangga or not database.PAKAI_MYSQL:
        return None

    try:
        if time.time() >= _cermin_berikutnya:
            cermin_acuan(db)
            _cermin_berikutnya = time.time() + JEDA_CERMIN
    except Exception as e:
        print("  [penyangga] gagal mencerminkan acuan: %s" % str(e)[:120])

    try:
        moved = kosongkan()
        if moved:
            total = sum(moved.values())
            print("  [penyangga] %d baris tertahan dikirim ke basis data: %s"
                  % (total, ", ".join("%s=%d" % kv
                                      for kv in sorted(moved.items()))))
            return moved
    except Exception as e:
        print("  [penyangga] gagal mengosongkan: %s" % str(e)[:120])
    return None


def jumlah_tertahan():
    """{table: count} of measurement rows still waiting in the buffer.

    Reference tables are not counted: they are copies, not backlog.
    """
    if not berkas_ada():
        return {}
    md = database.Base.metadata
    ada = set(inspect(database.engine_penyangga).get_table_names())
    hasil = {}
    with database.engine_penyangga.connect() as p:
        limit = _batas_cermin(p)
        for nama in HASIL:
            if nama not in ada or nama not in md.tables:
                continue
            table = md.tables[nama]
            perintah = select(func.count()).select_from(table)
            if nama in limit:
                # Mirrored rows are not backlog: they are copies from MySQL, not unsent
                # measurements.
                perintah = perintah.where(table.c.id > limit[nama])
            n = p.execute(perintah).scalar() or 0
            if n:
                hasil[nama] = n
    return hasil


def _batas_cermin(sambungan):
    """{table: highest mirrored id}. Empty if never mirrored."""
    try:
        line = sambungan.exec_driver_sql(
            "SELECT tabel, id_maks FROM cermin_batas").fetchall()
    except Exception:
        return {}
    return {t: (i or 0) for t, i in line}


def _buang_cermin():
    """Delete mirrored rows from the buffer before the rest is sent.

    Called right before draining; afterwards everything left belongs to the
    buffer.
    """
    md = database.Base.metadata
    with database.engine_penyangga.begin() as p:
        limit = _batas_cermin(p)
        for nama, id_max in limit.items():
            if nama in md.tables and id_max:
                p.execute(md.tables[nama].delete().where(
                    md.tables[nama].c.id <= id_max))
        p.exec_driver_sql("DELETE FROM cermin_batas")


def kosongkan(lapor=None):
    """Move the buffer's content to MySQL, then clean up.

    Returns {table: count}; empty means there was no backlog.

    ORDER: write to MySQL first, then delete from the buffer, per batch in
    `pindah_data.salin()`. Reversed, a dropped connection mid-way would lose rows
    from both places; this way the worst case is DUPLICATE rows, which are far
    easier to clean up than lost ones.
    """
    if not berkas_ada() or not database.PAKAI_MYSQL:
        return {}
    if not jumlah_tertahan():
        return {}
    if not mysql_hidup():
        return {}

    # Drop the mirror FIRST so only real backlog remains.
    _buang_cermin()

    md = database.Base.metadata

    # Parent tables are shifted first and keep their IDs.
    #
    # `konfig_temuan` references `konfig_snapshots` and `firewall_aturan`
    # references `firewall_snapshot`. If MySQL renumbered the parents while the
    # children kept old IDs, children would attach to the WRONG parent, silently
    # assigning one device's compliance findings to another device's snapshot.
    # See `pindah_data.INDUK_ANAK`.
    geseran = pindah_data.shift_parent(
        database.engine_penyangga, database.engine, md)
    if geseran and lapor:
        print("  [penyangga] id induk digeser: %s"
              % ", ".join("%s+%d" % kv for kv in sorted(geseran.items())))

    hasil = pindah_data.copy_all(
        database.engine_penyangga, database.engine, md,
        hapus_sumber=True, hanya=set(HASIL), diam=lapor is None,
        # `id` is dropped for ordinary tables: buffer IDs are unrelated to MySQL IDs.
        # See `pindah_data.salin()`.
        abaikan_id=True,
        # Except the parent tables above, whose shifted IDs are safe and MUST be kept
        # so children still point to the right row.
        jaga_id=set(pindah_data.INDUK_ANAK))

    # The reference mirror is dropped too: it is rewritten on the next healthy
    # round, and a stale copy could only mislead.
    with database.engine_penyangga.begin() as p:
        for nama in ACUAN:
            p.execute(delete(md.tables[nama]))

    return {k: v for k, v in hasil.items() if v}

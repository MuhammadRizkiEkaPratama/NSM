"""Copy rows between NSM databases, whatever the engine.

One copier serves two users: the one-time `nsm.db` (SQLite) -> MySQL move, and
draining `penyangga.db` into MySQL after the network recovers. Sharing the code
means the rarely-run drain path is the same code as the tested migration path.

Table order is not alphabetical: parents must precede children (`devices` before
`status_logs`, `konfig_snapshots` before `konfig_temuan`, `firewall_snapshot`
before `firewall_aturan`) because of foreign keys.

Re-runnable without duplicates: for numeric-key tables only rows with `id`
greater than the destination's max `id` are copied, so an interrupted move
resumes where it stopped. Natural-key tables (`nama_alamat.ip`,
`orang_ldap.uid`) are overwritten, since the same row means an updated value.
"""
import sys

from sqlalchemy import func, select, text, tuple_

# Order that is safe for foreign keys: parents first, children last.
URUTAN = [
    "devices",
    "ban_aktif",
    "services",
    "nama_alamat",
    "orang_ldap",
    "status_logs",
    "status_rollup_jam",
    "device_events",
    "service_checks",
    "service_events",
    "akses_web",
    "posisi_log",
    "flow_koneksi",
    "identitas_perangkat",
    "konfig_snapshots",
    "konfig_temuan",
    "bandwidth_samples",
    "transfer_berkas",
    "sesi_sftp",
    "firewall_snapshot",
    "firewall_aturan",
    "firewall_perubahan",
]

# Tables whose key is not a sequential number; rows are overwritten, not appended.
#
# A value is one column name (str) or several (tuple) for a composite key.
# `posisi_log` is the composite key `(device_id, jalur)`: it holds one "read up to
# byte N" marker per (device, log file), unique via `uq_posisi_device_jalur` in
# MySQL. Treating it as an ordinary numeric table made a buffer drain fail with a
# duplicate-entry error and stall all other backlog. Overwriting is also correct
# semantically: the position written during an outage is newer than the one frozen
# in MySQL, and keeping the old one would re-read already-sent log lines.
KUNCI_ALAMI = {"nama_alamat": "ip", "orang_ldap": "uid",
               "posisi_log": ("device_id", "jalur")}

# PARENT -> [(child table, column pointing to the parent)]
#
# When the buffer is drained, row `id`s are discarded so MySQL assigns new ones.
# Two table pairs reference each other (`konfig_temuan.snapshot_id` ->
# `konfig_snapshots.id`); if the parent got a new id while the child kept the old
# one, children would attach to the wrong parent. The unique index
# `ux_temuan_snapshot_aturan` caught this in testing; without it the rows would
# be accepted silently and be wrong forever.
INDUK_ANAK = {
    "konfig_snapshots": [("konfig_temuan", "snapshot_id")],
    "firewall_snapshot": [("firewall_aturan", "snapshot_id")],
}


def shift_parent(engine_sumber, engine_tujuan, metadata):
    """Shift parent ids in the SOURCE so they do not collide with the destination.

    Used before draining the buffer: instead of dropping the parent `id` and losing
    the link to its children, the id is moved to an unused range in the destination
    and the child pointer column is shifted by the same amount.

    Return {parent_table: shift} for printing if needed.
    """
    hasil = {}
    for parent, child_child in INDUK_ANAK.items():
        if parent not in metadata.tables:
            continue
        t_parent = metadata.tables[parent]

        with engine_sumber.connect() as s:
            limit = s.execute(
                select(func.min(t_parent.c.id), func.max(t_parent.c.id))).one()
        small, large = limit
        if small is None:
            continue

        with engine_tujuan.connect() as t:
            max_destination = t.execute(
                select(func.max(t_parent.c.id))).scalar() or 0

        # The result must be above the max id in the DESTINATION (no collision there) and
        # above the max id in the SOURCE (no collision while rows are shifted one by one).
        shift = max(max_destination + 1 - small, large + 1 - small)
        if shift <= 0:
            continue

        with engine_sumber.begin() as s:
            for child, kolom in child_child:
                if child in metadata.tables:
                    t_child = metadata.tables[child]
                    s.execute(t_child.update().values(
                        {kolom: t_child.c[kolom] + shift}))
            s.execute(t_parent.update().values({"id": t_parent.c.id + shift}))
        hasil[parent] = shift
    return hasil

# Time column per table, used to compare ranges after a move. Tables not listed have none.
KOLOM_WAKTU = {
    "status_logs": "timestamp",
    "status_rollup_jam": "jam",
    "device_events": "timestamp",
    "service_checks": "timestamp",
    "service_events": "timestamp",
    "akses_web": "waktu",
    "flow_koneksi": "waktu",
    "bandwidth_samples": "timestamp",
    "konfig_snapshots": "waktu",
    "transfer_berkas": "waktu",
    "firewall_snapshot": "waktu",
    "firewall_perubahan": "waktu",
    "ban_aktif": "waktu_ban",
}

BATCH = 2000


def _tabel(nama, metadata):
    return metadata.tables[nama]


def jumlah(engine, tabel):
    with engine.connect() as k:
        return k.execute(select(func.count()).select_from(tabel)).scalar() or 0


def rentang_waktu(engine, tabel, kolom):
    with engine.connect() as k:
        k1 = tabel.c[kolom]
        return k.execute(select(func.min(k1), func.max(k1))).one()


def salin(engine_sumber, engine_tujuan, nama, metadata, hapus_sumber=False,
          lapor=None, abaikan_id=False):
    """Copy one table. Return the number of rows actually copied.

    `hapus_sumber` is used by the buffer: rows that reached MySQL are deleted from
    the local file, only after the destination commit succeeds (the reverse order
    could lose rows from both places).

    `abaikan_id` is required for the buffer and must not be used for migration. In a
    migration the destination is empty and source `id`s are meaningful, so they are
    kept and resuming from the destination's max `id` avoids duplicates. Buffer
    `id`s are unrelated to MySQL `id`s, so filtering by `id > destination max` would
    skip the entire backlog without any error.
    """
    tabel = _tabel(nama, metadata)
    if nama not in engine_sumber.dialect.get_table_names(
            engine_sumber.connect()):
        return 0

    kunci_alami = KUNCI_ALAMI.get(nama)
    # Normalized to a tuple of columns so single-column and composite keys share one
    # code path. `None` means an ordinary numeric-key table.
    key_column = None
    if kunci_alami is not None:
        key_column = ((kunci_alami,) if isinstance(kunci_alami, str)
                       else tuple(kunci_alami))
    kolom = [k.name for k in tabel.columns]

    def _cocok(rows):
        """`key IN (...)` predicate for single and composite keys."""
        if len(key_column) == 1:
            k = key_column[0]
            return tabel.c[k].in_([r[k] for r in rows])
        kol = tuple_(*[tabel.c[k] for k in key_column])
        return kol.in_([tuple(r[k] for k in key_column) for r in rows])

    with engine_sumber.connect() as source:
        if key_column or abaikan_id:
            limit = None
        else:
            with engine_tujuan.connect() as t:
                limit = t.execute(select(func.max(tabel.c.id))).scalar()

        perintah = select(tabel)
        if limit is not None:
            perintah = perintah.where(tabel.c.id > limit)
        if not key_column:
            perintah = perintah.order_by(tabel.c.id)

        hasil = source.execution_options(stream_results=True).execute(perintah)

        copied = 0
        while True:
            line = hasil.fetchmany(BATCH)
            if not line:
                break
            content = [dict(zip(kolom, b)) for b in line]

            # Original `id` is kept: still needed to delete the right source row even though it is not written to the destination.
            id_source = [r.get("id") for r in content] if abaikan_id else None
            if abaikan_id:
                for r in content:
                    r.pop("id", None)

            with engine_tujuan.begin() as destination:
                if key_column:
                    destination.execute(tabel.delete().where(_cocok(content)))
                destination.execute(tabel.insert(), content)

            if hapus_sumber:
                with engine_sumber.begin() as s2:
                    if key_column:
                        s2.execute(tabel.delete().where(_cocok(content)))
                    else:
                        s2.execute(tabel.delete().where(
                            tabel.c.id.in_(
                                id_source if abaikan_id
                                else [r["id"] for r in content])))

            copied += len(content)
            if lapor:
                lapor(nama, copied)

        hasil.close()
    return copied


def copy_all(engine_sumber, engine_tujuan, metadata, hapus_sumber=False,
                hanya=None, diam=False, abaikan_id=False, jaga_id=()):
    """Copy all tables in ORDER. Return {table: count}.

    `jaga_id` names tables whose `id` is kept even when `abaikan_id` is on: parent
    tables whose children point at them, already shifted by `geser_induk()`. See `INDUK_ANAK`.
    """
    hasil = {}
    for nama in URUTAN:
        if hanya and nama not in hanya:
            continue
        if nama not in metadata.tables:
            continue

        def lapor(t, n, _nama=nama):
            if not diam:
                sys.stdout.write("\r  %-22s %8d" % (t, n))
                sys.stdout.flush()

        n = salin(engine_sumber, engine_tujuan, nama, metadata,
                  hapus_sumber=hapus_sumber, lapor=lapor,
                  abaikan_id=abaikan_id and nama not in jaga_id)
        hasil[nama] = n
        if not diam:
            if n:
                sys.stdout.write("\r  %-22s %8d  selesai\n" % (nama, n))
            else:
                sys.stdout.write("  %-22s %8d\n" % (nama, 0))
            sys.stdout.flush()
    return hasil


def bandingkan(engine_sumber, engine_tujuan, metadata, hanya=None):
    """Verify the destination has the same count and range as the source.

    Row counts alone are not enough (a table could miss a whole month and gain rows
    from elsewhere), so the first and last timestamps are compared too.
    """
    diff = []
    for nama in URUTAN:
        if hanya and nama not in hanya:
            continue
        if nama not in metadata.tables:
            continue
        tabel = metadata.tables[nama]

        a = jumlah(engine_sumber, tabel)
        b = jumlah(engine_tujuan, tabel)
        if a != b:
            diff.append((nama, "jumlah baris", a, b))
            continue

        kolom = KOLOM_WAKTU.get(nama)
        if kolom and a:
            wa = rentang_waktu(engine_sumber, tabel, kolom)
            wb = rentang_waktu(engine_tujuan, tabel, kolom)
            if wa != wb:
                diff.append((nama, "rentang %s" % kolom, wa, wb))
    return diff


# Foreign-key checks are deliberately not disabled. `SET FOREIGN_KEY_CHECKS=0` is
# per connection, while each batch in `salin` takes a different pooled connection,
# so it would give false safety. It is also unnecessary: all FK pairs in `nsm.db`
# had zero orphans before the move, and leaving checks on makes MySQL stop on any future orphan.

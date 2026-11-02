"""Prove that a dump file contains every live table.

`mysqldump` can exit 0 with a plausible size and still miss a table created
after the dump was taken, so comparing `information_schema` with itself proves
nothing. This module reads the dump file inside the zip and checks that each
live table has a `CREATE TABLE`, so an incomplete backup reports itself when made.
The file is read as a stream: the dump is hundreds of MB and the backup runs
alongside the poller.
"""
import re

# mysqldump always writes `CREATE TABLE` with backticks and the table name on the
# same line; `IF NOT EXISTS` is handled because some versions emit it.
POLA = re.compile(rb"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`([^`]+)`",
                  re.IGNORECASE)

# Tail carried into the next chunk so a `CREATE TABLE` split at a chunk boundary
# is not lost; 200 bytes exceeds the longest statement the pattern can match.
TUMPANG = 200

BESAR_POTONG = 1 << 22          # 4 MB


def tabel_dalam_dump(jalur):
    """Set of table names that have a `CREATE TABLE` in the file."""
    found = set()
    remaining = b""
    with open(jalur, "rb") as f:
        while True:
            cut = f.read(BESAR_POTONG)
            if not cut:
                break
            data = remaining + cut
            for m in POLA.finditer(data):
                found.add(m.group(1).decode("utf-8", errors="replace"))
            remaining = data[-TUMPANG:]
    return found


def tabel_hidup(kursor, skema):
    """Set of table names that currently exist in the database.

    Views are excluded on purpose: `information_schema.tables` lists them, but
    mysqldump writes `CREATE VIEW`, which would cause false "missing table" alarms.
    """
    kursor.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %s AND table_type = 'BASE TABLE'", (skema,))
    return {b[0] for b in kursor.fetchall()}


def bandingkan(jalur_dump, tabel_hidup_set):
    """Return (missing, extra), both sorted sets of table names.

    `extra` is not a failure: it means a table in the dump no longer exists, i.e.
    was dropped after the last backup. It is still worth surfacing.
    """
    inner = tabel_dalam_dump(jalur_dump)
    return sorted(tabel_hidup_set - inner), sorted(inner - tabel_hidup_set)

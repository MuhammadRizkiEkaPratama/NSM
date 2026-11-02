"""How many seconds ago did the poller last write? Prints a single number.

    python cek_segar.py     -> "12"   (seconds since the last row)
                            -> "-1"   (no rows at all)

A separate file rather than a line inside restart_nsm.ps1: the old check
opened `nsm.db` directly with `sqlite3`. After the move to MySQL it kept
running without error, read the now-frozen SQLite file, and declared a healthy
poller dead; an always-red check stops being trusted within days. Going through
`database.py` makes the check follow wherever NSM writes.
"""
import sys
from datetime import datetime

from sqlalchemy import func, select

import database
import models


def main():
    try:
        with database.engine.connect() as k:
            last = k.execute(
                select(func.max(models.StatusLog.timestamp))).scalar()
    except Exception as e:
        # An unreachable database is a DIFFERENT condition from a silent poller, and the
        # caller may tell them apart. The message goes to stderr so stdout stays a
        # single number.
        sys.stderr.write("basis data tidak terjangkau: %s\n" % str(e)[:120])
        return 2

    if last is None:
        print(-1)
        return 0

    print(int((datetime.now() - last).total_seconds()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

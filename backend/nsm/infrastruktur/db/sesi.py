"""Single place to open and close database sessions.

When each of 56 files calls `SessionLocal()` itself, closing is inconsistent:
some routes use `try/finally`, others call `db.close()` on the last line,
which leaks the session on an error. With MySQL across the network
(`database.py`), a leaked session holds one of a limited number of connection
slots, and the symptom shows up far from the cause. `sesi()` takes closing out
of the route author's hands.

`unit_kerja()` is separate because writes need more than closing: they must be
ATOMIC, so if the second row fails the first must not remain. Two names make
that choice visible at the call site.

The engine, the SQLite buffer, and all connection decisions stay in
`database.py`; this file only manages session lifetime.
"""
from contextlib import contextmanager

from database import SessionLocal


@contextmanager
def sesi():
    """Read-only session, guaranteed to close even on error."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def unit_kerja():
    """Write session: `commit` if the block completes, `rollback` if it raises.

    A half-applied change is worse than a fully failed one: in a monitoring
    tool, partially wrong data gets read as correct data.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

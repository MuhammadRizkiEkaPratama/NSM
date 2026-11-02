"""Domain shapes: what NSM talks about, independent of how it is stored.

The SQLAlchemy models in `models.py` are the shape of a DATABASE ROW, not of
a concept. A function that accepts an ORM object must live inside an open
database session and cannot be tested without a database.

The frozen dataclasses below know nothing about SQL. The `aplikasi` layer
speaks in these shapes; `infrastruktur` translates to and from rows.

This does NOT replace `models.py`; the tables stay there. These are only the
shapes that CROSS a layer boundary, carrying only the fields actually crossed.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class RujukanDevice:
    """A device's identity together with its monitoring state.

    "Paused" is carried as three states, not two — the same three the page
    already distinguishes: not paused, paused with a recorded reason, and
    paused with no recorded reason. The third is not "no reason"; it means the
    reason was never written down, and that is precisely the one worth asking
    about.
    """
    id: int
    nama: str
    ip: str
    tipe: Optional[str] = None
    platform: Optional[str] = None
    lokasi: Optional[str] = None
    aktif: bool = True
    penting: bool = False
    jeda_alasan: Optional[str] = None
    jeda_sejak: Optional[datetime] = None
    jeda_oleh: Optional[str] = None


@dataclass(frozen=True)
class Denyut:
    """One probe result: up or not, how fast, and from which source.

    `sumber` (`icmp`/`tcp`/`lokal`) is carried along because "ping is blocked"
    and "the device is down" are two different conclusions, and the source is
    the only thing that can tell them apart.
    """
    device_id: int
    waktu: datetime
    terjangkau: Optional[bool]
    rtt_ms: Optional[float] = None
    sumber: Optional[str] = None

"""Contracts for the outside world: what the application layer needs, not who provides it.

`report_service` imports `config`, `rollup`, `jeda`, `dialek`, AND
`ubah_acl_router` (a module that CHANGES router config) just because one report
function reads something from it, so importing report code also loads a device
write path.

The `Protocol`s below invert that dependency. A use case states "I need
something that lists devices"; WHO provides it (SQLAlchemy on the primary lab
instance, an in-memory list in tests) is decided at the composition root in
`antarmuka/http/`, not by the file that uses it.

`Protocol` rather than an abstract base class because it is structural:
existing classes satisfy the contract without changes, so old code keeps
working as is during the migration, with no `class X(BaseY)` added to files
already in use.
"""
from datetime import datetime
from typing import List, Optional, Protocol

from nsm.domain.model import Denyut, RujukanDevice


class Jam(Protocol):
    """Time source, so that "now" can be fixed in tests.

    Several NSM rules depend on wall-clock time (monitoring window, working
    hours, 60-minute ban expiry). While `datetime.now()` is called inside a
    function, those rules can only be tested by waiting.
    """
    def sekarang(self) -> datetime: ...


class GudangDevice(Protocol):
    """Read the device list. READ only; the write path has its own contract."""
    def semua(self) -> List[RujukanDevice]: ...
    def ambil(self, device_id: int) -> Optional[RujukanDevice]: ...


class GudangDenyut(Protocol):
    """Read probe results.

    `terakhir_semua()` is in the contract, not just the implementation, because
    it answers a DIFFERENT question from `terakhir()`: the current state of the
    whole fleet, not of one device. Answering it with one `terakhir()` call per
    device costs 1+N queries to a remote database, a difference felt on a page
    that refreshes every ten seconds.
    """
    def terakhir(self, device_id: int) -> Optional[Denyut]: ...
    def terakhir_semua(self) -> dict: ...
    def rentang(self, device_id: int, mulai: datetime,
                selesai: datetime) -> List[Denyut]: ...


class Laporan(Protocol):
    """Report calculations.

    During the migration this contract is fulfilled by
    `infrastruktur/warisan/laporan.py`, which forwards to `report_service` as is.
    Functions move one at a time into `aplikasi/kasus/`, and callers need not know
    when, because they hold this contract, not the module.
    """
    def ringkasan(self, period: str) -> dict: ...
    def ketersediaan(self, period: str) -> list: ...
    def sparkline(self, period: str, kotak: int) -> list: ...


class Pengaturan(Protocol):
    """Config values, already parsed and typed."""
    @property
    def interval_poll(self) -> int: ...
    @property
    def ambang_down(self) -> int: ...
    @property
    def auto_ban_aktif(self) -> bool: ...

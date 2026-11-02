"""Composition root: the only place that knows which implementation fills which contract.

A route that imports `report_service` directly fixes the implementation
for ALL callers, including tests that need a different one. Collecting
those choices here means swapping a data source (adding a cache, or a fake
repository in tests) stops at this file.

FastAPI `Depends` is used as an injector, not a framework: each request
gets a session that `sesi()` guarantees to close, and repositories are
built on that session. Routes never touch `SessionLocal`.
"""
from nsm.infrastruktur.db.gudang import GudangDenyutSql, GudangDeviceSql
from nsm.infrastruktur.db.sesi import sesi
from nsm.infrastruktur.jam import JamSistem
from nsm.infrastruktur.warisan.laporan import LaporanWarisan
from nsm.pengaturan import pengaturan

JAM = JamSistem()


def beri_sesi():
    """FastAPI dependency: per-request session, closed after the response."""
    with sesi() as db:
        yield db


def beri_gudang_device(db):
    return GudangDeviceSql(db)


def beri_gudang_denyut(db):
    return GudangDenyutSql(db)


def beri_laporan(db):
    return LaporanWarisan(db)


def beri_pengaturan():
    return pengaturan()

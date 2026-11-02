"""`database.buat_lab()` and `lab_sementara()`: a replacement for global patching.

A test needing its own database used to patch the module variables
`database.engine` and `database.SessionLocal` and remember to restore them.
Some files never restored them, so later tests ran against an empty in-memory
database and passed silently. `lab_sementara()` restores in `finally`.

Also pins a corrected claim: `import database` opens no connections
(`create_engine` connects lazily).
"""
import pytest

import database

pytestmark = pytest.mark.murni


def test_buat_lab_berdiri_sendiri():
    """A new lab must not touch the module's own engine/session."""
    engine_original, session_original = database.engine, database.SessionLocal
    mesin, factory = database.create_lab()
    try:
        assert mesin is not engine_original
        assert factory is not session_original
        assert database.engine is engine_original, "buat_lab() menyentuh global"
        assert database.SessionLocal is session_original, "buat_lab() menyentuh global"
    finally:
        mesin.dispose()


def test_lab_sementara_mengarahkan_lalu_mengembalikan():
    engine_original, session_original = database.engine, database.SessionLocal
    with database.lab_sementara() as (mesin, _factory):
        assert database.engine is mesin, "global tidak diarahkan ke lab"
        assert database.SessionLocal is not session_original
    assert database.engine is engine_original, "global TIDAK dikembalikan"
    assert database.SessionLocal is session_original, "global TIDAK dikembalikan"


def test_lab_sementara_mengembalikan_walau_ada_galat():
    """Restore in `finally`, not at the end of the block; this is the difference from hand patching."""
    engine_original, session_original = database.engine, database.SessionLocal
    with pytest.raises(RuntimeError):
        with database.lab_sementara():
            raise RuntimeError("sengaja")
    assert database.engine is engine_original
    assert database.SessionLocal is session_original


def test_tabelnya_benar_benar_dibuat():
    import models
    with database.lab_sementara() as (_engine, factory):
        db = factory()
        try:
            d = models.Device(name="Uji", ip_address="10.0.0.1",
                              device_type="server", platform="linux", aktif=1)
            db.add(d)
            db.commit()
            assert db.query(models.Device).count() == 1
        finally:
            db.close()


def test_lab_terpisah_tidak_saling_melihat():
    """Two labs run side by side without contaminating each other (impossible with global patching)."""
    import models
    a_engine, a_factory = database.create_lab()
    b_engine, b_factory = database.create_lab()
    try:
        models.Base.metadata.create_all(a_engine)
        models.Base.metadata.create_all(b_engine)
        da = a_factory()
        da.add(models.Device(name="HanyaDiA", ip_address="10.0.0.2",
                             device_type="server", platform="linux", aktif=1))
        da.commit()
        db_ = b_factory()
        try:
            assert da.query(models.Device).count() == 1
            assert db_.query(models.Device).count() == 0, "lab B melihat isi lab A"
        finally:
            da.close()
            db_.close()
    finally:
        a_engine.dispose()
        b_engine.dispose()


def test_import_database_tidak_membuka_sambungan():
    """`create_engine` does not connect. If someone adds a connection at import time
    this test says so; 88 files import this module, including scripts that never
    touch the database.
    """
    kolam = database.engine.pool
    assert kolam.checkedout() == 0, (
        "ada sambungan yang sedang dipakai sesudah impor -- `database.py` "
        "menyambung saat diimpor, dan 88 berkas mengimpornya")

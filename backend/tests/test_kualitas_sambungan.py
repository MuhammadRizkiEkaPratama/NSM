"""`hitung_kualitas_sambungan()`: packet-loss verdict (docs/design/NETWORK-STATUS.md).

Verdict thresholds (`report_service.KEHILANGAN_BAGUS/CUKUP/BURUK`):

    < 1% good    >= 1% fair    >= 5% poor    >= 15% very poor

1000 samples make each failed row exactly 0.1%, so boundaries at 1.0 / 5.0 /
15.0 percent are tested without rounding. This is pure verdict logic, with no
`StatusRollupJam`; rollup merging is tested in `uji_rollup.py`.

The `fixture` restores `database.engine` and `database.SessionLocal` in
`finally`. Unrestored patches would make later tests pass silently against an
empty in-memory database, since all files share one pytest process.
"""
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.murni

T0 = datetime(2026, 8, 19, 6, 0, 0)
SAMPEL = 1000

# (device_id, jumlah gagal, persen diharap, vonis diharap)
KASUS_BATAS = [
    (1, 0,   0.0,  "bagus"),
    (2, 9,   0.9,  "bagus"),  # just below the `bagus`/`cukup` threshold
    (3, 10,  1.0,  "cukup"),  # exactly at the threshold -> `cukup`
    (4, 49,  4.9,  "cukup"),  # just below the `cukup`/`buruk` threshold
    (5, 50,  5.0,  "buruk"),  # exactly at the threshold -> `buruk`
    (6, 149, 14.9, "buruk"),  # just below the `buruk`/`sangat_buruk` threshold
    (7, 150, 15.0, "sangat_buruk"),  # exactly at the boundary -> very poor
    (8, 999, 99.9, "sangat_buruk"),  # almost all failed
]


@pytest.fixture
def db():
    """In-memory SQLite; `database` is restored afterwards. Without the `finally`
    below, later tests would write to an empty database and still look healthy.
    """
    import database

    with database.lab_sementara() as (_engine, factory):
        session = factory()
        try:
            yield session
        finally:
            session.close()


def buat_device(db, id_, nama):
    import models
    d = models.Device(id=id_, name=nama, ip_address="10.0.2.%d" % id_,
                      device_type="server", platform="linux", aktif=1)
    db.add(d)
    db.commit()
    return d


def isi_sampel(db, did, gagal_n, latensi_maks=None):
    """`SAMPEL` rows, the FIRST `gagal_n` of them failed (RTO)."""
    import models
    t = T0
    for i in range(SAMPEL):
        alive = i >= gagal_n
        rtt = None
        if alive:
            rtt = 10.0
            if latensi_maks is not None and i == SAMPEL - 1:
                rtt = latensi_maks
        db.add(models.StatusLog(device_id=did, timestamp=t,
                                is_reachable=alive, response_time_ms=rtt))
        t += timedelta(seconds=1)
    db.commit()


@pytest.mark.parametrize("did,gagal_n,persen_harap,vonis_harap", KASUS_BATAS,
                         ids=["%d_gagal_%s" % (k[1], k[3]) for k in KASUS_BATAS])
def test_batas_vonis_persis_di_tepi(db, did, gagal_n, persen_harap, vonis_harap):
    """Each boundary case is its own test, so a failure names the boundary that moved."""
    import report_service as rs

    buat_device(db, did, "Kasus%d" % did)
    isi_sampel(db, did, gagal_n)
    hasil = rs.hitung_kualitas_sambungan(db, did, "uji%d" % did, T0)

    assert hasil["kehilangan_persen"] == persen_harap, (
        "device %d (%d/%d gagal): kehilangan_persen" % (did, gagal_n, SAMPEL))
    assert hasil["vonis"] == vonis_harap, "device %d: vonis" % did


def test_tanpa_sampel_mengembalikan_none_bukan_nol(db):
    """`None` and `0.0` mean different things: `0.0%` is "measured, nothing lost";
    `None` is "never measured". Conflating them makes a never-monitored device
    look perfect.
    """
    import report_service as rs

    buat_device(db, 9, "TidakPernahDipantau")
    hasil = rs.hitung_kualitas_sambungan(db, 9, "uji9", T0)

    assert hasil["kehilangan_persen"] is None, "bukan 0.0 — beda arti"
    assert hasil["vonis"] is None
    assert hasil["sampel"] == 0


def test_latensi_maks_mengambil_tertinggi_bukan_rata_rata(db):
    import report_service as rs

    buat_device(db, 10, "LatensiTinggi")
    isi_sampel(db, 10, gagal_n=5, latensi_maks=987.6)
    hasil = rs.hitung_kualitas_sambungan(db, 10, "uji10", T0)

    assert hasil["latensi_maks_ms"] == 987.6, "nilai tertinggi yang disisipkan"
    # Opposite-direction guard: if the formula silently became an average, the
    # value would be 10.0.
    assert hasil["latensi_maks_ms"] != 10.0, "bukan rata-rata"


def test_fixture_mengembalikan_database_seperti_semula():
    """Prove the restore really happened. Runs WITHOUT the `db` fixture, so it sees
    the module state after earlier fixtures finished; a missed restore would leave
    `database.engine` pointing at in-memory SQLite.
    """
    import database
    assert "sqlite://" != str(database.engine.url) or database.engine.url.database, (
        "database.engine masih menunjuk SQLite dalam ingatan — fixture tidak "
        "mengembalikannya, dan setiap uji sesudah ini akan menulis ke basis "
        "data kosong sambil terlihat sehat")

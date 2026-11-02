"""`hitung_kestabilan()`: stable/unstable hysteresis (docs/design/NETWORK-STATUS.md).

Rules tested:
* STABLE -> UNSTABLE: at least `min_siklus` (3) DOWNs within the last `jendela_menit` (15) minutes.
* UNSTABLE -> STABLE: quiet (no DOWN) for `pulih_menit` (10) minutes.
* Category `baseline` is excluded; it is not a real outage.
* Status is computed from the WHOLE history, not one report period.

Config thresholds are overridden with `config.sementara()` and the database
comes from `database.lab_sementara()`, both restored in `finally`.

Scenarios 2-5 (device 2) stay in one test on purpose: `hitung_kestabilan` reads
the device's entire DOWN history without filtering by `sekarang`, so the
scenarios depend on insertion order and splitting them would make each test
see events that have not happened yet.
"""
import contextlib
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.murni

T0 = datetime(2026, 8, 19, 8, 0, 0)
JENDELA = timedelta(minutes=15)
PULIH = timedelta(minutes=10)


class Lab:

    def __init__(self, db, models):
        self.db = db
        self.models = models

    def device(self, id_, nama):
        d = self.models.Device(id=id_, name=nama, ip_address="10.0.1.%d" % id_,
                               device_type="server", platform="linux", aktif=1)
        self.db.add(d)
        self.db.commit()
        return d

    def event(self, did, ts, tipe, kategori="dead"):
        self.db.add(self.models.DeviceEvent(device_id=did, timestamp=ts,
                                            event_type=tipe, category=kategori))
        self.db.commit()

    def gangguan(self, did, ts, lama_detik=5, kategori="dead"):
        self.event(did, ts, "DOWN", kategori)
        self.event(did, ts + timedelta(seconds=lama_detik), "UP", "recovered")


@pytest.fixture
def lab():
    """Clean database per test; everything patched is restored in `finally`."""
    import config
    import database
    import models

    with contextlib.ExitStack() as stack:
        _engine, factory = stack.enter_context(database.lab_sementara())
        db = factory()
        stack.callback(db.close)
        # Thresholds are pinned independent of the real `.env`. `config.sementara()`
        # replaces the values rather than patching the functions, so nothing can be
        # left unrestored.
        stack.enter_context(config.sementara(
            STABIL_MIN_SIKLUS="3", STABIL_JENDELA_MENIT="15",
            STABIL_PULIH_MENIT="10"))
        yield Lab(db, models)


def test_device_tanpa_gangguan_dianggap_stabil(lab):
    import report_service as rs

    lab.device(1, "Sepi")
    h = rs.hitung_kestabilan(lab.db, 1, T0)
    assert h["stabil"] is True, "device tanpa event sama sekali dianggap stabil"
    assert h["lama_detik"] is None, "belum pernah dipantau -> None, bukan 0"


def test_histeresis_masuk_lalu_keluar_dari_tidak_stabil(lab):
    """Four sequential scenarios on ONE device; the order is part of the test.
    Kept together because `hitung_kestabilan` reads the whole DOWN history
    without filtering by `sekarang`.
    """
    import report_service as rs

    lab.device(2, "DuaKali")

    # Below the threshold: 2 DOWNs in 15 minutes -> still stable
    lab.gangguan(2, T0, lama_detik=10)
    lab.gangguan(2, T0 + timedelta(minutes=5), lama_detik=10)
    h = rs.hitung_kestabilan(lab.db, 2, T0 + timedelta(minutes=6))
    assert h["stabil"] is True, "2 gangguan dalam 15 menit belum cukup"

    # Exactly at the threshold: 3rd DOWN -> UNSTABLE
    ts3 = T0 + timedelta(minutes=10)
    lab.gangguan(2, ts3, lama_detik=10)
    h = rs.hitung_kestabilan(lab.db, 2, ts3 + timedelta(minutes=1))
    assert h["stabil"] is False, "DOWN ke-3 dalam jendela -> tidak stabil"
    assert h["sejak"] == ts3.isoformat(), "status mulai TEPAT di DOWN ke-3"
    assert h["siklus_jendela"] == 3
    assert h["lama_detik"] == 60, "dihitung dari 'sejak' ke 'sekarang'"

    # further outage: 'sejak' must NOT move backward
    ts4 = ts3 + timedelta(minutes=2)
    lab.gangguan(2, ts4)
    h = rs.hitung_kestabilan(lab.db, 2, ts4 + timedelta(minutes=1))
    assert h["stabil"] is False, "masih tidak stabil"
    assert h["sejak"] == ts3.isoformat(), (
        "'sejak' tidak berubah — masih DOWN ke-3, bukan ke-4")
    assert h["siklus_jendela"] == 4

    # a full 10 quiet minutes -> STABLE again
    h = rs.hitung_kestabilan(lab.db, 2, ts4 + PULIH + timedelta(seconds=1))
    assert h["stabil"] is True, "hening 10 menit -> stabil lagi"
    assert h["sejak"] == (ts4 + PULIH).isoformat(), (
        "'sejak' pemulihan = waktu gangguan terakhir + 10 menit")

    # opposite-direction guard: one second short is not enough
    h = rs.hitung_kestabilan(lab.db, 2, ts4 + PULIH - timedelta(seconds=1))
    assert h["stabil"] is False, (
        "hening 1 detik KURANG dari 10 menit -> masih tidak stabil")


def test_setelah_pulih_penuh_siklus_baru_mulai_dari_nol(lab):
    """A single outage after recovery must not drop the status immediately."""
    import report_service as rs

    lab.device(3, "PulihLaluGoyahLagi")
    a = T0
    lab.gangguan(3, a)
    b = a + timedelta(minutes=5)
    lab.gangguan(3, b)
    c = b + timedelta(minutes=5)
    lab.gangguan(3, c)  # 3rd DOWN -> unstable from here
    # A FULL 10 quiet minutes, then ONE new outage.
    d = c + PULIH + timedelta(minutes=1)
    lab.gangguan(3, d)

    h = rs.hitung_kestabilan(lab.db, 3, d + timedelta(seconds=30))
    assert h["stabil"] is True, (
        "satu gangguan sesudah pulih penuh tidak langsung tidak-stabil lagi")
    assert h["siklus_jendela"] == 0, "siklus nol karena sedang stabil"


def test_down_berkategori_baseline_dikecualikan(lab):
    """`baseline` marks a new device's first row, not an outage."""
    import report_service as rs

    lab.device(4, "BaselineSaja")
    for i in range(3):
        lab.event(4, T0 + timedelta(minutes=i), "DOWN", "baseline")

    h = rs.hitung_kestabilan(lab.db, 4, T0 + timedelta(minutes=3))
    assert h["stabil"] is True, "3 DOWN berkategori baseline tidak memicu apa pun"


def test_down_tepat_di_tepi_jendela_ikut_dihitung(lab):
    import report_service as rs

    lab.device(5, "TepiJendela")
    f = T0
    lab.gangguan(5, f)
    lab.gangguan(5, f + timedelta(minutes=7))
    exact_edge = f + JENDELA  # exactly 15 minutes after the first
    lab.gangguan(5, exact_edge)

    h = rs.hitung_kestabilan(lab.db, 5, exact_edge + timedelta(seconds=30))
    assert h["stabil"] is False, "DOWN tepat di tepi jendela (15:00) ikut terhitung"


def test_down_satu_detik_lewat_jendela_tidak_dihitung(lab):
    import report_service as rs

    lab.device(6, "LewatJendela")
    g = T0
    lab.gangguan(6, g)
    lab.gangguan(6, g + timedelta(minutes=7))
    via_edge = g + JENDELA + timedelta(seconds=1)
    lab.gangguan(6, via_edge)

    h = rs.hitung_kestabilan(lab.db, 6, via_edge + timedelta(seconds=30))
    assert h["stabil"] is True, (
        "gangguan #1 sudah kedaluwarsa, cuma 2 dalam jendela sekarang")


def test_uji_ini_sendiri_bisa_gagal(lab):
    """Deliberately planted fault: `min_siklus=1` must drop the status at once.

    If THIS test fails, the test is wrong, not the code: a checker never shown to
    find a problem only gives false confidence. The threshold is 2, not 1:
    patching `config.get_stabil_min_siklus` directly would bypass its
    `max(2, ...)` clamp and test a configuration that cannot exist on the lab
    instance, so this goes through `config.sementara()`, which uses the real getter.
    """
    import config
    import report_service as rs

    lab.device(7, "UjiRusak")
    lab.gangguan(7, T0)
    lab.gangguan(7, T0 + timedelta(minutes=1))

    with config.sementara(STABIL_MIN_SIKLUS="2"):
        h = rs.hitung_kestabilan(lab.db, 7, T0 + timedelta(minutes=2))
    assert h["stabil"] is False, (
        "dengan min_siklus=2, dua gangguan dalam jendela sudah tidak stabil")

    # Opposite-direction guard: outside the block the threshold is 3 again and the
    # same two outages are no longer enough. Without this, the test above would also
    # pass if the override leaked and kept the threshold at 2.
    h = rs.hitung_kestabilan(lab.db, 7, T0 + timedelta(minutes=2))
    assert h["stabil"] is True, (
        "di luar `sementara()` ambangnya harus kembali 3 -- dua gangguan belum cukup")

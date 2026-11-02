"""`.env` cache and temporary overrides.

Every `config.get_*` call used to open and parse `.env` from disk. Contents
are now cached, keyed by the file fingerprint (`st_mtime_ns`, size).

Two things must stay true:
1. Edits to `.env` are picked up without a restart (the file is edited while
   services run, for example to flip automation switches).
2. Overrides must not leak: `sementara()` must restore the value, or every
   later test runs with wrong settings without any error.

Tests always override with a value that differs from the current one and
check three points: outside, inside, and after.
"""
import os
import shutil

import pytest

import config

pytestmark = pytest.mark.murni


@pytest.fixture(autouse=True)
def bersih():
    config.muat_ulang()
    yield
    config._TIMPA = None
    config.muat_ulang()


def test_suntingan_env_terbaca_tanpa_restart(tmp_path):
    copy_of = tmp_path / "env-uji"
    shutil.copy(config._ENV, copy_of)
    original = config._ENV
    try:
        config._ENV = str(copy_of)
        config.muat_ulang()
        before = config.get_interval()

        with open(copy_of, "a", encoding="utf-8") as f:
            f.write("\nPOLL_INTERVAL=%d\n" % (before + 7))
        os.utime(copy_of, None)

        assert config.get_interval() == before + 7, (
            "cache basi: suntingan `.env` tidak terbaca tanpa restart")
    finally:
        config._ENV = original
        config.muat_ulang()


def test_hasil_baca_adalah_salinan():
    before = config.get_interval()
    d = config._baca()
    d["POLL_INTERVAL"] = "9999"
    assert config.get_interval() == before


@pytest.mark.parametrize("kunci,timpa", [
    ("POLL_INTERVAL", "999"),
    ("DOWN_THRESHOLD", "42"),
])
def test_sementara_mengubah_lalu_mengembalikan(kunci, timpa):
    """The override value deliberately differs from the current one; an equal value
    would make the test pass without testing anything.
    """
    getter = {"POLL_INTERVAL": config.get_interval,
              "DOWN_THRESHOLD": config.get_down_threshold}[kunci]
    outer = getter()
    assert str(outer) != timpa, "nilai timpaan harus berbeda dari yang berlaku"

    with config.sementara(**{kunci: timpa}):
        assert getter() == int(timpa), "timpaan tidak berlaku di dalam blok"
    assert getter() == outer, "timpaan BOCOR keluar dari bloknya"


def test_sementara_tidak_menyentuh_disk():
    mt = os.stat(config._ENV).st_mtime_ns
    with config.sementara(POLL_INTERVAL="999"):
        pass
    assert os.stat(config._ENV).st_mtime_ns == mt, (
        "`sementara()` menulis ke `.env` sungguhan -- ia tidak boleh")


def test_galat_di_tengah_tidak_meninggalkan_timpaan():
    """Restore in `finally`, not at the end of the block, so a failing test cannot
    leave settings overridden for the rest of the process.
    """
    outer = config.get_interval()
    with pytest.raises(RuntimeError):
        with config.sementara(POLL_INTERVAL="555"):
            raise RuntimeError("sengaja")
    assert config.get_interval() == outer


def test_sementara_bisa_disarangkan():
    with config.sementara(POLL_INTERVAL="11"):
        assert config.get_interval() == 11
        with config.sementara(POLL_INTERVAL="22"):
            assert config.get_interval() == 22
        assert config.get_interval() == 11, "blok dalam tidak mengembalikan"


def test_cache_benar_benar_mengurangi_pembacaan_disk(monkeypatch):
    """Prove the cache works: count file opens. `os.stat` is still called every time;
    that is the price of noticing `.env` edits.
    """
    config.muat_ulang()
    n = {"buka": 0}
    unblock_original = open

    def hitung(berkas, *a, **k):
        if str(berkas) == config._ENV:
            n["buka"] += 1
        return unblock_original(berkas, *a, **k)

    monkeypatch.setattr("builtins.open", hitung)
    for _ in range(50):
        config.get_interval()

    assert n["buka"] == 1, (
        "50 panggilan membuka `.env` %d kali; seharusnya sekali" % n["buka"])

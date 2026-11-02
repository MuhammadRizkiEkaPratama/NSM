"""Availability is not published from too short an observation.

Regression: a gateway paused while DOWN had only 26 seconds observed in a 24
hour window, yet 0.188% availability was published and drawn next to devices
observed for hours. The old condition `window > 0` let any observation through.

Checks:
1. Below the threshold: `availability` is None and `cukup_diamati` is False.
2. Above it: the value is published normally (the threshold must not swallow
   healthy devices).
3. The overall average is not dragged by withheld values.
4. A withheld device still reports how long it was observed.

The setup is expensive (2,880 `status_logs` rows), so it is a module-scoped
fixture. `jeda.lupakan_cache()` runs at both ends so a stale `jeda` cache does
not leak into the next test file and silently change availability numbers.
"""
import contextlib
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.murni


@pytest.fixture(scope="module")
def hasil_availability():
    """Build two contrasting devices and return the `availability_semua` result.

    Device 1: paused while DOWN. Device 2: fully monitored and healthy.
    """
    import database
    import jeda
    import models
    import report_service as rs

    with contextlib.ExitStack() as stack:
        _engine, factory = stack.enter_context(database.lab_sementara())
        db = factory()
        stack.callback(db.close)
        # Clear the `jeda` cache at both ends; a stale cache leaks into the next test file.
        jeda.lupakan_cache()
        stack.callback(jeda.lupakan_cache)

        finish = datetime.now()
        start = finish - timedelta(hours=24)

        def device(id_, nama):
            d = models.Device(id=id_, name=nama, ip_address="10.9.9.%d" % id_,
                              device_type="router", platform="linux", aktif=1)
            db.add(d)
            return d

        # Device 1: paused while DOWN. Pings stopped 23 hours ago in a DOWN state.
        device(1, "Dijeda selagi DOWN")
        halt = finish - timedelta(hours=23)
        db.add(models.DeviceEvent(device_id=1, event_type="DOWN",
                                  category="dead",
                                  timestamp=halt - timedelta(seconds=30)))
        for i in range(6):
            db.add(models.StatusLog(
                device_id=1, timestamp=halt - timedelta(seconds=30 - i * 5),
                is_reachable=False, response_time_ms=None, sumber="icmp"))

        # --- Device 2: dipantau penuh, sehat -------------------------------
        device(2, "Dipantau penuh")
        db.add(models.DeviceEvent(device_id=2, event_type="UP",
                                  category="baseline", timestamp=start))
        # Row spacing must be tighter than `jeda.ambang_detik()` (60 seconds);
        # otherwise each gap reads as a monitoring hole and healthy devices get held back.
        t = start
        while t < finish:
            db.add(models.StatusLog(device_id=2, timestamp=t,
                                    is_reachable=True, response_time_ms=1.0,
                                    sumber="icmp"))
            t += timedelta(seconds=30)

        db.commit()

        per_nama = {x["name"]: x
                    for x in rs.availability_semua(db, "24h")["devices"]}
        yield {
            "per_nama": per_nama,
            "ringkasan": rs.ringkasan(db, "24h"),
            "min_diamati": rs.MIN_DIAMATI_DETIK,
        }


def test_pengamatan_terlalu_pendek_angkanya_ditahan(hasil_availability):
    a = hasil_availability["per_nama"]["Dijeda selagi DOWN"]
    assert a["availability"] is None, "availability tidak diterbitkan"
    assert a["cukup_diamati"] is False, "ditandai tidak cukup diamati"
    assert a["durasi_diamati_detik"] < hasil_availability["min_diamati"], (
        "diamati %s dtk, ambang %s"
        % (a["durasi_diamati_detik"], hasil_availability["min_diamati"]))


def test_keterangannya_tetap_ada_supaya_halaman_bisa_menjelaskan(hasil_availability):
    a = hasil_availability["per_nama"]["Dijeda selagi DOWN"]
    assert a["durasi_diamati_teks"] and a["durasi_diamati_teks"] != "-", (
        "durasi_diamati_teks kosong -> %r" % a["durasi_diamati_teks"])
    assert a["tak_terpantau_teks"], (
        "tak_terpantau_teks kosong -> %r" % a["tak_terpantau_teks"])


def test_penjaga_arah_sebaliknya_device_sehat_tidak_ikut_ditahan(hasil_availability):
    b = hasil_availability["per_nama"]["Dipantau penuh"]
    assert b["cukup_diamati"] is True, "ditandai cukup diamati"
    assert b["availability"] is not None, (
        "ambangnya menelan device yang seharusnya terukur")
    assert b["availability"] > 99, "nilainya masuk akal -> %r" % b["availability"]


def test_rata_rata_tidak_terseret_angka_yang_ditahan(hasil_availability):
    r = hasil_availability["ringkasan"]
    assert r["availability_rata"] is not None
    assert r["availability_rata"] > 99, (
        "dapat %r; kalau 0,x berarti angka yang ditahan ikut terhitung"
        % r["availability_rata"])


def test_ambangnya_diumumkan_bukan_angka_rahasia_di_dalam_kode(hasil_availability):
    a = hasil_availability["per_nama"]["Dijeda selagi DOWN"]
    assert a["min_diamati_detik"] == hasil_availability["min_diamati"]

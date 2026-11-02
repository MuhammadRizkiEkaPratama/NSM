"""`ringkas_layanan_per_device()`: service state on the dashboard cards.

Separate from `layanan_semua()` because the dashboard refreshes every 5
seconds and `layanan_semua()` computes availability (scanning `status_logs`
for monitoring gaps and rebuilding `service_events`), which is wasted work
for numbers the dashboard does not show.

Checks:
1. Grouping per device; a device without services is absent, not an empty list.
2. Never checked (`ok: None`) is distinct from down (`ok: False`).
3. Paused counts as neither healthy nor failing.
4. The LAST check is the one read, not the first found.

Setup uses `database.lab_sementara()`, which restores in `finally`.
"""
import contextlib
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.murni

T0 = datetime(2026, 7, 1, 12, 0, 0)


@pytest.fixture(scope="module")
def per_device():
    """Empat device kontras, kembalikan `ringkas_layanan_per_device()["per_device"]`."""
    import database
    import models
    import report_service as rs

    with contextlib.ExitStack() as stack:
        _engine, factory = stack.enter_context(database.lab_sementara())
        db = factory()
        stack.callback(db.close)

        def device(id_, nama):
            db.add(models.Device(id=id_, name=nama, ip_address="10.0.0.%d" % id_,
                                 device_type="server", platform="linux", aktif=1))

        def layanan(id_, did, nama, jenis="tcp", port=22, aktif=1):
            db.add(models.Service(id=id_, device_id=did, nama=nama, jenis=jenis,
                                  port=port, aktif=aktif))

        def cekan(sid, waktu, ok, kategori=None, kode=None):
            db.add(models.ServiceCheck(service_id=sid, timestamp=waktu, ok=ok,
                                       kode=kode, waktu_ms=1.0, kategori=kategori))

        # Device 1: two services, one healthy and one down.
        device(1, "Web+SSH")
        layanan(1, 1, "SSH", port=22)
        layanan(2, 1, "Web", jenis="http", port=80)
        cekan(1, T0, True)
        cekan(2, T0, True)  # OLD check
        cekan(2, T0 + timedelta(minutes=5), False,
              kategori="koneksi_ditolak", kode=None)  # LATEST check

        # Device 2: one service never checked.
        device(2, "Baru didaftarkan")
        layanan(3, 2, "MySQL", jenis="mysql", port=3306)

        # Device 3: one paused service.
        device(3, "Sedang dijeda")
        layanan(4, 3, "SSH dijeda", port=22, aktif=0)
        cekan(4, T0, False, kategori="timeout")

        # Device 4: no services.
        device(4, "Tanpa layanan")

        db.commit()
        yield rs.ringkas_layanan_per_device(db)["per_device"]


def test_pengelompokan_per_device(per_device):
    assert sorted(per_device.keys()) == ["1", "2", "3"], (
        "kunci device berupa teks, bukan angka")
    assert "4" not in per_device, (
        "device tanpa layanan tidak muncul sama sekali -- bukan muncul dengan "
        "daftar kosong")
    assert per_device["1"]["total"] == 2


def test_device_dengan_satu_sehat_satu_mati(per_device):
    d = per_device["1"]
    assert d["sehat"] == 1
    assert d["bermasalah"] == 1

    web = next(s for s in d["layanan"] if s["nama"] == "Web")
    assert web["ok"] is False, "yang dibaca pemeriksaan TERAKHIR, bukan yang lama"
    assert web["kategori_teks"] is not None, (
        "kalimat sebab ikut dikirim, disusun Python")

    ssh = next(s for s in d["layanan"] if s["nama"] == "SSH")
    assert ssh["kategori_teks"] is None, (
        "layanan yang sehat tidak membawa kalimat sebab")


def test_belum_pernah_diperiksa_bukan_berarti_mati(per_device):
    """`None` and `False` mean different things; treating them the same would wrongly accuse a healthy service."""
    d = per_device["2"]
    mysql = d["layanan"][0]
    assert mysql["ok"] is None, "ok bernilai None, bukan False"
    assert d["sehat"] == 0, "tidak dihitung sehat"
    assert d["bermasalah"] == 0, "tidak dihitung bermasalah"
    assert mysql["terakhir_cek"] is None


def test_dijeda_tidak_dihitung_sehat_maupun_bermasalah(per_device):
    d = per_device["3"]
    assert d["dijeda"] == 1
    assert d["bermasalah"] == 0, (
        "tidak dihitung bermasalah walau cekan terakhirnya gagal")
    assert d["sehat"] == 0
    assert d["layanan"][0]["aktif"] is False


@pytest.mark.parametrize("did", ["1", "2", "3"])
def test_total_selalu_sama_dengan_jumlah_golongannya(per_device, did):
    content = per_device[did]
    not_yet = sum(1 for s in content["layanan"] if s["aktif"] and s["ok"] is None)
    assert content["sehat"] + content["bermasalah"] + content["dijeda"] + not_yet == content["total"]


def test_tidak_ada_lapangan_availability_yang_bocor_ke_sini(per_device):
    """Guards against a performance regression, not a calculation error: if fields
    from `layanan_semua()` were copied here, the dashboard would silently go back
    to computing period figures every 5 seconds.
    """
    leak = [k for s in per_device["1"]["layanan"] for k in s
             if k in ("availability", "diamati_detik", "total_down_detik",
                      "insiden", "tak_terpantau_detik")]
    assert leak == [], "lapangan periode bocor ke jalur ringkas: %r" % leak

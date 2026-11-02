"""Escalating backoff when notification delivery fails.

Checks:
1. The first failure is not retried on the next round.
2. Gaps widen: 30, 60, 300, 900, 1800, 3600 seconds.
3. Widening stops at 1 hour.
4. After a success the failure count resets (next failure starts at 30 s).
5. A deferred event does not touch the network during the wait; delaying only
   the error message would not reduce load on the mail server.

Patching uses `monkeypatch` (restored after each test) and
`database.lab_sementara()`, so no config, clock, or `_tunda` state leaks.
"""
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.murni

MULAI = datetime(2026, 7, 28, 12, 0, 0)
TANGGA = [30, 60, 300, 900, 1800, 3600]


class JamPalsu:
    """Stand-in for the `datetime` module with a controllable `now()`, so the test
    finishes instantly instead of waiting 1 h 47 min 30 s.
    """

    def __init__(self, waktu):
        self._waktu = waktu

    def now(self):
        return self._waktu


@pytest.fixture
def lab(monkeypatch):
    """Own database plus notifications that never touch the network. All patching
    goes through `monkeypatch`, which restores even if the test fails midway.
    """
    import contextlib

    import config
    import database
    import models
    import notifikasi

    with contextlib.ExitStack() as stack:
        _engine, factory = stack.enter_context(database.lab_sementara())
        db = factory()
        stack.callback(db.close)

        # Config is faked so the test touches neither `.env`, the network, nor a real mail server.
        monkeypatch.setattr(config, "get_notif_enabled", lambda: True)
        monkeypatch.setattr(config, "get_notif_jeda_menit", lambda: 0)
        monkeypatch.setattr(config, "get_notif_config", lambda: {
            "url": "http://uji.invalid/notify",
            "base_url": "http://uji.invalid",
        })

        # `_tunda` is module state: cleared before AND restored after, or leftovers
        # would look like a queue to the next test.
        asli_tunda = dict(notifikasi._tunda)
        notifikasi._tunda.clear()
        stack.callback(lambda: (notifikasi._tunda.clear(),
                                 notifikasi._tunda.update(asli_tunda)))

        db.add(models.Device(id=1, name="VM Uji", ip_address="10.0.0.1",
                             device_type="server", platform="linux", aktif=1))
        db.add(models.DeviceEvent(device_id=1, event_type="DOWN",
                                  timestamp=datetime.now(), category="dead",
                                  detail="uji", duration_sec=10))
        db.commit()
        yield db


@pytest.fixture
def jam(monkeypatch):
    """Set the clock `notifikasi` sees. Restored automatically."""
    import notifikasi

    def setel(waktu):
        monkeypatch.setattr(notifikasi, "datetime", JamPalsu(waktu))
    return setel


def _jalankan_tangga(db, jam, pengirim, putaran=7):
    """Jalankan `putaran` percobaan gagal; kembalikan jarak antar percobaan."""
    import notifikasi

    distance = []
    waktu = MULAI
    for _ in range(putaran):
        # Advance the clock to when this event may be retried, and record how far it
        # jumped from the previous attempt.
        content = notifikasi._tunda.get(1)
        if content:
            distance.append(round((content[1] - waktu).total_seconds()))
            waktu = content[1]
        jam(waktu)
        notifikasi.proses_antrean(db, pengirim=pengirim)
    return distance


@pytest.fixture
def selalu_gagal():
    """A sender that always fails, counting how many times it is called."""
    hitung = {"n": 0}

    def kirim(*_a, **_k):
        hitung["n"] += 1
        raise RuntimeError("smtp.gmail.com: Connect timed out")

    kirim.hitung = hitung
    return kirim


def test_tangga_jeda_sesuai_rencana(lab, jam, selalu_gagal):
    distance = _jalankan_tangga(lab, jam, selalu_gagal)
    assert distance == TANGGA, "jarak antar percobaan (detik): %r" % distance


def test_melebarnya_berhenti_di_satu_jam(lab, jam, selalu_gagal):
    distance = _jalankan_tangga(lab, jam, selalu_gagal)
    assert max(distance) == 3600


def test_pengirim_dipanggil_sekali_per_percobaan(lab, jam, selalu_gagal):
    _jalankan_tangga(lab, jam, selalu_gagal)
    assert selalu_gagal.hitung["n"] == 7, "bukan tiap putaran poller"


def test_masa_tunggu_menahan_panggilan_keluar(lab, jam, selalu_gagal):
    """The core of the fix: the outgoing call itself must stop, not just the error message."""
    import notifikasi

    jam(MULAI)
    notifikasi.proses_antrean(lab, pengirim=selalu_gagal)  # first failure
    after_fail = selalu_gagal.hitung["n"]

    hasil = None
    for second in (5, 10, 20):  # three poller rounds within 30 seconds
        jam(MULAI + timedelta(seconds=second))
        hasil = notifikasi.proses_antrean(lab, pengirim=selalu_gagal)

    assert selalu_gagal.hitung["n"] == after_fail, (
        "panggilan keluar bertambah selama masa tunggu")
    assert hasil["tertunda"] == 1, "putaran itu dilaporkan sebagai tertunda"


def test_setelah_berhasil_hitungan_gagal_dilupakan(lab, jam, selalu_gagal):
    import notifikasi

    jam(MULAI)
    notifikasi.proses_antrean(lab, pengirim=selalu_gagal)
    assert notifikasi._tunda, "harusnya ada catatan tunda sesudah gagal"

    jam(MULAI + timedelta(seconds=60))
    notifikasi.proses_antrean(
        lab, pengirim=lambda *a, **k: {"terkirim": 1, "pelanggan": 1})
    assert len(notifikasi._tunda) == 0, "masih ada sisa catatan tunda"

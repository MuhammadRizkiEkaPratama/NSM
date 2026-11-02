"""The SSH command client IP is inherited across poller rounds within the SAME session.

The `USER_START` line (SSH session IP) appears once per session, at the start.
`perintahlog.gabung()` only sees lines within one log chunk, so once
`USER_START` falls out of the read window, later events of the same session
lose the address even though an earlier stored row has it. This left the
"source address" column of the traffic table half empty.

Fix in `poller.simpan_traffic_device()`: before saving a row without
`ip_klien`, look up an IP already known for the same (device_id, session) in
stored rows. This is safe because auditd session numbers (`ses=`) keep
increasing and are not reused quickly: one session = one IP. The last two tests
keep the limits: never-known stays empty, and the same session number on
another device is not mixed up.

Uses `database.buat_lab()` (the session is passed as an argument), so the
global `SessionLocal` is never redirected.
"""
from datetime import datetime, timedelta

import pytest

import models
import poller

pytestmark = pytest.mark.murni

MULAI = datetime(2026, 8, 19, 16, 20, 0)
IP_ARIF = "192.168.56.1"


def bacaan_perintah(jalur, kejadian, posisi_baru=100):
    return {"log": [], "sftp": [], "smb": [], "flow": [],
            "perintah": [{"jalur": jalur, "service_id": 1, "galat": None,
                          "kejadian": kejadian, "posisi_baru": posisi_baru}]}


def kejadian(waktu, pengguna, perintah, argumen, ip, sesi):
    return {"waktu": waktu, "pengguna": pengguna, "perintah": perintah,
            "argumen": argumen, "berhasil": 1, "ip_klien": ip, "sesi": sesi}


@pytest.fixture
def lab():
    import database

    engine, factory = database.create_lab()
    models.Base.metadata.create_all(engine)
    db = factory()
    try:
        d = models.Device(name="Server Berkas Uji", ip_address="192.168.56.105",
                          device_type="server", platform="linux", aktif=True)
        db.add(d)
        db.commit()
        yield db, d
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def sesudah_dua_putaran(lab):
    """Round 1 (IP known), then round 2 (`USER_START` already out of the window).
    Kept in one fixture because round 2 only means something after round 1 wrote its row.
    """
    db, d = lab
    poller.simpan_traffic_device(db, d, bacaan_perintah("audit.log", [
        kejadian(MULAI, "arif", "whoami", "whoami", IP_ARIF, "2610"),
        kejadian(MULAI + timedelta(seconds=5), "arif", "ls",
                 "ls -la /srv/sharing", IP_ARIF, "2610"),
    ], 100))
    db.commit()

    # Round 2: same session, `USER_START` past the read window (the real case);
    # `gabung()` no longer sees it, so `ip_klien` arrives empty from `perintahlog`.
    poller.simpan_traffic_device(db, d, bacaan_perintah("audit.log", [
        kejadian(MULAI + timedelta(minutes=1), "arif", "cp",
                 "cp jadwal.xlsx video/", None, "2610"),
        kejadian(MULAI + timedelta(minutes=1, seconds=30), "arif", "rm",
                 "rm jadwal.xlsx", None, "2610"),
    ], 200))
    db.commit()
    return db


def test_putaran_pertama_membawa_ip(sesudah_dua_putaran):
    line = (sesudah_dua_putaran.query(models.PerintahPengguna)
             .filter(models.PerintahPengguna.perintah.in_(("whoami", "ls")))
             .all())
    assert len(line) == 2
    assert all(b.ip_klien == IP_ARIF for b in line), (
        "-> %r" % [(b.perintah, b.ip_klien) for b in line])


def test_putaran_kedua_mewarisi_ip_dari_sesi_yang_sama(sesudah_dua_putaran):
    """Core of the fix: the "source address" column stops being half empty."""
    line = (sesudah_dua_putaran.query(models.PerintahPengguna)
             .filter(models.PerintahPengguna.perintah.in_(("cp", "rm")))
             .all())
    assert len(line) == 2
    assert all(b.ip_klien == IP_ARIF for b in line), (
        "IP tidak diwarisi -> %r" % [(b.perintah, b.ip_klien) for b in line])


def test_sesi_yang_belum_pernah_punya_ip_tetap_kosong(lab):
    """First limit: do not guess. If never known, stay empty; an invented address
    reads as evidence, an empty one reads as "unknown".
    """
    db, d = lab
    poller.simpan_traffic_device(db, d, bacaan_perintah("audit.log", [
        kejadian(MULAI, "dewi", "ls", "ls", None, "9999")], 50))
    db.commit()

    line = db.query(models.PerintahPengguna).all()
    assert len(line) == 1
    assert line[0].ip_klien is None, "IP ditebak, bukan dibiarkan kosong"


def test_device_lain_dengan_nomor_sesi_sama_tidak_tertukar(lab):
    """Second limit: auditd `ses=` numbers are per machine, not global. Without this
    guard, inheritance that is right for one device would attach someone else's
    address to another.
    """
    db, d_a = lab
    d_b = models.Device(name="Server Lain", ip_address="192.168.56.199",
                        device_type="server", platform="linux", aktif=True)
    db.add(d_b)
    db.commit()

    # Device A, sesi 500, IP dikenal.
    poller.simpan_traffic_device(db, d_a, bacaan_perintah("a.log", [
        kejadian(MULAI, "x", "whoami", "whoami", "10.0.0.5", "500")], 10))
    db.commit()

    # Device B, session 500: SAME number, DIFFERENT device, IP not yet known.
    poller.simpan_traffic_device(db, d_b, bacaan_perintah("b.log", [
        kejadian(MULAI, "y", "whoami", "whoami", None, "500")], 10))
    db.commit()

    line_b = (db.query(models.PerintahPengguna)
               .filter(models.PerintahPengguna.device_id == d_b.id).all())
    assert len(line_b) == 1
    assert line_b[0].ip_klien is None, (
        "device B mewarisi IP milik device A -> %r" % line_b[0].ip_klien)

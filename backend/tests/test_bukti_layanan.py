"""Service incident evidence chain mentions the service's own port.

Two defects fixed: the service's own port never appeared (a card about port
80 never mentioned port 80), and port 443 was marked red although HTTPS was
never installed on that server. A red mark for something that never existed
is not evidence.

Touches neither network nor database; it tests the sentence builder.
"""
import pytest

import diagnosa
import report_service as rs

pytestmark = pytest.mark.murni


def baris_ke(baris, teks):
    """First evidence line containing `teks`. Raises if none."""
    return next(b for b in baris if teks in b["teks"])


@pytest.fixture(scope="module")
def kasus_http_mati():
    """Web server: port 80 is down and HTTPS was never installed there.
    The only registered service is port 80, so a 22 that answers is good
    news and a closed 443 is no news.
    """
    teks = diagnosa.build_evidence(
        "192.168.1.103", ping_ok=True, ping_ms=1.23,
        port_lain={22: True, 443: False},
        port_layanan=80, port_layanan_ok=False,
        diharapkan={80},
    )
    return rs._urai_bukti(teks)


def test_port_layanannya_sendiri_disebut(kasus_http_mati):
    assert any("Port 80" in b["teks"] for b in kasus_http_mati)
    assert baris_ke(kasus_http_mati, "Port 80")["ok"] is False


def test_port_tanpa_layanan_terdaftar_netral_bukan_gagal(kasus_http_mati):
    b443 = baris_ke(kasus_http_mati, "Port 443")
    assert b443["ok"] is None, "443 ditandai gagal padahal HTTPS tidak dipasang"
    assert "tidak ada layanan terdaftar" in b443["teks"], (
        "alasannya tidak ikut ditulis -> %s" % b443["teks"])


def test_port_pembanding_yang_menjawab_tetap_ok(kasus_http_mati):
    assert baris_ke(kasus_http_mati, "Port 22")["ok"] is True


def test_port_layanan_disebut_sebelum_port_pembanding(kasus_http_mati):
    sort = {t: [i for i, b in enumerate(kasus_http_mati) if t in b["teks"]][0]
            for t in ("Port 80", "Port 22")}
    assert sort["Port 80"] < sort["Port 22"]


def test_port_pembanding_yang_punya_layanan_tetap_gagal():
    """Opposite-direction guard: here a closed 80 IS bad news because a service is
    registered there. Neutralizing all comparison ports would swallow real bad news.
    """
    teks = diagnosa.build_evidence(
        "192.168.56.104", ping_ok=False, ping_ms=None,
        port_lain={80: False, 443: False},
        port_layanan=22, port_layanan_ok=False,
        diharapkan={22, 80},
    )
    baris = rs._urai_bukti(teks)
    assert baris_ke(baris, "Port 80")["ok"] is False, "punya layanan -> tetap gagal"
    assert baris_ke(baris, "Port 443")["ok"] is None, "tanpa layanan -> tetap netral"


def test_port_terbuka_tetapi_jawaban_layanan_salah():
    """Apache returning 500 on every request: port open, service failing."""
    teks = diagnosa.build_evidence(
        "192.168.1.103", ping_ok=True, ping_ms=0.8,
        port_lain={22: True, 443: False},
        port_layanan=80, port_layanan_ok=True,
        diharapkan={80},
    )
    b80 = baris_ke(rs._urai_bukti(teks), "Port 80")
    assert b80["ok"] is True, "masih menerima koneksi -> OK"
    assert "belum mati" in b80["teks"], (
        "kalimatnya tidak menyebut prosesnya belum mati -> %s" % b80["teks"])


def test_kesimpulan_membedakan_rusak_di_dalam_dari_mati():
    k = diagnosa.simpulkan(True, False, {22: True, 443: False}, port_terbuka=True)
    assert "rusak di dalam" in k, "-> %s" % k


@pytest.mark.parametrize("ping,port_lain,port_terbuka,harus_memuat", [
    (True,  {22: True},             False, "berhenti benar-benar layanan ini"),
    (False, {22: False, 80: False}, False, "gangguan device"),
    (False, {22: True},             False, "Ping diblokir"),
    (True,  {22: False, 80: False}, False, "kewalahan"),
], ids=["layanan_berhenti", "device_gangguan", "ping_diblokir", "kewalahan"])
def test_kesimpulan_lama_tidak_berubah(ping, port_lain, port_terbuka, harus_memuat):
    """Regression guard: states previously concluded correctly stay correct."""
    k = diagnosa.simpulkan(ping, False, port_lain, port_terbuka=port_terbuka)
    assert harus_memuat in k, "-> %s" % k


def test_baris_bukti_lama_di_basis_data_tetap_terbaca_sama():
    """Already-stored rows have no service port and no INFO marker. Their meaning
    must not change after this fix; history that silently changes meaning is
    worse than lost history.
    """
    old = rs._urai_bukti("OK|Ping menjawab (1.00 ms), mesinnya hidup\n"
                          "GAGAL|Port 443 tidak menjawab")
    assert len(old) == 2
    assert old[0]["ok"] is True
    assert old[1]["ok"] is False


def test_baris_tanpa_penanda_tetap_netral():
    assert rs._urai_bukti("sekadar catatan")[0]["ok"] is None

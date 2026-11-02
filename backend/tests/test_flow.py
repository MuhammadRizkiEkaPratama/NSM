"""FLOW reader (`connectors/flow.py`): TCP conversations from `ss -tin`.

The old `POLA_ALAMAT` used `\\S+` for local/peer addresses, the same shape that
let NUL bytes become a huge `ip_klien` in `akseslog.py` and roll back the save
transaction. The source here is live `ss -tin` output, so risk is lower, but
the pattern was tightened anyway.

Runs purely in memory: no database, no devices.
"""
import pytest

from connectors import flow

pytestmark = pytest.mark.murni


def test_baris_ss_tin_normal_ipv4_terurai():
    output = (
        "0      0      192.168.56.103:22   192.168.56.1:50393\n"
        "\t bytes_sent:1234 bytes_received:5678\n"
    )
    hasil = flow.urai(output)
    assert len(hasil) == 1

    k = hasil[0]
    assert k["ip_lokal"] == "192.168.56.103"
    assert k["ip_lawan"] == "192.168.56.1"
    assert k["port_lokal"] == 22
    assert k["byte_keluar"] == 1234.0
    assert k["byte_masuk"] == 5678.0


def test_alamat_ipv6_berkurung_siku_tetap_terurai():
    """Regression guard: the square brackets are dropped, their content is not."""
    hasil = flow.urai("0      0      [::1]:8080   [::ffff:192.168.56.1]:443\n")
    assert len(hasil) == 1
    assert hasil[0]["ip_lokal"] == "::1"


def test_byte_nul_di_alamat_tidak_tertelan():
    """Regression: a line containing NUL bytes must yield no connection at all
    (the old pattern turned it into a huge address that rolled back the transaction).
    """
    output = ("0      0      " + ("\x00" * 300)
                + "192.168.56.103:22   192.168.56.1:50393\n")
    assert flow.urai(output) == [], "baris ber-NUL tidak boleh cocok pola"


def test_alamat_berpenanda_zona_antarmuka_tetap_terbaca():
    """Regression, second attempt: the first fix whitelisted pure IP characters,
    which silently dropped valid forms such as `10.0.2.15%enp0s3` (Linux
    interface zone). The pattern now only forbids NUL. This test prevents
    over-tightening, which is a silent failure.
    """
    hasil = flow.urai("0      0      10.0.2.15%enp0s3:68   10.0.2.2:67\n")
    assert len(hasil) == 1, "alamat berpenanda zona TETAP menghasilkan koneksi"
    assert hasil[0]["ip_lokal"] == "10.0.2.15%enp0s3", "penanda zonanya utuh"


def test_alamat_sangat_panjang_dipotong_atau_ditolak():
    """Second net: length is capped even if the pattern lets a value through. Either
    rejecting or truncating is fine; a 500-digit address must not reach the database column.
    """
    hasil = flow.urai("0      0      %s:22   192.168.56.1:50393\n" % ("1" * 500))
    if hasil:
        assert len(hasil[0]["ip_lokal"]) <= 45, (
            "dipotong ke <=45 karakter, dapat %d" % len(hasil[0]["ip_lokal"]))

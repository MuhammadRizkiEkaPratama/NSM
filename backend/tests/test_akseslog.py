"""Web access log parser (`connectors/akseslog.py`).

A corrupt log line (leading NUL bytes from a log write cut off by a crash)
used to match the old IP pattern (`\\S+`) and produce a client IP hundreds of
bytes long, exceeding the MySQL column ("Data too long"). Because all rows of
a device are saved in one transaction, one bad line rolled back every row and
stalled the log read position without any visible error.

Fixed in two layers: the pattern only accepts valid IPv4/IPv6 characters, and
`ip_klien` is truncated to 45 characters as a second net, like the other fields.

Runs purely in memory: no database, no devices.
"""
import pytest

from connectors import akseslog

pytestmark = pytest.mark.murni

BARIS_NORMAL = ('192.168.56.1 - - [08/Aug/2026:18:05:59 +0000] '
                '"GET /login HTTP/1.1" 200 10929 "-" "Mozilla/5.0"')

BARIS_LENGKAP = ('192.168.56.1 - - [17/Aug/2026:04:43:36 +0000] '
                 '"GET /login HTTP/1.1" 200 10929 "-" '
                 '"NSM-Monitor/1.0 (Network Status Monitor)"')


def test_baris_normal_terurai():
    d = akseslog.urai_baris(BARIS_NORMAL)
    assert d is not None, "baris normal tidak terurai"
    assert d["ip_klien"] == "192.168.56.1"
    assert d["metode"] == "GET"
    assert d["path"] == "/login"
    assert d["status"] == 200


def test_baris_ber_nul_tidak_cocok_sama_sekali():
    """Regression: a corrupt line must not match at all. A half-parsed line would
    still be saved and roll back the transaction.
    """
    baris = ("\x00" * 300 + '192.168.56.1 - - [15/Aug/2026:19:19:58 +0000] '
             '"GET /login HTTP/1.1" 200 10929 "-" "UjiNSM/1.0"')
    d = akseslog.urai_baris(baris)
    assert d is None, (
        "ip_klien %r sepanjang %d"
        % ((d or {}).get("ip_klien"), len((d or {}).get("ip_klien") or "")))


def test_ip_panjang_ditolak_atau_dipotong():
    """Second net: length is capped even if the pattern lets a value through.
    Either outcome (pattern rejects or value truncated) is acceptable; an
    oversized string reaching the database column is not.
    """
    baris = ('%s - - [08/Aug/2026:18:05:59 +0000] '
             '"GET /login HTTP/1.1" 200 10929 "-" "Mozilla/5.0"' % ("1" * 500))
    d = akseslog.urai_baris(baris)
    if d is not None:
        assert len(d["ip_klien"]) <= 45, "panjangnya %d" % len(d["ip_klien"])


def test_baris_terakhir_yang_terpotong_tidak_jadi_baris_baru():
    """Regression: a read cut off mid-line (`head -c` at byte 1,000,000 of the
    access log) must not advance the position, so the line is re-read whole on the
    next round. Advancing would lose half a line and leave a phantom address.
    """
    potongan = "5000\n" + BARIS_LENGKAP[:87]  # cut off, without "\n"
    baris, posisi, _rotated, _exists = akseslog.baca_potongan(potongan, 0)
    assert baris == [], "baris terpotong ikut jadi baris baru -> %r" % baris
    assert posisi == 0, "posisi maju, jadi separuh baris hilang selamanya"


def test_putaran_berikutnya_membaca_baris_itu_utuh():
    """Counterpart of the test above: once the server finishes writing, the line is complete."""
    potongan_1 = "5000\n" + BARIS_LENGKAP[:87]
    _b1, posisi1, _d1, _a1 = akseslog.baca_potongan(potongan_1, 0)

    potongan_2 = "5000\n" + BARIS_LENGKAP + "\n"
    baris2, _p2, _d2, _a2 = akseslog.baca_potongan(potongan_2, posisi1)
    assert len(baris2) == 1, "baris utuh terbaca sekali jalan, bukan pecah"

    d = akseslog.urai_baris(baris2[0])
    assert d is not None
    assert d["ip_klien"] == "192.168.56.1", "ip_klien harus UTUH, bukan potongan"


def test_potongan_yang_memang_lengkap_tetap_terbaca():
    """Opposite direction: complete lines must not be held back. Tightening that
    drops valid lines is a silent failure.
    """
    potongan = "5000\n" + BARIS_LENGKAP + "\n"
    baris, _p, _d, _a = akseslog.baca_potongan(potongan, 0)
    assert len(baris) == 1

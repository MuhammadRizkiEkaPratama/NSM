"""Cause/effect separation tests with synthetic scenarios.

Eight independent scenarios, so one failing scenario does not hide the others.
Synthetic data is used rather than taking down real servers: `akar.nilai()`
is pure (it takes the list of failed services as an argument instead of
reading the database), so every branch can be tested without breaking anything.
"""
import pytest

import akar

pytestmark = pytest.mark.murni


# Synthetic map mimicking this lab:
#   service 3 = MySQL on device 11 (data server)
#   service 5 = E-Canteen on device 6 (web server)
#   service 7 = LDAP on device 4 (directory)
#   service 2 = SSH on device 6 (web server)
PETA = {
    5: [(3, None, "E-Canteen menyimpan datanya di basis data ini"),
        (7, None, "sandi diperiksa ke direktori")],
    2: [(7, None, "sssd mengenali pemakai dari direktori")],
    8: [(None, 11, "aplikasinya berjalan di mesin itu")],
}


def vonis(hasil, sid):
    return hasil[sid]["vonis"]


def test_data_server_mati_mysql_akibat_ecanteen_akibat():
    h = akar.nilai(None, {3: 11, 5: 6}, {11}, peta=PETA)
    assert vonis(h, 3) == "akibat", "MySQL disebut akibat (mesinnya sendiri mati)"
    assert h[3]["karena_device"] == 11, "alasannya menunjuk ke perangkat"
    assert vonis(h, 5) == "akibat", "E-Canteen disebut akibat"
    assert h[5]["karena_layanan"] == 3, "alasannya menunjuk ke MySQL"


def test_hanya_mysql_mati_mesin_sehat_maka_mysql_sebab():
    h = akar.nilai(None, {3: 11, 5: 6}, set(), peta=PETA)
    assert vonis(h, 3) == "sebab", "MySQL disebut sebab"
    assert vonis(h, 5) == "akibat", "E-Canteen tetap akibat"


def test_direktori_mati_menjatuhkan_dua_layanan_di_dua_mesin():
    h = akar.nilai(None, {7: 4, 5: 6, 2: 6}, set(), peta=PETA)
    assert vonis(h, 7) == "sebab", "LDAP disebut sebab"
    assert vonis(h, 5) == "akibat", "E-Canteen akibat"
    assert vonis(h, 2) == "akibat", "SSH server web akibat"


def test_dua_gangguan_tak_berhubungan_tetap_dua_sebab():
    h = akar.nilai(None, {3: 11, 2: 6}, set(), peta=PETA)
    assert vonis(h, 3) == "sebab", "MySQL sebab"
    assert vonis(h, 2) == "sebab", "SSH server web sebab (LDAP-nya sehat)"


def test_bergantung_pada_perangkat_bukan_layanan():
    h = akar.nilai(None, {8: 6}, {11}, peta=PETA)
    assert vonis(h, 8) == "akibat", "layanan 8 akibat karena perangkat 11 mati"


def test_lingkaran_ketergantungan_tidak_menggantung():
    """What matters is that it terminates, not that the answer is right.

    A dependency cycle has no right answer; the evaluation must not loop forever
    or drop a node from the result.
    """
    circle = {1: [(2, None, "a butuh b")], 2: [(1, None, "b butuh a")]}
    h = akar.nilai(None, {1: 9, 2: 9}, set(), peta=circle)
    assert sorted(h) == [1, 2], "keduanya dinilai, tidak ada yang hilang"


def test_semuanya_sehat_tidak_ada_vonis():
    h = akar.nilai(None, {}, set(), peta=PETA)
    assert h == {}, "tidak ada vonis sama sekali"
    assert akar.ringkas(h) == "", "ringkasannya kosong"


def test_kalimat_ringkasan_menyebut_jumlah_terdampak():
    h = akar.nilai(None, {3: 11, 5: 6, 2: 6}, {11}, peta=PETA)
    r = akar.ringkas(h)
    assert "ikut terdampak" in r, "menyebut jumlah sebab dan terdampak -> %r" % r

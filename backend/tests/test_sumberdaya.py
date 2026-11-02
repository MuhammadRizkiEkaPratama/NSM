"""Saturation readings: number parsing and thresholds.

The parser is tested apart from the device because `df`, `free`, and
`/proc/loadavg` output differs across distributions and versions. Testing over
SSH against one server only tests the one output shape it happens to use.
Here broken shapes are tested too (missing line, absurd number, empty output):
a read failure must never end up as zero, or an unreadable machine would look
like the most relaxed machine on the network.
"""
import pytest

from connectors import sumberdaya as sd

pytestmark = pytest.mark.murni

NORMAL = "disk=47\nmem=72.0\nload1=1.12\ninti=2\n"


def test_keluaran_normal_terurai():
    n = sd.urai(NORMAL)
    assert n.get("disk") == 47.0
    assert n.get("mem") == 72.0
    # 1.12 divided by 2 cores = 0.56, so it compares with machines of a different core count.
    assert n.get("load") == 0.56, "beban DIBAGI jumlah inti"


@pytest.mark.parametrize("masukan", ["", None], ids=["kosong", "None"])
def test_keluaran_kosong_tidak_menghasilkan_angka_nol(masukan):
    """If empty were read as 0%, a machine that FAILED TO BE READ would look the most
    relaxed. "Unknown" and "relaxed" are opposite conclusions and only one may reassure.
    """
    assert sd.urai(masukan) == {}


def test_vonis_atas_nilai_kosong_juga_kosong():
    assert sd.vonis({}) == {}


def test_baris_yang_hilang_tidak_merusak_yang_lain():
    n = sd.urai("disk=91\ninti=4\n")
    assert n.get("disk") == 91.0, "disk tetap terbaca"
    assert "mem" not in n, "memori tidak diisi tebakan"
    assert "load" not in n, "beban tidak dihitung tanpa load1"


def test_beban_tanpa_jumlah_inti_tidak_dibagi_sembarangan():
    n = sd.urai("load1=3.0\n")
    assert n.get("load1") == 3.0, "load1 mentah tetap ada"
    assert "load" not in n, "load per inti TIDAK dikarang"


@pytest.mark.parametrize("nilai,vonis_harap", [
    (79.0, "sehat"),
    (80.0, "perhatian"),  # EXACTLY at the threshold -> escalates
    (89.9, "perhatian"),
    (90.0, "bahaya"),  # EXACTLY at the threshold -> escalates
], ids=["79_sehat", "80_perhatian", "89.9_perhatian", "90_bahaya"])
def test_ambang_disk_dua_tingkat(nilai, vonis_harap):
    assert sd.vonis({"disk": nilai})["disk"] == vonis_harap


@pytest.mark.parametrize("nilai,vonis_harap", [
    (80.0, "sehat"),  # the original label had a typo; the value is correct
    (86.0, "perhatian"),
], ids=["80_sehat", "86_perhatian"])
def test_ambang_memori(nilai, vonis_harap):
    """Memory uses the `available` column, not `used`; with `used`, Linux counts
    cache as used and a healthy machine would always read 90%.
    """
    assert sd.vonis({"mem": nilai})["mem"] == vonis_harap


@pytest.mark.parametrize("ukuran", ["disk", "mem", "load"])
def test_tiap_ukuran_punya_kalimat_dan_langkahnya(ukuran):
    assert sd.ARTI.get(ukuran), "%s tidak punya kalimat arti" % ukuran
    assert len(sd.LANGKAH.get(ukuran, [])) >= 2, (
        "%s punya kurang dari dua langkah" % ukuran)

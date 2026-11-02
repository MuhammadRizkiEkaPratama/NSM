"""Identity marker sources: ARP, SNMP, SSH.

Counterpart of `uji_identitas.py`, which tests the weighing; this tests
collection. Two cases come from real defects found in the lab:
1. The wrong NIC's MAC on multi-homed hosts: the first command returned the
   NAT NIC (default route) while ARP saw the host-only NIC NSM talks over.
2. MAC notation differs per OS (Windows hyphens, Linux colons, Cisco dots).

Both end the same way: the same MAC reads as different, the verdict becomes
`bertentangan`, and that blocks the write path. A guard that accuses correct
devices teaches people to disable it.

No device is contacted in this file.
"""
import pytest

import identitas_sumber as s

pytestmark = pytest.mark.murni

MAC_BAKU = "02:00:5e:10:00:01"

ARP_WINDOWS = """
Interface: 192.168.56.1 --- 0x3
  Internet Address      Physical Address      Type
  192.168.56.60         ca-01-0a-6f-00-00     dynamic
  192.168.56.101        08-00-27-35-8d-d0     dynamic
  192.168.56.255        ff-ff-ff-ff-ff-ff     static
  224.0.0.22            01-00-5e-00-00-16     static

Interface: 192.168.1.3 --- 0x9
  192.168.1.1           02-00-5e-10-00-01     dynamic
  192.168.1.255         ff-ff-ff-ff-ff-ff     static
"""

SHOW_VERSION = """Cisco IOS Software, 7200 Software (C7200-ADVENTERPRISEK9-M), Version 15.2(4)S7, RELEASE SOFTWARE (fc4)
Technical Support: http://www.cisco.com/techsupport
Copyright (c) 1986-2016 by Cisco Systems, Inc.

ROM: ROMMON EMULATION MICROCODE

R1 uptime is 2 hours, 11 minutes
System returned to ROM by unknown reload cause

Cisco 7206VXR (NPE400) processor (revision A) with 491520K/32768K bytes of memory.
Processor board ID 4279256517
"""


@pytest.mark.parametrize("bentuk", [
    "02-00-5e-10-00-01",      # Windows
    "02:00:5E:10:00:01",      # Linux, huruf besar
    "02:00:5e:10:00:01",      # Linux, huruf kecil
    "0200.5e10.0001",         # Cisco
    "2458-6ED0-190E",
])
def test_penulisan_mac_diseragamkan(bentuk):
    assert s.normalkan_mac(bentuk) == MAC_BAKU


def test_tiga_penulisan_berbeda_menghasilkan_satu_nilai():
    """Otherwise the same MAC from two sources is judged `bertentangan`, which blocks
    the write path to a correct device.
    """
    hasil = {s.normalkan_mac(x) for x in
             ("02-00-5e-10-00-01", "02:00:5E:10:00:01", "0200.5e10.0001")}
    assert len(hasil) == 1, "-> %r" % hasil


@pytest.mark.parametrize("buruk", [
    "", None, "bukan mac", "02-00-5e-10-00", "02-00-5e-10-00-01-ff",
], ids=["kosong", "None", "bukan_mac", "kurang_oktet", "lebih_oktet"])
def test_bentuk_mac_yang_tidak_sah_ditolak(buruk):
    assert s.normalkan_mac(buruk) is None


@pytest.mark.parametrize("semu", [
    "ff:ff:ff:ff:ff:ff",   # siaran
    "00:00:00:00:00:00",  # empty / `lo`
    "01:00:5e:00:00:fb",   # multicast IPv4
    "33:33:00:00:00:01",   # multicast IPv6
])
def test_mac_semu_dibuang(semu):
    assert s._mac_semu(semu)


def test_mac_sungguhan_tidak_ikut_dibuang():
    """Opposite-direction guard: an over-wide filter drops valid markers and pushes
    the verdict to `belum_diketahui`.
    """
    assert not s._mac_semu(MAC_BAKU)


@pytest.fixture(scope="module")
def peta_arp():
    return s.baca_arp(ARP_WINDOWS)


@pytest.mark.parametrize("alamat,mac", [
    ("192.168.56.60", "ca:01:0a:6f:00:00"),
    ("192.168.56.101", "08:00:27:35:8d:d0"),
    ("192.168.1.1", MAC_BAKU),
], ids=["router_gns3", "vm", "gateway_rumah"])
def test_arp_terbaca(peta_arp, alamat, mac):
    assert peta_arp.get(alamat) == mac


@pytest.mark.parametrize("alamat", ["192.168.56.255", "224.0.0.22"],
                         ids=["siaran", "multicast"])
def test_alamat_semu_tidak_ikut_masuk_peta(peta_arp, alamat):
    assert alamat not in peta_arp


def test_jumlah_yang_terbaca(peta_arp):
    assert len(peta_arp) == 3


@pytest.mark.parametrize("masukan", ["", None], ids=["kosong", "None"])
def test_arp_kosong_tidak_meledak(masukan):
    assert s.baca_arp(masukan) == {}


@pytest.fixture(scope="module")
def perintah_mac():
    return dict(s.perintah_linux("192.168.56.101"))["mac"]


def test_alamat_perangkat_ikut_ke_dalam_perintah(perintah_mac):
    assert "192.168.56.101" in perintah_mac, (
        "perintahnya tidak menyebut alamat, jadi ia menebak kartu")


def test_tidak_lagi_memakai_rute_bawaan(perintah_mac):
    """On multi-homed hosts the default route points at the NAT NIC while NSM talks
    over host-only. Both MACs are valid; the question was wrong.
    """
    assert "route show default" not in perintah_mac
    assert "route get" not in perintah_mac


def test_membaca_alamat_kartu_dari_sys_class_net(perintah_mac):
    assert "/sys/class/net/" in perintah_mac


def test_alamat_dibersihkan_sebelum_masuk_perintah_shell():
    malicious = dict(s.perintah_linux("192.168.1.1; rm -rf /"))["mac"]
    assert "rm -rf" not in malicious, "-> %r" % malicious
    assert ";" not in malicious.split("awk")[0], "-> %r" % malicious


def test_windows_ditanya_hostname_tapi_bukan_mac():
    """The laptop has a dozen NICs and a wrong answer would yield `bertentangan` on a
    correct device. The MAC is taken from `psutil`, mapped by address.
    """
    label = [x[0] for x in s.PERINTAH_WINDOWS]
    assert "hostname" in label
    assert "mac" not in label


# ---------------------------------------------------------------------------
# 6. Uraian `show version` Cisco
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def rinci_cisco():
    return s.urai_show_version(SHOW_VERSION)


def test_show_version_terurai(rinci_cisco):
    assert rinci_cisco.get("serial") == "4279256517"
    assert rinci_cisco.get("model") == "7206VXR"
    assert (rinci_cisco.get("versi_ios") or "").startswith("15.2"), (
        "-> %r" % rinci_cisco.get("versi_ios"))


def test_show_version_kosong_tidak_meledak():
    assert s.urai_show_version("") == {}


# ---------------------------------------------------------------------------
# 7. Uraian keluaran Linux
# ---------------------------------------------------------------------------
def test_keluaran_linux_terurai():
    clean = s.parse_linux({
        "machine_id": "af7c5983589e46ceba12cdefb762662f\n",
        "hostname": "nsm-ubuntu\n",
        "mac": "08:00:27:35:8d:d0\n",
    })
    assert clean.get("machine_id") == "af7c5983589e46ceba12cdefb762662f"
    assert clean.get("hostname") == "nsm-ubuntu"
    assert clean.get("mac") == "08:00:27:35:8d:d0", "sudah seragam"


@pytest.mark.parametrize("buruk", [
    "cat: /etc/machine-id: No such file or directory",
    "", "   ", "bukan-heks-sama-sekali",
], ids=["pesan_galat", "kosong", "spasi", "bukan_heks"])
def test_machine_id_yang_bukan_identitas_ditolak(buruk):
    """A marker containing an error message would be compared as if it were an
    identity, and two machines that both failed would look identical.
    """
    hasil = s.parse_linux({"machine_id": buruk})
    assert "machine_id" not in hasil, "tersimpan %r" % hasil.get("machine_id")


def test_keluaran_kosong_menghasilkan_penanda_kosong():
    assert s.parse_linux({}) == {}


def test_mac_nol_tidak_jadi_penanda():
    assert "mac" not in s.parse_linux({"mac": "00:00:00:00:00:00"})

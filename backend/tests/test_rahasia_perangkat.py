"""Per-platform secret masking, tested against vendor config samples.

The base patterns in `connectors/konfig.py POLA_RAHASIA` are Cisco IOS shaped
(`enable secret 5 ...`, `snmp-server community ...`, `password 7 ...`) and do
not match, for example:

    set password=Example                           (MikroTik)
    set psksecret ENC AK1abc==                     (FortiOS)
    local-user a password irreversible-cipher      (Huawei VRP)

Config snapshots are stored in `nsm.db`, which is copied to cloud storage by
the nightly backup, so unmasked secrets would leave the network.

Each platform is tested three ways:
1. the secret value is gone
2. the line structure stays (a vanished `snmp community` line is a change
   that must stay visible)
3. without the platform argument the secret is still present; otherwise the
   base patterns already caught it and the per-platform patterns prove nothing

No device is contacted. Samples are built from vendor documentation, like the
`dokumentasi`-level definitions they test.
"""
import pytest

import dialek_perangkat as dp
from connectors import konfig

pytestmark = pytest.mark.murni


CONTOH = {
    "mikrotik_routeros": (
        "/ppp secret\n"
        "add name=vpnuser password=RahasiaSekali service=pptp\n"
        "/snmp community\n"
        "set [ find default=yes ] name=publik authentication-password=AuthRahasia "
        "encryption-password=EncRahasia\n"
        "/interface wireless security-profiles\n"
        "set [ find default=yes ] wpa2-pre-shared-key=KunciWifi123\n"
        "/ip ipsec peer\n"
        "add address=1.2.3.4 secret=IpsecRahasia\n"
        "/ip address\n"
        "add address=10.0.0.1/24 interface=ether1\n"
    ),
    "juniper_junos": (
        "set system host-name R-JAKARTA\n"
        "set system root-authentication encrypted-password \"$6$aaa$bbb\"\n"
        "set system login user admin authentication encrypted-password \"$6$ccc$ddd\"\n"
        "set snmp community publikRO authorization read-only\n"
        "set security ike policy IKE-POL pre-shared-key ascii-text \"RahasiaIke\"\n"
        "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/24\n"
    ),
    "arista_eos": (
        "hostname SW-ARISTA\n"
        "username admin privilege 15 role network-admin secret sha512 $6$aaa$bbb\n"
        "tacacs-server key 7 070C285F4D06\n"
        "radius-server host 10.0.0.9 key 7 121A0C041104\n"
        "interface Ethernet1\n"
        "   description Uplink ke inti\n"
    ),
    "huawei_vrp": (
        "sysname SW-HUAWEI\n"
        "snmp-agent community read publikRO\n"
        "local-user admin password irreversible-cipher $1c$aaa$bbb\n"
        "ipsec proposal p1\n"
        " pre-shared-key cipher %^%#RahasiaIpsec#%^%\n"
        "ospf 1\n"
        " area 0.0.0.0\n"
        "  authentication-key cipher %^%#RahasiaOspf#%^%\n"
        "interface GigabitEthernet0/0/1\n"
        " ip address 10.0.0.1 255.255.255.0\n"
    ),
    "fortinet": (
        "config system admin\n"
        "    edit \"admin\"\n"
        "        set password ENC AK1RahasiaAdmin==\n"
        "    next\n"
        "end\n"
        "config vpn ipsec phase1-interface\n"
        "    edit \"vpn-kantor\"\n"
        "        set psksecret ENC AK1RahasiaPsk==\n"
        "        set remote-gw 203.0.113.9\n"
        "    next\n"
        "end\n"
        "config vpn certificate local\n"
        "    edit \"sertifikat-vpn\"\n"
        "        set private-key ENC AK1RahasiaKunci==\n"
        "    next\n"
        "end\n"
        "config system snmp user\n"
        "    edit \"pemantau\"\n"
        "        set auth-pwd ENC AK1RahasiaAuth==\n"
        "        set priv-pwd ENC AK1RahasiaPriv==\n"
        "    next\n"
        "end\n"
    ),
}

# Values that must not remain in stored text, per platform.
BOCOR = {
    "mikrotik_routeros": ["RahasiaSekali", "AuthRahasia", "EncRahasia",
                          "KunciWifi123", "IpsecRahasia"],
    "juniper_junos": ["$6$aaa$bbb", "$6$ccc$ddd", "publikRO", "RahasiaIke"],
    "arista_eos": ["$6$aaa$bbb", "070C285F4D06", "121A0C041104"],
    "huawei_vrp": ["publikRO", "$1c$aaa$bbb", "RahasiaIpsec", "RahasiaOspf"],
    "fortinet": ["AK1RahasiaAdmin", "AK1RahasiaPsk", "AK1RahasiaAuth",
                 "AK1RahasiaPriv", "AK1RahasiaKunci"],
}

# Lines that MUST stay readable after masking; losing structure hides changes
# that deserve attention.
BERTAHAN = {
    "mikrotik_routeros": ["/ppp secret", "name=vpnuser", "wpa2-pre-shared-key=",
                          "add address=10.0.0.1/24"],
    "juniper_junos": ["set system host-name R-JAKARTA", "encrypted-password",
                      "authorization read-only", "ge-0/0/0"],
    "arista_eos": ["hostname SW-ARISTA", "username admin privilege 15",
                   "tacacs-server key", "description Uplink ke inti"],
    "huawei_vrp": ["sysname SW-HUAWEI", "snmp-agent community read",
                   "local-user admin password", "ip address 10.0.0.1",
                   "authentication-key cipher"],
    "fortinet": ["config system admin", "set password", "set psksecret",
                 "set remote-gw 203.0.113.9", "set private-key"],
}


# Extra samples: other output forms of the same platform.
#
# Junos can be read in two forms; `juniper_junos.yaml` uses `| display set` but
# also keeps fallback patterns for the curly-brace form, in case the command is
# ever changed to plain `show configuration`. A fallback that is never tested is
# not a fallback.
CONTOH_TAMBAHAN = {
    "juniper_junos": [(
        "system {\n"
        "    host-name R-JAKARTA;\n"
        "    root-authentication {\n"
        "        encrypted-password \"$6$eee$fff\";\n"
        "    }\n"
        "}\n"
        "security {\n"
        "    ike {\n"
        "        policy IKE-POL {\n"
        "            pre-shared-key ascii-text \"RahasiaKurawal\";\n"
        "        }\n"
        "    }\n"
        "}\n"
    )],
}

BERPOLA = sorted(CONTOH)


@pytest.fixture(scope="module")
def tersamar():
    return {p: konfig.olah(CONTOH[p], p)[0] for p in BERPOLA}


@pytest.fixture(scope="module")
def tanpa_platform():
    """Same samples WITHOUT naming the platform (the behavior before definition
    files existed). Used by the opposite-direction guard.
    """
    return {p: konfig.olah(CONTOH[p])[0] for p in BERPOLA}


@pytest.mark.parametrize("platform", BERPOLA)
def test_definisinya_memang_punya_pola(platform):
    """Most basic guard: the tests below would pass by themselves if a sample
    happened to contain no secret at all.
    """
    assert dp.ambil(platform).rahasia, "%s tidak menyebut `rahasia:`" % platform


@pytest.mark.parametrize("platform", BERPOLA)
def test_nilai_rahasia_hilang(platform, tersamar):
    hasil = tersamar[platform]
    for value in BOCOR[platform]:
        assert value not in hasil, (
            "%s: %r masih tersimpan apa adanya\n---\n%s" % (platform, value, hasil))


@pytest.mark.parametrize("platform", BERPOLA)
def test_struktur_barisnya_bertahan(platform, tersamar):
    """Only the VALUE is replaced. Dropping the whole line would hide the most
    noteworthy change: an `snmp community` line that VANISHED from a config.
    """
    hasil = tersamar[platform]
    for chunk in BERTAHAN[platform]:
        assert chunk in hasil, (
            "%s: struktur %r ikut hilang\n---\n%s" % (platform, chunk, hasil))


@pytest.mark.parametrize("platform", BERPOLA)
def test_penanda_disamarkan_muncul(platform, tersamar):
    assert "<DISAMARKAN>" in tersamar[platform]


@pytest.mark.parametrize("platform", BERPOLA)
def test_tanpa_pola_platform_rahasianya_memang_bocor(platform, tanpa_platform):
    """Opposite-direction guard; without it the tests above prove nothing.

    If the Cisco-style base patterns already caught everything, the per-platform
    patterns add nothing and the "secret is gone" tests would stay green even if
    every definition file were deleted. One value per platform is enough to prove
    the gap exists.
    """
    hasil = tanpa_platform[platform]
    still_leak = [n for n in BOCOR[platform] if n in hasil]
    assert still_leak, (
        "%s: pola dasar Cisco sudah menangkap SEMUA rahasia di contoh ini, "
        "jadi pola per-platform di berkas definisinya tidak menambah apa pun. "
        "Kalau itu benar, hapus polanya; kalau contohnya yang kurang mewakili, "
        "perbaiki contohnya." % platform)


@pytest.mark.parametrize("platform", BERPOLA)
def test_tiap_pola_yang_didaftarkan_memang_menyala(platform):
    """Every pattern under `rahasia:` must actually catch something.

    Born from a real finding: when the first five vendor definitions were
    written, five of fifteen patterns never fired. Causes differ: the Cisco base
    pattern already caught it (redundant pattern), the sample lacked that form
    (add the sample), or the line form was invented (drop the pattern). All look
    the same from outside, a silent pattern, and a secret-masking file with dead
    patterns gives false confidence. This test forces each case to be resolved.
    """
    import re
    # The base patterns run first, so the remainder is checked. Extra samples are
    # included because a pattern may apply to only one output form of the platform.
    base = "\n".join(konfig.samarkan(c) for c in
                      [CONTOH[platform]] + CONTOH_TAMBAHAN.get(platform, []))
    for r in dp.ambil(platform).rahasia:
        pola = re.compile(r["pola"])
        assert pola.search(base), (
            "%s: pola %r tidak menangkap apa pun di contoh uji.\n"
            "Tiga kemungkinan, dan semuanya harus diselesaikan di sini:\n"
            "  1. pola dasar Cisco sudah menangkapnya -> buang polanya\n"
            "  2. contoh ujinya belum memuat bentuk itu -> tambah contohnya\n"
            "  3. bentuk barisnya dikarang -> buang polanya"
            % (platform, r["pola"]))


@pytest.mark.parametrize("platform", BERPOLA)
def test_polanya_kekal_dijalankan_dua_kali(platform, tersamar):
    """Masking already-masked text must not change it again; otherwise the
    fingerprint changes every round and NSM reports "config changed" for a device
    nobody touched (the failure `BARIS_BERUBAH_SENDIRI` already guards, via another door).
    """
    sekali = tersamar[platform]
    two_times, _ = konfig.olah(sekali, platform)
    assert two_times == sekali


@pytest.mark.parametrize("platform", BERPOLA)
def test_sidik_jari_stabil(platform):
    """Direct consequence of the test above, but through the path actually used to
    decide "needs saving or not".
    """
    a = konfig.olah(CONTOH[platform], platform)[1]
    b = konfig.olah(CONTOH[platform], platform)[1]
    assert a == b


def test_platform_tak_dikenal_tidak_meledak():
    """A device with an empty platform exists in the lab (a WiFi gateway with NULL
    platform) and must not stop processing.
    """
    for entah in (None, "", "nokia_sros"):
        teks, sidik = konfig.olah("hostname X\n", entah)
        assert teks == "hostname X"
        assert sidik


def test_perilaku_cisco_tidak_berubah():
    """Regression guard for the only platform actually monitored. `cisco_ios.yaml`
    has no `rahasia:` on purpose (the base patterns are Cisco-shaped), so naming
    the platform must not change any result for R1 and R2.
    """
    contoh = ("hostname R1\n"
              "enable secret 5 $1$aaa$bbb\n"
              "snmp-server community rahasia RO\n"
              "line vty 0 4\n"
              " password 7 08701E1D\n")
    assert konfig.olah(contoh) == konfig.olah(contoh, "cisco_ios")
    hasil = konfig.olah(contoh, "cisco_ios")[0]
    for bocor in ("$1$aaa$bbb", "rahasia", "08701E1D"):
        assert bocor not in hasil


@pytest.mark.parametrize("platform,contoh,bocor,bertahan", [
    ("juniper_junos", CONTOH_TAMBAHAN["juniper_junos"][0],
     ["$6$eee$fff", "RahasiaKurawal"],
     ["host-name R-JAKARTA;", "encrypted-password", "pre-shared-key"]),
], ids=["junos_kurung_kurawal"])
def test_bentuk_keluaran_lain_ikut_tersamar(platform, contoh, bocor, bertahan):
    """A fallback that is never tested is not a fallback.

    `juniper_junos.yaml` uses `show configuration | display set` but keeps
    patterns for the curly-brace form too, since the command could be changed. If
    the fallback silently failed, secret masking would vanish without a sound:
    the snapshot would look normal but contain password hashes.
    """
    hasil = konfig.olah(contoh, platform)[0]
    for value in bocor:
        assert value not in hasil, "%r masih ada\n---\n%s" % (value, hasil)
    for chunk in bertahan:
        assert chunk in hasil, "struktur %r hilang\n---\n%s" % (chunk, hasil)

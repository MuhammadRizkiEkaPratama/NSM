"""Parsing tested against REAL device output.

`test_rahasia_perangkat.py` tests masking against samples written from vendor
docs, which only contain forms already thought of. This file uses recordings:
config snapshots NSM stored on the lab instance for weeks, exported unchanged
from `konfig_snapshots`. The first sweep of 100 snapshots found a secret form
that passed every pattern, a community string at the tail of an
`snmp-server host ... version 2c <community> udp-port ...` line, which the
base pattern (only `snmp-server community X`) never touched.

Guards:
1. No secret is published. The recordings go into the public repo;
   `test_tidak_ada_rahasia_*` scans each file with the same patterns as the
   runtime scanner and fails for any new recording carrying a secret.
2. Parsing is correct on real input: interface list, address-holding
   interface lookup, ACL change detection, and masking idempotence.

No device is contacted in this file.
"""
import os
import re

import pytest

import dialek_perangkat as dp
from connectors import konfig

pytestmark = pytest.mark.murni

SEMUA = dp.rekaman()
CISCO = dp.rekaman("cisco_ios")

# Secret forms that must not remain in any recording. Deliberately WIDER than
# the runtime `POLA_RAHASIA`: that one masks, this one accuses. A masker may miss
# a form; the guard deciding what may be published must not.
POLA_BOCOR = [
    ("hash bergaya unix",
     re.compile(r"\$[0-9a-z]{1,3}\$[^\s$]{4,}")),
    ("kunci privat",
     re.compile(r"(?i)BEGIN [A-Z ]*PRIVATE KEY")),
    # The lookahead is at the START of the line, not mid-pattern. With
    # `(?!<DISAMARKAN>)` in the middle, the regex backtracked past the optional
    # `version 2c` group and matched the word `version` on already-masked lines,
    # wrongly accusing all four Cisco recordings. A guard that accuses the innocent
    # is as damaging as one that passes the guilty: both get disabled.
    ("community di baris snmp-server host",
     re.compile(r"(?im)^(?!.*<DISAMARKAN>)(?!.*\bversion\s+3\b)"
                r"\s*snmp-server\s+host\s+\S+"
                r"(?:\s+vrf\s+\S+)?(?:\s+(?:traps|informs))?"
                r"(?:\s+version\s+(?:1|2c))?\s+\S+")),
    ("community polos",
     re.compile(r"(?im)^\s*snmp-server\s+community\s+(?!<DISAMARKAN>)\S+")),
    ("secret/password polos",
     re.compile(r"(?im)^\s*\S*\s*(?:secret|password|passwd)\s+\d*\s*"
                r"(?!<DISAMARKAN>)\S+\s*$")),
    ("kunci pra-berbagi polos",
     re.compile(r"(?im)^\s*(?:pre-shared-key|key-string)\s+"
                r"(?!<DISAMARKAN>)\S+")),
]


def test_ada_rekamannya():
    """If empty, this whole file would pass without testing anything."""
    assert SEMUA, "tidak ada rekaman termuat"


def test_setiap_berkas_di_cakram_terdaftar_di_manifes():
    """A file missing from the manifest is never tested, including never scanned for secrets."""
    terdaftar = {r.berkas for r in SEMUA}
    di_cakram = set()
    for root_cause, _, berkas in os.walk(dp.DIREKTORI_REKAMAN):
        for b in berkas:
            # The manifest and its guide are not recordings. Excluded by NAME, not by
            # pattern: a pattern exclusion could silently swallow a recording that happens
            # to match, and an unlisted recording is never scanned for secrets.
            if b in (dp.NAMA_MANIFES, "README.md"):
                continue
            rel = os.path.relpath(os.path.join(root_cause, b), dp.DIREKTORI_REKAMAN)
            di_cakram.add(rel.replace(os.sep, "/"))
    assert di_cakram == terdaftar, (
        "hanya di cakram: %s | hanya di manifes: %s"
        % (sorted(di_cakram - terdaftar), sorted(terdaftar - di_cakram)))


@pytest.mark.parametrize("r", SEMUA, ids=lambda r: r.berkas)
def test_tiap_rekaman_menyebut_asal_usulnya(r):
    """A recording with no stated origin cannot be told apart from a hand-written sample."""
    assert r.perangkat, "%s: `perangkat` kosong" % r.berkas
    assert r.direkam, "%s: `direkam` kosong" % r.berkas
    assert r.platform in dp.semua(), (
        "%s: platform %r tidak punya berkas definisi" % (r.berkas, r.platform))


@pytest.mark.parametrize("r", SEMUA, ids=lambda r: r.berkas)
def test_rekaman_tidak_kosong(r):
    """An empty file would pass every test below. The minimum is low on purpose:
    what is guarded is that content exists, not its length.
    """
    assert len(r.teks.splitlines()) >= 10, "%s cuma %d baris" % (
        r.berkas, len(r.teks.splitlines()))


@pytest.mark.parametrize("r", SEMUA, ids=lambda r: r.berkas)
def test_tidak_ada_rahasia_di_rekaman(r):
    """MOST IMPORTANT GUARD IN THIS FILE.

    Recordings are published to the public repo. Once a secret enters Git
    history, removing it means rewriting history, and by then it is in every
    copy. So ADDING a recording fails here; the guard stands at the corpus
    entrance, not on the monitoring path.
    """
    for nama, pattern in POLA_BOCOR:
        cocok = pattern.search(r.teks)
        assert not cocok, (
            "%s memuat %s yang belum tersamar:\n    %s"
            % (r.berkas, nama, cocok.group(0).strip()[:100]))


def test_penjaga_rahasianya_memang_bisa_menuduh():
    """A guard never seen red has not proven it guards anything. Run against the
    EXACT line that once got through, not an invented example.
    """
    leak = ("snmp-server host 192.168.56.156 version 2c public udp-port 1162\n"
             "username nsm privilege 15 secret 5 $1$abc$defghijkl\n")
    kena = [nama for nama, pattern in POLA_BOCOR if pattern.search(leak)]
    assert "community di baris snmp-server host" in kena
    assert "hash bergaya unix" in kena


def test_penyamar_lab_menutup_bentuk_yang_pernah_lolos():
    """Opposite direction: the runtime pattern now really catches it. If this fails,
    old recordings stay clean (masked at export) but NEW snapshots would store the
    community string as is in the database, and the database goes into backups.
    """
    original = "snmp-server host 192.168.56.156 version 2c public udp-port 1162"
    hasil = konfig.samarkan(original)
    assert "public" not in hasil, "-> %s" % hasil
    assert "<DISAMARKAN>" in hasil
    assert "udp-port 1162" in hasil, "struktur barisnya ikut hilang -> %s" % hasil


@pytest.mark.parametrize("r", SEMUA, ids=lambda r: r.berkas)
def test_olah_kekal_pada_keluaran_nyata(r):
    """Processing twice must give the same result; otherwise the fingerprint
    changes every poller round and NSM reports "config changed" for untouched
    devices. Not theoretical: the new `snmp-server host` pattern violated it on
    first try (it backtracked past the optional `version 2c` group and masked the
    word `version` on the second pass), found by this test.
    """
    sekali, sidik1 = konfig.olah(r.teks, r.platform)
    two_times, sidik2 = konfig.olah(sekali, r.platform)
    assert two_times == sekali
    assert sidik1 == sidik2


@pytest.mark.parametrize("r", SEMUA, ids=lambda r: r.berkas)
def test_baris_berubah_sendiri_sudah_terbuang(r):
    """`ntp clock-period`, timestamps, and NVRAM usage reports change without anyone
    touching the device. If they survive `bersihkan()`, every comparison reports a false diff.
    """
    clean = konfig.bersihkan(r.teks)
    remaining = [b for b in clean.splitlines()
            if konfig.BARIS_BERUBAH_SENDIRI.match(b)]
    assert not remaining, "%s masih memuat %r" % (r.berkas, remaining[:3])


@pytest.mark.parametrize("r", CISCO, ids=lambda r: r.berkas)
def test_daftar_interface_menemukan_interface_nyata(r):
    """Used to validate command parameters. A pattern check alone is not enough:
    `FastEthernet9/9` matches any pattern but does not exist on the device.
    """
    iface = konfig.daftar_interface(r.teks)
    assert iface, "%s: tidak satu interface pun terbaca" % r.berkas
    assert len(iface) == len(set(iface)), "ada nama interface kembar"
    for n in iface:
        assert not n.startswith("!") and " " not in n, "nama aneh: %r" % n


@pytest.mark.parametrize("r", CISCO, ids=lambda r: r.berkas)
def test_interface_untuk_ip_konsisten_dengan_konfigurasinya_sendiri(r):
    """Every `ip address` in the config must trace back to the interface holding it.

    This prevents a class of error that already happened (docs/POSTMORTEM-R1.md):
    sending a shutdown command to the interface NSM itself uses to reach the
    device. Once sent, the connection drops and no reverse command can be sent.
    Tested both ways against real configs: each (interface, address) pair is
    taken from its own recording.
    """
    pair = []
    iface = None
    for line in r.teks.splitlines():
        m = re.match(r"^interface\s+(\S+)\s*$", line.strip(), re.I)
        if m:
            iface = m.group(1)
            continue
        m = re.match(r"^ip address\s+(\S+)\s+\S+", line.strip(), re.I)
        if m and iface:
            pair.append((iface, m.group(1)))

    assert pair, "%s: tidak ada `ip address` sama sekali" % r.berkas
    for nama, alamat in pair:
        assert konfig.interface_untuk_ip(r.teks, alamat) == nama, (
            "%s: alamat %s seharusnya di %s" % (r.berkas, alamat, nama))


@pytest.mark.parametrize("r", CISCO, ids=lambda r: r.berkas)
def test_alamat_yang_tidak_ada_menghasilkan_none(r):
    """Limit: not found must be None, not a guess. Callers treat None as "cannot be
    confirmed", NOT "safe"; an incomplete snapshot must not read as proof of safety.
    """
    assert konfig.interface_untuk_ip(r.teks, "203.0.113.99") is None


@pytest.fixture(scope="module")
def dasar():
    """A real Cisco config, already processed; the baseline for the comparisons below."""
    if not CISCO:
        pytest.skip("belum ada rekaman cisco_ios")
    return konfig.olah(CISCO[0].teks, "cisco_ios")[0]


def test_penambahan_acl_terdeteksi(dasar):
    """Born from a real event: an ACL line was added on R2 directly via its CLI
    between two consecutive snapshots, and `baris_tambah` could not tell "ACL
    changed" from "banner changed".
    """
    baru = dasar + "\nip access-list extended NSM-BLOKIR\n permit ip any any\n"
    _t, _h, diff = konfig.beda_baris(dasar, baru)
    assert konfig.deteksi_acl_berubah(diff) is True


def test_perubahan_bukan_acl_tidak_ikut_terdeteksi(dasar):
    """Opposite-direction guard: detection that answers "yes" to every change is not detection."""
    baru = dasar.replace("ip domain name lab.local", "ip domain name lab.lokal")
    if baru == dasar:
        baru = dasar + "\nbanner motd ^Uji^\n"
    _t, _h, diff = konfig.beda_baris(dasar, baru)
    assert konfig.deteksi_acl_berubah(diff) is False


def test_konfigurasi_yang_tidak_berubah_tidak_menghasilkan_selisih(dasar):
    """Foundation: the same snapshot must read the same. Otherwise every poller
    round saves a new snapshot for a quiet device and the history fills with
    changes that never happened.
    """
    tambah, delete, diff = konfig.beda_baris(dasar, dasar)
    assert (tambah, delete) == (0, 0)
    assert konfig.deteksi_acl_berubah(diff) is False


@pytest.mark.parametrize("r", CISCO, ids=lambda r: r.berkas)
def test_perintah_di_manifes_sama_dengan_yang_di_definisi(r):
    """A recording claiming to be one command's output but produced by another
    would test parsing against the wrong output, and pass.
    """
    assert r.perintah == dp.ambil(r.platform).perintah("konfigurasi")


def test_manifes_yang_menunjuk_berkas_hilang_ditolak(tmp_path, monkeypatch):
    """A dangling manifest is worse than an empty one: an empty one looks empty, a
    dangling one looks complete.
    """
    (tmp_path / dp.NAMA_MANIFES).write_text(
        "rekaman:\n- berkas: hantu/tidak-ada.txt\n  platform: linux\n",
        encoding="utf-8")
    monkeypatch.setattr(dp, "DIREKTORI_REKAMAN", str(tmp_path))
    with pytest.raises(dp.DefinisiRusak) as g:
        dp.rekaman()
    assert "tidak ada" in str(g.value)


def test_platform_tanpa_rekaman_menghasilkan_daftar_kosong():
    """Empty is NOT an error. Most platforms have no recordings yet, which is an honest state."""
    assert dp.rekaman("juniper_junos") == []
    assert dp.rekaman("entah_apa") == []


# `samarkan_ulang_potret.py` WRITES to the stored history on the lab instance,
# so the part deciding what it writes is tested here rather than trusted from a
# correct-looking dry run.
import samarkan_ulang_potret as sup  # noqa: E402


def test_penyamar_ulang_menyamarkan_baris_yang_dimaksud():
    old = ("hostname R1\n"
            "snmp-server host 192.168.56.156 version 2c public udp-port 1162\n")
    baru = sup.samarkan_saja(old, "cisco_ios")
    assert "public" not in baru
    assert "<DISAMARKAN>" in baru
    assert "hostname R1" in baru
    assert "udp-port 1162" in baru


def test_penyamar_ulang_TIDAK_ikut_membersihkan():
    """Safety core of that script. `olah()` runs `bersihkan()` at the end, and the
    cleaning rules were added later, after the oldest snapshots were stored. Using
    `olah()` to re-mask would apply today's rules to history recorded under
    yesterday's, i.e. rewrite history. The script's first dry run did abort itself
    for this reason on snapshots #1, #2, and #3.
    """
    old = ("Using 1019 out of 522232 bytes\n"
            "!\n"
            "!\n"
            "hostname R1\n"
            "ntp clock-period 17179738\n")
    baru = sup.samarkan_saja(old, "cisco_ios")
    assert baru == old, "penyamar ulang ikut membersihkan -> %r" % baru
    # Opposite direction: `olah()` does drop them, which is right for NEW
    # snapshots; only using it on old ones is wrong.
    assert konfig.olah(old, "cisco_ios")[0] != old


def test_penyamar_ulang_kekal():
    """Running it on already-masked snapshots changes nothing, so the script is safe to repeat."""
    old = "snmp-server host 10.0.0.1 version 2c Rahasia\n"
    sekali = sup.samarkan_saja(old, "cisco_ios")
    assert sup.periksa(sekali, "cisco_ios") == (None, None)


@pytest.mark.parametrize("r", CISCO, ids=lambda r: r.berkas)
def test_rekaman_yang_sudah_terbit_tidak_akan_disentuh_skrip_itu(r):
    """Recordings here were masked at export. If the script still finds something to
    change, the export used a different measure than the re-masker: two answers
    to one question.
    """
    assert sup.periksa(r.teks, r.platform) == (None, None)

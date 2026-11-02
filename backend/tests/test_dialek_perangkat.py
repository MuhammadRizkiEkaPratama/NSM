"""Device definition files: loader, validator, and the evidence-level rule.

1. The move to YAML must be a pure move: `test_setara_*` compare the literal
   values that applied before the definition files existed with the files.
2. A definition file cannot raise its own privileges. A platform whose
   definition was written from vendor docs and never run on a real device must
   not enable the write path, even if the file says `didukung: true`. A command
   that was correct per Cisco docs once permanently killed a lab router
   (docs/POSTMORTEM-R1.md).

No device is contacted in this file.
"""
import pytest
import yaml

import dialek_perangkat as dp
from connectors import konfig as _konfig
from connectors import ssh as _ssh

pytestmark = pytest.mark.murni


def test_semua_berkas_termuat():
    """If one file is broken, `_muat()` raises and NSM does not start. This is
    deliberate: a silently ignored broken definition silently removes a capability.
    """
    daftar = dp.muat_ulang()
    assert daftar, "tidak ada satu pun definisi termuat"


@pytest.mark.parametrize("nama", sorted(dp.semua()))
def test_tiap_definisi_punya_keterangan_dan_tingkat_bukti(nama):
    d = dp.ambil(nama)
    assert d.keterangan and d.keterangan != nama, (
        "%s: `keterangan` kosong -- yang muncul di layar tinggal nama teknisnya"
        % nama)
    assert d.teruji in dp.TERUJI


@pytest.mark.parametrize("nama", sorted(dp.semua()))
def test_definisi_teruji_menyebut_asalnya(nama):
    d = dp.ambil(nama)
    if d.teruji in ("lab", "rekaman"):
        assert d.sumber.strip(), "%s: teruji=%s tanpa `sumber`" % (nama, d.teruji)


SEBELUM_PINDAH = {
    "konfigurasi": {
        "cisco_ios": "show running-config",
        "mikrotik_routeros": "/export",
    },
    "konfigurasi_startup": {
        "cisco_ios": "show startup-config",
    },
}


@pytest.mark.parametrize("kunci", sorted(SEBELUM_PINDAH))
def test_nilai_lama_tidak_bergeser(kunci):
    """A move that shifts one value is not a move. R1 and R2 are monitored with these
    commands today; one wrong letter stops config collection silently.
    """
    for platform, perintah in SEBELUM_PINDAH[kunci].items():
        assert dp.ambil(platform).perintah(kunci) == perintah, (
            "%s.%s bergeser dari nilai labnya" % (platform, kunci))


@pytest.mark.parametrize("kunci,tabel", [
    ("konfigurasi", "PERINTAH"),
    ("konfigurasi_startup", "PERINTAH_STARTUP"),
])
def test_tabel_lab_memang_datang_dari_definisi(kunci, tabel):
    """`konfig.PERINTAH` is derived, not typed. This guards the derivation: if the
    table were rewritten as a literal, definition files would silently stop mattering.
    """
    from_file = {n: d.perintah(kunci)
                   for n, d in dp.semua().items() if d.perintah(kunci)}
    assert getattr(_konfig, tabel) == from_file


def test_platform_yang_ditambahkan_setelah_pemindahan_belum_teruji():
    """Platforms beyond those that existed before MUST have evidence level
    `dokumentasi`. Guards against someone adding a vendor file for hardware they do
    not own and writing `teruji: lab`, which would enable the write path with no
    command ever run.
    """
    # Only these four were ever actually contacted. `mikrotik_routeros` is
    # deliberately not exempt: being in the table is not proof it was ever run.
    earlier = {"cisco_ios", "linux", "windows", "lokal"}
    for nama, d in dp.semua().items():
        if nama in earlier:
            continue
        assert d.teruji == "dokumentasi", (
            "%s ditambahkan sesudah pemindahan tetapi mengaku `%s`. Kalau "
            "perangkatnya memang ada, ubah uji ini dan tulis buktinya di sana."
            % (nama, d.teruji))


def test_setara_perintah_cisco_yang_dipakai_ssh():
    baca = dp.ambil("cisco_ios").baca
    for kunci, perintah in (
            ("nama_host", "show run | include hostname"),
            ("identitas", "show version | include Cisco IOS Software"),
            ("uptime", "show version | include uptime"),
            ("interface_ringkas", "show ip interface brief"),
            ("tabel_rute", "show ip route"),
            ("cpu", "show processes cpu | include CPU utilization"),
            ("interface_rinci", "show interfaces"),
    ):
        assert baca.get(kunci) == perintah, (
            "cisco_ios.baca.%s -> %r" % (kunci, baca.get(kunci)))


@pytest.fixture(scope="module")
def teks_di_ssh():
    """Every text literal in `connectors/ssh.py`, after decoding.

    Uses `ast` rather than raw text: the source writes `"ipconfig | findstr /i \\\\"IPv4\\\\""`
    while the device receives no backslashes. Compare what is sent, not what is typed.
    """
    import ast
    with open(_ssh.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


@pytest.mark.parametrize("platform", ["linux", "windows", "cisco_ios"])
def test_tiap_perintah_bertingkat_lab_ada_di_kode_lab(platform, teks_di_ssh):
    """Every command in a `lab`-level file must appear verbatim in the production
    code it came from. Comparing against the source proves `teruji: lab` means the
    command really ran, not that it was written from docs. Commands live in more
    than one place in `ssh.py` (tables and function bodies), so the whole text is searched.
    """
    d = dp.ambil(platform)
    assert d.teruji == "lab", "uji ini khusus definisi yang mengaku `lab`"
    for kunci, perintah in d.baca.items():
        if perintah in _konfig.PERINTAH.values():
            continue                      # asalnya konfig.py, diuji terpisah
        if perintah in _konfig.PERINTAH_STARTUP.values():
            continue
        assert perintah in teks_di_ssh, (
            "%s.baca.%s = %r tidak ada di %s -- ini perintah KARANGAN, dan "
            "berkasnya mengaku `teruji: lab`"
            % (platform, kunci, perintah, _ssh.__file__))


def test_linux_sengaja_tidak_punya_perintah_konfigurasi():
    """Absence is meaningful. Linux has no single equivalent of `show running-config`;
    guessing (`cat /etc/network/interfaces`) would report "config changed" on every
    netplan/NetworkManager host, and an always-on warning stops being read.
    """
    assert dp.ambil("linux").perintah("konfigurasi") is None
    assert "linux" not in _konfig.PERINTAH, "kedua sisi harus sepakat"


def buat(**isi):
    base = {"nama": "uji", "teruji": "dokumentasi"}
    base.update(isi)
    return dp.Definisi(base["nama"], base)


def test_definisi_dokumentasi_tidak_boleh_menulis():
    """Core rule: the file says yes; the answer is still no."""
    d = buat(teruji="dokumentasi", tulis={"didukung": True, "simpan": "save"})
    assert d.tulis["didukung"] is True, "berkasnya memang menyatakan boleh"
    assert d.boleh_menulis is False, "tapi haknya tidak ikut naik"


def test_definisi_lab_boleh_menulis():
    """Opposite-direction guard: a rule that answers "no" to every input is a wall, not a rule."""
    d = buat(teruji="lab", sumber="R1", tulis={"didukung": True})
    assert d.boleh_menulis is True


def test_definisi_rekaman_TIDAK_boleh_menulis():
    """Reversed in step 9.4: `rekaman` (recorded output) must NOT permit writes.

    Adding recordings is entirely offline, so it must not enable the write path
    for vendors nobody here has touched. Recordings prove we can read what a
    device says, not what a write command does there (that is what killed R1).
    """
    d = buat(teruji="rekaman", sumber="rekaman vendor",
             tulis={"didukung": True})
    assert d.tulis["didukung"] is True, "berkasnya memang menyatakan boleh"
    assert d.boleh_menulis is False, "tapi rekaman tidak memberi izin menulis"


def test_lab_yang_tidak_menyatakan_didukung_tetap_tidak_boleh():
    assert buat(teruji="lab", sumber="R1", tulis={}).boleh_menulis is False


@pytest.mark.parametrize("nama", sorted(dp.semua()))
def test_tidak_ada_definisi_terpasang_yang_melanggar(nama):
    d = dp.ambil(nama)
    if d.teruji == "dokumentasi":
        assert d.boleh_menulis is False, (
            "%s bertingkat `dokumentasi` tetapi jalur tulisnya menyala" % nama)


def test_jaring_pengaman_bawaannya_tidak_ada():
    """A wrong default here kills devices (docs/POSTMORTEM-R1.md), so a file's
    silence must mean "does not have".
    """
    assert buat().jaring_pengaman["jenis"] == "tidak_ada"
    assert dp.TIDAK_DIKENAL.jaring_pengaman["jenis"] == "tidak_ada"
    assert buat().bisa_pasang_jaring_pengaman is False


def test_punya_mekanisme_TIDAK_sama_dengan_bisa_memasangnya():
    """Replaces `reload_aman`. Arista, Huawei, and MikroTik have safety-net
    mechanisms but NSM does not know the command sequence for any of them;
    equating "has" with "can be installed" would make NSM think they are protected.
    """
    has = buat(tulis={"jaring_pengaman": {"jenis": "reload"}})
    assert has.jaring_pengaman["jenis"] == "reload"
    assert has.bisa_pasang_jaring_pengaman is False, (
        "mengaku bisa memasang padahal `pasang` kosong")

    can = buat(tulis={"jaring_pengaman": {
        "jenis": "reload", "pasang": "reload in {menit}",
        "penanda_terpasang": ["scheduled"]}})
    assert can.bisa_pasang_jaring_pengaman is True


@pytest.mark.parametrize("nama,jenis", [
    ("cisco_ios", "reload"),
    ("juniper_junos", "commit_confirmed"),
    ("arista_eos", "commit_confirmed"),
    ("huawei_vrp", "reload"),
    ("mikrotik_routeros", "commit_confirmed"),
    ("fortinet", "tidak_ada"),
    ("linux", "tidak_ada"),
    ("windows", "tidak_ada"),
    ("lokal", "tidak_ada"),
])
def test_tiap_platform_menyatakan_jaring_pengamannya(nama, jenis):
    """The field used to be `reload_aman`, and three of nine platforms misleadingly
    answered "no" (their safety net exists, just not as `reload`).
    """
    assert dp.ambil(nama).jaring_pengaman["jenis"] == jenis


def test_hanya_cisco_dan_junos_yang_bisa_dipasang_hari_ini():
    """Pinned so adding a platform is a conscious decision: it makes NSM start
    sending safety-net setup commands to that vendor's devices.
    """
    can = sorted(n for n, d in dp.semua().items()
                  if d.bisa_pasang_jaring_pengaman)
    assert can == ["cisco_ios", "juniper_junos"]


def test_jaring_yang_bisa_dipasang_wajib_bisa_dibuktikan():
    """Setup commands can fail silently (permission denied, unanswered prompt). If
    sending continued anyway, the command would run with no safety net at all.
    """
    with pytest.raises(dp.DefinisiRusak) as g:
        dp._periksa("uji.yaml", {
            "nama": "x", "teruji": "dokumentasi",
            "tulis": {"jaring_pengaman": {"jenis": "reload",
                                          "pasang": "reload in 5"}}})
    assert "penanda_terpasang" in str(g.value)


@pytest.mark.parametrize("nama", sorted(dp.semua()))
def test_jaring_pengaman_terpasang_wajib_punya_penandanya(nama):
    j = dp.ambil(nama).jaring_pengaman
    if j["pasang"]:
        assert j["penanda_terpasang"], "%s: `pasang` tanpa `penanda_terpasang`" % nama
        assert j["kukuhkan"], (
            "%s: bisa memasang jaring tetapi tidak bisa mengukuhkannya -- "
            "perangkatnya akan pulih sendiri walau perubahannya benar" % nama)


@pytest.mark.parametrize("entah", ["nokia_sros", "", None, "cisco ios"],
                         ids=["vendor_lain", "kosong", "None", "ejaan_lain"])
def test_platform_tak_dikenal_dapat_definisi_aman(entah):
    """A device that vanishes from the screen because its platform is unknown is
    worse than one with partial data. Ping, TCP, and SNMP need no definition.
    """
    d = dp.ambil(entah)
    assert d is not None
    assert d.perintah("konfigurasi") is None
    assert d.boleh_menulis is False
    assert d.jaring_pengaman["jenis"] == "tidak_ada"
    assert d.dikenal is False


def test_netmiko_device_type_jatuh_ke_nama_platform():
    assert buat(nama="arista_eos").netmiko_device_type == "arista_eos"
    assert buat(nama="huawei_vrp",
                akses={"netmiko_device_type": "huawei"}).netmiko_device_type == "huawei"


@pytest.mark.parametrize("isi,potongan_pesan", [
    ({"nama": "x", "teruji": "lab", "sumber": "R1", "bacaa": {}}, "tidak dikenal"),
    ({"nama": "x", "teruji": "sudah_dicoba"}, "teruji harus"),
    ({"nama": "x", "teruji": "lab"}, "wajib menyebut `sumber`"),
    ({"nama": "x", "teruji": "dokumentasi", "deteksi": {"sysobjektid": []}},
     "deteksi.sysobjektid"),
    ({"nama": "x", "teruji": "dokumentasi", "akses": {"jenis": "router"}},
     "akses.jenis harus"),
    ({"nama": "x", "teruji": "dokumentasi", "baca": {"cpu": 5}},
     "harus teks perintah"),
    ({"nama": "x", "teruji": "dokumentasi", "rahasia": [{"pola": "a"}]},
     "rahasia[0]"),
    ({"nama": "x", "teruji": "dokumentasi", "tulis": {"reload_amaan": True}},
     "tulis.reload_amaan"),
], ids=["kunci_salah_ketik", "teruji_ngawur", "lab_tanpa_sumber",
        "deteksi_salah_ketik", "jenis_ngawur", "perintah_bukan_teks",
        "rahasia_tak_lengkap", "tulis_salah_ketik"])
def test_berkas_salah_ditolak_saat_dimuat(isi, potongan_pesan):
    """A typo that is silently ignored changes from "fails at load" to "quietly has
    no effect", which is only noticed months later.
    """
    with pytest.raises(dp.DefinisiRusak) as error:
        dp._periksa("uji.yaml", isi)
    assert potongan_pesan in str(error.value), "-> %s" % error.value


def test_berkas_benar_lolos():
    """Opposite-direction guard: a validator that rejects everything validates nothing."""
    dp._periksa("uji.yaml", {
        "nama": "x", "keterangan": "X", "teruji": "lab", "sumber": "R1",
        "deteksi": {"sysobjectid": [".1.3.6.1.4.1.9."]},
        "akses": {"netmiko_device_type": "cisco_ios", "jenis": "jaringan"},
        "baca": {"konfigurasi": "show running-config"},
        "tulis": {"didukung": True, "simpan": "write memory"},
        "rahasia": [{"pola": "^password ", "ganti": "<X>"}],
    })


@pytest.mark.parametrize("nama", sorted(dp.semua()))
def test_nama_di_dalam_berkas_sama_dengan_nama_berkasnya(nama):
    d = dp.ambil(nama)
    import os
    assert os.path.basename(d.berkas) == "%s.yaml" % nama


@pytest.mark.parametrize("oid,harap", [
    (".1.3.6.1.4.1.9.1.222", "cisco_ios"),
    ("1.3.6.1.4.1.9.1.222", "cisco_ios"),  # without leading dot
    (".1.3.6.1.4.1.8072.3.2.10", "linux"),
    (".1.3.6.1.4.1.99999.1", None),  # vendor without a file yet
    ("", None),
    (None, None),
], ids=["cisco", "cisco_tanpa_titik", "linux", "vendor_asing", "kosong", "None"])
def test_cocok_sysobjectid(oid, harap):
    assert dp.dari_sysobjectid(oid) == harap


def test_prefiks_lebih_rinci_menang():
    """One device can match two definitions (vendor prefix and model prefix); the
    more specific one wins.
    """
    general = buat(nama="vendor_umum", deteksi={"sysobjectid": [".1.3.6.1.4.1.9."]})
    detail = buat(nama="model_khusus",
                 deteksi={"sysobjectid": [".1.3.6.1.4.1.9.1.1745"]})
    oid = ".1.3.6.1.4.1.9.1.1745"
    assert general.cocok_sysobjectid(oid) and detail.cocok_sysobjectid(oid)

    original = dp._DAFTAR
    try:
        dp._DAFTAR = {"vendor_umum": general, "model_khusus": detail}
        assert dp.dari_sysobjectid(oid) == "model_khusus"
    finally:
        dp._DAFTAR = original


def test_direktori_definisi_tidak_menyimpan_berkas_asing():
    """Non-`.yaml` files in this directory are silently ignored by `_muat()`, which
    is exactly how a definition goes missing unnoticed.
    """
    import os
    for berkas in os.listdir(dp.DIREKTORI):
        if berkas == "rekaman":
            # Corpus of recorded real device output; its content is guarded by
            # `tests/test_rekaman.py`, including the secret scan.
            assert os.path.isdir(os.path.join(dp.DIREKTORI, berkas))
            continue
        assert berkas.endswith(".yaml") or berkas == "README.md", (
            "berkas asing di direktori definisi: %s" % berkas)


@pytest.mark.parametrize("nama", sorted(dp.semua()))
def test_berkas_bisa_dibaca_ulang_utuh(nama):
    """Reloading must yield the same content (guards against YAML that depends on file order)."""
    with open(dp.ambil(nama).berkas, encoding="utf-8") as f:
        isi = yaml.safe_load(f)
    assert isi["nama"] == nama


# Values that applied before capabilities existed, copied verbatim from the
# moved `platform ==` branches. Written as literals, not read from the definition
# files: the selected platform set decides which devices the poller contacts,
# the firewall blocks, and the recovery restores. A platform silently added
# means new SSH sessions; one silently removed means a device stops being monitored.
SEBELUM_KEMAMPUAN = {
    # `nsm/pemantau/firewall.py:249`, `ubah_acl_router.py:136`,
    # `penjaga_aksi.py:347,402`, `report_service/firewall.py:1000`
    ("firewall", "acl"): ["cisco_ios"],

    # `nsm/pemantau/firewall.py:420`, `ubah_firewall.py:102`,
    # `report_service/firewall.py:788,792,798,1089`
    ("firewall", "ufw"): ["linux"],

    # `nsm/pemantau/firewall.py:319`, `report_service/firewall.py:820`
    ("firewall", "netsh"): ["lokal"],

    # `nsm/pemantau/sumberdaya.py:36`
    ("baca_sumberdaya", True): ["linux"],

    # `nsm/pemantau/trafik.py:457`
    ("baca_trafik", True): ["linux"],

    # `nsm/pemantau/konfig.py:199`
    ("baca_konfig_layanan", True): ["linux"],

    # `identitas_sumber.py:344,380`
    ("identitas", "cisco"): ["cisco_ios"],
    ("identitas", "linux"): ["linux"],
    ("identitas", "windows"): ["windows"],

    # 14 places, see the `lokal` note in `_KEMAMPUAN`.
    ("lokal", True): ["lokal"],
}


@pytest.mark.parametrize("kunci", sorted(SEBELUM_KEMAMPUAN, key=str))
def test_kemampuan_memilih_platform_yang_sama_dengan_sebelumnya(kunci):
    """A move that shifts one platform is not a move. `alias` is excluded from the
    comparison because it is new; it is tested separately below.
    """
    nama, nilai = kunci
    kanonik = [p for p in dp.platform_dengan(nama, nilai) if p in dp.semua()]
    assert kanonik == SEBELUM_KEMAMPUAN[kunci]


def test_tiap_kemampuan_punya_setidaknya_satu_pemilik():
    for nama, jenis in dp._KEMAMPUAN.items():
        nilai = (True,) if jenis is bool else ("acl", "ufw", "netsh",
                                               "cisco", "linux", "windows")
        assert dp.platform_dengan(nama, *nilai), (
            "kemampuan %r tidak dimiliki platform mana pun" % nama)


@pytest.mark.parametrize("nama", sorted(dp.semua()))
def test_definisi_dokumentasi_tidak_mengaku_punya_kemampuan(nama):
    """Each capability enables a path that contacts devices. A platform never
    contacted must not enable any, same as the write-path rule.
    """
    d = dp.ambil(nama)
    if d.teruji != "dokumentasi":
        return
    for k in dp._KEMAMPUAN:
        nilai = d.kemampuan(k)
        assert not nilai, (
            "%s bertingkat `dokumentasi` tetapi mengaku kemampuan %s=%r"
            % (nama, k, nilai))


def test_kemampuan_yang_tidak_disebut_menjawab_paling_tidak_mampu():
    """A reversed default is dangerous, not just wrong: a new definition that forgot
    `firewall` would make NSM try `ufw` on a device without it (open SSH session,
    send command, store the failure as an event).
    """
    kosong = dp.Definisi("x", {"nama": "x", "teruji": "dokumentasi"})
    assert kosong.kemampuan("firewall") == ""
    assert kosong.kemampuan("baca_sumberdaya") is False
    assert kosong.firewall == ""
    assert kosong.lokal is False
    assert dp.TIDAK_DIKENAL.firewall == ""
    assert dp.TIDAK_DIKENAL.lokal is False


def test_kemampuan_yang_tidak_dikenal_melempar():
    """A capability-name typo in CODE must not silently answer "cannot"."""
    with pytest.raises(KeyError):
        dp.ambil("linux").kemampuan("baca_sumberdya")
    with pytest.raises(KeyError):
        dp.platform_dengan("firewal", "ufw")


# ---------------------------------------------------------------------------
# 10. Alias
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ditulis", ["ubuntu", "debian", "UBUNTU", " Debian "])
def test_nama_lain_menunjuk_platform_yang_sama(ditulis):
    assert dp.ambil(ditulis).nama == "linux"
    assert dp.ambil(ditulis).firewall == "ufw"


def test_nama_lain_ikut_di_daftar_untuk_kueri_sql():
    """Otherwise a device with platform `ubuntu` would answer "has ufw" via `ambil()`
    in Python and "no" via SQL.
    """
    assert "ubuntu" in dp.platform_dengan("firewall", "ufw")
    assert "debian" in dp.platform_dengan("baca_sumberdaya", True)


def test_nama_lain_tidak_muncul_sebagai_definisi_tersendiri():
    assert "ubuntu" not in dp.semua()
    assert "debian" not in dp.semua()


def test_nama_lain_yang_bentrok_ditolak():
    """Two platforms claiming the same name would make `ambil()` depend on file read order."""
    with pytest.raises(dp.DefinisiRusak):
        dp._peta_alias({
            "a": dp.Definisi("a", {"nama": "a", "teruji": "dokumentasi",
                                   "alias": ["sama"]}, berkas="a.yaml"),
            "b": dp.Definisi("b", {"nama": "b", "teruji": "dokumentasi",
                                   "alias": ["sama"]}, berkas="b.yaml"),
        })


def test_nama_lain_tidak_boleh_menutupi_platform_sungguhan():
    with pytest.raises(dp.DefinisiRusak):
        dp._peta_alias({
            "linux": dp.Definisi("linux", {"nama": "linux",
                                           "teruji": "dokumentasi"},
                                 berkas="linux.yaml"),
            "a": dp.Definisi("a", {"nama": "a", "teruji": "dokumentasi",
                                   "alias": ["linux"]}, berkas="a.yaml"),
        })


@pytest.mark.parametrize("ditulis", ["CISCO_IOS", "Cisco_IOS", " cisco_ios ",
                                     "LINUX", "Ubuntu"],
                         ids=["huruf_besar", "campur", "berspasi", "linux_besar",
                              "alias_campur"])
def test_ejaan_huruf_besar_kecil_diterima(ditulis):
    """Deliberate behavior change that closes an existing mismatch: `identitas_sumber.py`
    lowercases the platform but other paths matched exactly, so a `Linux` device had
    its identity markers collected but its config not read. Matching is now
    case-insensitive everywhere; no platform value in the database changes behavior today.
    """
    d = dp.ambil(ditulis)
    assert d.dikenal, "%r tidak dikenali" % ditulis
    assert d.nama in ("cisco_ios", "linux")


@pytest.mark.parametrize("nama", sorted(dp.semua()))
def test_yang_mengaku_rekaman_memang_punya_rekamannya(nama):
    """Gives the `rekaman` level meaning. Without this guard `teruji: rekaman` is
    just a word anyone can type; a file must not raise its own level without the
    recordings to back it.
    """
    d = dp.ambil(nama)
    if d.teruji != "rekaman":
        return
    assert dp.rekaman(nama), (
        "%s mengaku `teruji: rekaman` tetapi tidak ada satu berkas rekaman pun "
        "untuknya di perangkat/rekaman/" % nama)


def test_platform_yang_punya_rekaman_tidak_wajib_bertingkat_rekaman():
    """The reverse direction is deliberately not enforced: `cisco_ios` and `linux`
    have recordings AND the stronger `lab` level, and requiring `rekaman` would downgrade them.
    """
    for nama in ("cisco_ios", "linux"):
        assert dp.rekaman(nama), "%s seharusnya punya rekaman" % nama
        assert dp.ambil(nama).teruji == "lab"


def test_jaring_cisco_sama_persis_dengan_yang_dulu_tertanam_di_kode():
    """Values that applied before the safety net moved to files, copied from
    `kirim_perintah.py` and written as literals. One wrong letter stops the R1/R2
    safety net from being installed silently (sending is refused, but the screen
    only says "safety net not installed").
    """
    j = dp.ambil("cisco_ios").jaring_pengaman
    assert j["jenis"] == "reload"
    assert j["pasang"] == "reload in {menit}"
    assert j["bukti"] == "show reload"
    assert j["kukuhkan"] == "reload cancel"
    # TWO markers: IOS answers "Reload scheduled for <time>" or "Reload scheduled in
    # <duration>" depending on the command form.
    assert j["penanda_terpasang"] == ["scheduled for", "scheduled in"]
    assert j["penanda_lepas"] == ["no reload is scheduled"]


def test_pasang_cisco_menghasilkan_perintah_yang_sama_seperti_dulu():
    """The template is filled, not just stored; an unformatted `reload in {menit}`
    would be sent to the router as is.
    """
    assert (dp.ambil("cisco_ios").jaring_pengaman["pasang"].format(menit=5)
            == "reload in 5")

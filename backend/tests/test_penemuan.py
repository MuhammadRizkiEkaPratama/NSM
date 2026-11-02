"""Device discovery: scan guard rails, storage, and the gate into `devices`.

No packet is sent from this file; it tests the decisions. Two things are guarded:
1. Scans have guard rails: public ranges, huge ranges, and typos are rejected
   before any packet is sent.
2. Findings never enter `devices` on their own. The only way is `setujui()`
   (a human approves), which creates the device with `aktif=0`.

Both keep NSM from being loaded from the network.
"""
from datetime import datetime, timedelta

import pytest

import models
import penemuan as p

pytestmark = pytest.mark.murni


@pytest.fixture
def lab():
    import database

    engine, factory = database.create_lab()
    models.Base.metadata.create_all(engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def temuan(ip, **k):
    k.setdefault("hidup", True)
    return p.Temuan(ip, **k)


# ---------------------------------------------------------------------------
# 1. Pagar pemindaian
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("jaringan,jumlah", [
    ("192.168.56.0/30", 2),        # jaringan + siaran dibuang
    ("192.168.56.0/29", 6),
    ("192.168.56.60/32", 1),  # single address: nothing dropped
    ("10.0.0.0/24", 254),
    ("172.16.5.0/24", 254),
], ids=["p30", "p29", "satu_alamat", "sepuluh", "tujuhbelas_dua"])
def test_rentang_pribadi_diterima(jaringan, jumlah):
    assert len(p.alamat_dalam(jaringan)) == jumlah


def test_alamat_jaringan_dan_siaran_tidak_ikut_dipindai():
    """Neither is a host. Pinging them adds packets without information, and a reply
    from a broadcast address can read as many hosts at once.
    """
    alamat = p.alamat_dalam("192.168.56.0/29")
    assert "192.168.56.0" not in alamat, "alamat jaringan ikut"
    assert "192.168.56.7" not in alamat, "alamat siaran ikut"


@pytest.mark.parametrize("publik", [
    "8.8.8.0/24", "1.1.1.1/32", "104.16.0.0/24",
], ids=["google", "cloudflare", "cdn"])
def test_rentang_publik_ditolak(publik):
    """Scanning public addresses looks hostile to the receiving side, and the
    originating network's owner bears the consequences.
    """
    with pytest.raises(p.PindaiDitolak) as g:
        p.alamat_dalam(publik)
    assert "pribadi" in str(g.value)


@pytest.mark.parametrize("khusus", [
    "203.0.113.0/30",  # TEST-NET-3, RFC 5737 (documentation)
    "198.18.0.0/30",  # RFC 2544 (device benchmarking)
    "169.254.1.0/30",      # link-local
    "127.0.0.0/30",        # loopback
], ids=["testnet", "benchmark", "link_local", "loopback"])
def test_rentang_khusus_ikut_diterima(khusus):
    """Intentional: `ipaddress.is_private` is broader than RFC 1918 and also covers
    special-purpose ranges such as TEST-NET and benchmarking ranges. None are
    real internet addresses used by others, which is what the guard actually asks.
    Written as a test so the behavior is a recorded decision, not a library accident.
    """
    assert p.alamat_dalam(khusus)


def test_rentang_publik_bisa_dilewati_dengan_sengaja():
    """Opposite-direction guard: a fence with no gate gets torn down entirely."""
    assert p.alamat_dalam("203.0.113.0/30", izinkan_publik=True)


def test_rentang_raksasa_ditolak():
    """Without the guard, one typo (`10.0.0.0/8` instead of `/24`) would flood NSM's
    own network for hours with no way to stop it from the screen.
    """
    with pytest.raises(p.PindaiDitolak) as g:
        p.alamat_dalam("10.0.0.0/8")
    assert "melebihi batas" in str(g.value)


def test_penolakan_rentang_raksasa_tidak_ikut_mengerjakan_yang_raksasa():
    """The guard must not do excessive work itself. `alamat_dalam()` used to build
    the address list first and check its length afterwards (16.7M address objects
    for `10.0.0.0/8`); the size is now checked first, which took this file from
    30.7 s to 1.6 s. The 1 second limit below is loose enough not to flake on a busy machine.
    """
    import time
    t0 = time.time()
    for large in ("10.0.0.0/8", "172.16.0.0/12", "0.0.0.0/0"):
        with pytest.raises(p.PindaiDitolak):
            p.alamat_dalam(large)
    old = time.time() - t0
    assert old < 1.0, ("menolak tiga rentang raksasa makan %.1f dtk -- "
                        "alamatnya dibangun sebelum ukurannya diperiksa" % old)


def test_batasnya_bisa_dinaikkan_dengan_sengaja():
    assert len(p.alamat_dalam("10.0.0.0/22", batas=2000)) == 1022


@pytest.mark.parametrize("buruk", ["", "bukan-jaringan", "192.168.1.999/24",
                                   "192.168.1.0/33", None],
                         ids=["kosong", "teks", "oktet_ngawur", "prefiks_ngawur",
                              "None"])
def test_masukan_ngawur_ditolak_bukan_didiamkan(buruk):
    """A typo must stop here, not silently become a different scan."""
    with pytest.raises(p.PindaiDitolak):
        p.alamat_dalam(buruk)


@pytest.mark.parametrize("oid,harap", [
    (".1.3.6.1.4.1.9.1.222", "cisco_ios"),
    (".1.3.6.1.4.1.14988.1", "mikrotik_routeros"),
    (".1.3.6.1.4.1.2636.1.1.1.2", "juniper_junos"),
    (".1.3.6.1.4.1.30065.1.3011", "arista_eos"),
    (".1.3.6.1.4.1.2011.2.240", "huawei_vrp"),
    (".1.3.6.1.4.1.12356.101.1", "fortinet"),
    (".1.3.6.1.4.1.99999.1", None),
    (None, None),
], ids=["cisco", "mikrotik", "juniper", "arista", "huawei", "fortinet",
        "vendor_asing", "kosong"])
def test_pengenalan_platform(oid, harap):
    """The table belongs to the definition files, not to discovery: a new vendor is
    recognized by adding a YAML file, not by editing code.
    """
    assert p.kenali(oid) == harap


def test_temuan_baru_tersimpan(lab):
    summarize = p.simpan(lab, [temuan("192.168.56.100", rtt_ms=4.6,
                                    port_terbuka=[22, 80])])
    assert summarize == {"baru": 1, "diperbarui": 0, "total": 1}

    line = p.daftar(lab)
    assert len(line) == 1
    assert line[0].ip_address == "192.168.56.100"
    assert line[0].status == "baru"
    assert line[0].port_terbuka == "22,80"


def test_alamat_yang_sama_diperbarui_bukan_ditambah(lab):
    p.simpan(lab, [temuan("192.168.56.100", rtt_ms=1.0)])
    p.simpan(lab, [temuan("192.168.56.100", rtt_ms=9.0)])

    line = p.daftar(lab)
    assert len(line) == 1, "alamat kembar jadi dua baris"
    assert line[0].rtt_ms == 9.0, "nilai terbaru tidak masuk"


def test_pertama_terlihat_tidak_pernah_ditimpa(lab):
    """"Since when has this been on the network" is lost forever if every scan overwrites it."""
    p.simpan(lab, [temuan("192.168.56.100")])
    line = p.daftar(lab)[0]
    earlier = datetime.now() - timedelta(days=30)
    line.pertama_terlihat = earlier
    lab.commit()

    p.simpan(lab, [temuan("192.168.56.100")])
    line = p.daftar(lab)[0]
    assert line.pertama_terlihat == earlier
    assert line.terakhir_terlihat > earlier, "yang terakhir justru harus maju"


def test_pemindaian_tanpa_snmp_tidak_menghapus_platform_yang_sudah_dikenali(lab):
    """Information must not be lost because of how a scan was run. A first scan with
    SNMP credentials identifies the device; a later scan without credentials (for
    example a scheduled one) must not overwrite that with empty.
    """
    p.simpan(lab, [temuan("192.168.56.60", sysobjectid=".1.3.6.1.4.1.9.1.222",
                          platform="cisco_ios")])
    p.simpan(lab, [temuan("192.168.56.60")])  # without SNMP

    line = p.daftar(lab)[0]
    assert line.platform == "cisco_ios"
    assert line.sysobjectid == ".1.3.6.1.4.1.9.1.222"


def test_platform_yang_berubah_tetap_diperbarui(lab):
    """Opposite-direction guard: "do not overwrite with empty" must not become "never
    overwrite"; the same address can be used by a different machine.
    """
    p.simpan(lab, [temuan("192.168.56.60", sysobjectid=".1.3.6.1.4.1.9.1.222",
                          platform="cisco_ios")])
    p.simpan(lab, [temuan("192.168.56.60", sysobjectid=".1.3.6.1.4.1.14988.1",
                          platform="mikrotik_routeros")])
    assert p.daftar(lab)[0].platform == "mikrotik_routeros"


# ---------------------------------------------------------------------------
# 4. Keputusan manusia BERTAHAN
# ---------------------------------------------------------------------------
def test_yang_diabaikan_tidak_muncul_lagi_walau_dipindai_ulang(lab):
    """Otherwise the queue shows the same content on every scan, and a list that never
    changes stops being read.
    """
    p.simpan(lab, [temuan("192.168.56.200")])
    p.abaikan(lab, p.daftar(lab)[0].id)

    p.simpan(lab, [temuan("192.168.56.200")])  # scan again
    assert p.daftar(lab, status="baru") == []
    assert len(p.daftar(lab, status="diabaikan")) == 1


def test_yang_diabaikan_tetap_diperbarui_terakhir_terlihatnya(lab):
    """Ignored does not mean unobserved: "that address is still on the network" is
    still news after deciding it is not ours.
    """
    p.simpan(lab, [temuan("192.168.56.200")])
    p.abaikan(lab, p.daftar(lab)[0].id)
    line = p.daftar(lab, status="diabaikan")[0]
    line.terakhir_terlihat = datetime.now() - timedelta(days=3)
    lab.commit()

    p.simpan(lab, [temuan("192.168.56.200")])
    line = p.daftar(lab, status="diabaikan")[0]
    assert line.terakhir_terlihat > datetime.now() - timedelta(minutes=1)


def test_menyimpan_temuan_tidak_membuat_device_apa_pun(lab):
    """Core of the design: if this fails, anyone who can plug in one IP address can
    add load to NSM.
    """
    p.simpan(lab, [temuan("192.168.56.%d" % n) for n in range(100, 140)])
    assert lab.query(models.Device).count() == 0
    assert len(p.daftar(lab)) == 40


def test_setujui_membuat_device_yang_belum_aktif(lab):
    """Approving means "yes, this is our device", which differs from "start monitoring now"."""
    p.simpan(lab, [temuan("192.168.56.150", port_terbuka=[22, 80])])
    d = p.setujui(lab, p.daftar(lab)[0].id, nama="Server Baru")

    assert d.id
    assert d.ip_address == "192.168.56.150"
    assert d.aktif == 0, ("device langsung aktif -- gangguan palsu pada hari "
                          "pertama adalah cara tercepat membuat orang berhenti "
                          "mempercayai halaman insiden")


def test_setujui_menautkan_dan_memindahkan_statusnya(lab):
    p.simpan(lab, [temuan("192.168.56.150")])
    d = p.setujui(lab, p.daftar(lab)[0].id, nama="Server Baru")

    assert p.daftar(lab, status="baru") == [], "masih ditawarkan sesudah disetujui"
    line = p.daftar(lab, status="disetujui")[0]
    assert line.device_id == d.id


def test_platform_hasil_pengenalan_ikut_ke_device(lab):
    """A device recognized via sysObjectID gets its platform immediately, so once
    activated it produces data without waiting for someone to fill it in.
    """
    p.simpan(lab, [temuan("192.168.56.60", sysobjectid=".1.3.6.1.4.1.9.1.222",
                          platform="cisco_ios")])
    d = p.setujui(lab, p.daftar(lab)[0].id, nama="Router Baru",
                  device_type="router")
    assert d.platform == "cisco_ios"


def test_platform_bisa_ditimpa_saat_menyetujui(lab):
    """A human's approval overrides sysObjectID when they differ."""
    p.simpan(lab, [temuan("192.168.56.60", platform="cisco_ios")])
    d = p.setujui(lab, p.daftar(lab)[0].id, nama="Bukan Cisco",
                  platform="arista_eos")
    assert d.platform == "arista_eos"


def test_menyetujui_dua_kali_ditolak(lab):
    p.simpan(lab, [temuan("192.168.56.150")])
    tid = p.daftar(lab)[0].id
    p.setujui(lab, tid, nama="Sekali")
    with pytest.raises(ValueError) as g:
        p.setujui(lab, tid, nama="Dua kali")
    assert "sudah jadi device" in str(g.value)


def test_alamat_yang_sudah_punya_device_ditolak(lab):
    """Two rows for one address would mean two histories for one machine."""
    lab.add(models.Device(name="Sudah Ada", ip_address="192.168.56.103",
                          device_type="server", platform="linux", aktif=1))
    lab.commit()

    p.simpan(lab, [temuan("192.168.56.103")])
    with pytest.raises(ValueError) as g:
        p.setujui(lab, p.daftar(lab)[0].id, nama="Kembar")
    assert "sudah terdaftar" in str(g.value)
    assert lab.query(models.Device).count() == 1, "device kembar terlanjur dibuat"


def test_mengabaikan_yang_sudah_disetujui_ditolak(lab):
    p.simpan(lab, [temuan("192.168.56.150")])
    tid = p.daftar(lab)[0].id
    p.setujui(lab, tid, nama="Server")
    with pytest.raises(ValueError):
        p.abaikan(lab, tid)


@pytest.mark.parametrize("fungsi", ["setujui", "abaikan"])
def test_temuan_yang_tidak_ada_ditolak_bukan_didiamkan(lab, fungsi):
    with pytest.raises(ValueError):
        if fungsi == "setujui":
            p.setujui(lab, 9999, nama="Hantu")
        else:
            p.abaikan(lab, 9999)


# ---------------------------------------------------------------------------
# 6. Tenant
# ---------------------------------------------------------------------------
def test_temuan_terpisah_antar_tenant(lab):
    """The same address can exist in two tenants' networks (192.168.1.1 is
    everywhere); merging them would show tenant A's findings to tenant B.
    """
    p.simpan(lab, [temuan("192.168.1.1")], tenant_id=1)
    p.simpan(lab, [temuan("192.168.1.1")], tenant_id=2)

    assert len(p.daftar(lab, tenant_id=1)) == 1
    assert len(p.daftar(lab, tenant_id=2)) == 1
    assert len(p.daftar(lab, tenant_id=None)) == 2, "keduanya tetap ada"


def test_device_hasil_persetujuan_mewarisi_tenant(lab):
    p.simpan(lab, [temuan("192.168.1.1")], tenant_id=7)
    d = p.setujui(lab, p.daftar(lab, tenant_id=7)[0].id, nama="Milik Tenant 7")
    assert d.tenant_id == 7


def test_penyaring_tenant_mengenal_tabel_temuan():
    """A new table forgotten in the tenant filter leaks silently: no error, just a
    list containing another tenant's data.
    """
    import tenancy
    assert models.PerangkatDitemukan in tenancy.SEMUA_KELAS
    assert tenancy._kriteria(models.PerangkatDitemukan, 3) is not None


# The route functions are called directly, not through `TestClient`:
# `starlette.testclient` needs `httpx`, which is not installed (and adding a
# library to the runtime just for tests is not worth it), and `uji_main.py`
# already works this way. FastAPI's body parsing and URL routing are not tested here.
from fastapi import HTTPException  # noqa: E402

from nsm.antarmuka.http.rute import penemuan as rute  # noqa: E402


def test_rute_menolak_rentang_publik_sebagai_400(lab):
    """400, not 500: the request is rejected, NSM is not broken. The user sees the
    message instead of a generic error.
    """
    with pytest.raises(HTTPException) as g:
        rute.penemuan_pindai("8.8.8.0/24", False, lab)
    assert g.value.status_code == 400
    assert "pribadi" in str(g.value.detail)


def test_rute_menolak_rentang_raksasa_sebagai_400(lab):
    with pytest.raises(HTTPException) as g:
        rute.penemuan_pindai("10.0.0.0/8", False, lab)
    assert g.value.status_code == 400
    assert "melebihi batas" in str(g.value.detail)


def test_rute_daftar_menolak_status_ngawur(lab):
    with pytest.raises(HTTPException) as g:
        rute.penemuan_daftar("ngawur", lab)
    assert g.value.status_code == 400


def test_rute_daftar_menerima_semua(lab):
    p.simpan(lab, [temuan("192.168.56.101")])
    p.abaikan(lab, p.daftar(lab)[0].id)
    assert rute.penemuan_daftar("baru", lab)["jumlah"] == 0
    assert rute.penemuan_daftar("semua", lab)["jumlah"] == 1


def test_rute_menyebut_tingkat_bukti_platformnya(lab):
    """Shown on purpose: a device matching a `dokumentasi`-level definition is
    recognized, but that recognition was never tested on a real device, and the
    person approving should know before pressing the button.
    """
    p.simpan(lab, [temuan("192.168.56.60", sysobjectid=".1.3.6.1.4.1.9.1.222",
                          platform="cisco_ios"),
                   temuan("192.168.56.70", sysobjectid=".1.3.6.1.4.1.2636.1",
                          platform="juniper_junos")])
    menurut = {t["ip_address"]: t["teruji"]
               for t in rute.penemuan_daftar("baru", lab)["temuan"]}
    assert menurut["192.168.56.60"] == "lab"
    assert menurut["192.168.56.70"] == "dokumentasi"


def test_rute_setujui_mengembalikan_device_belum_aktif(lab):
    p.simpan(lab, [temuan("192.168.56.150")])
    tid = p.daftar(lab)[0].id
    h = rute.penemuan_setujui(tid, "Server Baru", "server", None, lab)
    assert h["aktif"] == 0
    assert "BELUM AKTIF" in h["catatan"], (
        "tanggapannya tidak menyebut device-nya belum aktif, jadi orang akan "
        "menunggu data yang tidak akan datang")


def test_rute_setujui_dua_kali_jadi_400(lab):
    p.simpan(lab, [temuan("192.168.56.150")])
    tid = p.daftar(lab)[0].id
    rute.penemuan_setujui(tid, "Sekali", "server", None, lab)
    with pytest.raises(HTTPException) as g:
        rute.penemuan_setujui(tid, "Dua kali", "server", None, lab)
    assert g.value.status_code == 400


def test_rute_abaikan_temuan_hantu_jadi_400(lab):
    with pytest.raises(HTTPException) as g:
        rute.penemuan_abaikan(9999, lab)
    assert g.value.status_code == 400

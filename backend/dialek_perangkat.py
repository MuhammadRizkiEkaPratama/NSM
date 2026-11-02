"""Per-device differences collected in one place, read from files.

Modeled on `dialek.py`, which collects SQLite vs MySQL differences, for the same
reason: scattered differences cannot be counted, and what cannot be counted
cannot be shown complete.

One deliberate difference: database dialects are CODE because there are two and
that will not grow. Device dialects are FILES because their number must grow
without touching code. Someone with a Nokia SR OS should be able to add
`nokia_sros.yaml` and be done.

    backend/perangkat/cisco_ios.yaml   ->  dialek_perangkat.ambil("cisco_ios")

Three things this file guards, each from a failure that really happened here or
in similar tools:

1. AN UNKNOWN PLATFORM IS STILL MONITORED. `ambil()` never raises and never
   returns None; an unknown platform gets a safe empty definition. Ping, TCP and
   SNMP need no definition at all, and a device vanishing from the screen because
   its name was not recognized is worse than a device with less complete data.

2. THE EVIDENCE LEVEL IS STORED AND IT BINDS. A definition written from vendor
   documentation and never run on a real device must not enable the write path,
   whatever its own file says. See `Definisi.boleh_menulis`.

3. MISTYPED KEYS ARE REJECTED AT LOAD TIME, not ignored. A config file that
   accepts any key turns a typo from "fails at load" into "silently has no
   effect", which is only noticed when someone asks why a command never runs.
"""
import os

import yaml

DIREKTORI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "perangkat")

# Evidence levels, strongest first. The order is meaningful.
TERUJI = ("lab", "rekaman", "dokumentasi")

# Allowed keys. Anything outside this stops loading; see reason 3 in the module
# docstring.
_BAGIAN = {
    "nama": str,
    "keterangan": str,
    "teruji": str,
    "sumber": str,
    "alias": list,
    "deteksi": dict,
    "akses": dict,
    "baca": dict,
    "tulis": dict,
    "kemampuan": dict,
    "rahasia": list,
}
_DETEKSI = {"sysobjectid", "nama_mengandung"}
_AKSES = {"netmiko_device_type", "butuh_enable", "jenis", "paging_mati"}
_TULIS = {"didukung", "simpan", "mode_konfig", "jaring_pengaman"}

# SAFETY NET: replaces the Cisco-specific `reload_aman`.
#
# `reload_aman` named ONE Cisco mechanism for a question that applies generally,
# so three vendors misleadingly answered "no": their safety net exists, it is just
# not `reload`.
#
# The real question, taken from the `kirim_perintah.py` flow:
#
#     Is there a way to install something that RECOVERS BY ITSELF if the change
#     cuts the connection, and if so, how to install it, prove it is installed,
#     and confirm that the change may stay?
#
# Both mechanisms have exactly the same shape, so one schema holds both:
#
#     do nothing -> the device recovers itself
#     confirm    -> the change stays
#
#     Cisco IOS      install `reload in N`          confirm `reload cancel`
#     Juniper Junos  install `commit confirmed N`   confirm `commit`
#
# An EMPTY `pasang` means something different from `jenis: tidak_ada`, honestly:
# the first means "the mechanism exists but NSM does not know how to run it", the
# second "there is none". Treating them alike would erase information the owner of
# the device needs.
_JARING = {"jenis", "pasang", "bukti", "penanda_terpasang",
           "kukuhkan", "penanda_lepas"}
_JENIS_JARING = {"reload", "commit_confirmed", "tidak_ada"}
# `baca` is deliberately NOT restricted in its keys: it holds per-vendor command
# names and will grow. Only the values (which must be text) are checked, in
# `_periksa()`.

_JENIS = {"jaringan", "host"}

# CAPABILITIES.
#
# Each key is one QUESTION that used to be answered by scattered
# `if platform == "..."`. The difference is not just location: the scattered form
# asks about the BRAND, this asks about the CAPABILITY, and only the latter can be
# answered for a device nobody has seen yet.
#
#     if d.platform == "linux"           -> "is this Linux?"
#     if dialek.ambil(p).baca_sumberdaya -> "can its CPU be read?"
#
# The first must be edited every time a new operating system turns out to qualify.
# The second does not.
#
# THE LIST IS CLOSED, and each key comes from a branch that REALLY EXISTS in the
# code, not from a capability list invented first and then given users. A
# capability without users is a field nobody checks, and such fields end up wrong.
_KEMAMPUAN = {
    # Mechanism for blocking an address ON this device.
    #   acl    ACL on a router              (ubah_acl_router.py)
    #   ufw    host firewall via ufw        (ubah_firewall.py)
    #   netsh  Windows Firewall on the machine NSM itself runs on
    #   ""     none; addresses cannot be blocked on this device
    "firewall": str,

    # CPU / RAM / disk over SSH. `nsm/pemantau/sumberdaya.py`.
    "baca_sumberdaya": bool,

    # User command log (auditd). `nsm/pemantau/trafik.py`.
    "baca_trafik": bool,

    # Service configuration files. `connectors/konfig_linux.py`.
    "baca_konfig_layanan": bool,

    # How identity markers (MAC, serial, machine-id) are collected.
    #   cisco | linux | windows | ""      `identitas_sumber.py`
    "identitas": str,

    # The machine NSM ITSELF runs on. Not a vendor dialect but a structural fact, and
    # it is here for exactly that reason: `platform == "lokal"` was scattered across
    # 14 places as a literal string, and scattered literals cannot be counted.
    "lokal": bool,
}
_FIREWALL = {"acl", "ufw", "netsh", ""}
_IDENTITAS = {"cisco", "linux", "windows", ""}


class DefinisiRusak(Exception):
    """The definition file is unusable. The message names the file and the key."""


class Definisi:
    """One platform. Read-only after creation."""

    def __init__(self, nama, content=None, berkas=None):
        content = content or {}
        self.nama = nama
        self.berkas = berkas
        self.keterangan = content.get("keterangan") or nama
        self.teruji = content.get("teruji") or "dokumentasi"
        self.sumber = content.get("sumber") or ""
        self.alias = [str(a) for a in (content.get("alias") or [])]
        self.deteksi = content.get("deteksi") or {}
        self.akses = content.get("akses") or {}
        self.baca = content.get("baca") or {}
        self.tulis = content.get("tulis") or {}
        self._kemampuan = content.get("kemampuan") or {}
        self.rahasia = content.get("rahasia") or []
        self.dikenal = bool(content)

    # -- questions that used to be answered by `if platform == ...` --

    def perintah(self, apa):
        """Command for reading something, or None if this platform has no such concept.

        None means something different from an empty string, and the difference
        matters: a device that does not separate running from startup config must not be
        reported as having unsaved configuration. This is exactly the distinction
        `konfig.ambil_startup()` already makes.
        """
        value = self.baca.get(apa)
        return value or None

    @property
    def netmiko_device_type(self):
        """The name netmiko understands. Falls back to the platform name when not given,
        since for most platforms they are the same.
        """
        return self.akses.get("netmiko_device_type") or self.nama

    @property
    def boleh_menulis(self):
        """Whether the write path may be enabled for this platform.

        Enforced in code, deliberately, not in a document (rule in
        docs/design/DEVICE-AGNOSTIC.md): a definition never run on a real device must
        not enable the write path EVEN IF ITS OWN FILE SAYS IT MAY. A file that can
        raise its own privileges is not configuration, it is a door.

        Why so strict: docs/POSTMORTEM-R1.md records one command that was CORRECT per
        Cisco documentation (`reload in N`) and permanently killed a router, because the
        real environment differed from what the documentation assumed. A command right
        on paper and wrong in reality has already happened in this lab.

        ONLY `lab` QUALIFIES; `rekaman` (recording) DELIBERATELY DOES NOT. If recordings
        also granted write permission, adding a recording file (work done entirely
        offline, with no packet sent) would ENABLE THE WRITE PATH to MikroTik, Junos,
        EOS, VRP and FortiOS devices nobody here has touched.

        The distinction is simple and non-negotiable:

            a recording proves we can READ what the device says.
            It proves nothing about what a write command DOES on that device.

        No amount of recorded `show running-config` output shows that `write memory`
        behaves as we assume, and that is exactly what killed R1. Writing needs the
        device, not the recording.
        """
        return bool(self.tulis.get("didukung")) and self.teruji == "lab"

    @property
    def jaring_pengaman(self):
        """Mechanism that RECOVERS BY ITSELF if a change cuts the connection.

        A dict with fixed keys; anything not mentioned holds the least capable value.
        Replaces `reload_aman`; see `_JARING` for why the old name was misleading.

        The default is `tidak_ada`, on purpose: a wrong default here KILLS DEVICES
        (docs/POSTMORTEM-R1.md), so a file's silence must mean "has none", not "has one".
        """
        j = dict(self.tulis.get("jaring_pengaman") or {})
        j.setdefault("jenis", "tidak_ada")
        for k in ("pasang", "bukti", "kukuhkan"):
            j.setdefault(k, "")
        for k in ("penanda_terpasang", "penanda_lepas"):
            j.setdefault(k, [])
        return j

    @property
    def bisa_pasang_jaring_pengaman(self):
        """Whether NSM knows HOW to install the safety net on this platform.

        Deliberately different from "has a safety net". Three vendors have the mechanism
        but NSM does not know the command sequence, and what decides whether a send may
        run is the second, not the first. A device whose net exists on paper but is not
        really installed is as exposed as one with no net at all.
        """
        j = self.jaring_pengaman
        return j["jenis"] != "tidak_ada" and bool(j["pasang"])

    # -- capabilities --

    def kemampuan(self, nama):
        """Answer to one capability question. See `_KEMAMPUAN`.

        A platform that does not mention it answers the LEAST CAPABLE VALUE: `False` for
        yes/no questions, `""` for mechanism questions. This default is deliberate and
        consistent with `jaring_pengaman`: a file's silence must mean "cannot", not
        "can".

        With the default reversed, a new definition file that forgot to fill in
        `firewall` would make NSM try to run `ufw` on a device without ufw, and trying
        means opening an SSH session, sending commands, then storing the failure as an
        event.
        """
        if nama not in _KEMAMPUAN:
            raise KeyError(
                "kemampuan %r tidak dikenal. Yang ada: %s. Menambah yang baru "
                "berarti menambahnya ke `_KEMAMPUAN` DAN mengisinya di berkas "
                "definisi yang relevan." % (nama, ", ".join(sorted(_KEMAMPUAN))))
        return self._kemampuan.get(nama, False if _KEMAMPUAN[nama] is bool else "")

    @property
    def firewall(self):
        """`acl` | `ufw` | `netsh` | `""`. Mechanism for blocking addresses."""
        return self.kemampuan("firewall")

    @property
    def lokal(self):
        """The machine NSM itself runs on."""
        return self.kemampuan("lokal")

    def cocok_sysobjectid(self, oid):
        """True if this SNMP OID belongs to that platform.

        Prefix match, not exact (the LibreNMS way). One vendor has thousands of full
        OIDs, one per model, and listing them all would leave a new model from the SAME
        vendor unrecognized.
        """
        if not oid:
            return False
        oid = str(oid).strip().lstrip(".")
        for prefix in self.deteksi.get("sysobjectid") or []:
            if oid.startswith(str(prefix).strip().lstrip(".")):
                return True
        return False

    def __repr__(self):
        return "<Definisi %s teruji=%s tulis=%s>" % (
            self.nama, self.teruji, self.boleh_menulis)


# Definition for a platform with no file. NOT None, and not an error: see reason 1
# in the module docstring.
TIDAK_DIKENAL = Definisi("tidak_dikenal")


def _periksa(filename, content):
    """Raise `DefinisiRusak` if anything is wrong. Changes nothing."""
    def salah(message):
        raise DefinisiRusak("%s: %s" % (filename, message))

    if not isinstance(content, dict):
        salah("isinya bukan pemetaan kunci-nilai")

    for kunci, value in content.items():
        if kunci not in _BAGIAN:
            salah("kunci tidak dikenal %r (yang ada: %s)"
                  % (kunci, ", ".join(sorted(_BAGIAN))))
        if not isinstance(value, _BAGIAN[kunci]):
            salah("kunci %r harus %s, bukan %s"
                  % (kunci, _BAGIAN[kunci].__name__, type(value).__name__))

    if content.get("teruji") not in TERUJI:
        salah("teruji harus salah satu dari %s, bukan %r"
              % (", ".join(TERUJI), content.get("teruji")))

    # An evidence level without its provenance is not evidence, it is a claim.
    if content.get("teruji") in ("lab", "rekaman") and not (content.get("sumber") or "").strip():
        salah("teruji=%r wajib menyebut `sumber`: pada perangkat apa, atau "
              "rekaman dari mana" % content.get("teruji"))

    for kunci, valid in (("deteksi", _DETEKSI), ("akses", _AKSES), ("tulis", _TULIS)):
        for k in (content.get(kunci) or {}):
            if k not in valid:
                salah("%s.%s tidak dikenal (yang ada: %s)"
                      % (kunci, k, ", ".join(sorted(valid))))

    jenis = (content.get("akses") or {}).get("jenis")
    if jenis is not None and jenis not in _JENIS:
        salah("akses.jenis harus %s, bukan %r" % ("/".join(sorted(_JENIS)), jenis))

    for k, v in (content.get("baca") or {}).items():
        if not isinstance(v, str):
            salah("baca.%s harus teks perintah, bukan %s" % (k, type(v).__name__))

    net = (content.get("tulis") or {}).get("jaring_pengaman")
    if net is not None:
        if not isinstance(net, dict):
            salah("tulis.jaring_pengaman harus pemetaan kunci-nilai")
        for k in net:
            if k not in _JARING:
                salah("tulis.jaring_pengaman.%s tidak dikenal (yang ada: %s)"
                      % (k, ", ".join(sorted(_JARING))))
        if net.get("jenis") not in _JENIS_JARING:
            salah("tulis.jaring_pengaman.jenis harus salah satu dari %s, "
                  "bukan %r" % ("/".join(sorted(_JENIS_JARING)),
                                net.get("jenis")))
        for k in ("penanda_terpasang", "penanda_lepas"):
            if k in net and not isinstance(net[k], list):
                salah("tulis.jaring_pengaman.%s harus daftar teks" % k)
        # A net that can be INSTALLED but not PROVEN installed is one whose existence is
        # assumed, not known; `kirim_perintah.py` refuses to run without the proof because
        # the install command can fail silently.
        if net.get("pasang") and not net.get("penanda_terpasang"):
            salah("tulis.jaring_pengaman punya `pasang` tetapi tidak punya "
                  "`penanda_terpasang` -- jaring yang tidak bisa dibuktikan "
                  "terpasang tidak boleh dipakai sebagai jaring")

    for k, v in (content.get("kemampuan") or {}).items():
        if k not in _KEMAMPUAN:
            salah("kemampuan.%s tidak dikenal (yang ada: %s)"
                  % (k, ", ".join(sorted(_KEMAMPUAN))))
        if not isinstance(v, _KEMAMPUAN[k]):
            salah("kemampuan.%s harus %s, bukan %s"
                  % (k, _KEMAMPUAN[k].__name__, type(v).__name__))

    fw = (content.get("kemampuan") or {}).get("firewall")
    if fw is not None and fw not in _FIREWALL:
        salah("kemampuan.firewall harus salah satu dari %s, bukan %r"
              % ("/".join(sorted(x or '""' for x in _FIREWALL)), fw))

    ident = (content.get("kemampuan") or {}).get("identitas")
    if ident is not None and ident not in _IDENTITAS:
        salah("kemampuan.identitas harus salah satu dari %s, bukan %r"
              % ("/".join(sorted(x or '""' for x in _IDENTITAS)), ident))

    for i, a in enumerate(content.get("alias") or []):
        if not isinstance(a, str) or not a.strip():
            salah("alias[%d] harus teks tidak kosong" % i)

    for i, r in enumerate(content.get("rahasia") or []):
        if not (isinstance(r, dict) and "pola" in r and "ganti" in r):
            salah("rahasia[%d] harus punya kunci `pola` dan `ganti`" % i)


def _muat():
    daftar = {}
    if not os.path.isdir(DIREKTORI):
        return daftar
    for berkas in sorted(os.listdir(DIREKTORI)):
        if not berkas.endswith(".yaml") or berkas.startswith("_"):
            continue
        path = os.path.join(DIREKTORI, berkas)
        with open(path, encoding="utf-8") as f:
            content = yaml.safe_load(f) or {}
        _periksa(berkas, content)
        nama = content.get("nama") or os.path.splitext(berkas)[0]
        if nama != os.path.splitext(berkas)[0]:
            raise DefinisiRusak(
                "%s: `nama` (%r) harus sama dengan nama berkasnya. Kalau tidak, "
                "berkas yang dicari lewat nama platform tidak akan ketemu."
                % (berkas, nama))
        if nama in daftar:
            raise DefinisiRusak("%s: platform %r sudah didefinisikan" % (berkas, nama))
        daftar[nama] = Definisi(nama, content, berkas=path)
    return daftar


def _peta_alias(daftar):
    """{alias: canonical_name}. Two definitions must not claim the same name."""
    peta = {}
    for nama, d in daftar.items():
        for a in d.alias:
            a = a.strip().lower()
            if a in daftar:
                raise DefinisiRusak(
                    "%s: alias %r bentrok dengan nama platform yang sudah ada"
                    % (os.path.basename(d.berkas or nama), a))
            if a in peta and peta[a] != nama:
                raise DefinisiRusak(
                    "alias %r diakui dua platform sekaligus: %s dan %s"
                    % (a, peta[a], nama))
            peta[a] = nama
    return peta


_DAFTAR = _muat()
_ALIAS = _peta_alias(_DAFTAR)


def muat_ulang():
    """Reload the definition files. Used by tests and when a file is added."""
    global _DAFTAR, _ALIAS
    _DAFTAR = _muat()
    _ALIAS = _peta_alias(_DAFTAR)
    return _DAFTAR


def ambil(platform):
    """Definition for a platform. NEVER None, never raises.

    An empty or unknown platform gets `TIDAK_DIKENAL`, which answers "no commands at
    all" to every question and "may not write", without stopping monitoring.

    Aliases (`alias:`) are recognized too. People write `ubuntu` and `debian` in the
    platform column, and rejecting them would make a legitimate device lose its
    capabilities over spelling.
    """
    p = (platform or "").strip().lower()
    return _DAFTAR.get(p) or _DAFTAR.get(_ALIAS.get(p, ""), TIDAK_DIKENAL)


def semua():
    """All loaded definitions, sorted by name. Aliases are NOT included: the files are
    returned, one row per file.
    """
    return dict(sorted(_DAFTAR.items()))


def platform_dengan(kemampuan, *value):
    """Platform names whose capability has one of the values in `nilai`.

    Used by SQL queries, which cannot call `ambil()` per row:

        Device.platform.in_(dialek_perangkat.platform_dengan("firewall", "ufw"))

    ALIASES ARE RETURNED TOO. Otherwise a device with platform `ubuntu` would answer
    "has ufw" through `ambil()` in Python and "no" when filtered through SQL: two
    answers for one device depending on which path happened to be used. That class
    of defect is the hardest to trace, since each path looks right on its own.
    """
    if kemampuan not in _KEMAMPUAN:
        raise KeyError("kemampuan %r tidak dikenal. Yang ada: %s"
                       % (kemampuan, ", ".join(sorted(_KEMAMPUAN))))
    hasil = []
    for nama, d in sorted(_DAFTAR.items()):
        if d.kemampuan(kemampuan) in value:
            hasil.append(nama)
            hasil.extend(sorted(a.strip().lower() for a in d.alias))
    return hasil


def dari_sysobjectid(oid):
    """Which platform matches this SNMP OID, or None.

    The LONGEST prefix wins. `.1.3.6.1.4.1.9.` (Cisco) and `.1.3.6.1.4.1.9.1.1745`
    (one Cisco model) both match the same device; the more specific one knows more.
    """
    terbaik, length = None, -1
    for nama, d in sorted(_DAFTAR.items()):
        for prefix in d.deteksi.get("sysobjectid") or []:
            prefix = str(prefix).strip().lstrip(".")
            if str(oid or "").strip().lstrip(".").startswith(prefix) and len(prefix) > length:
                terbaik, length = nama, len(prefix)
    return terbaik


# ---------------------------------------------------------------------------
# Recordings of real device output
# ---------------------------------------------------------------------------
DIREKTORI_REKAMAN = os.path.join(DIREKTORI, "rekaman")
NAMA_MANIFES = "manifes.yaml"


class Rekaman:
    """One real device output, with its provenance.

    The provenance is stored for a reason: a recording without a note on where it
    came from cannot be told apart from a hand-written example, and its whole value
    lies in that difference.
    """

    def __init__(self, content, teks):
        self.berkas = content["berkas"]
        self.platform = content["platform"]
        self.perintah = content.get("perintah") or ""
        self.perangkat = content.get("perangkat") or ""
        self.direkam = content.get("direkam") or ""
        self.teks = teks

    def __repr__(self):
        return "<Rekaman %s %d baris>" % (self.berkas, len(self.teks.splitlines()))


def rekaman(platform=None):
    """Recordings of real device output, filtered by platform.

    An empty list if there are none, and empty is NOT an error: most platforms have
    none yet, which is an honest state.
    """
    path = os.path.join(DIREKTORI_REKAMAN, NAMA_MANIFES)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        manifes = yaml.safe_load(f) or {}

    hasil = []
    for content in manifes.get("rekaman") or []:
        if platform and content.get("platform") != platform:
            continue
        berkas = os.path.join(DIREKTORI_REKAMAN, *content["berkas"].split("/"))
        if not os.path.exists(berkas):
            raise DefinisiRusak(
                "%s menyebut %s, tetapi berkasnya tidak ada. Manifes yang "
                "menunjuk berkas hilang lebih buruk daripada manifes kosong: "
                "yang kosong terlihat kosong, yang menggantung terlihat "
                "lengkap." % (NAMA_MANIFES, content["berkas"]))
        with open(berkas, encoding="utf-8") as f:
            hasil.append(Rekaman(content, f.read()))
    return hasil

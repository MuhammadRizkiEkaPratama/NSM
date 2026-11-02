"""Catalog of parameterized configuration commands.

THIS FILE SENDS NOTHING TO DEVICES. It only builds command text and validates
parameters. Sending lives in a separate module.

WHY A CATALOG, NOT A FREE CLI BOX. A free CLI box moves all security responsibility to
whoever types, the opposite of this tool's purpose. A tool that accepts any command is not
automation; it is a terminal with an extra step. With a catalog, what can be sent to a
device is a closed set decided in advance, and every human-fillable value has passed an
allowlist.

PARAMETER VALIDATION IS THE SECURITY. An unvalidated parameter is command injection into
the device CLI. If an interface description is filled with:

    Uplink to switch
     no shutdown
     ip address 10.0.0.1 255.255.255.0

the second and third lines would run as commands. This is the same class of
vulnerability as SQL injection, only the target is a router.

Four rules close it:

1. Newlines are rejected ABSOLUTELY in every parameter, before any other check.
2. Each parameter type has an ALLOWLIST, not a denylist. A denylist always loses: every
   forbidden thing must be named, and anything forgotten is a hole.
3. A parameter can never become the command NAME. The template `description {teks}`
   cannot turn into another command whatever `{teks}` holds, because `{teks}` has passed
   the allowlist.
4. Validation happens here (Python), not in the browser. Browser validation is
   convenience; server-side rejection is what secures.
"""
import re

# PARAMETER TYPES
#
# Each type has its own checker. It returns an error message (str) if rejected, or None if
# accepted. Messages are written for a human who filled in a field wrong, not for programs
# to match.

# Rejected before anything else. `\n` and `\r` separate commands in a device CLI; if one
# gets through, every guard below it is meaningless.
_BARIS_BARU = re.compile(r"[\r\n\x00-\x08\x0b-\x1f\x7f]")

_POLA_TEKS = re.compile(r"^[A-Za-z0-9 .,\-_/()]+$")
_POLA_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]{0,62}$")
_POLA_IFACE = re.compile(r"^[A-Za-z][A-Za-z0-9]*[0-9](?:/[0-9]+)*(?:\.[0-9]+)?$")


def _cek_umum(nilai):
    if nilai is None:
        return "belum diisi"
    if not isinstance(nilai, str):
        return "harus berupa teks"
    if _BARIS_BARU.search(nilai):
        # Stated openly: someone pasting a multi-line config needs to know WHY it was rejected, not
        # only that it was.
        return ("tidak boleh memuat baris baru atau karakter kendali. Tiap "
                "perintah dikirim satu per satu lewat katalog, dan menempelkan "
                "beberapa baris sekaligus akan menjalankan perintah yang tidak "
                "terlihat di pratinjau")
    if not nilai.strip():
        return "tidak boleh kosong"
    return None


def _cek_teks(nilai, maks=200):
    galat = _cek_umum(nilai)
    if galat:
        return galat
    if len(nilai) > maks:
        return f"terlalu panjang, maksimum {maks} huruf"
    if not _POLA_TEKS.match(nilai):
        return ("hanya boleh huruf, angka, spasi, dan tanda . , - _ / ( )")
    return None


def _cek_nama_host(nilai):
    galat = _cek_umum(nilai)
    if galat:
        return galat
    if not _POLA_HOST.match(nilai):
        return ("nama perangkat hanya boleh huruf, angka, dan tanda hubung; "
                "harus diawali huruf atau angka; maksimum 63 huruf")
    return None


def _cek_alamat_ip(nilai):
    galat = _cek_umum(nilai)
    if galat:
        return galat
    section = nilai.split(".")
    if len(section) != 4:
        return "harus berbentuk empat angka dipisah titik, misalnya 192.168.56.1"
    for b in section:
        if not b.isdigit() or not (0 <= int(b) <= 255):
            return "tiap angka harus 0 sampai 255"
        if len(b) > 1 and b[0] == "0":
            # `010` is interpreted differently by some tools. Rejecting it is cheaper than guessing
            # what the writer meant.
            return "jangan diawali angka nol, tulis 10 bukan 010"
    return None


def _cek_interface(nilai, interface_tersedia=None):
    """Interface name, which MUST really exist on that device.

    A pattern check is not enough: `FastEthernet9/9` passes any pattern but does not exist,
    and the router rejects a command for a missing interface after half the other commands
    were already sent. The interface list comes from the LATEST config snapshot, so
    validation uses the device's actual state, not a guess.
    """
    galat = _cek_umum(nilai)
    if galat:
        return galat
    if not _POLA_IFACE.match(nilai):
        return ("nama interface tidak dikenali, contoh yang benar: "
                "FastEthernet0/0, GigabitEthernet0/1, Loopback0")
    if interface_tersedia is not None:
        if nilai not in interface_tersedia:
            available = ", ".join(sorted(interface_tersedia)) or "(tidak ada)"
            return (f"interface '{nilai}' tidak ada di perangkat ini. "
                    f"Yang tersedia: {available}")
    return None


JENIS = {
    "teks": _cek_teks,
    "nama_host": _cek_nama_host,
    "alamat_ip": _cek_alamat_ip,
    "interface": _cek_interface,
}


# CATALOG
#
# `perintah` is the list of lines to send, with `{nama}` replaced by the parameter value.
# `configure terminal` and `end` are NOT written here: the sender adds them, so no catalog
# entry can forget to close configuration mode.
#
# `memutus` marks commands that can cut NSM's access to the device. Not to forbid them, but
# so the preview can warn and the sender can demand stricter safety nets.
KATALOG = [
    {
        "id": "iface_keterangan",
        "nama": "Ubah keterangan interface",
        "penjelasan": "Menulis catatan pada sebuah interface. Tidak mengubah "
                      "cara kerja jaringan sama sekali, hanya keterangan.",
        "platform": "cisco_ios",
        "memutus": False,
        "parameter": [
            {"nama": "interface", "jenis": "interface", "label": "Interface"},
            {"nama": "teks", "jenis": "teks", "label": "Keterangan"},
        ],
        "perintah": ["interface {interface}", " description {teks}"],
    },
    {
        "id": "iface_mati",
        "nama": "Matikan interface",
        "penjelasan": "Mematikan sebuah interface. KALAU interface itu yang "
                      "dipakai NSM untuk menghubungi perangkat, sambungan akan "
                      "terputus dan perangkat hanya bisa pulih lewat reload.",
        "platform": "cisco_ios",
        "memutus": True,
        "parameter": [
            {"nama": "interface", "jenis": "interface", "label": "Interface"},
        ],
        "perintah": ["interface {interface}", " shutdown"],
    },
    {
        "id": "iface_hidup",
        "nama": "Nyalakan interface",
        "penjelasan": "Menyalakan kembali interface yang sedang dimatikan.",
        "platform": "cisco_ios",
        "memutus": False,
        "parameter": [
            {"nama": "interface", "jenis": "interface", "label": "Interface"},
        ],
        "perintah": ["interface {interface}", " no shutdown"],
    },
    {
        "id": "hostname",
        "nama": "Ubah nama perangkat",
        "penjelasan": "Mengubah hostname. Terlihat di prompt CLI dan di "
                      "konfigurasi, tidak mengubah alamat atau perutean.",
        "platform": "cisco_ios",
        "memutus": False,
        "parameter": [
            {"nama": "nama", "jenis": "nama_host", "label": "Nama baru"},
        ],
        "perintah": ["hostname {nama}"],
    },
    {
        "id": "ntp_tambah",
        "nama": "Tambah server NTP",
        "penjelasan": "Menambah sumber waktu. Berguna karena jam perangkat "
                      "yang meleset membuat log sulit disandingkan.",
        "platform": "cisco_ios",
        "memutus": False,
        "parameter": [
            {"nama": "alamat", "jenis": "alamat_ip", "label": "Alamat server NTP"},
        ],
        "perintah": ["ntp server {alamat}"],
    },
    {
        "id": "ntp_hapus",
        "nama": "Hapus server NTP",
        "penjelasan": "Menghapus satu sumber waktu dari daftar.",
        "platform": "cisco_ios",
        "memutus": False,
        "parameter": [
            {"nama": "alamat", "jenis": "alamat_ip", "label": "Alamat server NTP"},
        ],
        "perintah": ["no ntp server {alamat}"],
    },
    {
        "id": "banner",
        "nama": "Ubah banner login",
        "penjelasan": "Mengubah tulisan yang muncul saat orang masuk ke "
                      "perangkat. Tidak mengubah siapa yang boleh masuk.",
        "platform": "cisco_ios",
        "memutus": False,
        "parameter": [
            {"nama": "teks", "jenis": "teks", "label": "Isi banner"},
        ],
        # ^C is the start/end marker of a banner on Cisco IOS. Since `teks` has passed the
        # allowlist it cannot contain ^C and end the banner early.
        "perintah": ["banner motd ^C{teks}^C"],
    },

    # SIX MORE COMMANDS
    #
    # Added so the config recoverer (`pemulih/konfig.py`) can fix every SoT key classified
    # `aman_otomatis` in `sot/katalog.py`. Before, the catalog only had commands for hostname,
    # ntp, and banner, so other keys were detected as drifted but could never be fixed.
    #
    # The four remaining keys (`domain`, `exec_timeout_menit`, `vty_izin`, `ssh_saja`) are
    # deliberately NOT added as automatic commands: they are `wajib_manusia`, so gate 1 of the
    # automation gate would ALWAYS refuse them. Adding commands would only create a path that
    # is never walked and mislead people into thinking the recoverer can fix them.
    #
    # The list-type keys (`dns_server`, `logging_server`) come as add/remove pairs, following
    # the existing `ntp_tambah`/`ntp_hapus` pattern: `pemulih/konfig.py` reconciles the
    # difference instead of deleting everything and rewriting it, which would open a brief
    # window with no service at all for addresses that were already correct.
    {
        "id": "zona_waktu",
        "nama": "Setel zona waktu",
        "penjelasan": "Menyetel zona waktu perangkat. Tidak memutus lalu "
                      "lintas apa pun; yang salah hanya jam di log sampai "
                      "diperbaiki -- dan itu justru alasan memperbaikinya "
                      "cepat.",
        "platform": "cisco_ios",
        "memutus": False,
        "parameter": [
            # `jenis: teks` because the value already has the form "WIB 7 0" from
            # `katalog.zona_cisco()`, not typed by a human. The `teks` allowlist already rejects
            # newlines and control characters.
            {"nama": "zona", "jenis": "teks", "label": "Zona (mis. WIB 7 0)"},
        ],
        "perintah": ["clock timezone {zona}"],
    },
    {
        "id": "dns_tambah",
        "nama": "Tambah server DNS",
        "penjelasan": "Menambah satu penerjemah nama. Perangkat jaringan "
                      "tidak memakai DNS untuk meneruskan paket, jadi ini "
                      "tidak menyentuh jalur data.",
        "platform": "cisco_ios",
        "memutus": False,
        "parameter": [
            {"nama": "alamat", "jenis": "alamat_ip", "label": "Alamat server DNS"},
        ],
        "perintah": ["ip name-server {alamat}"],
    },
    {
        "id": "dns_hapus",
        "nama": "Hapus server DNS",
        "penjelasan": "Menghapus satu penerjemah nama dari daftar.",
        "platform": "cisco_ios",
        "memutus": False,
        "parameter": [
            {"nama": "alamat", "jenis": "alamat_ip", "label": "Alamat server DNS"},
        ],
        "perintah": ["no ip name-server {alamat}"],
    },
    {
        "id": "logging_tambah",
        "nama": "Tambah server syslog",
        "penjelasan": "Menambah tujuan pengiriman log. Log yang hanya "
                      "tersimpan di perangkat ikut hilang bersama "
                      "perangkatnya -- persis saat ia paling dibutuhkan.",
        "platform": "cisco_ios",
        "memutus": False,
        "parameter": [
            {"nama": "alamat", "jenis": "alamat_ip", "label": "Alamat server syslog"},
        ],
        "perintah": ["logging host {alamat}"],
    },
    {
        "id": "logging_hapus",
        "nama": "Hapus server syslog",
        "penjelasan": "Menghapus satu tujuan pengiriman log.",
        "platform": "cisco_ios",
        "memutus": False,
        "parameter": [
            {"nama": "alamat", "jenis": "alamat_ip", "label": "Alamat server syslog"},
        ],
        "perintah": ["no logging host {alamat}"],
    },
    {
        "id": "snmp_lokasi",
        "nama": "Setel lokasi fisik (SNMP)",
        "penjelasan": "Keterangan letak perangkat. Metadata murni -- tidak "
                      "dibaca proses apa pun di perangkat, dan TIDAK memuat "
                      "rahasia SNMP apa pun.",
        "platform": "cisco_ios",
        "memutus": False,
        "parameter": [
            {"nama": "teks", "jenis": "teks", "label": "Lokasi fisik"},
        ],
        "perintah": ["snmp-server location {teks}"],
    },
    {
        "id": "snmp_kontak",
        "nama": "Setel penanggung jawab (SNMP)",
        "penjelasan": "Siapa yang dihubungi kalau perangkat ini bermasalah. "
                      "Metadata murni.",
        "platform": "cisco_ios",
        "memutus": False,
        "parameter": [
            {"nama": "teks", "jenis": "teks", "label": "Penanggung jawab"},
        ],
        "perintah": ["snmp-server contact {teks}"],
    },
    {
        "id": "http_mati",
        "nama": "Matikan server HTTP bawaan",
        "penjelasan": "Mematikan antarmuka web bawaan IOS yang hampir tidak "
                      "pernah dipakai dan hampir tidak pernah ditambal. "
                      "Jalan masuk yang tidak diawasi adalah yang paling "
                      "berguna bagi penyerang.",
        "platform": "cisco_ios",
        "memutus": False,
        # TWO lines at once: `ip http server` and `ip http secure-server` are separate services,
        # and disabling only one leaves the other door open. `drift/ekstrak.py` also treats
        # `layanan_http_mati` as True only when BOTH are off; this command is deliberately made to
        # match that judgment.
        "parameter": [],
        "perintah": ["no ip http server", "no ip http secure-server"],
    },
]

PETA_KATALOG = {p["id"]: p for p in KATALOG}


def daftar(platform=None):
    return [p for p in KATALOG if platform is None or p["platform"] == platform]


def validasi(perintah_id, nilai, interface_tersedia=None):
    """Check all parameters. Returns a dict `{parameter_name: error_message}`.

    An empty dict means accepted. All parameters are checked, not just up to the first error:
    someone who filled in two fields wrong should learn about both at once.
    """
    p = PETA_KATALOG.get(perintah_id)
    if not p:
        return {"_": f"Perintah '{perintah_id}' tidak ada di katalog"}

    nilai = nilai or {}
    galat = {}

    # Unknown parameters are rejected, not silently ignored. A foreign value passing unchecked
    # signals a caller that believes it can send something that is not actually used.
    known = {q["nama"] for q in p["parameter"]}
    for k in nilai:
        if k not in known:
            galat[k] = "parameter ini tidak dikenal untuk perintah tersebut"

    for q in p["parameter"]:
        checker = JENIS[q["jenis"]]
        if q["jenis"] == "interface":
            message = checker(nilai.get(q["nama"]), interface_tersedia)
        else:
            message = checker(nilai.get(q["nama"]))
        if message:
            galat[q["nama"]] = message

    return galat


def susun(perintah_id, nilai, interface_tersedia=None):
    """Build the command lines that WOULD be sent. Sends nothing.

    Raises ValueError if any parameter fails validation. Building must never happen on
    unvalidated values: once a line is built it looks ready to send, and a check deferred to
    later eventually gets skipped.
    """
    galat = validasi(perintah_id, nilai, interface_tersedia)
    if galat:
        raise ValueError("; ".join(f"{k}: {v}" for k, v in sorted(galat.items())))

    p = PETA_KATALOG[perintah_id]
    return [b.format(**nilai) for b in p["perintah"]]


def pratinjau(perintah_id, nilai, interface_tersedia=None):
    """What would be sent, with warnings. Does NOT send.

    This is what a human sees before pressing the button, and it must match exactly what is
    later sent. A preview that differs from reality is worse than none, because it gets
    people to approve something they never read.
    """
    p = PETA_KATALOG.get(perintah_id)
    if not p:
        return {"ok": False, "galat": {"_": f"Perintah '{perintah_id}' tidak ada di katalog"}}

    galat = validasi(perintah_id, nilai, interface_tersedia)
    if galat:
        return {"ok": False, "galat": galat, "perintah": p["nama"]}

    baris = susun(perintah_id, nilai, interface_tersedia)

    peringatan = []
    if p["memutus"]:
        peringatan.append(
            "Perintah ini bisa memutus sambungan NSM ke perangkat. Jalur kirim "
            "akan memasang `reload in 5` lebih dulu, sehingga perangkat "
            "mengembalikan dirinya sendiri kalau sambungan tidak pulih.")
    peringatan.append(
        "Perubahan TIDAK disimpan permanen. Selama belum disimpan, "
        "perangkat akan kembali ke konfigurasi lamanya saat dinyalakan ulang.")

    return {
        "ok": True,
        "perintah": p["nama"],
        "penjelasan": p["penjelasan"],
        "memutus": p["memutus"],
        # What will really be sent, including the configuration-mode wrapper. Shown in full so no
        # line is sent without ever being seen.
        "baris": ["configure terminal"] + baris + ["end"],
        "peringatan": peringatan,
        "terkirim": False,
    }

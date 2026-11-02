"""Catalog of intent keys: what may be declared and what is valid as its value.

Rules as DATA, like `connectors/kepatuhan.py`. The code reads this catalog when validating,
rendering and building the web form, so a new key is one entry here.

Validation is strict because values end up in templates, then in configuration lines, and
later on real device CLIs. An interface description is in the same risk class as the
parameters in `connectors/perintah.py`: a value with a newline could smuggle in an extra command.
1. No value may contain newlines or control characters, checked for EVERY shape.
2. Every key has an allow-list pattern: reject everything except what matches.
3. Values are length-limited here, not by the database column, which would truncate silently.

Secrets never enter intent: no keys for enable passwords, SNMP communities, pre-shared keys or
account passwords. `connectors/konfig.py` masks secrets before storing snapshots; putting them
back here would defeat that. Rendered configuration is therefore INCOMPLETE and cannot be the
only source for rebuilding a device from scratch; its purpose is checking the declared parts.
"""
import re

# --- Known value shapes ---
TEKS = "teks"
ANGKA = "angka"
BOOL = "bool"
PILIHAN = "pilihan"
DAFTAR_IP = "daftar_ip"
DAFTAR_TEKS = "daftar_teks"

BENTUK_DAFTAR = (DAFTAR_IP, DAFTAR_TEKS)

# Any control character (including newline, carriage return, tab) and DEL.
#
# Checked before any key pattern: this is the one check whose reason is not tidiness but
# "one value must not become two command lines".
_KENDALI = re.compile(r"[\x00-\x1f\x7f]")

# IPv4 only. A half-correct IPv6 pattern is worse than an honest rejection.
_IPV4 = re.compile(
    r"^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
    r"(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$")

# Hostname per RFC 1123: alphanumeric at the ends, hyphen allowed in the
# middle, at most 63 characters per label.
_HOSTNAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?$")

# Nama domain: label-label hostname dipisah titik.
_DOMAIN = re.compile(
    r"^[A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)*$")

# Free text printed into the configuration (description, SNMP location, banner). Quotes,
# exclamation marks and braces are deliberately disallowed: they mean something to both the
# Cisco CLI and Linux config files, and no legitimate text needs them.
_TEKS_AMAN = re.compile(r"^[A-Za-z0-9 .,\-_/:@()#+&]{0,200}$")

# Interface names are shaped by the device: FastEthernet0/0, GigabitEthernet0/1.100, Vlan1, enp0s3, eth0.
_IFACE = re.compile(r"^[A-Za-z][A-Za-z0-9]*([0-9]+(/[0-9]+)*(\.[0-9]+)?)?$")

# Cisco VLAN name: no spaces, at most 32 characters.
_NAMA_VLAN = re.compile(r"^[A-Za-z0-9_\-]{1,32}$")


class Ditolak(Exception):
    """Invalid intent value. The message is meant to be read by a human on screen."""


# CATALOG
#
# `platform` decides on which devices a key appears. A key that does not apply to a platform
# is not shown in its form and must not be stored for it: a stored value that is never used
# is a lie waiting to be read.
KUNCI = [
    {
        "kunci": "hostname",
        "judul": "Nama perangkat (hostname)",
        "bentuk": TEKS,
        "pola": _HOSTNAME,
        "maks": 63,
        "platform": ["cisco_ios", "linux"],
        "wajib": True,
        "contoh": "R1",
        "kenapa": "Nama yang muncul di prompt, di syslog, dan di setiap baris "
                  "bukti yang dikumpulkan NSM. Perangkat yang namanya tidak "
                  "sesuai membuat seluruh jejaknya sulit ditelusuri balik.",
    },
    {
        "kunci": "domain",
        "judul": "Nama domain",
        "bentuk": TEKS,
        "pola": _DOMAIN,
        "maks": 100,
        "platform": ["cisco_ios", "linux"],
        "wajib": False,
        "contoh": "bsp.id",
        "kenapa": "Cisco IOS menolak membuat kunci RSA (prasyarat SSH) sebelum "
                  "nama domain terisi. Jadi ini bukan kerapian penamaan; tanpa "
                  "ia, SSH tidak bisa dinyalakan sama sekali.",
    },
    {
        "kunci": "zona_waktu",
        "judul": "Zona waktu",
        "bentuk": PILIHAN,
        "pilihan": ["Asia/Jakarta", "Asia/Makassar", "Asia/Jayapura", "UTC"],
        "platform": ["cisco_ios", "linux"],
        "wajib": True,
        "contoh": "Asia/Jakarta",
        "kenapa": "Jam perangkat yang melenceng membuat korelasi antar-log "
                  "mustahil. Sudah terjadi dua kali di lab ini: jam .103 "
                  "melenceng 15 jam, dan nsm-app sempat UTC sementara seluruh "
                  "lab WIB sehingga data baru tercatat mundur 7 jam.",
    },
    {
        "kunci": "ntp_server",
        "judul": "Server NTP",
        "bentuk": DAFTAR_IP,
        "maks_item": 4,
        "platform": ["cisco_ios", "linux"],
        "wajib": True,
        "contoh": "192.168.56.104",
        "kenapa": "Zona waktu yang benar tidak menolong kalau jamnya sendiri "
                  "hanyut. NTP yang dinyatakan di sini adalah yang akan "
                  "dibandingkan Tahap 2 dengan yang benar-benar terpasang.",
    },
    {
        "kunci": "dns_server",
        "judul": "Server DNS",
        "bentuk": DAFTAR_IP,
        "maks_item": 3,
        "platform": ["cisco_ios", "linux"],
        "wajib": False,
        "contoh": "192.168.56.104",
        "kenapa": "Dipakai perangkat untuk menerjemahkan nama. Kosong berarti "
                  "perangkat hanya mengenal alamat angka.",
    },
    {
        "kunci": "logging_server",
        "judul": "Server syslog",
        "bentuk": DAFTAR_IP,
        "maks_item": 2,
        "platform": ["cisco_ios", "linux"],
        "wajib": False,
        "contoh": "192.168.56.156",
        "kenapa": "Log yang hanya tersimpan di perangkat akan ikut hilang "
                  "bersama perangkatnya -- persis saat log itu paling "
                  "dibutuhkan.",
    },
    {
        "kunci": "snmp_lokasi",
        "judul": "Lokasi fisik (SNMP sysLocation)",
        "bentuk": TEKS,
        "pola": _TEKS_AMAN,
        "maks": 100,
        "platform": ["cisco_ios", "linux"],
        "wajib": False,
        "contoh": "Lokasi A - rak 1",
        "kenapa": "Menjawab 'perangkat ini yang mana secara fisik' tanpa perlu "
                  "menelusuri kabel. TIDAK memuat rahasia SNMP apa pun.",
    },
    {
        "kunci": "snmp_kontak",
        "judul": "Penanggung jawab (SNMP sysContact)",
        "bentuk": TEKS,
        "pola": _TEKS_AMAN,
        "maks": 100,
        "platform": ["cisco_ios", "linux"],
        "wajib": False,
        "contoh": "network@bsp.id",
        "kenapa": "Siapa yang dihubungi kalau perangkat ini bermasalah.",
    },
    {
        "kunci": "banner_masuk",
        "judul": "Banner peringatan saat login",
        "bentuk": TEKS,
        "pola": _TEKS_AMAN,
        "maks": 200,
        "platform": ["cisco_ios", "linux"],
        "wajib": False,
        "contoh": "Akses terbatas. Aktivitas dicatat.",
        "kenapa": "Salah satu dari 23 aturan kepatuhan yang sudah dinilai NSM. "
                  "Nilainya hukum, bukan teknis: tanpa peringatan tertulis, "
                  "'saya tidak tahu ini terlarang' jadi pembelaan yang sah.",
    },
    {
        "kunci": "exec_timeout_menit",
        "judul": "Sesi menganggur ditutup setelah (menit)",
        "bentuk": ANGKA,
        "min": 1,
        "maks_nilai": 60,
        "platform": ["cisco_ios"],
        "wajib": True,
        "contoh": "10",
        "kenapa": "`exec-timeout 0 0` berarti sesi yang ditinggalkan terbuka "
                  "tetap berhak penuh selamanya. Ini temuan kepatuhan yang "
                  "MASIH AKTIF di R1 saat Tahap 1 ditulis.",
    },
    {
        "kunci": "vty_izin",
        "judul": "Alamat yang boleh membuka sesi vty",
        "bentuk": DAFTAR_IP,
        "maks_item": 8,
        "platform": ["cisco_ios"],
        "wajib": False,
        "contoh": "192.168.56.156",
        "kenapa": "Tanpa pembatasan, siapa pun yang bisa mencapai perangkat "
                  "boleh mencoba masuk sebanyak yang ia mau. Kosongkan hanya "
                  "kalau memang disengaja -- dan itu akan terlihat sebagai "
                  "temuan kepatuhan, bukan sebagai kelalaian.",
    },
    {
        "kunci": "ssh_saja",
        "judul": "Hanya SSH di vty (telnet dimatikan)",
        "bentuk": BOOL,
        "platform": ["cisco_ios"],
        "wajib": True,
        "contoh": "ya",
        "kenapa": "Telnet mengirim sandi polos. Lab ini sudah membuktikan "
                  "sekali bahwa sandi polos benar-benar bisa dibaca dari "
                  "kabel -- lihat LDAP-TLS.md.",
    },
    {
        "kunci": "layanan_http_mati",
        "judul": "Server HTTP bawaan dimatikan",
        "bentuk": BOOL,
        "platform": ["cisco_ios"],
        "wajib": True,
        "contoh": "ya",
        "kenapa": "`ip http server` menyalakan antarmuka web yang hampir tidak "
                  "pernah dipakai dan hampir tidak pernah ditambal. Jalan "
                  "masuk yang tidak diawasi adalah yang paling berguna bagi "
                  "penyerang.",
    },
]

# Indexed once at module load; key lookup happens on every save and render.
PETA = {k["kunci"]: k for k in KUNCI}


def untuk_platform(platform):
    """Keys that apply to a platform, in catalog order.

    The catalog order drives both the web form field order and the rendered config line order,
    so the two cannot drift apart.
    """
    return [k for k in KUNCI if platform in k["platform"]]


def platform_didukung():
    """Platforms that have intent keys. Derived, not listed."""
    hasil = set()
    for k in KUNCI:
        hasil.update(k["platform"])
    return sorted(hasil)


def _tolak_kendali(kunci, teks):
    if _KENDALI.search(teks):
        raise Ditolak(
            "%s memuat aksara kendali atau baris baru. Nilai intent ikut "
            "tercetak ke konfigurasi perangkat, dan satu baris baru di sana "
            "berarti satu perintah tambahan yang tidak diminta siapa pun."
            % kunci)


def _satu_teks(spec, nilai):
    """Validate a single text value. Returns the tidied form."""
    kunci = spec["kunci"]
    if not isinstance(nilai, str):
        raise Ditolak("%s harus teks, bukan %s."
                      % (kunci, type(nilai).__name__))
    teks = nilai.strip()
    _tolak_kendali(kunci, teks)
    limit = spec.get("maks", 200)
    if len(teks) > limit:
        raise Ditolak("%s maksimum %d aksara, diberi %d."
                      % (kunci, limit, len(teks)))
    pola = spec.get("pola")
    if pola is not None and teks and not pola.match(teks):
        raise Ditolak(
            "%s tidak sesuai bentuk yang diizinkan. Contoh yang sah: %s"
            % (kunci, spec.get("contoh", "-")))
    return teks


def periksa(kunci, nilai):
    """Validate one intent value. Raises `Ditolak`, or returns the tidied value.

    The returned value is CANONICAL (stripped text, Python list, True/False), and that is what
    gets stored, so "  R1  " and "R1" never become two intents with different render fingerprints.
    """
    spec = PETA.get(kunci)
    if spec is None:
        raise Ditolak(
            "kunci intent '%s' tidak dikenal. Yang dikenal: %s"
            % (kunci, ", ".join(sorted(PETA))))

    bentuk = spec["bentuk"]

    if bentuk == TEKS:
        return _satu_teks(spec, nilai)

    if bentuk == PILIHAN:
        teks = _satu_teks(dict(spec, maks=100, pola=None), nilai)
        if teks not in spec["pilihan"]:
            raise Ditolak("%s harus salah satu dari: %s"
                          % (kunci, ", ".join(spec["pilihan"])))
        return teks

    if bentuk == BOOL:
        # Accepts the shapes that really come from the web form and JSON, but nothing that merely "looks right".
        if isinstance(nilai, bool):
            return nilai
        if isinstance(nilai, str):
            t = nilai.strip().lower()
            if t in ("ya", "true", "1"):
                return True
            if t in ("tidak", "false", "0"):
                return False
        raise Ditolak("%s harus ya/tidak, diberi %r." % (kunci, nilai))

    if bentuk == ANGKA:
        # `isinstance(True, int)` is True in Python, so bool is rejected explicitly (same convention as `ubah_firewall.py`).
        if isinstance(nilai, bool) or not isinstance(nilai, (int, str)):
            raise Ditolak("%s harus bilangan bulat." % kunci)
        try:
            angka = int(str(nilai).strip())
        except ValueError:
            raise Ditolak("%s harus bilangan bulat, diberi %r."
                          % (kunci, nilai))
        if angka < spec.get("min", 0) or angka > spec.get("maks_nilai", 65535):
            raise Ditolak("%s harus antara %d dan %d, diberi %d."
                          % (kunci, spec.get("min", 0),
                             spec.get("maks_nilai", 65535), angka))
        return angka

    if bentuk in BENTUK_DAFTAR:
        if isinstance(nilai, str):
            # The web form sends one comma-separated line. It is split HERE so the stored form stays the only canonical form.
            butir = [b.strip() for b in nilai.split(",")]
        elif isinstance(nilai, (list, tuple)):
            butir = [str(b).strip() for b in nilai]
        else:
            raise Ditolak("%s harus daftar." % kunci)
        butir = [b for b in butir if b]
        limit = spec.get("maks_item", 8)
        if len(butir) > limit:
            raise Ditolak("%s maksimum %d entri, diberi %d."
                          % (kunci, limit, len(butir)))
        for b in butir:
            _tolak_kendali(kunci, b)
            if bentuk == DAFTAR_IP and not _IPV4.match(b):
                raise Ditolak("%s: '%s' bukan alamat IPv4 yang sah."
                              % (kunci, b))
            if bentuk == DAFTAR_TEKS and not _TEKS_AMAN.match(b):
                raise Ditolak("%s: '%s' memuat aksara yang tidak diizinkan."
                              % (kunci, b))
        # Duplicates are dropped but typed order is kept: NTP server order matters on Cisco IOS
        # (the first is tried first), while duplicate entries would produce doubled config lines
        # reported as permanent drift.
        unique = []
        for b in butir:
            if b not in unique:
                unique.append(b)
        return unique

    raise Ditolak("bentuk '%s' belum ditangani untuk kunci %s."
                  % (bentuk, kunci))


def _periksa_kumpulan(platform, nilai_per_kunci):
    """Validate a set of key->value pairs against a platform. Does NOT check required completeness
    (shared by `periksa_parsial` and `periksa_lengkap`).

    Unknown keys are rejected, and so are keys that do not apply to this platform (not stored
    as values that are never used at render time).
    """
    berlaku = {k["kunci"]: k for k in untuk_platform(platform)}
    if not berlaku:
        raise Ditolak(
            "platform '%s' belum punya katalog intent. Yang didukung: %s"
            % (platform, ", ".join(platform_didukung())))

    hasil = {}
    for kunci, nilai in nilai_per_kunci.items():
        if kunci not in PETA:
            raise Ditolak("kunci intent '%s' tidak dikenal." % kunci)
        if kunci not in berlaku:
            raise Ditolak(
                "kunci '%s' tidak berlaku untuk platform %s. Menyimpannya "
                "akan menghasilkan nilai yang tidak pernah dipakai saat "
                "render -- dan nilai tersimpan yang tidak berarti apa-apa "
                "lebih menyesatkan daripada nilai yang tidak ada."
                % (kunci, platform))
        rapi = periksa(kunci, nilai)
        # An empty value means "not declared". It is not stored as an empty row, so "never filled in"
        # and "deliberately cleared" cannot become indistinguishable later.
        if rapi == "" or rapi == []:
            continue
        hasil[kunci] = rapi
    return hasil, berlaku


def periksa_parsial(platform, nilai_per_kunci):
    """Validate the SUBMITTED key->value pairs without requiring completeness.

    Used by the save path (`sot/service.py`): the intent form may be filled in stages.
    Completeness is checked separately right before RENDER (`kekurangan`), so "incomplete"
    and "invalid" are different errors.
    """
    hasil, _ = _periksa_kumpulan(platform, nilai_per_kunci)
    return hasil


def periksa_lengkap(platform, nilai_per_kunci):
    """Validate a device's WHOLE intent at once, INCLUDING completeness.

    Returns a canonical dict ready to store. Raises `Ditolak` on the FIRST error. For the
    staged save path see `periksa_parsial`.
    """
    hasil, berlaku = _periksa_kumpulan(platform, nilai_per_kunci)
    for kunci, spec in berlaku.items():
        if spec.get("wajib") and kunci not in hasil:
            raise Ditolak(
                "%s wajib diisi untuk platform %s (contoh: %s)."
                % (spec["judul"], platform, spec.get("contoh", "-")))
    return hasil


def kekurangan(platform, nilai_tersimpan):
    """Required keys NOT yet present in `nilai_tersimpan` (dict key->value).

    Returns key specs (not only names) so callers can show titles and examples directly.
    An empty list means the intent is complete enough to render.
    """
    return [spec for spec in untuk_platform(platform)
            if spec.get("wajib") and spec["kunci"] not in nilai_tersimpan]


# REPEATED SECTIONS: interfaces, VLANs, routes.
#
# Not in `KUNCI` because they are many rows per device, not one value. Validation stays in
# this file so no intent value can enter the database through a path that skips the
# control-character check.

def periksa_interface(baris):
    """One intended interface row. Returns a canonical dict."""
    nama = str(baris.get("nama", "")).strip()
    _tolak_kendali("interface.nama", nama)
    if not nama or not _IFACE.match(nama) or len(nama) > 60:
        raise Ditolak(
            "nama interface '%s' tidak sah. Contoh yang sah: "
            "FastEthernet0/0, GigabitEthernet0/1.100, Vlan1, enp0s3." % nama)

    deskripsi = str(baris.get("deskripsi") or "").strip()
    _tolak_kendali("interface.deskripsi", deskripsi)
    if deskripsi and not _TEKS_AMAN.match(deskripsi):
        raise Ditolak("deskripsi interface %s memuat aksara yang tidak "
                      "diizinkan." % nama)

    ip = str(baris.get("ip") or "").strip()
    mask = str(baris.get("mask") or "").strip()
    if ip and not _IPV4.match(ip):
        raise Ditolak("alamat interface %s tidak sah: '%s'." % (nama, ip))
    if mask and not _IPV4.match(mask):
        raise Ditolak("subnet mask interface %s tidak sah: '%s'."
                      % (nama, mask))
    # An IP without a mask would render `ip address 10.0.0.1`, which IOS rejects midway through a push.
    if ip and not mask:
        raise Ditolak("interface %s diberi alamat tanpa subnet mask." % nama)
    if mask and not ip:
        raise Ditolak("interface %s diberi subnet mask tanpa alamat." % nama)

    vlan = baris.get("vlan")
    if vlan not in (None, "", 0):
        try:
            vlan = int(vlan)
        except (TypeError, ValueError):
            raise Ditolak("VLAN interface %s harus bilangan." % nama)
        if not 1 <= vlan <= 4094:
            raise Ditolak("VLAN interface %s harus 1-4094, diberi %d."
                          % (nama, vlan))
    else:
        vlan = None

    return {
        "nama": nama,
        "deskripsi": deskripsi or None,
        "ip": ip or None,
        "mask": mask or None,
        "vlan": vlan,
        # Default is UP, not down: an intent that forgets to mention `shutdown` must not mean "shut this interface down".
        "shutdown": bool(baris.get("shutdown")),
    }


def periksa_vlan(baris):
    """One intended VLAN row."""
    try:
        vid = int(baris.get("vlan_id"))
    except (TypeError, ValueError):
        raise Ditolak("nomor VLAN harus bilangan, diberi %r."
                      % baris.get("vlan_id"))
    if not 1 <= vid <= 4094:
        raise Ditolak("nomor VLAN harus 1-4094, diberi %d." % vid)
    nama = str(baris.get("nama") or "").strip()
    _tolak_kendali("vlan.nama", nama)
    if nama and not _NAMA_VLAN.match(nama):
        raise Ditolak("nama VLAN %d tidak sah: '%s' (tanpa spasi, maksimum "
                      "32 aksara)." % (vid, nama))
    return {"vlan_id": vid, "nama": nama or None}


def periksa_rute(baris):
    """One intended static route row."""
    tujuan = str(baris.get("tujuan") or "").strip()
    mask = str(baris.get("mask") or "").strip()
    next_hop = str(baris.get("next_hop") or "").strip()
    for label, nilai in (("tujuan", tujuan), ("mask", mask),
                         ("next_hop", next_hop)):
        if not nilai:
            raise Ditolak("rute statis wajib punya %s." % label)
        if not _IPV4.match(nilai):
            raise Ditolak("rute statis: %s '%s' bukan alamat IPv4 yang sah."
                          % (label, nilai))
    catatan = str(baris.get("catatan") or "").strip()
    _tolak_kendali("rute.catatan", catatan)
    if catatan and not _TEKS_AMAN.match(catatan):
        raise Ditolak("catatan rute memuat aksara yang tidak diizinkan.")
    return {"tujuan": tujuan, "mask": mask, "next_hop": next_hop,
            "catatan": catatan or None}


# RISK CLASSIFICATION, used by `drift/` to label each deviation as "safe to automate" or "needs a human".
#
# Kept separate from `KUNCI` on purpose, so the already validated save path is untouched.
# This is only classification, not execution: the automation guard and the config restorer
# must still check their own guard at the point of execution instead of trusting this label.
RISIKO_AMAN = "aman_otomatis"
RISIKO_MANUSIA = "wajib_manusia"

# (level, reason). The reason must be showable to report readers, so this data is meant to be READ too.
RISIKO_KUNCI = {
    "hostname": (RISIKO_MANUSIA,
        "Identitas perangkat. Risiko teknisnya rendah, tapi mengubahnya "
        "tanpa sepengetahuan operator membuat nama di layar tidak lagi "
        "cocok dengan yang diingat orang -- kebingungan yang mahal saat "
        "insiden sungguhan sedang ditangani."),
    "domain": (RISIKO_MANUSIA,
        "Nama domain dipakai IOS saat membuat kunci RSA (prasyarat SSH). "
        "Mengubahnya di perangkat yang kuncinya sudah ada tidak merusak "
        "sesi yang berjalan, tapi implikasi kripto sebaiknya tidak "
        "diputuskan mesin sendirian."),
    "zona_waktu": (RISIKO_AMAN,
        "Tidak memutus lalu lintas apa pun. Yang salah hanya jam di log "
        "sampai diperbaiki -- dan itu justru argumen UNTUK memperbaikinya "
        "cepat, bukan alasan menunda."),
    "ntp_server": (RISIKO_AMAN,
        "Menambah/memperbaiki server NTP tidak memutus sesi atau trafik "
        "yang sedang berjalan."),
    "dns_server": (RISIKO_AMAN,
        "Sama seperti NTP -- resolusi nama tidak dipakai jalur data "
        "perangkat jaringan itu sendiri."),
    "logging_server": (RISIKO_AMAN,
        "Menambah tujuan log tidak mengubah perilaku perangkat."),
    "snmp_lokasi": (RISIKO_AMAN, "Metadata murni, tidak dibaca proses apa pun di perangkat."),
    "snmp_kontak": (RISIKO_AMAN, "Metadata murni, tidak dibaca proses apa pun di perangkat."),
    "banner_masuk": (RISIKO_AMAN,
        "Teks yang ditampilkan sebelum login. Tidak memutus sesi yang "
        "sudah terbuka, tidak mengubah jalur data."),
    "exec_timeout_menit": (RISIKO_MANUSIA,
        "Mengubah nilai ini bisa memutus SESI ADMIN YANG SEDANG BERLANGSUNG "
        "-- termasuk berpotensi sesi milik operator yang menerapkannya "
        "sendiri. Persis kelas risiko yang membuat `line vty` diberi jaring "
        "pengaman `reload in` di kirim_perintah.py."),
    "vty_izin": (RISIKO_MANUSIA,
        "RISIKO TERTINGGI di seluruh katalog ini: `access-class` yang "
        "salah bisa MENGUNCI SELURUH AKSES MANAJEMEN ke perangkat, termasuk "
        "jalur NSM sendiri. Never automate a lockout."),
    "ssh_saja": (RISIKO_MANUSIA,
        "Mematikan telnet bisa memutus SESI TELNET yang sedang aktif saat "
        "itu juga -- tindakan yang tepat, tapi waktunya harus dipilih "
        "manusia, bukan dijalankan begitu terdeteksi."),
    "layanan_http_mati": (RISIKO_AMAN,
        "Mematikan server HTTP bawaan yang memang jarang dipakai sengaja. "
        "Tidak ada sesi manajemen yang lewat jalur ini di lab ini."),
}

# Interface/VLAN/route: the risk is inherent to the CATEGORY, not to a particular value.
# All three are WAJIB_MANUSIA without exception: changing interface IP/shutdown, VLAN
# membership or static routes is exactly what the design puts last (highest risk) among the
# planned remediators, and full automation is not considered before the guard and real rollback exist.
RISIKO_KATEGORI = {
    "interface": (RISIKO_MANUSIA,
        "Mengubah IP/deskripsi/status interface bisa memutus konektivitas "
        "seketika. Kategori risiko tertinggi di seluruh SoT."),
    "vlan": (RISIKO_MANUSIA,
        "Perubahan VLAN memengaruhi segmentasi L2 yang bisa menjangkau "
        "banyak perangkat sekaligus, bukan cuma satu."),
    "rute": (RISIKO_MANUSIA,
        "Rute statis yang salah bisa menciptakan blackhole atau loop "
        "routing -- gagalnya tidak selalu langsung terlihat."),
}


def risiko_kunci(kunci):
    """(level, reason) for one intent key. Defaults to wajib_manusia if a catalog key was never
    classified, so an oversight ends in "ask a human", not "automatic".
    """
    return RISIKO_KUNCI.get(kunci, (RISIKO_MANUSIA, "belum diklasifikasikan -- default aman"))


def risiko_kategori(kategori):
    """(level, reason) for the interface/vlan/route categories."""
    return RISIKO_KATEGORI.get(kategori, (RISIKO_MANUSIA, "belum diklasifikasikan -- default aman"))


# TIME ZONE: one map, used by both the renderer and the parser.
#
# `cisco_ios.j2` once rendered `clock timezone Asia-Jakarta`, which is not valid IOS syntax,
# while `drift/ekstrak.py` reads the first token after `clock timezone` (`WIB` on a real
# device). The values would never match: drift would be reported forever and the remediator
# would retry endlessly.
#
# Cisco value: (name, hour_offset, minute_offset). The name uses the Indonesian abbreviation
# the lab devices use, not the IANA code.
ZONA_KE_CISCO = {
    "Asia/Jakarta":  ("WIB",  7, 0),
    "Asia/Makassar": ("WITA", 8, 0),
    "Asia/Jayapura": ("WIT",  9, 0),
    "UTC":           ("UTC",  0, 0),
}

# The reverse, used by `drift/ekstrak.py` to translate what is read on the device back to the
# canonical intent form. DERIVED, not retyped, so the two maps cannot diverge.
CISCO_KE_ZONA = {v[0]: k for k, v in ZONA_KE_CISCO.items()}


def zona_cisco(zona):
    """'Asia/Jakarta' -> 'WIB 7 0'. Used by the template through the render context.

    An unmapped zone is returned as-is: it cannot happen through the normal path
    (`periksa()` limits to `pilihan`), and raising inside render would break the whole page.
    """
    entry = ZONA_KE_CISCO.get(zona)
    if entry is None:
        return zona
    nama, hour, minute = entry
    return "%s %d %d" % (nama, hour, minute)

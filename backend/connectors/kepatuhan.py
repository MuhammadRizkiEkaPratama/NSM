"""Evaluates device configuration against explainable security rules.

Config backups answer "WHAT changed?". This module answers "is what is there now safe?".

ZERO CONTACT WITH DEVICES. Everything is judged from the snapshot text already stored in
`konfig_snapshots`: no new connections or commands, and this file must not import any
connector that opens the network.

RULES ARE DATA, NOT NESTED `if`s. Rules written as functions cannot be displayed,
counted, or explained to a report reader. Rules written as data can be all three, so
"which rules does NSM check" has an answer on screen, not only in code.

THREE OUTCOMES, NOT TWO:
    `PATUH`          the rule applies to this device and is satisfied
    `TEMUAN`         the rule applies and is not satisfied
    `TIDAK_BERLAKU`  the rule is not meant for this device's platform
The third is required. Without it a Linux device would look 100% compliant with Cisco
rules that were never checked against it, a number that is arithmetically true but
misleading. The Audit Log uses the same idea (skipped next to OK/failed).

SECRETS STAY MASKED. `konfig.samarkan()` replaces secret values with `<DISAMARKAN>`
before storing. Some rules are tempted to need the real value (e.g. "is the SNMP
community `public`?"); that is refused, because a compliance tool that required storing
raw secrets would create more risk than it finds. Still judgeable without the value: the
presence of a line, the hash TYPE (`secret 5` vs `secret 9`; the number is not secret),
and accompanying privilege (`privilege 15`).
"""
import re

PATUH = "PATUH"
TEMUAN = "TEMUAN"
TIDAK_BERLAKU = "TIDAK_BERLAKU"

TINGGI = "tinggi"
SEDANG = "sedang"
RENDAH = "rendah"

# Severity order for sorting, defined once so pages, reports, and alerts agree.
URUTAN_KEPARAHAN = {TINGGI: 0, SEDANG: 1, RENDAH: 2}


# ===========================================================================
# Pemecah blok konfigurasi Cisco IOS
# ===========================================================================
def pecah_blok(teks):
    """Split a configuration into `[(block_title, [lines inside])]`.

    Cisco IOS marks ownership by INDENTATION: an indented line belongs to the last
    non-indented line above it. Without that, "no telnet INSIDE line vty" cannot be told
    apart from "no telnet anywhere", which are different rules with different answers. A
    global line with nothing under it still becomes a block titled by itself with an empty
    list, so global searches need no special case.

    Two block forms are supported, and both are needed:
        Cisco IOS   indentation         `line vty 0 4`, then indented lines
        Linux       `### x` markers     assembled by `connectors/konfig_linux.py`
    Linux has no single config file, so its snapshot is built from several sources, each
    with a `### name` header. Without the second form every Linux line would be its own
    block, and "firewall must be active IN the firewall section" could not be told apart
    from "the word `active` appears somewhere": two questions that happen to agree today and
    will not tomorrow.
    """
    block = []
    judul = None
    content = []
    mode_section = "###" in (teks or "")

    for line in (teks or "").splitlines():
        if not line.strip() or line.strip() == "!":
            continue
        if mode_section:
            if line.startswith("###"):
                if judul is not None:
                    block.append((judul, content))
                judul = line.strip()
                content = []
            elif judul is not None:
                content.append(line.strip())
            continue
        if line[0].isspace():
            if judul is not None:
                content.append(line.strip())
            continue
        if judul is not None:
            block.append((judul, content))
        judul = line.strip()
        content = []
    if judul is not None:
        block.append((judul, content))
    return block


def baris_semua(teks):
    """Meaningful lines only: no `!` separators and no blank lines. Line numbers follow the
    ORIGINAL file, not the filtered text, so a finding pointing at line 12 matches what the
    reader sees when opening the snapshot.
    """
    hasil = []
    for n, line in enumerate((teks or "").splitlines(), 1):
        if not line.strip() or line.strip() == "!":
            continue
        hasil.append((n, line))
    return hasil


# RULE CATALOG
#
# `cara` decides what satisfies a rule:
#     `tidak_boleh_ada`  finding if the pattern IS found
#     `harus_ada`        finding if the pattern is NOT found
#
# `dalam` limits the search to blocks whose title matches; empty means the whole config.
#
# `pola_alternatif` (optional) is searched in the WHOLE config. If found, the rule counts
# as satisfied even when the main pattern is not. Used for rules with more than one valid
# way to comply.
KATALOG = [
    {
        "id": "vty_telnet",
        "judul": "Telnet terbuka di jalur vty",
        "platform": "cisco_ios",
        "keparahan": TINGGI,
        "cara": "tidak_boleh_ada",
        "dalam": r"^line vty",
        "pola": r"^transport input .*(telnet|all)",
        "kenapa": "Telnet mengirim nama pengguna dan sandi dalam bentuk yang "
                  "bisa dibaca langsung dari kabel. Siapa pun yang bisa "
                  "melihat lalu lintas di jalur yang sama mendapatkan "
                  "kredensial perangkat tanpa perlu menebak apa pun.",
        "perbaikan": "line vty 0 4\n transport input ssh",
    },
    {
        "id": "ssh_v2",
        "judul": "SSH masih versi 1",
        "platform": "cisco_ios",
        "keparahan": TINGGI,
        "cara": "harus_ada",
        "dalam": "",
        "pola": r"^ip ssh version 2",
        "kenapa": "SSH versi 1 punya kelemahan yang sudah diketahui dan tidak "
                  "diperbaiki; ia bisa diserang di tengah jalan. Tanpa baris "
                  "ini, perangkat menerima keduanya, dan penyerang tinggal "
                  "meminta yang lemah.",
        "perbaikan": "ip ssh version 2",
    },
    {
        "id": "snmp_community",
        "judul": "SNMP v1/v2c masih dipakai",
        "platform": "cisco_ios",
        "keparahan": TINGGI,
        "cara": "tidak_boleh_ada",
        "dalam": "",
        "pola": r"^snmp-server community",
        "kenapa": "SNMP v1 dan v2c mengirim community string tanpa enkripsi, "
                  "dan community string adalah satu-satunya yang menjaganya. "
                  "Membacanya dari jaringan cukup untuk membaca seluruh "
                  "keadaan perangkat.",
        "perbaikan": "no snmp-server community <nama>\n"
                     "snmp-server group ... v3 priv ...",
    },
    {
        "id": "http_server",
        "judul": "Server HTTP perangkat masih menyala",
        "platform": "cisco_ios",
        "keparahan": SEDANG,
        # `harus_ada: no ip http server`, not `tidak_boleh_ada: ip http server`. IOS only writes
        # the line when the feature is turned OFF (enabled is the default on many images), so a
        # rule searching for the enabled line would report compliant for devices that never
        # touched it, which are the ones most likely still running it.
        "cara": "harus_ada",
        "dalam": "",
        "pola": r"^no ip http server",
        "kenapa": "Antarmuka web perangkat jaringan jarang dipakai dan jarang "
                  "diperbarui, sementara ia menerima sandi lewat HTTP polos. "
                  "Ia menambah jalan masuk tanpa menambah kemampuan yang "
                  "tidak sudah dipunyai SSH.",
        "perbaikan": "no ip http server\nno ip http secure-server",
    },
    {
        "id": "akun_privilege15",
        "judul": "Akun berhak penuh (privilege 15)",
        "platform": "cisco_ios",
        "keparahan": TINGGI,
        "cara": "tidak_boleh_ada",
        "dalam": "",
        "pola": r"^username \S+ privilege 15",
        "kenapa": "Akun yang dipakai memantau seharusnya hanya bisa MEMBACA. "
                  "Dengan privilege 15 ia bisa mengubah apa pun, dan "
                  "satu-satunya yang menahannya adalah kode NSM sendiri, "
                  "bukan perangkatnya. Siapa pun yang memegang salinan "
                  "nsm.db memegang kredensial yang berhak penuh.",
        "perbaikan": "username nsm privilege 5 secret <sandi>\n"
                     "privilege exec level 5 show running-config",
    },
    {
        "id": "logging",
        "judul": "Perangkat tidak mencatat apa pun",
        "platform": "cisco_ios",
        "keparahan": TINGGI,
        "cara": "harus_ada",
        "dalam": "",
        "pola": r"^logging (buffered|host|\d)",
        "kenapa": "Tanpa pencatatan, perubahan yang dilakukan seseorang di "
                  "luar NSM tidak meninggalkan jejak siapa dan kapan. "
                  "Satu-satunya bukti yang tersisa adalah selisih potret "
                  "berikutnya, dan itu hanya menyebutkan APA yang berubah.",
        "perbaikan": "logging buffered 16384\nlogging host <alamat syslog>",
    },
    {
        "id": "ntp",
        "judul": "Tidak ada sumber waktu (NTP)",
        "platform": "cisco_ios",
        "keparahan": SEDANG,
        "cara": "harus_ada",
        "dalam": "",
        "pola": r"^ntp server",
        "kenapa": "Perangkat yang jamnya tidak disinkronkan memberi cap waktu "
                  "yang tidak bisa disandingkan dengan catatan mana pun. "
                  "Proyek ini sudah membayar untuk itu di tempat lain: jam VM "
                  ".103 melar sampai halaman Kesehatan menyatakan sehat untuk "
                  "keadaan yang tidak sehat.",
        "perbaikan": "ntp server <alamat>",
    },
    {
        "id": "exec_timeout_nol",
        "judul": "Sesi tidak pernah kedaluwarsa (exec-timeout 0 0)",
        "platform": "cisco_ios",
        "keparahan": SEDANG,
        "cara": "tidak_boleh_ada",
        "dalam": r"^line ",
        "pola": r"^exec-timeout 0 0",
        "kenapa": "Sesi yang ditinggalkan terbuka tetap berhak penuh "
                  "selamanya. Siapa pun yang kemudian menyentuh konsol itu "
                  "melanjutkan sesi orang sebelumnya tanpa perlu masuk.",
        "perbaikan": "line con 0\n exec-timeout 10 0",
    },
    {
        "id": "aux_aktif",
        "judul": "Port AUX masih menerima sesi",
        "platform": "cisco_ios",
        "keparahan": SEDANG,
        "cara": "harus_ada",
        "dalam": r"^line aux",
        "pola": r"^no exec",
        "kenapa": "Port AUX hampir tidak pernah dipakai, jadi ia juga hampir "
                  "tidak pernah diperiksa. Jalan masuk yang tidak diawasi "
                  "adalah jalan masuk yang paling berguna bagi penyerang.",
        "perbaikan": "line aux 0\n no exec\n transport input none",
    },
    {
        "id": "enable_secret",
        "judul": "Tidak ada enable secret",
        "platform": "cisco_ios",
        "keparahan": SEDANG,
        "cara": "harus_ada",
        "dalam": "",
        "pola": r"^enable secret",
        "kenapa": "Tanpa enable secret, naik ke mode berhak penuh tidak "
                  "menuntut apa pun selain sudah berada di dalam. Satu sesi "
                  "yang bocor langsung berarti hak penuh.",
        "perbaikan": "enable secret <sandi>",
    },
    {
        "id": "hash_lemah",
        "judul": "Sandi disimpan dengan hash lemah",
        "platform": "cisco_ios",
        "keparahan": SEDANG,
        "cara": "tidak_boleh_ada",
        "dalam": "",
        # Type 5 = MD5; type 7 = reversible encoding that any online tool can decode. The number
        # itself is not secret, so judging it does not require the real value.
        "pola": r"(secret 5 |password 7 )",
        "kenapa": "Tipe 7 bukan hash sama sekali, melainkan penyandian yang "
                  "bisa dibalik dengan alat yang tersedia bebas. Tipe 5 (MD5) "
                  "sudah bisa ditebak-paksa dengan cepat pada perangkat keras "
                  "biasa. Yang layak dipakai tipe 8 atau 9.",
        "perbaikan": "username <nama> secret 9 <sandi>",
    },
    {
        "id": "vty_dibatasi",
        "judul": "Jalur vty terbuka dari alamat mana pun",
        "platform": "cisco_ios",
        "keparahan": SEDANG,
        "cara": "harus_ada",
        "dalam": r"^line vty",
        "pola": r"^access-class",
        # Restricting source addresses AND slowing repeated guesses are two valid ways to close the
        # same hole. A rule that recognizes only one would report findings for devices that are
        # already safe.
        "pola_alternatif": r"^login block-for",
        "kenapa": "Tanpa pembatasan, siapa pun yang bisa mencapai perangkat "
                  "di jaringan boleh mencoba masuk sebanyak yang ia mau. "
                  "Membatasi alamat asal atau memperlambat percobaan beruntun "
                  "mengubah tebakan-paksa dari mungkin jadi tidak praktis.",
        "perbaikan": "line vty 0 4\n access-class 10 in\n"
                     "atau: login block-for 120 attempts 3 within 60",
    },
    {
        "id": "password_encryption",
        "judul": "service password-encryption tidak menyala",
        "platform": "cisco_ios",
        "keparahan": RENDAH,
        "cara": "harus_ada",
        "dalam": "",
        "pola": r"^service password-encryption",
        "kenapa": "Tanpa ini, sandi yang belum di-hash tampil apa adanya di "
                  "konfigurasi. Ia bukan pengamanan sungguhan (penyandiannya "
                  "bisa dibalik), tetapi ia menutup pembacaan sekilas oleh "
                  "orang yang kebetulan melihat layar.",
        "perbaikan": "service password-encryption",
    },
    {
        "id": "banner",
        "judul": "Tidak ada banner peringatan",
        "platform": "cisco_ios",
        "keparahan": RENDAH,
        "cara": "harus_ada",
        "dalam": "",
        "pola": r"^banner (login|motd|exec)",
        "kenapa": "Banner tidak menghalangi siapa pun secara teknis. Gunanya "
                  "hukum: tanpa pemberitahuan bahwa akses tidak sah dilarang, "
                  "menuntut orang yang masuk tanpa izin jadi jauh lebih sulit "
                  "di banyak yurisdiksi.",
        "perbaikan": "banner login ^C Akses hanya untuk yang berwenang ^C",
    },
]

# LINUX RULES
#
# The snapshot is assembled by `connectors/konfig_linux.py` from several sources, each with
# a `### name` header. All are read WITHOUT sudo, verified beforehand with `cek_hak_akun.py`
# on both VMs rather than assumed.
#
# Acknowledged limit: it reads the FILES, not the effective configuration. `sshd -T` is
# more accurate but needs root, and a rule needing more privilege than the monitoring
# account has would force raising that account's rights, the opposite of the finding being
# reported.
KATALOG += [
    {
        "id": "linux_akun_setara_root",
        "judul": "Akun pemantau setara root lewat grup istimewa",
        "platform": "linux",
        "keparahan": TINGGI,
        "cara": "tidak_boleh_ada",
        # Section `akun-pemantau-grup`, NOT `grup-istimewa`. The latter lists anyone, including the
        # VM owner's human account, which MUST keep sudo as the only admin; checking it would make
        # this finding impossible to clear however correct the fix.
        "dalam": r"^### akun-pemantau-grup",
        # `lxd` and `docker` are named alongside `sudo` on purpose: both are widely documented
        # privilege-escalation paths, and both are often missed because their names do not sound
        # like "admin".
        "pola": r"^(lxd|docker)$",
        "kenapa": "Anggota grup `lxd` atau `docker` bisa menjadi root TANPA "
                  "sandi sama sekali: keduanya mengizinkan membuat wadah yang "
                  "memasang berkas sistem induknya. Untuk akun yang dipakai "
                  "alat pemantau, itu berarti kredensial yang tersimpan di "
                  "`nsm.db` — dan ikut tersalin ke cloud tiap malam — setara "
                  "dengan akses root ke mesin ini. Ini bentuk yang sama "
                  "dengan `privilege 15` di router, dan lebih buruk karena "
                  "naiknya tidak menuntut sandi.",
        # Removing `lxd` is SAFE even for the only admin account: its rights as a `sudo` member
        # remain, so it can restore itself. Unlike removing `sudo`, which the account that just
        # lost it cannot undo.
        "perbaikan": "getent group lxd docker   # lihat dulu siapa saja\n"
                     "sudo gpasswd -d <akun> lxd\n"
                     "sudo gpasswd -d <akun> docker\n"
                     "# aman walau ini satu-satunya admin: grup sudo tidak ikut hilang",
    },
    {
        "id": "linux_akun_sudo",
        "judul": "Akun pemantau ada di grup sudo",
        "platform": "linux",
        "keparahan": SEDANG,
        "cara": "tidak_boleh_ada",
        "dalam": r"^### akun-pemantau-grup",
        "pola": r"^(sudo|wheel|admin)$",
        "kenapa": "Akun yang tugasnya MEMBACA tidak perlu bisa menjadi root. "
                  "Sandinya tersimpan polos di `nsm.db`, jadi selama akun itu "
                  "ada di grup sudo, satu berkas yang bocor sama dengan akses "
                  "penuh ke mesin ini.",
        # THE FIX CREATES A NEW ACCOUNT INSTEAD OF REMOVING THE GROUP.
        #
        # A bare `gpasswd -d <account> sudo` is wrong for the most common case: on both lab VMs the
        # account NSM uses is the ONLY human account and the only `sudo` member, so running it
        # would remove the last admin and lock the owner out of the machine. User management
        # already guards the same trap (the last admin cannot be revoked).
        "perbaikan": "# JANGAN cabut grup kalau ini satu-satunya akun admin.\n"
                     "# Periksa dulu:  getent group sudo\n"
                     "# Yang benar: buat akun pemantau tersendiri, lalu\n"
                     "# arahkan NSM ke akun itu.\n"
                     "sudo adduser --disabled-password --gecos 'NSM baca' nsmro\n"
                     "sudo usermod -aG adm nsmro   # hanya kalau perlu baca log\n"
                     "# akun manusia TETAP di grup sudo",
    },
    {
        "id": "linux_ssh_root",
        "judul": "Login root langsung lewat SSH diizinkan",
        "platform": "linux",
        "keparahan": TINGGI,
        "cara": "tidak_boleh_ada",
        "dalam": r"^### sshd",
        "pola": r"^PermitRootLogin\s+yes",
        "kenapa": "Root adalah satu-satunya nama akun yang pasti ada di setiap "
                  "mesin Linux, jadi ia sasaran tebakan-paksa yang tidak perlu "
                  "ditebak namanya. Masuk sebagai pengguna biasa lalu naik "
                  "juga meninggalkan jejak siapa yang melakukannya.",
        "perbaikan": "PermitRootLogin prohibit-password",
    },
    {
        "id": "linux_ssh_sandi",
        "judul": "SSH masih menerima sandi",
        "platform": "linux",
        "keparahan": SEDANG,
        # `harus_ada` on the value `no`, deliberately. If `PasswordAuthentication` is not
        # mentioned at all, the OpenSSH default applies, and the default ACCEPTS passwords. A rule
        # written as "`yes` must not appear" would report compliant for a machine that accepts
        # passwords simply because it never touched the setting. Over-reporting here is far cheaper
        # than staying silent.
        "cara": "harus_ada",
        "dalam": r"^### sshd",
        "pola": r"^PasswordAuthentication\s+no",
        "kenapa": "Sandi bisa ditebak-paksa; kunci tidak. Kalau baris ini "
                  "tidak muncul sama sekali, yang berlaku adalah bawaan "
                  "OpenSSH, dan bawaannya MENERIMA sandi. Perlu diperiksa "
                  "juga di `/etc/ssh/sshd_config.d/`, yang menimpa berkas "
                  "utamanya.",
        "perbaikan": "PasswordAuthentication no\n"
                     "(pastikan kunci sudah terpasang lebih dulu)",
    },
    {
        "id": "linux_ssh_sandi_kosong",
        "judul": "SSH menerima sandi kosong",
        "platform": "linux",
        "keparahan": TINGGI,
        "cara": "tidak_boleh_ada",
        "dalam": r"^### sshd",
        "pola": r"^PermitEmptyPasswords\s+yes",
        "kenapa": "Akun bersandi kosong bisa dimasuki siapa pun yang tahu "
                  "nama akunnya. Tidak ada keadaan di mana ini disengaja pada "
                  "mesin yang terhubung jaringan.",
        "perbaikan": "PermitEmptyPasswords no",
    },
    {
        "id": "linux_firewall",
        "judul": "Firewall tidak aktif",
        "platform": "linux",
        "keparahan": TINGGI,
        "cara": "harus_ada",
        "dalam": r"^### firewall",
        "pola": r"^active",
        "kenapa": "Tanpa firewall, setiap layanan yang kebetulan mendengarkan "
                  "terbuka bagi siapa pun yang bisa mencapai mesin ini. "
                  "Layanan yang dipasang untuk uji coba lalu dilupakan adalah "
                  "cara paling lazim sebuah mesin terbuka tanpa ada yang tahu.",
        "perbaikan": "sudo ufw default deny incoming\nsudo ufw enable",
    },
    {
        "id": "linux_uid0",
        "judul": "Ada akun ber-UID 0 selain root",
        "platform": "linux",
        "keparahan": TINGGI,
        "cara": "tidak_boleh_ada",
        "dalam": r"^### akun-uid0",
        # Anything other than `root` in this section is a finding.
        "pola": r"^(?!root$)\S+",
        "kenapa": "UID 0 ADALAH root, apa pun namanya. Akun kedua ber-UID 0 "
                  "memberi hak penuh lewat nama yang tidak diawasi siapa pun, "
                  "dan itu bentuk pintu belakang yang paling sering luput "
                  "karena tidak terlihat mencurigakan di daftar akun.",
        "perbaikan": "sudo usermod -u <uid baru> <akun>",
    },
    {
        "id": "linux_pembaruan",
        "judul": "Ada pembaruan keamanan yang belum dipasang",
        "platform": "linux",
        "keparahan": SEDANG,
        "cara": "tidak_boleh_ada",
        "dalam": r"^### pembaruan-keamanan-tertunda",
        "pola": r"^[1-9]\d*$",
        "kenapa": "Kelemahan yang sudah ada tambalannya jauh lebih mudah "
                  "dipakai daripada yang belum, karena rinciannya sudah "
                  "diterbitkan bersama tambalannya. Mesin yang tertinggal "
                  "pembaruan justru menjadi sasaran yang lebih mudah setelah "
                  "tambalannya keluar, bukan sebelumnya.",
        "perbaikan": "sudo apt update && sudo apt upgrade",
    },
    {
        "id": "linux_x11",
        "judul": "X11Forwarding menyala",
        "platform": "linux",
        "keparahan": RENDAH,
        "cara": "tidak_boleh_ada",
        "dalam": r"^### sshd",
        "pola": r"^X11Forwarding\s+yes",
        "kenapa": "X11 forwarding membuka jalur dari server ke tampilan "
                  "klien, dan server yang sudah dikuasai bisa memakainya "
                  "untuk membaca tombol yang ditekan di sisi klien. Pada "
                  "server tanpa antarmuka grafis, ia menambah jalur tanpa "
                  "menambah kegunaan apa pun.",
        "perbaikan": "X11Forwarding no",
    },
]

PETA_KATALOG = {a["id"]: a for a in KATALOG}


def daftar_aturan(platform=None):
    if platform is None:
        return list(KATALOG)
    return [a for a in KATALOG if a["platform"] == platform]


# ===========================================================================
# Penilai
# ===========================================================================
def _cari(teks, aturan):
    """Search for a rule's pattern. Returns `(ditemukan, nomor_baris, baris)`.

    If `dalam` is given, the search is limited to blocks whose title matches. If that block
    does NOT EXIST the result is `(None, None, None)`, and the distinction matters: a rule
    like "line aux must have no exec" on a device with no `line aux` at all is not a finding,
    it is not applicable.
    """
    pola = re.compile(aturan["pola"], re.IGNORECASE)
    dalam = aturan.get("dalam") or ""

    if not dalam:
        for n, line in baris_semua(teks):
            if pola.search(line.strip()):
                return True, n, line.strip()
        return False, None, None

    pattern_block = re.compile(dalam, re.IGNORECASE)
    nomor = {}
    for n, line in baris_semua(teks):
        nomor.setdefault(line.rstrip(), n)

    ada_bloknya = False
    for judul, content in pecah_blok(teks):
        if not pattern_block.search(judul):
            continue
        ada_bloknya = True
        for line in content:
            if pola.search(line):
                cocok = [k for k in nomor if k.strip() == line]
                return True, (nomor[cocok[0]] if cocok else None), line
    if not ada_bloknya:
        return None, None, None
    return False, None, None


def nilai_satu(teks, aturan, platform):
    if platform != aturan["platform"]:
        return {"aturan_id": aturan["id"], "hasil": TIDAK_BERLAKU,
                "keparahan": aturan["keparahan"],
                "baris_bukti": None, "nomor_baris": None}

    exists, nomor, line = _cari(teks, aturan)

    if exists is None:
        return {"aturan_id": aturan["id"], "hasil": TIDAK_BERLAKU,
                "keparahan": aturan["keparahan"],
                "baris_bukti": None, "nomor_baris": None}

    if aturan.get("pola_alternatif") and not exists:
        alt = re.compile(aturan["pola_alternatif"], re.IGNORECASE)
        for n, b in baris_semua(teks):
            if alt.search(b.strip()):
                return {"aturan_id": aturan["id"], "hasil": PATUH,
                        "keparahan": aturan["keparahan"],
                        "baris_bukti": b.strip(), "nomor_baris": n}

    if aturan["cara"] == "tidak_boleh_ada":
        hasil = TEMUAN if exists else PATUH
    else:
        hasil = PATUH if exists else TEMUAN

    return {
        "aturan_id": aturan["id"],
        "hasil": hasil,
        "keparahan": aturan["keparahan"],
        # Evidence is stored only if the line was actually found. For a `harus_ada` rule that
        # becomes a finding, what proves it is the ABSENCE of a line, so there is none to point at.
        "baris_bukti": line if exists else None,
        "nomor_baris": nomor if exists else None,
    }


def nilai(teks, platform):
    """Evaluate the WHOLE catalog against one snapshot.

    Returns one result per rule, including `TIDAK_BERLAKU`. Inapplicable rules are returned
    on purpose so the page can say how many rules were not checked, instead of silently
    dropping them from the count.
    """
    return [nilai_satu(teks, a, platform) for a in KATALOG]


def ringkas(hasil):
    """Count per severity, not a single percentage, on purpose.

    "R1 is 78% compliant" is rejected because it adds up unlike things: open telnet and a
    missing banner are not one-twelfth of the same problem. Returns three numbers that
    cannot cover for each other.
    """
    r = {TINGGI: 0, SEDANG: 0, RENDAH: 0,
         "patuh": 0, "tidak_berlaku": 0, "temuan": 0}
    for h in hasil:
        if h["hasil"] == TEMUAN:
            r["temuan"] += 1
            r[h["keparahan"]] += 1
        elif h["hasil"] == PATUH:
            r["patuh"] += 1
        else:
            r["tidak_berlaku"] += 1
    return r

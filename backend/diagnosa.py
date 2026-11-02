"""Automatic diagnosis when a service has a problem, with suggested actions.

When a service outage opens, NSM logs into the device over SSH, runs a few
commands, and attaches the output to the event row. When the outage closes, the
same is repeated once more. Two snapshots, so before and after can be compared.

Why two: the snapshot at outage start captures evidence that disappears once the
service is restarted (e.g. the last lines of the error log). The snapshot at
recovery shows what changed. With only one you have a crime-scene photo without
the aftermath, or the reverse.

ALL COMMANDS HERE ARE READ-ONLY. NONE CHANGES ANYTHING ON THE DEVICE.

This is deliberate, not a limitation. NSM may LOOK as deeply as it can but must
not FIX things itself:

- A service that died from a full disk would be restarted over and over, each
  round hiding the real cause.
- A restart wipes in-memory traces, which is exactly the evidence you need if
  someone else caused the outage.
- If a real device is ever added to the list, one wrong target would take down
  a live service.

Writing to devices is a separate path (`kirim_perintah.py`) that requires
explicit approval; this file deliberately does not touch it.
"""
import re

import dialek_perangkat

# Check commands per service type. Read-only throughout.
#
# `--no-pager` is mandatory for systemctl: without it the output goes into `less`
# and the SSH session hangs waiting for a keypress that never comes (a classic
# mistake when running systemctl from scripts).
PERINTAH_UMUM = {
    "Waktu hidup & beban": "uptime",
    "Sisa disk": "df -h /",
    "Memori": "free -h",
}

PERINTAH_PER_LAYANAN = {
    "http": {
        "Status Apache": "systemctl status apache2 --no-pager -l 2>&1 | head -20",
        "Yang mendengarkan di port web": "ss -tlnp 2>/dev/null | grep -E ':(80|443)\\s' || echo 'TIDAK ADA yang mendengarkan di port 80/443'",
        "Log galat Apache terakhir": "tail -n 20 /var/log/apache2/error.log 2>/dev/null || echo '(log tidak terbaca)'",
    },
    "mysql": {
        "Status MySQL": "systemctl status mysql --no-pager -l 2>&1 | head -20",
        "Yang mendengarkan di port database": "ss -tlnp 2>/dev/null | grep ':3306\\s' || echo 'TIDAK ADA yang mendengarkan di port 3306'",
        "Log galat MySQL terakhir": "tail -n 20 /var/log/mysql/error.log 2>/dev/null || echo '(log tidak terbaca)'",
    },
    "tcp": {
        "Semua port yang mendengarkan": "ss -tlnp 2>/dev/null | head -20",
    },
}

# Suggested actions per cause category. Written as sentences saying WHAT to check
# and WHY, rather than commands to paste without understanding.
SARAN = {
    "koneksi_ditolak": (
        "Mesinnya sehat dan jaringannya sampai, jadi periksa layanannya di "
        "device itu. Mulai dari `systemctl status {unit}`; kalau tertulis "
        "inactive atau failed, baca baris terakhirnya, di situ biasanya "
        "sebabnya tertulis. Periksa juga sisa disk, layanan yang kehabisan "
        "ruang tulis sering berhenti tanpa pesan yang jelas."
    ),
    "timeout": (
        "Tidak ada yang menjawab sama sekali, jadi masalahnya di jalur, bukan "
        "di layanan. Periksa firewall device (`ufw status`), lalu pastikan "
        "port {port} memang diizinkan. Kalau firewall mati dan tetap tidak "
        "menjawab, kemungkinan device sedang terlalu sibuk untuk menerima "
        "koneksi baru."
    ),
    "host_tak_terjangkau": (
        "Tidak ada rute ke alamat itu. Periksa apakah VM-nya menyala dan "
        "apakah adapter Host-only-nya masih memegang alamat yang benar "
        "(`ip -br addr` di dalam VM). Alamat yang berubah diam-diam adalah "
        "sebab tersering."
    ),
    "http_5xx": (
        "Server web hidup tetapi aplikasinya gagal. Baca log galat Apache di "
        "bagian diagnosa di bawah, di situ biasanya tertulis baris kode atau "
        "koneksi database yang gagal. Periksa juga apakah layanan MySQL yang "
        "dipakai halaman ini sedang bermasalah."
    ),
    "http_4xx": (
        "Server web sehat, yang salah alamat halaman yang dipantau. Pastikan "
        "berkasnya benar-benar ada di device, atau perbaiki path layanan ini "
        "di NSM supaya menunjuk halaman yang tepat."
    ),
    "isi_tak_cocok": (
        "Halaman terbuka dan berkode normal, tetapi teks penandanya hilang. "
        "Ini pola khas halaman galat yang tetap dikirim dengan kode 200. Buka "
        "halamannya langsung di peramban untuk melihat apa yang sebenarnya "
        "tampil."
    ),
    "mysql_bukan_mysql": (
        "Ada program yang mendengarkan di port itu tetapi bukan MySQL. "
        "Periksa `ss -tlnp` di device untuk tahu program apa yang memakainya. "
        "Kalau kamu tidak mengenali programnya, perlakukan ini sebagai temuan "
        "keamanan, bukan sekadar salah konfigurasi."
    ),
    "http_tak_terduga": (
        "Kode status di luar yang diharapkan. Periksa apakah ada pengalihan "
        "(redirect) yang baru dipasang di konfigurasi web server."
    ),
    "gagal_lain": (
        "Sebabnya tidak dikenali NSM. Bagian diagnosa di bawah berisi keadaan "
        "device saat kejadian; mulailah dari sana."
    ),
}

# systemd unit name per service type, for use in the advice sentences.
UNIT = {"http": "apache2", "mysql": "mysql", "tcp": "layanan terkait"}


def susun_saran(kategori, jenis, port):
    """Suggested-action sentence. Always returns text, never None."""
    pattern = SARAN.get(kategori)
    if not pattern:
        return ("Belum ada saran khusus untuk sebab ini. Bagian diagnosa di "
                "bawah berisi keadaan device saat kejadian.")
    return pattern.format(unit=UNIT.get(jenis, "layanan terkait"), port=port or "-")


def perintah_untuk(jenis):
    """Set of read-only commands to run for this service type."""
    perintah = {}
    perintah.update(PERINTAH_PER_LAYANAN.get(jenis, PERINTAH_PER_LAYANAN["tcp"]))
    perintah.update(PERINTAH_UMUM)
    return perintah


# Last line of defense. Every command in this file is already read-only, but this
# list keeps a dangerous command from slipping in through a careless later edit.
# If anything matches, the command is NOT run.
#
# A separate layer because the author's good intentions guard nothing six months
# from now.
TERLARANG = re.compile(
    r"\b(rm|mv|dd|mkfs|shutdown|reboot|kill|pkill|chmod|chown|truncate|tee)\b"
    r"|systemctl\s+(start|stop|restart|reload|enable|disable|mask)"
    # Any remaining ">" after the safe redirections are removed in `aman()`.
    # Deliberately rigid: guessing the intent of a redirection is hard, and no READ
    # command needs to write to a file.
    r"|>",
    re.IGNORECASE,
)

# Two redirection forms that write nothing to a file, so they are removed before
# the command is checked:
#
#   2>/dev/null   discard errors (/dev/null is a sink, not a file)
#   2>&1          merge errors into normal output
#
# Needed because the pattern ">\s*/" would otherwise also catch "2>/dev/null",
# rejecting half of the built-in diagnostic commands and leaving the diagnosis
# nearly empty with no visible reason.
_PENGALIHAN_AMAN = re.compile(r"\d?>>?\s*(?:/dev/null|&\d)")


def aman(perintah):
    """True if this command only reads."""
    return not TERLARANG.search(_PENGALIHAN_AMAN.sub(" ", perintah))


def jalankan(device, jenis, timeout=10):
    """Run the diagnosis on the device; return display-ready text.

    Never raises: a failed diagnosis must not break incident recording. An incident
    recorded without diagnosis is far more useful than one lost because SSH had a
    problem.
    """
    # NETWORK devices (router/switch) do not run the shell commands in
    # `perintah_untuk()`. This asks `akses.jenis` from the definition file rather
    # than testing `platform == "cisco_ios"`, so the rejected set covers every
    # network vendor (MikroTik, Junos, EOS, VRP, FortiOS), none of which would answer
    # shell commands.
    #
    # Devices of kind `host` (linux, windows, local) pass as before; devices without
    # a platform are still rejected.
    if (not device.platform
            or dialek_perangkat.ambil(device.platform).akses.get("jenis")
               == "jaringan"):
        return ("Diagnosa otomatis hanya tersedia untuk device Linux. "
                f"Device ini berplatform {device.platform or 'kosong'}.")
    if not (device.username and device.password):
        return ("Diagnosa otomatis dilewati: device ini tidak punya kredensial "
                "SSH di NSM.")

    perintah = {k: v for k, v in perintah_untuk(jenis).items() if aman(v)}
    if not perintah:
        return "Tidak ada perintah yang lolos pemeriksaan keamanan."

    try:
        from connectors.ssh import SshConnector
        conn = SshConnector(device.ip_address, platform=device.platform,
                            username=device.username, password=device.password,
                            key_path=getattr(device, "ssh_key_path", None))
        hasil = conn._exec_info(perintah, timeout=timeout)
    except Exception as e:
        # This failure is itself valuable information: if SSH cannot get in either, more
        # than one service is in trouble.
        return ("Diagnosa gagal dijalankan: SSH ke device ini tidak berhasil "
                f"({e}). Perlu dicatat: kalau SSH ikut tidak bisa masuk, "
                "kemungkinan yang bermasalah mesinnya secara keseluruhan, "
                "bukan hanya layanan yang dipantau.")

    section = []
    for label, output in hasil.items():
        teks = (output or "").strip() or "(kosong)"
        section.append(f"### {label}\n{teks}")
    return "\n\n".join(section)


def build_evidence(ip, ping_ok, ping_ms, port_lain,
                port_layanan=None, port_layanan_ok=None, diharapkan=None):
    """Layered evidence chain, shown on the incident card.

    This is what lets the card answer "why", not just "what": the reader sees which
    layer is healthy and which failed, and can conclude where the problem lies.

    1. The service's own port is named, and named first. Evidence that does not
       cover the thing in question is not evidence.

    2. A port that was never installed is not flagged red. Port 443 on a server that
       never ran HTTPS is always closed, and a red cross would suggest a second
       problem. `diharapkan` holds the ports that have a registered service on that
       device; ports outside it are marked neutral, with the reason.

    `port_layanan_ok` here means "something is listening on that port", NOT "the
    service is healthy". Apache returning 500 for every request still leaves port 80
    open; the gap between the two facts is what separates a dead process from one
    that is broken inside.
    """
    diharapkan = diharapkan or set()
    line = []
    if ping_ok:
        ms = f"{ping_ms:.2f} ms" if ping_ms is not None else "-"
        line.append(f"OK|Ping menjawab ({ms}), mesinnya hidup")
    else:
        line.append("GAGAL|Ping tidak menjawab, mesinnya tidak terjangkau")

    if port_layanan is not None and port_layanan_ok is not None:
        if port_layanan_ok:
            line.append(f"OK|Port {port_layanan} (port layanan ini) masih "
                         "menerima koneksi, jadi prosesnya belum mati")
        else:
            line.append(f"GAGAL|Port {port_layanan} (port layanan ini) menolak "
                         "koneksi, tidak ada yang mendengarkan di sana")

    for port, opened in sorted(port_lain.items()):
        if opened:
            line.append(f"OK|Port {port} menjawab")
        elif port in diharapkan:
            line.append(f"GAGAL|Port {port} tidak menjawab")
        else:
            # Neutral, not a failure. A red mark for something that never existed is a
            # reading disturbance, not evidence.
            line.append(f"INFO|Port {port} tertutup, dan memang tidak ada "
                         "layanan terdaftar di port itu")
    return "\n".join(line)


def simpulkan(ping_ok, port_layanan_ok, port_lain, port_terbuka=None):
    """One-sentence conclusion from the evidence chain.

    If ping is alive and ANOTHER port answers but this service's port does not, the
    machine and network are proven healthy and the service itself is what died. That
    cannot be concluded from ping alone, which is the whole point of layered checks.

    `port_layanan_ok`: the service answered CORRECTLY.
    `port_terbuka`: something is listening on the port (may be None if not
    checked). They are different things, and separating them allows a conclusion
    that could not be expressed before: a process that is alive but broken inside.
    """
    exists_port_other = any(port_lain.values())
    if not ping_ok and not exists_port_other:
        return ("Mesinnya sendiri tidak menjawab apa pun. Ini gangguan device, "
                "bukan gangguan layanan.")
    if not port_layanan_ok and port_terbuka:
        return ("Port layanannya masih menerima koneksi, tetapi jawabannya tidak "
                "sesuai yang diharapkan. Prosesnya hidup dan rusak di dalam, "
                "bukan mati. Memulai ulang layanan biasanya menutupi gejalanya "
                "tanpa menyentuh sebabnya, jadi periksa lognya lebih dulu.")
    if ping_ok and exists_port_other and not port_layanan_ok:
        return ("Mesin dan jaringannya terbukti sehat karena ping dan port lain "
                "tetap menjawab. Yang berhenti benar-benar layanan ini.")
    if ping_ok and not exists_port_other and not port_layanan_ok:
        return ("Ping menjawab tetapi tidak satu pun port TCP menjawab. Mesinnya "
                "hidup, tetapi kemungkinan sedang kewalahan atau ada firewall "
                "yang memblokir seluruh port.")
    if not ping_ok and exists_port_other:
        return ("Ping diblokir tetapi port TCP tetap menjawab, jadi mesinnya "
                "hidup. Jangan membaca kegagalan ping di sini sebagai device mati.")
    return "Layanan menjawab dengan benar."

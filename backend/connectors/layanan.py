"""SERVICE checker: answers "is the service actually serving", not just "is the machine on".

`connectors/tcp.py` can open connections, but it is used to guess the cause when ping
fails and only says open or not. Here checks are LAYERED, and the layer that fails is the
diagnosis:

    ICMP   is the machine up?                 -> done by the poller
    TCP    is anything listening on the port? -> cek_tcp
    HTTP   is the answer correct?             -> cek_http
    MySQL  is the responder really MySQL?     -> cek_mysql

Connection refused and timeout are NOT the same failure:

    refused  something answered "this port is closed". Machine and network are fine,
             the application is down. Fix it on the device.
    timeout  no answer at all. The packet was dropped silently on the way, usually by
             a firewall. Fix it in the network.

Misreading these two means looking in the wrong place, which is costly in an emergency.

Every check in this file is READ-ONLY and uses only the Python standard library.
"""
import http.client
import socket
import struct
import time

# Cause categories. Used by the poller, reports, and incident cards, so defined once here
# so the three never name them differently.
DITOLAK = "koneksi_ditolak"
TIMEOUT = "timeout"
TAK_TERJANGKAU = "host_tak_terjangkau"
HTTP_5XX = "http_5xx"
HTTP_4XX = "http_4xx"
HTTP_LAIN = "http_tak_terduga"
ISI_TAK_COCOK = "isi_tak_cocok"
BUKAN_MYSQL = "mysql_bukan_mysql"
TERPUTUS = "koneksi_terputus"
GAGAL_LAIN = "gagal_lain"
PULIH = "pulih"

# Shortest timeout allowed. Not a matter of taste.
#
# A refused connection does not always arrive instantly. Measured on Windows: a connection
# to a closed port on 127.0.0.1 was answered "refused" only after 2007 ms, because Windows
# retries SYN before giving up. With a 2.0 s timeout the socket stopped waiting 7 ms BEFORE
# the refusal arrived and reported "timeout", the opposite of what this feature is for: the
# reader is told to check the firewall when the service is what is down. So the timeout has
# a floor, taken from measurement rather than guessed.
TIMEOUT_MINIMUM = 3.0

# Human-readable cause sentences, keyed like the categories above. They explain what the
# category MEANS rather than repeating its name: "connection refused" tells nothing to
# someone who does not already know.
TEKS_SEBAB = {
    DITOLAK: ("Port menolak koneksi. Mesinnya hidup dan jaringannya sampai, "
              "tetapi tidak ada program yang mendengarkan di port itu. "
              "Layanannya berhenti, bukan servernya."),
    TIMEOUT: ("Tidak ada jawaban sama sekali sampai batas waktu habis. "
              "Paketnya kemungkinan dibuang diam-diam oleh firewall, atau "
              "device terlalu sibuk untuk menjawab. Bedanya dengan koneksi "
              "ditolak: di sini tidak ada yang menjawab apa pun, jadi yang "
              "perlu diperiksa jalur jaringannya, bukan layanannya."),
    TAK_TERJANGKAU: ("Tidak ada rute menuju alamat itu. Ini masalah jaringan "
                     "atau alamatnya salah, bukan masalah layanan."),
    HTTP_5XX: ("Server web menjawab, tetapi melaporkan dirinya sendiri "
               "bermasalah. Layanannya hidup dan rusak di dalam, biasanya "
               "aplikasi atau database di belakangnya."),
    HTTP_4XX: ("Server web menjawab, tetapi halaman yang dipantau tidak ada "
               "atau ditolak. Servernya sehat; yang salah alamat halamannya "
               "atau izin aksesnya."),
    HTTP_LAIN: "Server web menjawab dengan kode status di luar yang diharapkan.",
    ISI_TAK_COCOK: ("Halaman terbuka dengan kode status benar, tetapi isinya "
                    "bukan yang diharapkan. Halaman bisa saja tampil sebagai "
                    "halaman galat yang tetap berkode 200."),
    BUKAN_MYSQL: ("Ada yang mendengarkan di port itu, tetapi sapaan pembukanya "
                  "bukan sapaan MySQL. Port itu dipakai program lain."),
    TERPUTUS: ("Koneksi diterima lalu diputus sebelum ada jawaban. Ini bukan "
               "ditolak dan bukan pula timeout: ada yang menjawab di port itu, "
               "tetapi menutup sambungan di tengah jalan. Sebab yang lazim: "
               "layanan sedang memuat ulang worker-nya, proses pelayannya mati "
               "saat menangani permintaan, atau kehabisan sumber daya."),
    GAGAL_LAIN: "Pemeriksaan gagal karena sebab yang tidak dikenali.",
}


# NEXT STEPS: the runbook attached to each incident
#
# `TEKS_SEBAB` above answers "what does it mean". It does not answer the more urgent
# question that follows: "so what do I do?". Without that, the incident page is useful only
# to people who already know the answer, and the person reading the screen during an
# outage is often the least experienced, because outages do not wait for working hours.
#
# Written as DATA, like the compliance rules, so "what steps does NSM suggest" has an
# answer on screen that can be checked instead of being spread through code.
#
# The shape is uniform on purpose: inspect first, change later. Each list starts with
# commands that only READ. A runbook whose first step is "restart the service" teaches a
# habit that destroys evidence before anyone sees it.
LANGKAH = {
    DITOLAK: [
        "systemctl status <layanan>   — masih jalan atau sudah berhenti?",
        "journalctl -u <layanan> -n 50 --no-pager   — kenapa ia berhenti",
        "ss -tlnp | grep <port>   — benar tidak ada yang mendengarkan?",
    ],
    TIMEOUT: [
        "ping <alamat>   — mesinnya sendiri masih menjawab?",
        "sudo ufw status numbered   — port ini masih diizinkan?",
        "traceroute <alamat>   — paketnya berhenti di lompatan ke berapa",
    ],
    TAK_TERJANGKAU: [
        "ip route   — ada rute menuju jaringan itu?",
        "periksa ACL di router antara sini dan sana",
        "kalau lintas lokasi: lihat halaman Firewall, bagian penolakan ACL",
    ],
    HTTP_5XX: [
        "buka halamannya sendiri di peramban — pesan galatnya apa",
        "tail -50 /var/log/apache2/error.log   (atau log aplikasinya)",
        "periksa basis data yang dipakainya — 5xx paling sering berasal "
        "dari belakang, bukan dari web servernya",
    ],
    HTTP_4XX: [
        "benarkah alamat halaman yang dipantau masih ada?",
        "kalau 403: periksa izin berkas dan aturan akses",
        "kalau 404: halamannya mungkin dipindah, perbarui path di Layanan",
    ],
    HTTP_LAIN: [
        "curl -i <alamat>   — lihat kode dan kepala jawabannya apa adanya",
        "kode 3xx berarti dialihkan; mungkin path-nya perlu diperbarui",
    ],
    ISI_TAK_COCOK: [
        "curl -s <alamat> | head -40   — apa yang sebenarnya keluar",
        "halaman galat yang tetap berkode 200 adalah sebab paling lazim",
        "kalau isinya memang sengaja berubah, perbarui `harap_teks` di Layanan",
    ],
    BUKAN_MYSQL: [
        "ss -tlnp | grep <port>   — program apa yang memakai port itu",
        "port itu mungkin diambil program lain setelah MySQL gagal menyala",
        "systemctl status mysql",
    ],
    TERPUTUS: [
        "journalctl -u <layanan> -n 50   — cari OOM atau worker yang mati",
        "free -m   — kehabisan memori adalah sebab yang paling sering",
        "kalau baru saja dimuat ulang, tunggu satu putaran lalu lihat lagi",
    ],
    GAGAL_LAIN: [
        "baca kolom bukti di kartu gangguan ini apa adanya",
        "ulangi pemeriksaannya secara manual dengan perintah yang sama",
    ],
}

# What to do if the steps above leave you stuck. Listed separately on purpose: giving up
# early with complete notes beats trying things until the evidence is erased.
KALAU_BUNTU = ("Salin kalimat sebab, bukti, dan potret diagnosa di kartu ini, "
               "lalu teruskan. Jangan menyalakan ulang layanannya lebih dulu — "
               "itu menghapus bukti yang dibutuhkan untuk mencari sebabnya.")


def langkah(kategori):
    return LANGKAH.get(kategori, LANGKAH[GAGAL_LAIN])


def teks_sebab(kategori):
    """Explanatory sentence for a category. Never returns None."""
    if not kategori:
        return "Sebab tidak diketahui."
    return TEKS_SEBAB.get(kategori, "Sebab tidak diketahui.")


def _golongkan_error(exc):
    """Translate a socket error into a category meaningful to humans.

    errno numbers differ between Windows and Linux, so the Python exception class is used
    first: `ConnectionRefusedError` and `socket.timeout` are normalized by Python on both
    systems, and they are the two that matter most.
    """
    if isinstance(exc, ConnectionRefusedError):
        return DITOLAK
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return TIMEOUT
    # Accepted then dropped. Different from both refused and timeout, so it has its own
    # category. Web service registration failed INTERMITTENTLY with "unrecognized cause" while
    # a browser opened the same page fine; a catch-all category that explains nothing is the
    # quickest way to make people blame the wrong part.
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError,
                        http.client.RemoteDisconnected,
                        http.client.IncompleteRead,
                        http.client.BadStatusLine)):
        return TERPUTUS
    if isinstance(exc, socket.gaierror):
        return TAK_TERJANGKAU
    if isinstance(exc, OSError):
        # WSAEHOSTUNREACH 10065 / WSAENETUNREACH 10051 on Windows,
        # EHOSTUNREACH 113 / ENETUNREACH 101 on Linux.
        if getattr(exc, "winerror", None) in (10051, 10065):
            return TAK_TERJANGKAU
        if exc.errno in (101, 113):
            return TAK_TERJANGKAU
        # Windows sometimes reports a timeout as OSError 10060 instead of `socket.timeout`,
        # depending on the connection stage when the limit was reached.
        if getattr(exc, "winerror", None) == 10060 or exc.errno == 110:
            return TIMEOUT
    return GAGAL_LAIN


def _batas(timeout):
    """Apply the timeout floor. See TIMEOUT_MINIMUM for the measured reason."""
    try:
        return max(TIMEOUT_MINIMUM, float(timeout or 0))
    except (TypeError, ValueError):
        return TIMEOUT_MINIMUM


def _hasil(ok, kategori=None, kode=None, waktu_ms=None, detail=None):
    return {
        "ok": ok,
        "kategori": kategori,
        "kode": kode,
        "waktu_ms": waktu_ms,
        "detail": detail or (teks_sebab(kategori) if not ok else None),
    }


def check_tcp(ip, port, timeout=5.0):
    """Prove that something is listening on a port.

    The cheapest check that still means something: one TCP handshake, no data sent. Suited
    to services with no polite way to be queried, such as SSH.
    """
    timeout = _batas(timeout)
    start = time.time()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return _hasil(True, waktu_ms=round((time.time() - start) * 1000, 2))
    except Exception as e:
        return _hasil(False, _golongkan_error(e), detail=None)
    finally:
        s.close()


def check_http(ip, port=80, path="/", timeout=5.0, harap_status=200,
             harap_teks=None):
    """Request a page, then check the status code and the content.

    The content is checked too because a broken application often still answers 200 while
    showing an error page. The status code alone can lie; a required piece of text cannot.
    """
    timeout = _batas(timeout)
    start = time.time()
    conn = None
    try:
        conn = http.client.HTTPConnection(ip, port, timeout=timeout)
        conn.request("GET", path or "/", headers={
            # Identify itself politely: whoever reads the server's access log must be able to tell
            # this request came from the monitor, not from a real visitor or a scanner.
            "User-Agent": "NSM-Monitor/1.0 (Network Status Monitor)",
            "Connection": "close",
        })
        resp = conn.getresponse()
        # Capped so a huge page cannot eat the poller's memory. 64 KB is more than enough to check
        # for a marker text.
        content = resp.read(65536)
        waktu = round((time.time() - start) * 1000, 2)
        kode = resp.status

        expected = harap_status or 200
        if kode != expected:
            if 500 <= kode <= 599:
                kategori = HTTP_5XX
            elif 400 <= kode <= 499:
                kategori = HTTP_4XX
            else:
                kategori = HTTP_LAIN
            return _hasil(
                False, kategori, kode=kode, waktu_ms=waktu,
                detail=f"{teks_sebab(kategori)} Kode yang diterima {kode}, "
                       f"yang diharapkan {expected}.")

        if harap_teks:
            try:
                teks = content.decode("utf-8", errors="replace")
            except Exception:
                teks = ""
            if harap_teks not in teks:
                return _hasil(
                    False, ISI_TAK_COCOK, kode=kode, waktu_ms=waktu,
                    detail=f"{teks_sebab(ISI_TAK_COCOK)} Teks penanda "
                           f"\"{harap_teks}\" tidak ditemukan di halaman.")

        return _hasil(True, kode=kode, waktu_ms=waktu)
    except Exception as e:
        return _hasil(False, _golongkan_error(e))
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def check_mysql(ip, port=3306, timeout=5.0):
    """Prove that whatever listens on the port really is MySQL.

    It reads the server greeting MySQL sends right after the connection opens, without ever
    logging in. Packet shape: 3 bytes length, 1 byte sequence number, 1 byte protocol version
    (10 for modern MySQL), then the server version as text ending in a zero byte.

    Why not just `cek_tcp`: an open port 3306 only proves some program is there. Reading the
    greeting proves it is MySQL and ready to serve.

    Deliberately does NOT log in and sends no queries. The data-ownership boundary of the
    project still holds: Python monitors, it does not read anyone's database contents.
    """
    timeout = _batas(timeout)
    start = time.time()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        header = s.recv(4)
        if len(header) < 4:
            return _hasil(False, BUKAN_MYSQL,
                          detail="Koneksi terbuka tetapi tidak ada sapaan pembuka.")
        length = struct.unpack("<I", header[:3] + b"\x00")[0]
        body = s.recv(min(length, 512))
        waktu = round((time.time() - start) * 1000, 2)

        if not body:
            return _hasil(False, BUKAN_MYSQL, waktu_ms=waktu,
                          detail="Koneksi terbuka tetapi tidak ada jawaban.")

        # 0xFF = MySQL ERROR packet, and it still proves MySQL is alive.
        #
        # A tightly locked server rejects unregistered hosts BEFORE the handshake, so an error
        # packet arrives instead of a greeting. Treating that as "not MySQL" would report EVERY
        # correctly configured database as wrong; the rejection is a sign of good configuration.
        #
        # Packet shape: 0xFF, 2 bytes error code, then the message.
        if body[0] == 0xFF:
            kode = struct.unpack("<H", body[1:3])[0] if len(body) >= 3 else 0
            message = body[3:].decode("utf-8", errors="replace").strip()
            return _hasil(True, waktu_ms=waktu,
                          detail=(f"MySQL hidup dan menjawab, tetapi menolak "
                                  f"alamat ini (galat {kode}). Itu wajar kalau "
                                  f"hanya host tertentu yang diizinkan. "
                                  f"Pesan server: {message[:140]}"))

        if body[0] != 10:
            return _hasil(False, BUKAN_MYSQL, waktu_ms=waktu)

        end = body.find(b"\x00", 1)
        version = body[1:end].decode("utf-8", errors="replace") if end > 1 else "?"
        return _hasil(True, waktu_ms=waktu,
                      detail=f"MySQL menjawab, versi server {version}.")
    except Exception as e:
        return _hasil(False, _golongkan_error(e))
    finally:
        s.close()


def periksa(jenis, ip, port, path=None, timeout=5.0, harap_status=None,
            harap_teks=None):
    """Single entry point for the poller: picks the checker by service type."""
    limit = _batas(timeout or 5.0)
    if jenis == "http":
        return check_http(ip, port or 80, path or "/", limit, harap_status,
                        harap_teks)
    if jenis == "mysql":
        return check_mysql(ip, port or 3306, limit)
    return check_tcp(ip, port, limit)

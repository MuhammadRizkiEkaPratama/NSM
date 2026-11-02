"""Packet capture for PLAIN HTTP: reads what the access log cannot, the request BODY,
including files UPLOADED through the web.

WHY IT EXISTS, AND ITS DELIBERATE LIMITS. `akses_web` (from the Apache access log) answers
"who requested which page" but is blind to what the CLIENT sent to the server. The access
log is written after the request finishes and never stores the body, so "someone uploaded a
file" can never be proven from it, only estimated from `byte_terima` when `mod_logio` is on.

Real capture (`dumpcap` + `tshark`) reads the request body, so an uploaded file's name is
read with CERTAINTY from the packet, not guessed.

THE SCOPE IS NARROW ON PURPOSE. This is a line that must not be crossed, not a limitation
not yet closed:

    captured:  PLAIN HTTP on ONE interface, ONE port (the web app on :8080)
    NOT:       SSH, LDAP (StartTLS), MySQL replication (TLS). All are encrypted ON
               PURPOSE so that nobody capturing can see their content. Reading them
               would mean breaking the TLS itself (a MITM certificate on every client),
               and a monitoring tool that cancels the protections it helped build is
               not a fix; it is a new hole where one was closed tight.

READ-ONLY, AND NO ROOT NEEDED. `dumpcap` already has the `cap_net_raw`/`cap_net_admin`
capabilities, and the `nsmro` account only needs to join the `wireshark` group once. No
write permission is added to any device. Capturing is still READING.

THIS IS A PERIODIC SNAPSHOT, NOT A FULL RECORDING. Capture runs in a window of a few
seconds each round, not continuously. Traffic between two windows is missed, the same limit
as `flow_koneksi`, and the screen says so.

Only POST/PUT/PATCH (requests that CARRY a body) are stored. GET is already fully recorded
in the access log; storing it again would only duplicate data. What this table adds is the
part the access log is blind to: content sent to the server.
"""
import binascii
import hashlib
import re
from datetime import datetime

# Interface and port captured. The lab (host-only) interface on the web server, not enp0s3
# (NAT), which does not carry the web app's traffic from the client machine.
IFACE = "enp0s8"
PORT = 8080

# Field separator for tshark output. '~' was chosen because it never appears in IP
# addresses, methods, URIs, or content-types, so it cannot be confused with the data itself.
PEMISAH = "~"

# Fields requested from tshark, IN ORDER. Changing the order here MUST be matched in
# `urai()`; the two are kept close together on purpose.
FIELDS = [
    "frame.time_epoch",       # 0  kapan
    "ip.src",
    "http.request.method",    # 2  POST/PUT/GET/...
    "http.request.uri",
    "http.content_type",      # 4  jenis badan
    "http.content_length",    # 5  besar badan
    "http.file_data",         # 6  ISI badan, heksadesimal
]

METODE_BERBADAN = {"POST", "PUT", "PATCH"}

# File name from the Content-Disposition header inside the multipart body.
# Example matched: filename="report.pdf"
_POLA_NAMA = re.compile(rb'filename="([^"]+)"')


def perintah(iface=IFACE, port=PORT, durasi=50):
    """tshark command that captures HTTP on one port for `durasi` seconds.

    The leading `timeout` KILLS tshark when time runs out, so no process is left hanging on the
    server if NSM forgets to stop it, the same pattern as `simulasi_serangan.py`: a capture
    that runs on with nobody telling it to stop is an orphan process waiting to be forgotten.

    `-Y http.request`: requests only, not responses. `-T fields`: structured output instead of
    free text whose format would have to be guessed.
    """
    fetch = " ".join("-e " + f for f in FIELDS)
    return (
        f"timeout {int(durasi)} tshark -i {iface} -f 'tcp port {int(port)}' "
        f"-Y http.request -T fields -E separator='{PEMISAH}' {fetch} "
        f"2>/dev/null"
    )


def _nama_berkas(hex_data):
    """Find the file name in a captured multipart body (hex). None if it is not a file upload
    (e.g. an ordinary form POST without a file).
    """
    if not hex_data:
        return None
    try:
        # tshark sometimes separates several file_data chunks with commas.
        raw = binascii.unhexlify(hex_data.replace(":", "").replace(",", ""))
    except (binascii.Error, ValueError):
        return None
    m = _POLA_NAMA.search(raw)
    if not m:
        return None
    try:
        return m.group(1).decode("utf-8", "replace")
    except Exception:
        return None


def _sidik(waktu, ip, uri, ukuran, nama):
    """Dedup key. It includes the time down to the second, so two different uploads of the same
    file stay two rows, while a capture window that happens to be read twice does not produce
    duplicate rows.
    """
    kunci = "%s|%s|%s|%s|%s" % (
        waktu.replace(microsecond=0).isoformat(), ip or "", uri or "",
        ukuran or "", nama or "")
    return hashlib.sha256(kunci.encode()).hexdigest()


def urai(keluaran):
    """Turn tshark output into a list of requests with bodies.

    A PURE function: it touches neither network nor database, so it can be tested with fake
    output and no devices. Only POST/PUT/PATCH are returned; GET is already in the access log.
    """
    hasil = []
    for line in (keluaran or "").splitlines():
        if not line.strip():
            continue
        section = line.split(PEMISAH)
        # Pad the row if tshark trimmed empty trailing fields.
        while len(section) < len(FIELDS):
            section.append("")

        epoch, ip, metode, uri, ctype, clen, fdata = section[:len(FIELDS)]
        metode = (metode or "").strip().upper()
        if metode not in METODE_BERBADAN:
            continue

        try:
            waktu = datetime.fromtimestamp(float(epoch))
        except (ValueError, OSError):
            waktu = datetime.now()

        try:
            ukuran = float(clen) if clen else None
        except ValueError:
            ukuran = None

        nama = _nama_berkas(fdata)
        # Multipart with a filename = file upload. Any other POST = submitted data (form fields):
        # still an "upload" in terms of direction, but without a file name.
        arah = "unggah"

        hasil.append({
            "waktu": waktu,
            "ip_klien": (ip or "").strip(),
            "arah": arah,
            "path": (uri or "").strip() or None,
            "nama_berkas": nama,
            "content_type": ((ctype or "").split(";")[0].strip() or None),
            "ukuran": ukuran,
            "sidik": _sidik(waktu, ip, uri, ukuran, nama),
        })
    return hasil


def tangkap(client, iface=IFACE, port=PORT, durasi=50):
    """Run the capture over an already-open SSH connection and return the list of requests with
    bodies. The caller provides `client` so one connection can be shared with other reads
    (the `baca_traffic_device` pattern).
    """
    _, out, _ = client.exec_command(perintah(iface, port, durasi),
                                    timeout=durasi + 20)
    teks = out.read().decode("utf-8", "replace")
    return urai(teks)

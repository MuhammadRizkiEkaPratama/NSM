"""Send IOS commands over the GNS3 console (raw telnet).

A plain socket is used instead of `telnetlib` (removed in Python 3.13); the GNS3
console is a plain byte stream and needs no telnet negotiation.

The console is used instead of SSH because a freshly created device has no IP
address, user, or SSH key yet. After SSH is up, NSM uses SSH.

Commands are sent line by line with a delay, and the full device reply is
returned unchanged. IOS rejects commands by writing `% Invalid input detected`
in the middle of the output, with no error code, so the reply must be read.
"""
import re
import socket
import time

# Marker that IOS rejected something. Searched in the whole reply, not just the
# last line: a command that fails mid-block lets the rest run.
POLA_GALAT = re.compile(
    r"(% Invalid input|% Incomplete command|% Ambiguous command|"
    r"% Unknown command|% Bad|Translating|% Authorization failed)", re.I)


class Konsol:
    def __init__(self, host, port, timeout=20):
        self.s = socket.create_connection((host, port), timeout)
        self.s.settimeout(timeout)
        self.buf = ""

    def baca(self, detik=2.0):
        """Read whatever arrives during `detik` seconds."""
        akhir = time.time() + detik
        keluar = ""
        self.s.settimeout(0.5)
        while time.time() < akhir:
            try:
                b = self.s.recv(65535)
                if not b:
                    break
                keluar += b.decode("utf-8", "replace")
                akhir = time.time() + 0.4
            except socket.timeout:
                pass
        return keluar

    def kirim(self, baris, jeda=0.6):
        self.s.sendall((baris + "\r\n").encode())
        time.sleep(jeda)
        return self.baca(1.2)

    def bangunkan(self):
        """Press Enter several times until the device responds.

        A freshly booted device may still show boot messages or wait on the initial
        configuration dialog; answering 'no' keeps the script from hanging.
        """
        for _ in range(6):
            keluar = self.kirim("", 0.4)
            if "initial configuration dialog" in keluar.lower():
                self.kirim("no", 1.0)
            if re.search(r"[>#]\s*$", keluar):
                return keluar
        return self.baca(2.0)

    def jalankan(self, perintah, jeda=0.6):
        """Kirim daftar perintah, kembalikan (keluaran, daftar_galat)."""
        semua = ""
        galat = []
        for p in perintah:
            keluar = self.kirim(p, jeda)
            semua += keluar
            if POLA_GALAT.search(keluar):
                galat.append((p, keluar.strip()[:200]))
        return semua, galat

    def tutup(self):
        try:
            self.s.close()
        except Exception:
            pass


def masuk_enable(k):
    """Make sure we are in enable mode (`#`), not user mode (`>`)."""
    keluar = k.bangunkan()
    if keluar.rstrip().endswith(">"):
        keluar += k.kirim("enable", 1.0)
        # If enable asks for a password, the device already has a configuration; stop
        # instead of guessing.
        if "password" in keluar.lower():
            raise RuntimeError(
                "Console minta sandi enable. Perangkat ini sudah "
                "dikonfigurasi; jangan ditimpa tanpa memeriksanya dulu.")
    return keluar

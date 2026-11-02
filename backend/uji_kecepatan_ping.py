"""Measure one ping round: sequential versus concurrent.

`poll_all()` checks devices one by one. A LIVE device answers in milliseconds, but
a DEAD one costs a full second (proving "nobody answers" means waiting for the
timeout), so round time grows linearly with dead devices and peaks during an
outage, when the poller most needs to be quick (symptom:
`poll_all skipped: maximum number of running instances reached`).

This file does NOT write to `nsm.db`: guaranteed-dead addresses are built in memory,
not registered as devices (a fake device would be pinged by the running poller and
log false outages). The real device list is only READ, to get addresses.

Compare the last two columns, wall-clock time versus CPU time: waiting for network
replies is idle time, so checking many devices at once adds almost no load.

Run: py uji_kecepatan_ping.py
"""
import sys
import time

from icmplib import ping, multiping

import database
import models
from config import get_probe_ports
from connectors.tcp import cek_port_terbuka

# Settings EXACTLY as in connectors/icmp.py; otherwise the numbers do not measure the real poller.
COUNT = 1
TIMEOUT = 1
PRIVILEGED = False

# How many checks may run concurrently in parallel mode.
PEKERJA = 50

# Host-only subnet addresses guaranteed to have no machine. Pings time out, which is
# the cost of a DEAD device being measured. Only unanswered ARP requests on this
# machine's own host-only adapter; no device is touched.
def alamat_mati(jumlah):
    return [f"192.168.56.{200 + i}" for i in range(jumlah)]


def alamat_sungguhan():
    """Addresses of really registered devices. READ ONLY."""
    db = database.SessionLocal()
    try:
        return [d.ip_address for d in
                db.query(models.Device).order_by(models.Device.id).all()]
    finally:
        db.close()


def ukur(fungsi):
    """Return (wall-clock seconds, CPU seconds) for one call."""
    t0, c0 = time.perf_counter(), time.process_time()
    fungsi()
    return time.perf_counter() - t0, time.process_time() - c0


def cara_berurutan(daftar_ip):
    """How the poller works NOW: one at a time, waiting for each reply."""
    def jalan():
        for ip in daftar_ip:
            ping(ip, count=COUNT, timeout=TIMEOUT, privileged=PRIVILEGED)
    return jalan


def cara_bersamaan(daftar_ip):
    """Proposed way: everything at once, then wait a single time."""
    def jalan():
        multiping(daftar_ip, count=COUNT, timeout=TIMEOUT,
                  privileged=PRIVILEGED, concurrent_tasks=PEKERJA)
    return jalan


def main():
    actual = alamat_sungguhan()
    print("=" * 78)
    print("LAMA SATU PUTARAN PING — berurutan versus bersamaan")
    print("=" * 78)
    print(f"  setelan ping   : count={COUNT}, timeout={TIMEOUT} dtk "
          f"(sama persis dengan connectors/icmp.py)")
    print(f"  pekerja paralel: {PEKERJA}")
    print(f"  device nyata   : {len(actual)} alamat, dibaca dari nsm.db")
    print(f"  alamat palsu   : dibuat di memori, TIDAK didaftarkan ke database")
    print()

    # Test layout: the first is the everyday state; the rest are outage states, which are what we want to measure.
    susunan = [
        ("6 device nyata (keadaan biasa)", actual),
        ("6 nyata + 20 mati", actual + alamat_mati(20)),
        ("6 nyata + 40 mati", actual + alamat_mati(40)),
    ]

    print(f"  {'Susunan':<32}{'Cara':<12}{'Jam dinding':>14}{'Waktu CPU':>14}")
    print("  " + "-" * 72)

    hasil = []
    for nama, ips in susunan:
        wall_s, cpu_s = ukur(cara_berurutan(ips))
        print(f"  {nama:<32}{'berurutan':<12}{wall_s:>12.2f} s{cpu_s:>12.2f} s")

        wall_p, cpu_p = ukur(cara_bersamaan(ips))
        print(f"  {'':<32}{'bersamaan':<12}{wall_p:>12.2f} s{cpu_p:>12.2f} s")

        times = wall_s / wall_p if wall_p > 0 else 0
        print(f"  {'':<32}{'':12}{'-> ' + f'{times:.1f}x lebih cepat':>26}")
        print()
        hasil.append((nama, len(ips), wall_s, wall_p))

    # Extra cost when a device JUST went down.
    #
    # poller.py:175 calls cek_port_terbuka() only on the UP->DOWN transition: three
    # ports in sequence with a 1 s timeout each, so the load peaks exactly when an outage begins.
    print("=" * 78)
    print("BIAYA TAMBAHAN SAAT DEVICE BARU SAJA MATI (transisi UP -> DOWN)")
    print("=" * 78)
    port = get_probe_ports()
    one = alamat_mati(1)[0]
    wall, cpu = ukur(lambda: cek_port_terbuka(one, port))
    print(f"  cek_port_terbuka({one}, {port})")
    print(f"  -> {wall:.2f} detik jam dinding, {cpu:.2f} detik CPU, "
          f"untuk SATU device")
    print()
    n = len(actual)
    # The "old way" numbers are fixed, not measured, since the code was replaced. They come from measurements before the change: sequential ping 1 s per dead device, sequential cek_port_terbuka 3.00 s per dead device.
    old = n * TIMEOUT + n * 3.00
    baru = 1.0 + n * wall
    print(f"  Kalau {n} device transisi UP -> DOWN di putaran yang sama:")
    print()
    print(f"    CARA LAMA (diukur sebelum perubahan)")
    print(f"      ping berurutan : {n} x {TIMEOUT},00 dtk = {n*TIMEOUT:.1f} dtk")
    print(f"      cek port       : {n} x 3,00 dtk = {n*3.00:.1f} dtk")
    print(f"      TOTAL          : {old:.1f} dtk")
    print()
    print(f"    CARA SEKARANG")
    print(f"      ping borongan  : 1 kali untuk semua = ~1,0 dtk")
    print(f"      cek port       : {n} x {wall:.2f} dtk = {n*wall:.1f} dtk")
    print(f"      TOTAL          : {baru:.1f} dtk  "
          f"({old/baru:.1f}x lebih cepat)")
    print()
    print(f"    Sisa yang belum dikerjakan: cek port masih berurutan ANTAR")
    print(f"    device. Port di dalam satu device sudah bersamaan (3,00 -> "
          f"{wall:.2f} dtk),")
    print(f"    tetapi device kedua masih menunggu device pertama selesai.")
    print()

    # ---------------------------------------------------------------
    print("=" * 78)
    print("BACAAN")
    print("=" * 78)
    print("  Waktu CPU nyaris nol di kedua cara, sementara jam dindingnya")
    print("  berbeda jauh. Itu bukti bahwa yang dihabiskan bukan tenaga")
    print("  prosesor, melainkan waktu MENUNGGU. Menunggu bersamaan tidak")
    print("  menambah kerja; ia cuma menghapus antreannya.")
    print()
    print("  Perhatikan juga bentuk kurvanya, bukan hanya satu angka:")
    for nama, n, s, p in hasil:
        print(f"    {n:>3} alamat  berurutan {s:>6.2f} dtk   bersamaan {p:>5.2f} dtk")
    print()
    print("  Berurutan tumbuh lurus mengikuti jumlah alamat yang mati.")
    print("  Bersamaan hampir datar. Selisih itulah yang menentukan apakah")
    print("  poller masih sanggup saat 40 device mati serentak.")


if __name__ == "__main__":
    main()
    sys.exit(0)

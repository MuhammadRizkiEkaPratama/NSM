from datetime import datetime

import dialek_perangkat
import jeda
import penyangga
from config import get_down_threshold, get_probe_ports
from connectors.icmp import IcmpConnector, ping_banyak
from connectors.lokal import LokalConnector, ip_sekarang
from connectors.tcp import cek_port_banyak, cek_port_terbuka
from models import Device, DeviceEvent, StatusLog

from ._inti import status_terakhir

# Consecutive failure count per device (in memory), so one lost ping does not record a DOWN incident.
gagal_beruntun = {}


# Until when a device may be considered TCP-reachable without rechecking (in
# memory). The port check takes about a second while the ping round runs every
# 5 seconds, so it is not repeated every round for devices whose ICMP is blocked.
tcp_terjangkau_sampai = {}


tcp_periksa_lagi_pada = {}


# Recheck interval; 60 s so a truly dead device is noticed within a minute.
JEDA_PROBE_TCP = 60


def beruntun_berikutnya(device_id, alive):
    """Consecutive failures for this device including the current ping result.
    Used by poll_all() before periksa_device() updates the count itself.
    """
    return 0 if alive else gagal_beruntun.get(device_id, 0) + 1


def perlu_probe_tcp(d, alive, beruntun, waktu):
    """True if this device's port should actually be probed this round.
    The rule lives here once because poll_all() and periksa_device() both use it.
    """
    if alive or dialek_perangkat.ambil(d.platform).lokal:
        return False
    if beruntun < get_down_threshold():
        # A single lost ping must not trigger a port check.
        return False
    if waktu.timestamp() < tcp_terjangkau_sampai.get(d.id, 0):
        return False
    return waktu.timestamp() >= tcp_periksa_lagi_pada.get(d.id, 0)


def tulis_event(db, device_id, tipe, kategori, detail, rtt, event_sebelum, waktu):
    """Store one transition. duration_sec is how long the PREVIOUS status lasted,
    excluding time the device was not monitored (see `jeda.py`), so closing the
    laptop overnight does not produce a huge bogus outage.
    """
    duration = None
    if event_sebelum is not None and event_sebelum.timestamp is not None:
        duration = (waktu - event_sebelum.timestamp).total_seconds()
        if duration < 0:
            duration = None
        else:
            tak_terpantau = jeda.tak_terpantau_antara(
                db, device_id, event_sebelum.timestamp, waktu)
            if tak_terpantau > 0:
                duration = max(0.0, duration - tak_terpantau)
                print(f"   [jeda] {int(tak_terpantau)} dtk tidak terpantau "
                      f"dipotong dari lama status sebelumnya")
    db.add(
        DeviceEvent(
            device_id=device_id,
            event_type=tipe,
            timestamp=waktu,
            duration_sec=duration,
            category=kategori,
            detail=detail,
            last_rtt_ms=rtt,
        )
    )
    return duration


def segarkan_ip_lokal(d):
    """Update the 'lokal' device's address when this machine changes networks.
    For this device the address is derived fact, unlike normal devices where it is
    a human choice and never changed silently. Changes are always printed.
    """
    baru = ip_sekarang()
    if baru and baru != d.ip_address:
        old = d.ip_address
        d.ip_address = baru
        print(f"   [lokal] {d.name}: alamat berubah {old} -> {baru} "
              f"(mesin ini berpindah jaringan)")
        return True
    return False


def periksa_device(db, d, hasil_ping=None, hasil_port=None):
    """Check one device, write status_logs, and record a transition if any.
    `hasil_ping` (alive, rtt) and `hasil_port` (list of answering ports) may be
    supplied by the caller when already probed concurrently. An empty port list
    ("tried, none answered") is different from None ("not tried yet").
    Order matters: all network work first, database writes last, so the SQLite
    write lock is not held during the port check (autoflush would turn the
    transaction into a write).
    """
    waktu = datetime.now()
    sumber = "lokal" if dialek_perangkat.ambil(d.platform).lokal else "icmp"
    if hasil_ping is not None:
        alive, rtt = hasil_ping
    elif dialek_perangkat.ambil(d.platform).lokal:
        segarkan_ip_lokal(d)
        alive, rtt = LokalConnector(d.ip_address).check_reachable()
    else:
        alive, rtt = IcmpConnector(d.ip_address).check_reachable()

    # 1. Hitung gagal beruntun (anti-flapping)
    if alive:
        gagal_beruntun[d.id] = 0
    else:
        gagal_beruntun[d.id] = gagal_beruntun.get(d.id, 0) + 1

    limit = get_down_threshold()

    # 2. A silent ping does not mean the host is down. If the TCP port probe gets
    # answers, the device is alive with ICMP blocked, and the proof is stored in the
    # `sumber` column. Guards: only used after consecutive failures reach the
    # threshold, and the result is valid for at most JEDA_PROBE_TCP seconds.
    if (not alive and not dialek_perangkat.ambil(d.platform).lokal
            and gagal_beruntun[d.id] >= limit):
        if waktu.timestamp() < tcp_terjangkau_sampai.get(d.id, 0):
            alive, sumber, rtt = True, "tcp", None
        elif perlu_probe_tcp(d, alive, gagal_beruntun[d.id], waktu):
            # Network work, deliberately done before any row enters the session (see the
            # ordering note in the docstring). Uses the concurrent result from poll_all()
            # when available; otherwise probes here as a safety net.
            ports = (hasil_port if hasil_port is not None
                     else cek_port_terbuka(d.ip_address, get_probe_ports()))
            tcp_periksa_lagi_pada[d.id] = waktu.timestamp() + JEDA_PROBE_TCP
            if ports:
                tcp_terjangkau_sampai[d.id] = waktu.timestamp() + JEDA_PROBE_TCP
                alive, sumber, rtt = True, "tcp", None
                print(f"   [tcp] {d.name}: ping diam, port "
                      f"{', '.join(str(p) for p in ports)} menjawab "
                      f"-> dianggap HIDUP (ICMP kemungkinan diblokir)")
            else:
                tcp_terjangkau_sampai.pop(d.id, None)

    line_raw = StatusLog(
        device_id=d.id,
        timestamp=waktu,
        is_reachable=alive,
        response_time_ms=rtt,
        sumber=sumber,
    )

    last = status_terakhir(db, d.id)

    if last is None:
        tipe = "UP" if alive else "DOWN"
        tulis_event(db, d.id, tipe, "baseline", "Catatan awal pemantauan.",
                    rtt, None, waktu)
        print(f"   [event] {d.name}: baseline {tipe}")
        db.add(line_raw)
        return alive, rtt

    previous = last.event_type

    # 4. UP -> DOWN, only after consecutive failures reach the threshold.
    # `alive` already includes the port check, so ping and ports are both silent
    # here and the category is simply "dead". The port check is not repeated.
    if previous == "UP" and not alive and gagal_beruntun[d.id] >= limit:
        detail = (
            "Ping tidak dibalas dan tidak ada port TCP ("
            + ", ".join(str(p) for p in get_probe_ports())
            + ") yang menjawab -> device kemungkinan MATI atau terputus dari jaringan."
        )
        duration = tulis_event(db, d.id, "DOWN", "dead", detail, None, last, waktu)
        old = f" (sebelumnya UP {int(duration)} dtk)" if duration else ""
        print(f"   [event] {d.name}: UP -> DOWN [dead]{old}")

    elif previous == "DOWN" and alive:
        # The wording depends on HOW the device proved alive again; do not claim
        # "replying to ping" for a device that does not answer ping.
        if sumber == "tcp":
            kategori = "ping_blocked"
            detail = (
                "Device terjangkau lagi lewat TCP (port "
                + ", ".join(str(p) for p in get_probe_ports())
                + "), TETAPI ping-nya tetap tidak dibalas. Mesinnya hidup; yang "
                "kemungkinan besar diblokir ICMP-nya, bukan mesinnya yang mati. "
                "Periksa firewall device (`sudo ufw status`)."
            )
        else:
            kategori = "recovered"
            detail = "Device kembali membalas ping."
        duration = tulis_event(db, d.id, "UP", kategori, detail, rtt, last, waktu)
        old = f" setelah DOWN {int(duration)} dtk" if duration else ""
        print(f"   [event] {d.name}: DOWN -> UP [{kategori}]{old}")

    db.add(line_raw)
    return alive, rtt


def poll_all():
    """One check round over all devices, in three phases:
    1. all pings concurrently, no database access
    1b. ports of devices whose ping is silent, also concurrently
    2. results written one by one
    Waiting dominates, so network work runs concurrently; SQLite allows a single
    writer, so database writes stay sequential.
    """
    db, _buffered = penyangga.sesi()
    try:
        # Paused devices are not pinged at all: pinging them would fill status_logs and
        # device_events with false outages.
        devices = [d for d in db.query(Device).all() if d.aktif != 0]
        if not devices:
            print("---")
            return

        # Phase 1: all network work, no database access.
        # "lokal" devices are excluded; they are read via psutil on this machine.
        remote = [d for d in devices if not dialek_perangkat.ambil(d.platform).lokal]
        try:
            peta = ping_banyak([d.ip_address for d in remote])
        except Exception as e:
            # Bulk ping failed entirely: the round must not die. An empty map makes each
            # device fall back to a single ping (slow but correct).
            peta = {}
            print(f"   [ping borongan gagal, kembali ke satu per satu] {e}")

        # Phase 1b: ports of devices whose ping is silent, concurrently.
        # The time is taken once so all devices are judged with the same clock.
        waktu_probe = datetime.now()
        need = [
            d for d in remote
            if perlu_probe_tcp(
                d,
                peta.get(d.ip_address, (True, None))[0],
                beruntun_berikutnya(
                    d.id, peta.get(d.ip_address, (True, None))[0]),
                waktu_probe,
            )
        ]
        port_map = {}
        if need:
            try:
                port_map = cek_port_banyak([d.ip_address for d in need],
                                            get_probe_ports())
            except Exception as e:
                port_map = {}
                print(f"   [cek port borongan gagal, kembali ke satu per satu] {e}")

        for d in devices:
            try:
                hasil = None if dialek_perangkat.ambil(d.platform).lokal else peta.get(d.ip_address)
                port = None if dialek_perangkat.ambil(d.platform).lokal else port_map.get(d.ip_address)
                alive, rtt = periksa_device(db, d, hasil_ping=hasil,
                                            hasil_port=port)
                # Commit here, not at the end of the round, so the write lock is not held
                # while the next device is prepared (see poll_bandwidth).
                db.commit()
                print(f"{d.name} ({d.ip_address}) = {'UP' if alive else 'DOWN'} {rtt} ms")
            except Exception as e:
                # One failing device must not stop the others. Roll back rather than save: a
                # half-written status/transition pair is more misleading than no data.
                db.rollback()
                print(f"{d.name} ({d.ip_address}) = ERROR: {e}")

        # Buffer maintenance runs AFTER all devices are recorded, so a long cleanup
        # cannot delay this round's pings.
        penyangga.rawat(db, _buffered)
        if _buffered:
            old = penyangga.lama_terputus()
            print("  [penyangga] basis data tidak terjangkau %.0f dtk — "
                  "hasil disimpan lokal" % (old or 0))
    finally:
        db.close()
    print("---")

from datetime import datetime

from sqlalchemy import desc

import dialek_perangkat
import penyangga
from connectors.lokal import LokalConnector
from connectors.snmp import SnmpConnector
from connectors.ssh import SshConnector
from models import BandwidthSample, Device

from ._inti import kerjakan_bersamaan, sasaran, status_terakhir


def sampel_terakhir(db, device_id, iface):
    return (
        db.query(BandwidthSample)
        .filter(BandwidthSample.device_id == device_id,
                BandwidthSample.iface == iface)
        .order_by(desc(BandwidthSample.timestamp), desc(BandwidthSample.id))
        .first()
    )


def satu_arah(octets_kini, octets_dulu, detik):
    """Convert a counter delta to bits per second.
    Returns None when it cannot be computed: no previous sample, counter went
    backwards (reboot/reset), or zero time delta.
    """
    if octets_kini is None or octets_dulu is None or detik <= 0:
        return None
    difference = octets_kini - octets_dulu
    if difference < 0:
        return None                       # counter mundur -> device reboot
    return round(difference * 8 / detik, 2)  # byte -> bit


def pilih_pembaca(d):
    """Choose how to read a device's traffic: local, then SNMP, then SSH.
    Local first, since reading this machine over the network is pointless; SNMP
    before SSH because it is one UDP packet with no login; SSH is the fallback.
    """
    if dialek_perangkat.ambil(d.platform).lokal:
        return LokalConnector(d.ip_address), "lokal"
    if d.snmp_user:
        return SnmpConnector(
            d.ip_address, user=d.snmp_user,
            auth_pass=d.snmp_auth_pass, priv_pass=d.snmp_priv_pass,
            auth_proto=d.snmp_auth_proto, priv_proto=d.snmp_priv_proto,
            port=d.snmp_port or 161,
        ), "snmp"
    return SshConnector(d.ip_address, platform=d.platform,
                        username=d.username, password=d.password,
                        key_path=d.ssh_key_path), "ssh"


def baca_bandwidth_device(s):
    """Network work only: read one device's counters. Returns (data, source).
    Must not touch the database (runs in a worker thread), hence `Sasaran` instead of a Device.
    """
    conn, sumber = pilih_pembaca(s)
    try:
        data = conn.get_bandwidth()
    except Exception as e:
        # SNMP failed but SSH credentials exist: fall back to SSH.
        if sumber == "snmp" and s.platform and s.username and s.password:
            print(f"[bw] {s.name}: SNMP gagal ({e}) -> coba SSH")
            conn = SshConnector(s.ip_address, platform=s.platform,
                                username=s.username, password=s.password,
                                key_path=s.ssh_key_path)
            data = conn.get_bandwidth()
            sumber = "ssh"
        else:
            raise
    return data, sumber


def simpan_bandwidth_device(db, d, data, sumber, waktu=None):
    """Database work only: convert counters to a rate and store the sample.
    Kept separate so network reads can run concurrently while writes stay
    sequential (SQLite allows a single writer).
    """
    if waktu is None:
        waktu = datetime.now()
    jumlah = 0

    for iface, value in data.items():
        in_oct = value.get("in_octets")
        out_oct = value.get("out_octets")
        in_bps = value.get("in_bps")
        out_bps = value.get("out_bps")

        # Cisco already reports a finished rate; Linux reports counters -> compute the difference
        if in_bps is None and out_bps is None:
            before = sampel_terakhir(db, d.id, iface)
            if before is not None and before.timestamp is not None:
                detik = (waktu - before.timestamp).total_seconds()
                in_bps = satu_arah(in_oct, before.in_octets, detik)
                out_bps = satu_arah(out_oct, before.out_octets, detik)

        db.add(BandwidthSample(
            device_id=d.id, iface=iface, timestamp=waktu,
            in_octets=in_oct, out_octets=out_oct,
            in_bps=in_bps, out_bps=out_bps,
            source=sumber,
        ))
        jumlah += 1
    return jumlah, sumber


def bisa_dibaca_bandwidth(d):
    """True if the device's traffic can be read at all: it is this machine, or has
    SNMP or SSH credentials. `ssh_key_path` counts as an SSH credential, otherwise
    key-based Linux devices would be skipped silently.
    """
    if dialek_perangkat.ambil(d.platform).lokal or d.snmp_user:
        return True
    return bool(d.platform and d.username and (d.password or d.ssh_key_path))


def poll_bandwidth():
    """Read traffic from all reachable devices.
    Skips devices without platform or credentials, and devices that are DOWN.
    Three phases, same as poll_all(): select devices (DB), read counters (network,
    concurrent), compute rates and store samples (DB, sequential).
    """
    db, _buffered = penyangga.sesi()
    try:
        choice = []
        for d in db.query(Device).all():
            if d.aktif == 0 or not bisa_dibaca_bandwidth(d):
                continue
            last = status_terakhir(db, d.id)
            if last is not None and last.event_type == "DOWN":
                continue
            choice.append((d, sasaran(d)))
        if not choice:
            return

        # --- Tahap 2: kerja jaringan, bersamaan ---
        hasil = kerjakan_bersamaan([s for _, s in choice],
                                   baca_bandwidth_device)

        # Taken after the read, not before: a timestamp taken before waiting on the
        # network would shrink the time delta and inflate every rate.
        waktu = datetime.now()

        for (d, s), (_, output, error) in zip(choice, hasil):
            if error is not None:
                print(f"[bw] {s.name}: gagal ({error})")
                continue
            data, sumber = output
            try:
                n, sumber = simpan_bandwidth_device(db, s, data, sumber, waktu)
                db.commit()
                print(f"[bw] {s.name}: {n} interface terbaca (via {sumber})")
            except Exception as e:
                db.rollback()
                print(f"[bw] {s.name}: gagal menyimpan ({e})")

            # Commit per device, not at the end of the round: a single long transaction holds
            # the SQLite write lock and makes the ping job wait (up to busy_timeout).
            # Per-device commits also keep one device's failure from affecting the others.
            # With WAL and synchronous=NORMAL a commit does not force a disk sync.
    finally:
        db.close()

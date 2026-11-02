from datetime import datetime
from sqlalchemy import desc
import penyangga
from models import (Device, Service, ServiceCheck, ServiceEvent)
from config import (get_probe_ports,
                    get_service_down_threshold, get_diagnosa_enabled)
import diagnosa
from connectors.icmp import IcmpConnector
from connectors.tcp import TcpConnector
from connectors import (layanan)


# Consecutive failure count per SERVICE, parallel to gagal_beruntun for ping.
gagal_layanan = {}


def event_layanan_terakhir(db, service_id):
    """Latest transition of a service, or None."""
    return (
        db.query(ServiceEvent)
        .filter(ServiceEvent.service_id == service_id)
        .order_by(desc(ServiceEvent.timestamp), desc(ServiceEvent.id))
        .first()
    )


def kumpulkan_bukti(db, d, s):
    """Build the layered evidence chain when a service has a problem:
    1. ping: is the machine alive?
    2. the service's own port
    3. comparison ports: is the network to the device still up?
    Also returns `diharapkan`, the ports with a registered service on this device.
    A comparison port not in it is closed because it was never open, so it must not
    be flagged as failed.
    """
    alive, rtt = IcmpConnector(d.ip_address).check_reachable()

    # The service's own port, checked separately from `layanan.periksa()`: the
    # question is "is anything listening", not "is the answer correct". Apache
    # returning 500 fails the first and passes the second, and that is the diagnosis.
    port_layanan_ok, _ = TcpConnector(
        d.ip_address, port=s.port, timeout=3.0).check_reachable()

    # Comparison ports: common ports that are NOT this service's port. If one answers,
    # the network to the device is still up.
    pembanding = [p for p in get_probe_ports() if p != s.port][:3]
    port_other = {}
    for p in pembanding:
        ok, _ = TcpConnector(d.ip_address, port=p, timeout=3.0).check_reachable()
        port_other[p] = ok

    # Ports with a registered service on this device. Read from the table, not
    # hard-coded, so registering an HTTPS service later changes how 443 is read.
    diharapkan = {
        p for (p,) in db.query(Service.port)
        .filter(Service.device_id == d.id, Service.aktif != 0).all()
        if p is not None
    }

    return alive, rtt, port_layanan_ok, port_other, diharapkan


def check_service(db, d, s):
    """Check one service, write the raw result, record a transition if any."""
    waktu = datetime.now()
    hasil = layanan.periksa(
        s.jenis, d.ip_address, s.port, path=s.path,
        timeout=s.timeout_detik or 5,
        harap_status=s.harap_status, harap_teks=s.harap_teks,
    )

    db.add(ServiceCheck(
        service_id=s.id, timestamp=waktu, ok=hasil["ok"],
        kode=hasil["kode"], waktu_ms=hasil["waktu_ms"],
        kategori=hasil["kategori"],
    ))

    if hasil["ok"]:
        gagal_layanan[s.id] = 0
    else:
        gagal_layanan[s.id] = gagal_layanan.get(s.id, 0) + 1

    limit = get_service_down_threshold()
    last = event_layanan_terakhir(db, s.id)

    if last is None:
        db.add(ServiceEvent(
            service_id=s.id, device_id=d.id,
            event_type="UP" if hasil["ok"] else "DOWN",
            timestamp=waktu, kategori="baseline",
            detail="Catatan awal pemantauan layanan.",
            kode=hasil["kode"],
        ))
        print(f"   [layanan] {d.name} / {s.nama}: baseline "
              f"{'UP' if hasil['ok'] else 'DOWN'}")
        return hasil

    previous = last.event_type

    # --- UP -> DOWN ---
    if previous == "UP" and not hasil["ok"] and gagal_layanan[s.id] >= limit:
        alive, rtt, port_layanan_ok, port_other, diharapkan = kumpulkan_bukti(db, d, s)
        bukti = diagnosa.build_evidence(d.ip_address, alive, rtt, port_other,
                                     port_layanan=s.port,
                                     port_layanan_ok=port_layanan_ok,
                                     diharapkan=diharapkan)
        # Second argument stays False: this concludes about a service that FAILED its
        # check. `port_terbuka` is separate because it answers another question.
        kesimpulan = diagnosa.simpulkan(alive, False, port_other,
                                        port_terbuka=port_layanan_ok)
        saran = diagnosa.susun_saran(hasil["kategori"], s.jenis, s.port)

        snapshot = None
        if get_diagnosa_enabled():
            snapshot = diagnosa.jalankan(d, s.jenis)

        duration = None
        if last.timestamp is not None:
            duration = (waktu - last.timestamp).total_seconds()
            if duration < 0:
                duration = None

        db.add(ServiceEvent(
            service_id=s.id, device_id=d.id, event_type="DOWN",
            timestamp=waktu, duration_sec=duration,
            kategori=hasil["kategori"],
            detail=f"{hasil['detail']}\n\n{kesimpulan}",
            kode=hasil["kode"], bukti=bukti, saran=saran,
            diagnosa_mulai=snapshot,
        ))
        print(f"   [layanan] {d.name} / {s.nama}: UP -> DOWN "
              f"[{hasil['kategori']}]")

    elif previous == "DOWN" and hasil["ok"]:
        duration = None
        if last.timestamp is not None:
            duration = (waktu - last.timestamp).total_seconds()
            if duration < 0:
                duration = None

        snapshot = None
        if get_diagnosa_enabled():
            snapshot = diagnosa.jalankan(d, s.jenis)

        db.add(ServiceEvent(
            service_id=s.id, device_id=d.id, event_type="UP",
            timestamp=waktu, duration_sec=duration, kategori="pulih",
            detail="Layanan kembali menjawab dengan benar.",
            kode=hasil["kode"], diagnosa_pulih=snapshot,
        ))
        if snapshot and last is not None:
            last.diagnosa_pulih = snapshot
        old = f" setelah DOWN {int(duration)} dtk" if duration else ""
        print(f"   [layanan] {d.name} / {s.nama}: DOWN -> UP{old}")

    return hasil


def poll_services():
    """Check all active services of devices that are not paused.
    Deliberately does NOT skip DOWN devices, unlike bandwidth: when ping fails but
    HTTP answers, ICMP is blocked rather than the device being dead.
    """
    db, _buffered = penyangga.sesi()
    try:
        line = (db.query(Service, Device)
                 .join(Device, Service.device_id == Device.id)
                 .all())
        for s, d in line:
            if d.aktif == 0 or s.aktif == 0:
                continue
            try:
                hasil = check_service(db, d, s)
                # Same reason as poll_bandwidth(), and more exposed here: when a service has a
                # problem, diagnosa.py opens SSH and runs sixteen commands, which can take tens
                # of seconds.
                db.commit()
                mark = "OK" if hasil["ok"] else f"GAGAL [{hasil['kategori']}]"
                kode = f" kode {hasil['kode']}" if hasil["kode"] else ""
                print(f"[svc] {d.name} / {s.nama} = {mark}{kode}")
            except Exception as e:
                # One failing service must not stop the rest.
                db.rollback()
                print(f"[svc] {d.name} / {s.nama} = ERROR: {e}")
    finally:
        db.close()

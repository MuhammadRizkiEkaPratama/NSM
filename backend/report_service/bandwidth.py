"""Bandwidth part of report_service: per-interface traffic for the device page."""
from datetime import datetime, timedelta

from sqlalchemy import desc, func

import dialek_perangkat
from models import BandwidthSample, Device

from ._inti import BW_BASI_DETIK, JENDELA_BW_DETIK, format_bps_lengkap, rentang


def bandwidth_device(db, device_id, period):
    """Per-interface traffic for the device page: latest rate, average and peak for the period."""
    start, finish, label = rentang(period)
    d = db.query(Device).filter(Device.id == device_id).first()
    if not d:
        return {"error": "Device tidak ditemukan"}

    # Traffic can be read via LOCAL reading, SNMP, or SSH; any one is enough.
    #
    # "Local" must be named explicitly: directly-read devices have no
    # username/password, and without this branch the page would claim traffic
    # cannot be read while samples are collected every 30 s. Windows devices over SSH
    # deliberately do not collect traffic, and the page says so.
    #
    # Without this branch the page shows "no data yet, numbers appear on the second
    # reading", a promise that never comes true.
    #
    # This still checks the platform, the only place in the report path to do so: the
    # question is about one specific row, "Laptop (via SSH)", which is the same
    # machine as "Laptop Sendiri" (which already reads its counters without a
    # connection). It is not a Windows property; a generic "platform has no
    # `interface_rinci` command" check would also catch `lokal`, handled by the branch below.
    if d.platform == "windows":
        return {
            "periode": label,
            "didukung": False,
            "alasan": ("Baris device ini sengaja tidak mengumpulkan lalu "
                       "lintas. Mesin yang sama sudah dibaca lewat jalur "
                       "lokal di device \"Laptop Sendiri\", yang memberi "
                       "counter tiap interface tanpa membuka koneksi apa pun. "
                       "Mengumpulkannya dua kali hanya menghasilkan dua angka "
                       "untuk satu kenyataan, dan cepat atau lambat keduanya "
                       "akan berbeda. Baris ini gunanya membuktikan jalur "
                       "remote ke Windows bekerja."),
            "interfaces": [],
        }

    has_local = dialek_perangkat.ambil(d.platform).lokal
    has_snmp = bool(d.snmp_user)
    has_ssh = bool(d.platform and not dialek_perangkat.ambil(d.platform).lokal
                     and d.username and (d.password or d.ssh_key_path))
    if not has_local and not has_snmp and not has_ssh:
        return {
            "periode": label,
            "didukung": False,
            "alasan": ("Device ini belum punya kredensial SNMP maupun SSH, jadi lalu "
                       "lintasnya tidak bisa dibaca. Ping hanya membuktikan device "
                       "hidup, bukan berapa data yang lewat."),
            "interfaces": [],
        }

    # Average and peak are computed IN the database (GROUP BY), not by pulling all
    # rows into Python: samples arrive twice a minute per interface, about 86,000
    # rows per interface over 30 days. SQL AVG/MAX ignore NULL, so the first sample
    # (no rate yet) does not pull the average down.
    agregat = (
        db.query(
            BandwidthSample.iface,
            func.avg(BandwidthSample.in_bps),
            func.avg(BandwidthSample.out_bps),
            func.max(BandwidthSample.in_bps),
            func.max(BandwidthSample.out_bps),
            func.count(BandwidthSample.id),
        )
        .filter(BandwidthSample.device_id == device_id,
                BandwidthSample.timestamp >= start)
        .group_by(BandwidthSample.iface)
        .order_by(BandwidthSample.iface)
        .all()
    )

    hasil = []
    total_sampel = 0
    for iface, in_average, out_average, in_peak, out_peak, jumlah in agregat:
        total_sampel += jumlah
        terakhir = (
            db.query(BandwidthSample)
            .filter(BandwidthSample.device_id == device_id,
                    BandwidthSample.iface == iface)
            .order_by(desc(BandwidthSample.timestamp), desc(BandwidthSample.id))
            .first()
        )
        in_current = terakhir.in_bps if terakhir else None
        out_current = terakhir.out_bps if terakhir else None
        in_teks, in_asli = format_bps_lengkap(in_current)
        out_teks, out_asli = format_bps_lengkap(out_current)
        in_rata_teks, in_rata_asli = format_bps_lengkap(in_average)
        out_rata_teks, out_rata_asli = format_bps_lengkap(out_average)
        in_puncak_teks, in_puncak_asli = format_bps_lengkap(in_peak)
        out_puncak_teks, out_puncak_asli = format_bps_lengkap(out_peak)

        hasil.append({
            "iface": iface,
            "in_bps": in_current,
            "out_bps": out_current,
            "in_teks": in_teks,
            "out_teks": out_teks,
            "in_rata_teks": in_rata_teks,
            "out_rata_teks": out_rata_teks,
            "in_puncak_teks": in_puncak_teks,
            "out_puncak_teks": out_puncak_teks,
            # Original value for the hover text; a single unit would otherwise erase information.
            "in_asli": in_asli,
            "out_asli": out_asli,
            "in_rata_asli": in_rata_asli,
            "out_rata_asli": out_rata_asli,
            "in_puncak_asli": in_puncak_asli,
            "out_puncak_asli": out_puncak_asli,
            "jumlah_sampel": jumlah,
            "terakhir": (terakhir.timestamp.isoformat()
                         if terakhir and terakhir.timestamp else None),
            "source": terakhir.source if terakhir else None,
        })

    return {
        "periode": label,
        "didukung": True,
        "alasan": None,
        "interfaces": hasil,
        "total_sampel": total_sampel,
    }


def bandwidth_terkini_semua(db):
    """Latest rate of every device, ONE request for the whole dashboard.

    A dedicated endpoint rather than `/devices/{id}/latest`: the dashboard refreshes
    every 5 s for all devices, so per-device requests would be many calls per beat.

    Reports each device's BUSIEST interface, not the sum: a laptop with four
    interfaces, two of them always-zero VMware adapters, would give a sum that
    answers nobody's question. The card shows "how much traffic, through where",
    with the interface name.
    """
    limit = datetime.now() - timedelta(seconds=JENDELA_BW_DETIK)

    # One query, filtered in Python: the window is short (10 min x 2 samples/min x
    # interfaces, about 200 rows here), and "latest row per interface" in pure SQL
    # needs a correlated subquery that costs more.
    line = (
        db.query(BandwidthSample)
        .filter(BandwidthSample.timestamp >= limit)
        .order_by(desc(BandwidthSample.timestamp), desc(BandwidthSample.id))
        .all()
    )

    # (device_id, iface) -> latest sample. Rows are in descending order, so the first one seen per pair is newest.
    latest = {}
    for b in line:
        kunci = (b.device_id, b.iface)
        if kunci not in latest:
            latest[kunci] = b

    hasil = {}
    for (device_id, iface), b in latest.items():
        enter = b.in_bps or 0.0
        keluar = b.out_bps or 0.0
        old = hasil.get(device_id)
        # Busiest interface = largest two-way sum, so an interface that only sends still
        # beats one that is truly idle.
        if old is None or (enter + keluar) > old["_sibuk"]:
            in_teks, in_asli = format_bps_lengkap(b.in_bps)
            out_teks, out_asli = format_bps_lengkap(b.out_bps)
            age = (datetime.now() - b.timestamp).total_seconds() if b.timestamp else None
            hasil[device_id] = {
                "_sibuk": enter + keluar,
                "iface": iface,
                "in_bps": b.in_bps,
                "out_bps": b.out_bps,
                "in_teks": in_teks,
                "out_teks": out_teks,
                "in_asli": in_asli,
                "out_asli": out_asli,
                # Where the number was read from, so an SNMP-to-SSH fallback is visible on screen, not just in the poller console.
                "source": b.source,
                "t": b.timestamp.isoformat() if b.timestamp else None,
                "umur_detik": round(age) if age is not None else None,
                "basi": bool(age is not None and age > BW_BASI_DETIK),
            }

    for content in hasil.values():
        content.pop("_sibuk", None)

    # Interface count per device, so the card can say that only one of several is shown.
    jumlah = {}
    for (device_id, _iface) in latest:
        jumlah[device_id] = jumlah.get(device_id, 0) + 1
    for device_id, content in hasil.items():
        content["jumlah_iface"] = jumlah.get(device_id, 1)

    # JSON keys are always text, so device ids are normalized here and JavaScript need not guess.
    return {"jendela_detik": JENDELA_BW_DETIK,
            "devices": {str(k): v for k, v in hasil.items()}}

"""Dashboard part of report_service."""
import hashlib
import json
from datetime import datetime, timedelta
from sqlalchemy import func
from models import (Device, DeviceEvent, BandwidthSample)

from ._inti import (format_bps_lengkap, ringkas_layanan_per_device, status_sekarang)



def ringkas_dashboard(db, titik=48):
    """Numbers an IT operator wants to see BEFORE opening other pages: are devices
    or services down, how many incidents since midnight, current network rate and
    the last hour's shape, and the slowest device.

    Deliberately few: a dashboard that shows everything stops being used. Every
    calculation here must stay cheap because the dashboard refreshes every 5
    seconds; no period availability (which sweeps `status_logs` and rebuilds
    `device_events`), only the state NOW.
    """
    sekarang = datetime.now()

    perangkat = db.query(Device).all()
    hidup = mati = tanya = dijeda = 0
    latency = []
    terlambat = None
    list_down_device = []
    for d in perangkat:
        if d.aktif == 0:
            # Paused is counted separately, not merged into "down": a device deliberately
            # not monitored is not a device with a problem.
            dijeda += 1
            continue
        s = status_sekarang(db, d.id)
        if s is None:
            tanya += 1
            continue
        if s.is_reachable:
            hidup += 1
            if s.response_time_ms is not None:
                latency.append(s.response_time_ms)
                if terlambat is None or s.response_time_ms > terlambat["ms"]:
                    terlambat = {"nama": d.name, "id": d.id,
                                 "ms": s.response_time_ms}
        else:
            mati += 1
            if len(list_down_device) < 5:
                list_down_device.append({"nama": d.name, "id": d.id,
                                           "ip": d.ip_address})

    # Uses the SAME function as the device card rather than its own count, so two
    # places never show different "services down" numbers on one screen.
    summarize_service = ringkas_layanan_per_device(db)
    service_total = service_down = 0
    daftar_mati = []
    name_device = {d.id: d.name for d in perangkat}
    for did, content in (summarize_service.get("per_device") or {}).items():
        # Counts come from what that function already computed (`total`, `bermasalah`),
        # not recomputed from the service list, to keep the "what counts as a problem" rule in one place.
        paused_service = content.get("dijeda", 0)
        service_total += content.get("total", 0) - paused_service
        service_down += content.get("bermasalah", 0)
        for s in content.get("layanan", []):
            if s.get("aktif") and s.get("ok") is False and len(daftar_mati) < 5:
                daftar_mati.append({
                    "nama": s.get("nama"),
                    "device": name_device.get(int(did), "?"),
                    "device_id": int(did),
                })

    begin_day = sekarang.replace(hour=0, minute=0, second=0, microsecond=0)
    insiden_hari_ini = (
        db.query(func.count(DeviceEvent.id))
        .filter(DeviceEvent.timestamp >= begin_day,
                DeviceEvent.event_type == "DOWN")
        .scalar()) or 0

    series, rate_current = _deret_laju_total(db, titik=titik)

    hasil = {
        "device": {
            "total": len(perangkat), "hidup": hidup, "mati": mati,
            "tanya": tanya, "dijeda": dijeda,
            "daftar_mati": list_down_device,
        },
        "layanan": {
            "total": service_total, "mati": service_down,
            "hidup": service_total - service_down, "daftar_mati": daftar_mati,
        },
        "insiden_hari_ini": insiden_hari_ini,
        "latency": {
            "rata_ms": (sum(latency) / len(latency)) if latency else None,
            "sampel": len(latency),
            "terlambat": terlambat,
        },
        "laju": rate_current,
        "deret_laju": series,
        "waktu": sekarang.isoformat(),
    }

    # Content fingerprint, same reason as `topologi()`: the receiver can tell "nothing changed" without comparing text that contains an always-different time.
    hasil["sidik"] = hashlib.sha1(
        json.dumps({k: v for k, v in hasil.items() if k != "waktu"},
                   sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return hasil


def _deret_laju_total(db, titik=48, detik_per_kotak=60):
    """Network-wide rate over time, as a ready-to-plot series.

    Summation rule, same as the device card: each device contributes only its
    BUSIEST interface, and those are summed across devices. Summing every interface
    would exceed real traffic (VMware adapters, and a router counts the same packet
    in and out). It is still NOT a de-duplicated network total: a packet crossing
    between locations is seen by several devices, so this is the sum of what each
    device sees, and the screen should say so.
    """
    limit = datetime.now() - timedelta(seconds=titik * detik_per_kotak)
    line = (db.query(BandwidthSample)
             .filter(BandwidthSample.timestamp >= limit)
             .order_by(BandwidthSample.timestamp)
             .all())

    # time bucket -> device -> (in, out) of its busiest interface
    box = {}
    for b in line:
        if not b.timestamp:
            continue
        k = int(b.timestamp.timestamp() // detik_per_kotak)
        enter = b.in_bps or 0.0
        keluar = b.out_bps or 0.0
        per_dev = box.setdefault(k, {})
        old = per_dev.get(b.device_id)
        if old is None or (enter + keluar) > (old[0] + old[1]):
            per_dev[b.device_id] = (enter, keluar)

    series = []
    for k in sorted(box):
        enter = sum(v[0] for v in box[k].values())
        keluar = sum(v[1] for v in box[k].values())
        series.append({
            "t": datetime.fromtimestamp(k * detik_per_kotak).isoformat(),
            "masuk_bps": enter,
            "keluar_bps": keluar,
            "perangkat": len(box[k]),
        })

    # "Now" is taken from the LAST non-empty bucket, not a second query: two
    # calculation paths for one number let the chart and the big number disagree.
    end = series[-1] if series else None
    if end:
        in_text, in_original = format_bps_lengkap(end["masuk_bps"])
        out_text, out_original = format_bps_lengkap(end["keluar_bps"])
        laju = {
            "masuk_bps": end["masuk_bps"], "keluar_bps": end["keluar_bps"],
            "masuk_teks": in_text, "keluar_teks": out_text,
            "masuk_asli": in_original, "keluar_asli": out_original,
            "perangkat": end["perangkat"], "waktu": end["t"],
        }
    else:
        laju = {
            "masuk_bps": None, "keluar_bps": None,
            "masuk_teks": "-", "keluar_teks": "-",
            "masuk_asli": None, "keluar_asli": None,
            "perangkat": 0, "waktu": None,
        }
    return series, laju

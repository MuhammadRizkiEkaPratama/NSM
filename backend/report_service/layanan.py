"""`layanan` section of report_service."""
from datetime import datetime
from sqlalchemy import desc
import jeda
from models import (Device, Service, ServiceCheck, ServiceEvent)

from ._inti import (PERIODE, PERIODE_NAMA, _urai_bukti, format_durasi, rentang, teks_kategori)



def _hitung_layanan(db, s, d, mulai, selesai, daftar_jeda=None):
    """Availability and incident count of one service over a period.

    Unobserved time is clipped with exactly the same rule as `hitung_device()`, so both
    "availability" figures share one denominator. The gaps used are those of the OWNING
    DEVICE, not the service: service checks run in the same job as the poller, so a device
    gap is a service gap, and the device's `status_logs` is the densest trace of it.
    """
    if daftar_jeda is None:
        daftar_jeda = jeda.find_gaps(db, d.id, mulai, selesai)

    ev = (db.query(ServiceEvent)
          .filter(ServiceEvent.service_id == s.id,
                  ServiceEvent.timestamp <= selesai)
          .order_by(ServiceEvent.timestamp, ServiceEvent.id)
          .all())

    state = None
    since = mulai
    for e in ev:
        if e.timestamp <= mulai:
            state = e.event_type
        else:
            break
    if state is None:
        pertama = ev[0] if ev else None
        if pertama is None:
            return None
        since = max(mulai, pertama.timestamp)
        state = pertama.event_type

    inner = [e for e in ev if e.timestamp > mulai]
    # Raw DOWN intervals are stored before clipping so the UI can explain wall-clock vs. observed downtime.
    selang = []
    insiden = 0
    start_down = since if state == "DOWN" else None
    if state == "DOWN":
        insiden += 1

    for e in inner:
        if e.event_type == "DOWN" and start_down is None:
            start_down = e.timestamp
            insiden += 1
        elif e.event_type == "UP" and start_down is not None:
            selang.append((start_down, e.timestamp))
            start_down = None
    berlangsung = start_down is not None
    if berlangsung:
        selang.append((start_down, selesai))

    total_down = 0.0
    total_down_raw = 0.0
    for begin, end in selang:
        raw = (end - begin).total_seconds()
        total_down_raw += raw
        total_down += max(0.0, raw - jeda.detik_tak_terpantau(
            daftar_jeda, begin, end))

    # The denominator is clipped too, not only the numerator; otherwise a healthy service during
    # a poller outage would look better than reality.
    tak_terpantau = jeda.detik_tak_terpantau(daftar_jeda, since, selesai)
    observed = (selesai - since).total_seconds() - tak_terpantau
    if observed <= 0:
        # Whole window unobserved: no basis for a number. None is read by the page as "no data yet".
        avail = None
        observed = 0.0
    else:
        avail = round(max(0.0, (observed - total_down) / observed) * 100, 3)

    last = (db.query(ServiceCheck)
                .filter(ServiceCheck.service_id == s.id)
                .order_by(desc(ServiceCheck.timestamp), desc(ServiceCheck.id))
                .first())

    has_category = bool(last and last.kategori)
    return {
        "id": s.id,
        "device_id": d.id,
        "device": d.name,
        "ip": d.ip_address,
        "nama": s.nama,
        "jenis": s.jenis,
        "port": s.port,
        "path": s.path,
        "aktif": s.aktif != 0,
        "ok": bool(last.ok) if last else None,
        "kode": last.kode if last else None,
        "waktu_ms": last.waktu_ms if last else None,
        "kategori": last.kategori if last else None,
        "kategori_teks": teks_kategori(last.kategori) if has_category else None,
        "terakhir_cek": last.timestamp.isoformat() if last else None,
        "availability": avail,
        "insiden": insiden,
        "total_down_detik": round(total_down),
        "total_down_teks": format_durasi(round(total_down)),
        "total_down_mentah_detik": round(total_down_raw),
        "berlangsung": berlangsung,
        "diamati_detik": round(observed),
        "diamati_teks": format_durasi(round(observed)),
        "tak_terpantau_detik": round(tak_terpantau),
        "tak_terpantau_teks": (format_durasi(round(tak_terpantau))
                               if tak_terpantau >= 1 else None),
    }


def layanan_semua(db, period):
    """All registered services with their state and availability."""
    mulai, selesai, label = rentang(period)
    line = (db.query(Service, Device)
             .join(Device, Device.id == Service.device_id)
             .order_by(Service.device_id, Service.id)
             .all())
    # Gaps are looked up once per device, not per service: `status_logs` has hundreds of thousands of rows.
    pause_device = {}
    hasil = []
    for s, d in line:
        if d.id not in pause_device:
            pause_device[d.id] = jeda.find_gaps(db, d.id, mulai, selesai)
        content = _hitung_layanan(db, s, d, mulai, selesai, pause_device[d.id])
        if content is None:
            content = {
                "id": s.id, "device_id": d.id, "device": d.name,
                "ip": d.ip_address, "nama": s.nama, "jenis": s.jenis,
                "port": s.port, "path": s.path, "aktif": s.aktif != 0,
                "ok": None, "kode": None, "waktu_ms": None,
                "kategori": None, "kategori_teks": None, "terakhir_cek": None,
                "availability": None, "insiden": 0, "total_down_detik": 0,
                "total_down_teks": "-", "total_down_mentah_detik": 0,
                "berlangsung": False, "diamati_detik": None,
                "diamati_teks": "-", "tak_terpantau_detik": 0,
                "tak_terpantau_teks": None,
            }
        hasil.append(content)

    aktif = [x for x in hasil if x["aktif"]]

    periode_detik = round(PERIODE.get(label, PERIODE["24h"]).total_seconds())
    observed = [x["diamati_detik"] for x in hasil
               if x.get("diamati_detik") is not None]
    # Uses `min`, not `max`: the most pessimistic coverage is the safest basis for a decision.
    diamati_detik = min(observed) if observed else None
    observed_max = max(observed) if observed else None
    periode_penuh = (diamati_detik is not None
                     and diamati_detik >= periode_detik * 0.99)
    return {
        "periode": label,
        "layanan": hasil,
        "total": len(hasil),
        "sehat": sum(1 for x in aktif if x["ok"] is True),
        "bermasalah": sum(1 for x in aktif if x["ok"] is False),
        "dijeda": len(hasil) - len(aktif),
        "periode_detik": periode_detik,
        "periode_teks": PERIODE_NAMA.get(label, label),
        "diamati_detik": diamati_detik,
        "diamati_teks": (format_durasi(diamati_detik)
                         if diamati_detik is not None else "-"),
        "diamati_maks_detik": observed_max,
        "diamati_maks_teks": (format_durasi(observed_max)
                              if observed_max is not None else "-"),
        "periode_penuh": periode_penuh,
    }


def riwayat_layanan(db, service_id, period, limit=100):
    """Incident history of one service, with the diagnosis of each event."""
    mulai, selesai, label = rentang(period)
    s = db.query(Service).filter(Service.id == service_id).first()
    if not s:
        return {"error": "Layanan tidak ditemukan"}
    d = db.query(Device).filter(Device.id == s.device_id).first()

    ev = (db.query(ServiceEvent)
          .filter(ServiceEvent.service_id == service_id,
                  ServiceEvent.timestamp >= mulai,
                  ServiceEvent.timestamp <= selesai)
          .order_by(desc(ServiceEvent.timestamp), desc(ServiceEvent.id))
          .all())

    riwayat = []
    for e in ev:
        if e.event_type != "DOWN" or e.kategori == "baseline":
            continue
        recover = (db.query(ServiceEvent)
                 .filter(ServiceEvent.service_id == service_id,
                         ServiceEvent.event_type == "UP",
                         ServiceEvent.timestamp > e.timestamp)
                 .order_by(ServiceEvent.timestamp)
                 .first())
        old = round(((recover.timestamp if recover else datetime.now())
                      - e.timestamp).total_seconds())
        riwayat.append({
            "id": e.id,
            "mulai": e.timestamp.isoformat(),
            "selesai": recover.timestamp.isoformat() if recover else None,
            "berlangsung": recover is None,
            "durasi_detik": old,
            "durasi_teks": format_durasi(old),
            "kategori": e.kategori,
            "kategori_teks": teks_kategori(e.kategori),
            "kode": e.kode,
            "detail": e.detail,
            "bukti": _urai_bukti(e.bukti),
            "saran": e.saran,
            "diagnosa_mulai": e.diagnosa_mulai,
            "diagnosa_pulih": e.diagnosa_pulih,
        })
        if len(riwayat) >= limit:
            break

    summarize = _hitung_layanan(db, s, d, mulai, selesai) if d else None
    return {
        "periode": label,
        "layanan": summarize,
        "riwayat": riwayat,
        "total_riwayat": len(riwayat),
    }


def layanan_device(db, device_id, period):
    """Services belonging to one device, for the device page."""
    semua = layanan_semua(db, period)
    semua["layanan"] = [x for x in semua["layanan"] if x["device_id"] == device_id]
    semua["total"] = len(semua["layanan"])
    return semua

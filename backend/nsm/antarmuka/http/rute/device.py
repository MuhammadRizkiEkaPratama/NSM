"""Device routes. Kept thin: parse, call one use case, return.
A separate `APIRouter` per area (instead of more lines in `main.py`) makes the boundary real:
device routes cannot quietly call firewall code because they do not import it.
"""
from datetime import datetime

from fastapi import APIRouter, Body, Depends, Response

import dialek_perangkat
import laporan_excel
import report_service
from connectors.ssh import SshConnector
from models import Device, DeviceEvent
from nsm.antarmuka.http import wiring
from nsm.antarmuka.http.media import XLSX
from nsm.aplikasi.kasus.lihat_device import LihatDevice
from nsm.infrastruktur.db.sesi import sesi

router = APIRouter(tags=["device"])


@router.get("/devices")
def daftar_device(db=Depends(wiring.beri_sesi)):
    """List of devices with their latest check result."""
    kasus = LihatDevice(wiring.beri_gudang_device(db), wiring.beri_gudang_denyut(db))
    return kasus.jalankan()


@router.post("/devices/{device_id}/aktif")
def set_aktif(device_id: int,
              aktif: bool = Body(..., embed=True),
              alasan: str = Body(None, embed=True),
              oleh: str = Body(None, embed=True), db=Depends(wiring.beri_sesi)):
    """Pause or resume monitoring of a device.

    The ONLY endpoint that writes to the database from the interface layer. It changes only NSM's
    own setting; no command is sent to the device. Old history is not touched.

    `alasan` is recorded so a legitimate pause can be told apart from a forgotten one. An empty
    reason is still accepted: forcing one makes people type "." which looks like an explanation.
    """
    d = db.query(Device).filter(Device.id == device_id).first()
    if not d:
        return {"error": "Device tidak ditemukan"}
    d.aktif = 1 if aktif else 0
    if d.aktif:
        # Resuming CLEARS the pause note; a leftover reason would read as a pause still in effect.
        d.jeda_alasan = d.jeda_sejak = d.jeda_oleh = None
    else:
        d.jeda_alasan = (alasan or "").strip()[:200] or None
        d.jeda_sejak = datetime.now()
        d.jeda_oleh = (oleh or "").strip()[:60] or None
    db.commit()
    return {
        "id": d.id,
        "name": d.name,
        "aktif": bool(d.aktif),
        "jeda_alasan": d.jeda_alasan,
        "jeda_sejak": d.jeda_sejak.isoformat() if d.jeda_sejak else None,
        "pesan": ("Pemantauan dilanjutkan" if d.aktif
                  else "Pemantauan dijeda — riwayat lama tetap tersimpan"),
    }


@router.post("/devices/{device_id}/penting")
def set_penting(device_id: int, penting: bool = Body(..., embed=True), db=Depends(wiring.beri_sesi)):
    """Turn email notifications on or off for a device.
    Only devices marked important send email on down and recovery; per-device on purpose, since
    alerts for everything become noise.
    """
    d = db.query(Device).filter(Device.id == device_id).first()
    if not d:
        return {"error": "Device tidak ditemukan"}
    d.penting = 1 if penting else 0

    old = 0
    if d.penting:
        # IMPORTANT: mark all OLD outages of this device as already sent, without sending. Unmarked
        # events were never processed, so turning the bell on would queue the whole history and send
        # it at once. Notifications apply only to outages after the switch is turned on.
        old = (db.query(DeviceEvent)
                .filter(DeviceEvent.device_id == d.id,
                        DeviceEvent.notif_terkirim.is_(None))
                .update({DeviceEvent.notif_terkirim: datetime.now()},
                        synchronize_session=False))
    db.commit()

    pesan = "Notifikasi dimatikan"
    if d.penting:
        pesan = ("Notifikasi dinyalakan — email dikirim saat device ini "
                 "bermasalah dan saat pulih")
        if old:
            pesan += (f". {old} gangguan lama dilewati supaya kotak "
                      f"masuk tidak langsung penuh")
    return {
        "id": d.id,
        "name": d.name,
        "penting": bool(d.penting),
        "gangguan_lama_dilewati": old,
        "pesan": pesan,
    }


@router.get("/devices/{device_id}/info")
def device_info(device_id: int):
    # The only route that closed its session without `finally`. It leaked only when the query itself
    # failed, which is exactly when the database is struggling. The response is unchanged.
    with sesi() as db:
        d = db.query(Device).filter(Device.id == device_id).first()
    if not d:
        return {"error": "Device tidak ditemukan"}
    if not d.platform:
        return {"device": d.name, "error": "Platform belum diisi untuk device ini"}
    # A device that is this machine itself is read directly, without SSH. See connectors/lokal.py.
    if dialek_perangkat.ambil(d.platform).lokal:
        try:
            from connectors.lokal import LokalConnector, ip_sekarang
            conn = LokalConnector(d.ip_address)
            data = conn.get_info()
            # An address that no longer matches is NOT a reason to refuse: data is read directly from the
            # right machine. Only warn that the row is stale; the poller fixes it next round.
            if not conn.ini_mesin_ini():
                data["Catatan alamat"] = (
                    f"Baris device masih menyimpan {d.ip_address}, sedangkan "
                    f"mesin ini sekarang memakai {ip_sekarang()}. Poller akan "
                    f"memperbaikinya otomatis.")
            return {"device": d.name, "data": data}
        except Exception as e:
            return {"device": d.name, "error": str(e)}
    try:
        conn = SshConnector(
            d.ip_address,
            platform=d.platform,
            username=d.username,
            password=d.password,
            key_path=d.ssh_key_path,
        )
        return {"device": d.name, "data": conn.get_info()}
    except Exception as e:
        return {"device": d.name, "error": str(e)}


@router.get("/devices/{device_id}/history")
def device_history(device_id: int, period: str = "24h", limit: int = 100, db=Depends(wiring.beri_sesi)):
    """Outage history of one device (when down, how long, category).
    Also carries `dampak_hilir`: how many OTHER devices have their path from NSM through this one
    ("if Switch A falls, 8 devices go dark"). Included here rather than as its own endpoint so
    one page needs one request.
    """
    hasil = report_service.riwayat_device(db, device_id, period, limit)
    try:
        import ketergantungan as _kg
        g = _kg.graf(db)
        hilir = _kg.hilir(db, device_id, g=g)
        complete, disconnect = _kg.graf_lengkap(db, g)
        hasil["dampak_hilir"] = {
            "jumlah": len(hilir),
            "daftar": [{"id": x["id"], "nama": x["nama"]} for x in hilir],
            # `pasti` distinguishes "nothing depends on it" from "NSM does not know": a 0 on an incomplete
            # graph must not read as a safety guarantee.
            "pasti": bool(complete),
            "tak_terjangkau": [x["nama"] for x in disconnect],
        }
    except Exception as e:
        hasil["dampak_hilir"] = {"jumlah": None, "daftar": [],
                                 "pasti": False, "galat": str(e)[:120]}
    return hasil


@router.get("/devices/{device_id}/bandwidth")
def device_bandwidth(device_id: int, period: str = "24h", db=Depends(wiring.beri_sesi)):
    """Per-interface traffic. Read-only, from samples the poller already collected; does not touch the device."""
    return report_service.bandwidth_device(db, device_id, period)


@router.get("/devices/{device_id}/chart")
def device_chart(device_id: int, points: int = 60, db=Depends(wiring.beri_sesi)):
    """Starting points for the ping and bandwidth charts. Called ONCE when the device page opens;
    the charts then grow from regular refresh data.
    """
    return report_service.data_grafik(db, device_id, points)


@router.get("/devices/{device_id}/export")
def device_export(device_id: int, period: str = "24h", oleh: str = "",
                  db=Depends(wiring.beri_sesi)):
    """Outage history of one device as an Excel file."""
    d = db.query(Device).filter(Device.id == device_id).first()
    nama = d.name if d else str(device_id)
    isi = laporan_excel.buat_laporan_device(db, device_id, period, oleh)
    return Response(content=isi, media_type=XLSX, headers={
        "X-Nama-Berkas": laporan_excel.nama_berkas("riwayat", nama),
    })


@router.get("/devices/{device_id}/latest")
def device_latest(device_id: int, db=Depends(wiring.beri_sesi)):
    """Latest points for the chart. Lightweight, called every 5 seconds."""
    return report_service.data_terbaru(db, device_id)


@router.get("/devices/bandwidth-terkini")
def bandwidth_terkini(db=Depends(wiring.beri_sesi)):
    """Latest rate of ALL devices at once, for the dashboard cards.
    Not a loop over `/devices/{id}/latest`: the dashboard refreshes every 5 s, and one request
    per device would mean dozens per minute through Java, Python and the database.
    """
    return report_service.bandwidth_terkini_semua(db)


@router.get("/devices/{device_id}/events")
def device_events(device_id: int, period: str = "24h", limit: int = 200, db=Depends(wiring.beri_sesi)):
    """Daftar event mentah UP/DOWN device (penelusuran detail)."""
    return report_service.event_mentah(db, device_id, period, limit)

"""`topologi` section of report_service."""
import hashlib
import json
from datetime import datetime, timedelta
from sqlalchemy import func
from models import (Device, Flow, DeviceLink)

from ._inti import (JENDELA_TOPOLOGI_MENIT, PORT_UMUM, _di_luar_jaringan, _ip_bersih, _peta_layanan_port, status_sekarang)



def topologi(db):
    """Device relationship map for the dashboard topology view.

    Nodes are ALL registered devices, so a dead or quiet device still appears. Conversations
    with addresses unknown to NSM (not in `devices`) are reported as external nodes with
    `dikenal: false`, since traffic leaving the lab is worth seeing.

    Connections are de-duplicated exactly like `percakapan_jaringan()`: `flow_koneksi` rows are
    60-second snapshots, so only the LAST snapshot per 5-tuple is used, not the sum.
    """
    perangkat = db.query(Device).order_by(Device.id).all()
    map_ip_id = {d.ip_address: d.id for d in perangkat if d.ip_address}
    map_service = _peta_layanan_port(db)

    simpul = []
    for d in perangkat:
        s = status_sekarang(db, d.id)
        if s is None:
            status = "tanya"
        else:
            status = "up" if s.is_reachable else "down"
        simpul.append({
            "id": d.id,
            "nama": d.name,
            "ip": d.ip_address,
            "lokasi": d.location,
            "jenis": d.device_type,
            "platform": d.platform,
            "status": status,
        })

    limit = datetime.now() - timedelta(minutes=JENDELA_TOPOLOGI_MENIT)

    line = (
        db.query(Flow.device_id, Flow.ip_lokal, Flow.port_lokal,
                 Flow.ip_lawan, Flow.port_lawan,
                 func.max(Flow.byte_masuk), func.max(Flow.byte_keluar),
                 func.max(Flow.waktu))
        .filter(Flow.waktu >= limit)
        .group_by(Flow.device_id, Flow.ip_lokal, Flow.port_lokal,
                  Flow.ip_lawan, Flow.port_lawan)
        .all())

    # Step 2: merge per device PAIR, one map line per pair; port detail stays in `pintu`.
    agregat = {}
    for dev_id, _ip_local, port_lokal, ip_lawan, port_lawan, enter, keluar, terakhir in line:
        opposite_clean = _ip_bersih(ip_lawan)
        id_opposite = map_ip_id.get(opposite_clean)
        kunci = (dev_id, id_opposite if id_opposite else opposite_clean)
        a = agregat.setdefault(kunci, {
            "dari_id": dev_id,
            "ke_id": id_opposite,
            "ke_alamat": None if id_opposite else opposite_clean,
            "dikenal": id_opposite is not None,
            "luar_jaringan": _di_luar_jaringan(opposite_clean),
            "koneksi": 0,
            "byte_masuk": 0.0,
            "byte_keluar": 0.0,
            "terakhir": None,
            "_pintu": {},
        })
        a["koneksi"] += 1
        a["byte_masuk"] += float(enter or 0)
        a["byte_keluar"] += float(keluar or 0)

        # Actual SERVICE port, not the raw remote port. A connection recorded on the server side
        # has a random client ephemeral port as its "remote" port. Same selection rule as
        # `percakapan_jaringan()`: NSM registration wins over guessing from well-known ports.
        reg_local = map_service.get((dev_id, int(port_lokal))) if port_lokal else None
        reg_opposite = (map_service.get((id_opposite, int(port_lawan)))
                     if id_opposite and port_lawan else None)
        um_local = PORT_UMUM.get(int(port_lokal)) if port_lokal else None
        um_opposite = PORT_UMUM.get(int(port_lawan)) if port_lawan else None

        if reg_local:
            port_gate, name_gate = port_lokal, reg_local
        elif reg_opposite:
            port_gate, name_gate = port_lawan, reg_opposite
        elif um_local:
            port_gate, name_gate = port_lokal, um_local
        elif um_opposite:
            port_gate, name_gate = port_lawan, um_opposite
        else:
            port_gate, name_gate = None, None

        if port_gate:
            # Dict key rather than a set: if the same port appears both unnamed and named, the named version wins.
            key_p = int(port_gate)
            if key_p not in a["_pintu"] or name_gate:
                a["_pintu"][key_p] = name_gate

        if terakhir and (a["terakhir"] is None or terakhir > a["terakhir"]):
            a["terakhir"] = terakhir

    tautan_lalu_lintas = []
    for a in agregat.values():
        pintu = a.pop("_pintu")
        a["pintu"] = [{"port": p, "nama": pintu[p]} for p in sorted(pintu)]
        a["terakhir"] = a["terakhir"].isoformat() if a["terakhir"] else None
        tautan_lalu_lintas.append(a)

    tautan_tetap = [{
        "id": t.id,
        "dari_id": t.device_a_id,
        "ke_id": t.device_b_id,
        "jenis": t.jenis,
        "keterangan": t.keterangan,
    } for t in db.query(DeviceLink).all()]

    hasil = {
        "perangkat": simpul,
        "tautan_lalu_lintas": tautan_lalu_lintas,
        "tautan_tetap": tautan_tetap,
        "jendela_menit": JENDELA_TOPOLOGI_MENIT,
        "diperiksa": datetime.now().isoformat(),
    }

    # Content fingerprint, so receivers can tell "nothing changed" without comparing raw text.
    #
    # It is computed here from content that excludes the timestamp. Otherwise the Java
    # "skip broadcast if identical to the previous beat" guard never fires, because `diperiksa`
    # differs on every response and browsers would redraw the whole map every two seconds.
    hasil["sidik"] = hashlib.sha1(
        json.dumps({k: v for k, v in hasil.items() if k != "diperiksa"},
                   sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return hasil

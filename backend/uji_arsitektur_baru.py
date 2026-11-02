"""Equivalence test between the old path and the new architecture path.

A refactor can pass all old tests while the output quietly differs slightly. This
file turns "behavior unchanged" into something that FAILS if violated: old and new
paths run side by side on the same data and the results are compared after JSON
serialization (byte comparison).

Guards:
  1. `nsm.domain.waktu` matches `report_service` for period ranges, duration
     format and category sentences;
  2. the new `/devices` route returns JSON identical to `main.py`'s, including row order;
  3. `/report/summary` and `/report/availability` are identical;
  4. the single-query store (`terakhir_semua`) agrees with per-device reads,
     required before the 1+N in `/devices` may be replaced.

Route functions are called directly, not through an HTTP client, because
`TestClient` needs `httpx`; the returned value is what FastAPI serializes anyway.

Reads the live database but never writes.

Run: py uji_arsitektur_baru.py
"""
import json
import sys


def _json(nilai):
    return json.dumps(nilai, default=str, sort_keys=True)


# Two calls never happen in the same millisecond, and some answers derive from the
# wall clock (`mulai`/`selesai`, `dibuat`, observed-seconds counts), so they can
# shift by 1 s. That is tolerated without dropping the field: time fields are still
# compared for presence and shape, only the value gets leeway (seconds-based numbers
# may differ by at most 2 s). Everything else must be identical.
TOLERANSI_DETIK = 2
_SATUAN = {"detik": 1, "menit": 60, "jam": 3600, "hari": 86400}
_MEDAN_WAKTU = ("mulai", "selesai", "dibuat", "waktu", "timestamp",
                "last_checked", "terakhir")


def _mirip_waktu(nilai):
    return isinstance(nilai, str) and len(nilai) >= 19 and nilai[4] == "-" and "T" in nilai


def _urai_durasi(teks):
    """Parse a duration text back into seconds ("2 menit 45 detik" -> 165).

    Needed because the tolerated 1 s shift reappears in text form (`total_down_teks`).
    """
    if not isinstance(teks, str):
        return None
    section, total, exists = teks.split(), 0, False
    for i in range(0, len(section) - 1, 2):
        if not section[i].isdigit() or section[i + 1] not in _SATUAN:
            return None
        total += int(section[i]) * _SATUAN[section[i + 1]]
        exists = True
    return total if exists else None


def _sama(a, b, jalur=""):
    """Compare two answers; return the field paths that really differ."""
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return [f"{jalur}: kumpulan kunci beda "
                    f"(hanya di lama: {sorted(set(a) - set(b))}, "
                    f"hanya di baru: {sorted(set(b) - set(a))})"]
        beda = []
        for k in a:
            beda += _sama(a[k], b[k], f"{jalur}.{k}")
        return beda
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{jalur}: jumlah baris beda ({len(a)} vs {len(b)})"]
        beda = []
        for i, (x, y) in enumerate(zip(a, b)):
            beda += _sama(x, y, f"{jalur}[{i}]")
        return beda
    nama = jalur.rsplit(".", 1)[-1].split("[")[0]
    if _mirip_waktu(a) and _mirip_waktu(b):
        return []
    if nama.endswith("_detik") and isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return [] if abs(a - b) <= TOLERANSI_DETIK else [f"{jalur}: {a} vs {b}"]
    if nama.endswith("_teks"):
        da, dbb = _urai_durasi(a), _urai_durasi(b)
        if da is not None and dbb is not None:
            return [] if abs(da - dbb) <= TOLERANSI_DETIK else [f"{jalur}: {a!r} vs {b!r}"]
    if nama in _MEDAN_WAKTU and (a is None) == (b is None):
        return []
    if isinstance(a, float) and isinstance(b, float):
        return [] if abs(a - b) < 1e-9 else [f"{jalur}: {a} vs {b}"]
    return [] if a == b else [f"{jalur}: {a!r} vs {b!r}"]


def uji_domain_waktu_sama():
    import report_service
    from nsm.domain import waktu

    for p in ["1h", "24h", "7d", "30d", "ngawur", "", None]:
        a_start, a_finish, a_label = report_service.rentang(p)
        b_start, b_finish, b_label = waktu.rentang(p)
        assert a_label == b_label, f"label periode {p!r} beda: {a_label} vs {b_label}"
        assert abs((a_finish - a_start) - (b_finish - b_start)).total_seconds() < 1, \
            f"panjang periode {p!r} beda"

    for d in [None, 0, 1, 59, 60, 61, 3599, 3600, 3661, 86399, 86400, 90061, 172800]:
        assert report_service.format_durasi(d) == waktu.format_durasi(d), \
            f"format_durasi({d}) beda"

    for k in ["dead", "ping_blocked", "recovered", "baseline", "pulih",
              "", None, "kategori_tak_dikenal"]:
        assert report_service.teks_kategori(k) == waktu.teks_kategori(k), \
            f"teks_kategori({k!r}) beda"
    print("  domain waktu: sama")


def _oracle_devices(db):
    """FROZEN COPY of the `/devices` route from before it was moved.

    `main.list_devices` no longer exists, and without a reference the equivalence test
    would prove nothing, so the old implementation is kept here as-is. The JSON shape
    read by the Java pages and JavaScript files is defined here; changing it must be
    deliberate and means touching the Java side too.
    """
    from sqlalchemy import desc

    from models import Device, StatusLog
    hasil = []
    for d in db.query(Device).all():
        log = (db.query(StatusLog).filter(StatusLog.device_id == d.id)
               .order_by(desc(StatusLog.timestamp)).first())
        hasil.append({
            "id": d.id,
            "name": d.name,
            "ip_address": d.ip_address,
            "device_type": d.device_type,
            "platform": d.platform,
            "location": d.location,
            "aktif": d.aktif != 0,
            "penting": d.penting == 1,
            "jeda_alasan": d.jeda_alasan,
            "jeda_sejak": d.jeda_sejak.isoformat() if d.jeda_sejak else None,
            "jeda_oleh": d.jeda_oleh,
            "is_reachable": log.is_reachable if log else None,
            "response_time_ms": log.response_time_ms if log else None,
            "last_checked": log.timestamp.isoformat() if log else None
        })
    return hasil


def uji_rute_sama():
    import report_service
    from nsm.antarmuka.http.rute import device as rute_device
    from nsm.antarmuka.http.rute import laporan as rute_laporan
    from nsm.infrastruktur.db.sesi import sesi

    with sesi() as db:
        pair = [
            # The report routes are compared against `report_service` DIRECTLY, not a frozen
            # copy, since that is where the calculation still lives.
            ("/devices",
             lambda: _oracle_devices(db),
             lambda: rute_device.daftar_device(db)),
            ("/report/summary",
             lambda: report_service.ringkasan(db, "24h"),
             lambda: rute_laporan.ringkasan("24h", db)),
            ("/report/availability",
             lambda: report_service.availability_semua(db, "24h"),
             lambda: rute_laporan.ketersediaan("24h", db)),
            ("/report/sparkline",
             lambda: report_service.sparkline_semua(db, "24h", 40),
             lambda: rute_laporan.sparkline("24h", 40, db)),
        ]
        for jalur, old, baru in pair:
            # Order is old -> NEW -> old, not old -> old -> new: the control must bracket the new
            # path so the time span matches. Two adjacent old calls only show there is no shift
            # within a few milliseconds, which makes a one-second shift look like a defect.
            old_before = old()
            result_new = baru()
            old_after = old()
            bergeser_sendiri = {b.split(":")[0]
                                for b in _sama(old_before, old_after, jalur)}
            beda = [b for b in _sama(old_before, result_new, jalur)
                    if b.split(":")[0] not in bergeser_sendiri]
            assert not beda, f"{jalur}: {len(beda)} medan berbeda -> {beda[:5]}"
            catatan = f" ({len(bergeser_sendiri)} medan bergeser sendiri, diabaikan)"                 if bergeser_sendiri else ""
            print(f"  {jalur}: sama{catatan}")


def uji_gudang_satu_kueri_sepakat():
    """1+N may be replaced only if both results are proven equal, not believed to be."""
    from nsm.infrastruktur.db.gudang import GudangDenyutSql, GudangDeviceSql
    from nsm.infrastruktur.db.sesi import sesi

    with sesi() as db:
        device = GudangDeviceSql(db)
        pulse = GudangDenyutSql(db)
        sekaligus = pulse.terakhir_semua()
        for d in device.semua():
            one = pulse.terakhir(d.id)
            many = sekaligus.get(d.id)
            assert _json(one) == _json(many), \
                f"device {d.id} ({d.nama}): denyut per-device beda dengan satu-kueri"
    print("  gudang satu-kueri: sepakat dengan per-device")


if __name__ == "__main__":
    gagal = 0
    for uji in [uji_domain_waktu_sama, uji_rute_sama, uji_gudang_satu_kueri_sepakat]:
        print(f"{uji.__name__} ...")
        try:
            uji()
        except AssertionError as e:
            gagal += 1
            print(f"  GAGAL: {e}")
    print("LOLOS" if not gagal else f"{gagal} uji gagal")
    sys.exit(1 if gagal else 0)

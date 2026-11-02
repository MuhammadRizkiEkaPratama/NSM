"""Test of `ringkas_layanan_per_device()`: service state on dashboard cards.

This path is separate from `layanan_semua()` because the dashboard refreshes
every 5 s, and `layanan_semua()` computes availability (scanning `status_logs`
and rebuilding `service_events`), which is wasteful for numbers the dashboard
does not show.

Tested:
1. Per-device grouping is correct; devices without services are absent.
2. Never checked (`ok: None`) is distinguished from down (`ok: False`).
3. Paused counts as neither healthy nor failing.
4. The LATEST check is the one read.

Run: py uji_layanan_ringkas.py
"""
import sys
from datetime import datetime, timedelta

lolos = 0
gagal = 0


def cek(nama, dapat, harap):
    global lolos, gagal
    if dapat == harap:
        lolos += 1
        print(f"  LOLOS  {nama}: {dapat}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama}: dapat {dapat!r}, harusnya {harap!r}")


def uji():
    print("=" * 74)
    print("ringkas_layanan_per_device(): keadaan layanan untuk kartu dashboard")
    print("=" * 74)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import database

    mesin = create_engine("sqlite://")
    original_engine, original_session = database.engine, database.SessionLocal
    database.engine = mesin
    database.SessionLocal = sessionmaker(bind=mesin)

    import models
    models.Base.metadata.create_all(mesin)
    db = database.SessionLocal()
    import report_service as rs

    t0 = datetime(2026, 7, 1, 12, 0, 0)

    def device(id_, nama):
        db.add(models.Device(id=id_, name=nama, ip_address=f"10.0.0.{id_}",
                             device_type="server", platform="linux", aktif=1))

    def layanan(id_, did, nama, jenis="tcp", port=22, aktif=1):
        db.add(models.Service(id=id_, device_id=did, nama=nama, jenis=jenis,
                              port=port, aktif=aktif))

    def cekan(sid, waktu, ok, kategori=None, kode=None):
        db.add(models.ServiceCheck(service_id=sid, timestamp=waktu, ok=ok,
                                   kode=kode, waktu_ms=1.0, kategori=kategori))

    device(1, "Web+SSH")
    layanan(1, 1, "SSH", port=22)
    layanan(2, 1, "Web", jenis="http", port=80)
    cekan(1, t0, True)
    cekan(2, t0, True)
    cekan(2, t0 + timedelta(minutes=5), False,
          kategori="koneksi_ditolak", kode=None)

    device(2, "Baru didaftarkan")
    layanan(3, 2, "MySQL", jenis="mysql", port=3306)

    device(3, "Sedang dijeda")
    layanan(4, 3, "SSH dijeda", port=22, aktif=0)
    cekan(4, t0, False, kategori="timeout")

    device(4, "Tanpa layanan")

    db.commit()
    hasil = rs.ringkas_layanan_per_device(db)
    pd = hasil["per_device"]

    print("\nPengelompokan per device")
    cek("kunci device berupa teks, bukan angka",
        sorted(pd.keys()), ["1", "2", "3"])
    cek("device tanpa layanan tidak muncul sama sekali", "4" in pd, False)
    cek("device 1 punya dua layanan", pd["1"]["total"], 2)

    print("\nDevice 1: satu sehat, satu mati")
    cek("jumlah sehat", pd["1"]["sehat"], 1)
    cek("jumlah bermasalah", pd["1"]["bermasalah"], 1)
    web = next(s for s in pd["1"]["layanan"] if s["nama"] == "Web")
    cek("yang dibaca pemeriksaan TERAKHIR, bukan yang lama", web["ok"], False)
    cek("kalimat sebab ikut dikirim, disusun Python",
        web["kategori_teks"] is not None, True)
    ssh = next(s for s in pd["1"]["layanan"] if s["nama"] == "SSH")
    cek("layanan yang sehat tidak membawa kalimat sebab",
        ssh["kategori_teks"], None)

    print("\nDevice 2: belum pernah diperiksa BUKAN berarti mati")
    mysql = pd["2"]["layanan"][0]
    cek("ok bernilai None, bukan False", mysql["ok"], None)
    cek("tidak dihitung sehat", pd["2"]["sehat"], 0)
    cek("tidak dihitung bermasalah", pd["2"]["bermasalah"], 0)
    cek("terakhir_cek kosong", mysql["terakhir_cek"], None)

    print("\nDevice 3: dijeda tidak dihitung sehat maupun bermasalah")
    cek("jumlah dijeda", pd["3"]["dijeda"], 1)
    cek("tidak dihitung bermasalah walau cekan terakhirnya gagal",
        pd["3"]["bermasalah"], 0)
    cek("tidak dihitung sehat", pd["3"]["sehat"], 0)
    cek("ditandai tidak aktif", pd["3"]["layanan"][0]["aktif"], False)

    print("\nPenjaga: total selalu sama dengan jumlah tiga golongannya")
    for did, content in pd.items():
        not_yet = sum(1 for s in content["layanan"] if s["aktif"] and s["ok"] is None)
        cek(f"device {did}",
            content["sehat"] + content["bermasalah"] + content["dijeda"] + not_yet,
            content["total"])

    print("\nPenjaga: tidak ada lapangan availability yang bocor ke sini")
    leak = [k for s in pd["1"]["layanan"] for k in s
             if k in ("availability", "diamati_detik", "total_down_detik",
                      "insiden", "tak_terpantau_detik")]
    cek("tidak ada lapangan periode", leak, [])

    db.close()
    database.engine, database.SessionLocal = original_engine, original_session


if __name__ == "__main__":
    uji()
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

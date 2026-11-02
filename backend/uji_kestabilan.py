"""Test of `hitung_kestabilan()`: stable/unstable hysteresis (docs/design/NETWORK-STATUS.md).

Rules under test:
- STABLE -> UNSTABLE: at least `min_siklus` (default 3) DOWN events within the
  last `jendela_menit` (default 15) minutes.
- UNSTABLE -> STABLE: no DOWN for `pulih_menit` (default 10) minutes.
- The 'baseline' category is excluded.
- Status is computed from the whole history, not one report period.

Uses an in-memory SQLite database; config is monkeypatched so thresholds stay 3/15/10.

Run: py uji_kestabilan.py
"""
from datetime import datetime, timedelta

lolos = 0
gagal = 0


def cek(nama, dapat, harap, toleransi=0.6):
    global lolos, gagal
    if isinstance(harap, (int, float)) and isinstance(dapat, (int, float)):
        ok = abs(dapat - harap) <= toleransi
    else:
        ok = dapat == harap
    if ok:
        lolos += 1
        print(f"  LOLOS  {nama}: {dapat}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama}: dapat {dapat}, harusnya {harap}")


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print(f"  LOLOS  {nama} {ket}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama} {ket}")


def main():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import database

    mesin = create_engine("sqlite://")
    database.engine = mesin
    database.SessionLocal = sessionmaker(bind=mesin)

    import models
    models.Base.metadata.create_all(mesin)
    db = database.SessionLocal()

    import config
    import report_service as rs

    # Thresholds are pinned independently of the real .env contents.
    config.get_stabil_min_siklus = lambda: 3
    config.get_stabil_jendela_menit = lambda: 15
    config.get_stabil_pulih_menit = lambda: 10

    window = timedelta(minutes=15)
    recover = timedelta(minutes=10)

    def device(id_, nama):
        d = models.Device(id=id_, name=nama, ip_address=f"10.0.1.{id_}",
                          device_type="server", platform="linux", aktif=1)
        db.add(d)
        db.commit()
        return d

    def event(did, ts, tipe, kategori="dead"):
        db.add(models.DeviceEvent(device_id=did, timestamp=ts,
                                  event_type=tipe, category=kategori))
        db.commit()

    t0 = datetime(2026, 8, 19, 8, 0, 0)

    # =========================================================================
    print("=" * 78)
    print("1. Device tanpa satu pun gangguan -> stabil, tidak error")
    # =========================================================================
    device(1, "Sepi")
    hasil = rs.hitung_kestabilan(db, 1, t0)
    benar("device tanpa event sama sekali dianggap stabil", hasil["stabil"] is True)
    cek("lama_detik None (tidak pernah dipantau)", hasil["lama_detik"], None)

    # =========================================================================
    print("\n2. Di bawah ambang: 2 DOWN dalam 15 menit -> MASIH stabil")
    # =========================================================================
    device(2, "DuaKali")
    event(2, t0, "DOWN")
    event(2, t0 + timedelta(seconds=10), "UP", "recovered")
    event(2, t0 + timedelta(minutes=5), "DOWN")
    event(2, t0 + timedelta(minutes=5, seconds=10), "UP", "recovered")
    hasil = rs.hitung_kestabilan(db, 2, t0 + timedelta(minutes=6))
    benar("2 gangguan dalam 15 menit belum cukup", hasil["stabil"] is True)

    # =========================================================================
    print("\n3. TEPAT di ambang: DOWN ke-3 dalam 15 menit -> TIDAK STABIL")
    # =========================================================================
    ts3 = t0 + timedelta(minutes=10)
    event(2, ts3, "DOWN")
    event(2, ts3 + timedelta(seconds=10), "UP", "recovered")
    hasil = rs.hitung_kestabilan(db, 2, ts3 + timedelta(minutes=1))
    benar("DOWN ke-3 dalam jendela -> tidak stabil", hasil["stabil"] is False)
    cek("status mulai TEPAT di DOWN ke-3", hasil["sejak"], ts3.isoformat())
    cek("siklus_jendela mencatat 3", hasil["siklus_jendela"], 3)
    cek("lama_detik dihitung dari 'sejak' ke 'sekarang'",
        hasil["lama_detik"], 60)

    # =========================================================================
    print("\n4. Sudah tidak stabil, gangguan lanjutan: TETAP tidak stabil, "
          "'sejak' tidak mundur")
    # =========================================================================
    ts4 = ts3 + timedelta(minutes=2)
    event(2, ts4, "DOWN")
    event(2, ts4 + timedelta(seconds=5), "UP", "recovered")
    hasil = rs.hitung_kestabilan(db, 2, ts4 + timedelta(minutes=1))
    benar("masih tidak stabil", hasil["stabil"] is False)
    cek("'sejak' TIDAK berubah (masih DOWN ke-3, bukan ke-4)",
        hasil["sejak"], ts3.isoformat())
    cek("siklus_jendela bertambah jadi 4", hasil["siklus_jendela"], 4)

    # =========================================================================
    print("\n5. Hening 10 menit penuh sejak gangguan TERAKHIR -> STABIL lagi")
    # =========================================================================
    now5 = ts4 + recover + timedelta(seconds=1)
    hasil = rs.hitung_kestabilan(db, 2, now5)
    benar("hening 10 menit -> stabil lagi", hasil["stabil"] is True)
    cek("'sejak' pemulihan = waktu gangguan terakhir + 10 menit",
        hasil["sejak"], (ts4 + recover).isoformat())

    print("\n   PENJAGA ARAH SEBALIKNYA")
    now_b = ts4 + recover - timedelta(seconds=1)
    hasil = rs.hitung_kestabilan(db, 2, now_b)
    benar("hening 1 detik KURANG dari 10 menit -> masih tidak stabil",
          hasil["stabil"] is False)

    # =========================================================================
    print("\n6. Setelah pulih, siklus baru butuh min_siklus LAGI dari nol "
          "(bukan lanjut dari yang lama)")
    # =========================================================================
    device(3, "PulihLaluGoyahLagi")
    a = t0
    event(3, a, "DOWN")
    event(3, a + timedelta(seconds=5), "UP", "recovered")
    b = a + timedelta(minutes=5)
    event(3, b, "DOWN")
    event(3, b + timedelta(seconds=5), "UP", "recovered")
    c = b + timedelta(minutes=5)
    event(3, c, "DOWN")
    event(3, c + timedelta(seconds=5), "UP", "recovered")
    d = c + recover + timedelta(minutes=1)
    event(3, d, "DOWN")
    event(3, d + timedelta(seconds=5), "UP", "recovered")
    hasil = rs.hitung_kestabilan(db, 3, d + timedelta(seconds=30))
    benar("satu gangguan setelah pulih penuh TIDAK langsung tidak-stabil lagi "
          "(siklus mulai dari nol)", hasil["stabil"] is True)
    cek("siklus_jendela nol karena sedang stabil", hasil["siklus_jendela"], 0)

    # =========================================================================
    print("\n7. Baseline dikecualikan: 3 DOWN berkategori baseline TIDAK "
          "memicu tidak-stabil")
    # =========================================================================
    device(4, "BaselineSaja")
    e = t0
    event(4, e, "DOWN", "baseline")
    event(4, e + timedelta(minutes=1), "DOWN", "baseline")
    event(4, e + timedelta(minutes=2), "DOWN", "baseline")
    hasil = rs.hitung_kestabilan(db, 4, e + timedelta(minutes=3))
    benar("DOWN berkategori baseline diabaikan", hasil["stabil"] is True)

    # =========================================================================
    print("\n8. Batas jendela: DOWN ke-3 TEPAT di tepi 15 menit ikut "
          "dihitung, sedikit LEWAT tidak")
    # =========================================================================
    device(5, "TepiJendela")
    f = t0
    event(5, f, "DOWN")
    event(5, f + timedelta(seconds=5), "UP", "recovered")
    event(5, f + timedelta(minutes=7), "DOWN")
    event(5, f + timedelta(minutes=7, seconds=5), "UP", "recovered")
    exact_edge = f + window
    event(5, exact_edge, "DOWN")
    event(5, exact_edge + timedelta(seconds=5), "UP", "recovered")
    hasil = rs.hitung_kestabilan(db, 5, exact_edge + timedelta(seconds=30))
    benar("DOWN tepat di tepi jendela (15:00) ikut terhitung -> tidak stabil",
          hasil["stabil"] is False)

    device(6, "LewatJendela")
    g = t0
    event(6, g, "DOWN")
    event(6, g + timedelta(seconds=5), "UP", "recovered")
    event(6, g + timedelta(minutes=7), "DOWN")
    event(6, g + timedelta(minutes=7, seconds=5), "UP", "recovered")
    via_edge = g + window + timedelta(seconds=1)
    event(6, via_edge, "DOWN")
    event(6, via_edge + timedelta(seconds=5), "UP", "recovered")
    hasil = rs.hitung_kestabilan(db, 6, via_edge + timedelta(seconds=30))
    benar("DOWN 1 detik LEWAT dari jendela pertama -> gangguan #1 sudah "
          "kadaluarsa, masih stabil (cuma 2 dalam jendela sekarang)",
          hasil["stabil"] is True)

    # =========================================================================
    print("\n9. Kerusakan sengaja ditanam: min_siklus dipaksa 1 -> harus "
          "langsung tidak stabil di DOWN pertama (menguji uji ini sendiri)")
    # =========================================================================
    config.get_stabil_min_siklus = lambda: 1
    device(7, "UjiRusak")
    h = t0
    event(7, h, "DOWN")
    hasil = rs.hitung_kestabilan(db, 7, h + timedelta(seconds=1))
    benar("dengan min_siklus=1, satu DOWN saja sudah tidak stabil "
          "(kalau ini GAGAL, ujinya sendiri yang salah, bukan kodenya)",
          hasil["stabil"] is False)
    config.get_stabil_min_siklus = lambda: 3  # kembalikan

    print()
    print("=" * 78)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 78)
    return gagal == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)

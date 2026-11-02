"""Test of `hitung_kualitas_sambungan()`: packet-loss verdict (docs/design/NETWORK-STATUS.md).

Verdict thresholds (report_service.KEHILANGAN_BAGUS/CUKUP/BURUK):
  < 1% bagus   >= 1% cukup   >= 5% buruk   >= 15% sangat_buruk

Uses no StatusRollupJam, so only the verdict is tested (merging is covered in
uji_rollup.py). 1000 samples make each failed row exactly 0.1%, so the exact
1.0 / 5.0 / 15.0 boundaries can be tested without rounding.

Run: py uji_kualitas_sambungan.py
"""
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

    import report_service as rs

    t0 = datetime(2026, 8, 19, 6, 0, 0)
    sample = 1000

    def device(id_, nama):
        d = models.Device(id=id_, name=nama, ip_address=f"10.0.2.{id_}",
                          device_type="server", platform="linux", aktif=1)
        db.add(d)
        db.commit()
        return d

    def isi(did, gagal_n, latensi_maks=None):
        """N sample rows, `gagal_n` of them with is_reachable=False (RTO)."""
        t = t0
        for i in range(sample):
            alive = i >= gagal_n
            rtt = None
            if alive:
                rtt = 10.0
                if latensi_maks is not None and i == sample - 1:
                    rtt = latensi_maks
            db.add(models.StatusLog(device_id=did, timestamp=t,
                                    is_reachable=alive, response_time_ms=rtt))
            t += timedelta(seconds=1)
        db.commit()

    KASUS = [
        # (device_id, gagal, persen_diharap, vonis_diharap)
        (1, 0,   0.0, "bagus"),
        (2, 9,   0.9, "bagus"),  # just BELOW the bagus/cukup boundary
        (3, 10,  1.0, "cukup"),  # EXACTLY at the boundary -> cukup
        (4, 49,  4.9, "cukup"),  # just BELOW the cukup/buruk boundary
        (5, 50,  5.0, "buruk"),  # EXACTLY at the boundary -> buruk
        (6, 149, 14.9, "buruk"),  # just BELOW the buruk/sangat_buruk boundary
        (7, 150, 15.0, "sangat_buruk"),
        (8, 999, 99.9, "sangat_buruk"),
    ]

    print("=" * 78)
    print("1. Batas vonis, persis di tepi (1000 sampel supaya presisi 0,1%)")
    print("=" * 78)
    for did, gagal_n, percent_expected, verdict_expected in KASUS:
        device(did, f"Kasus{did}")
        isi(did, gagal_n)
        hasil = rs.hitung_kualitas_sambungan(db, did, f"uji{did}", t0)
        cek(f"device {did} ({gagal_n}/{sample} gagal): kehilangan_persen",
            hasil["kehilangan_persen"], percent_expected)
        cek(f"device {did}: vonis", hasil["vonis"], verdict_expected)

    print("\n" + "=" * 78)
    print("2. Device tanpa satu pun sampel -> None, BUKAN 0%")
    print("=" * 78)
    device(9, "TidakPernahDipantau")
    hasil = rs.hitung_kualitas_sambungan(db, 9, "uji9", t0)
    cek("kehilangan_persen None (bukan 0.0 -- beda arti)",
        hasil["kehilangan_persen"], None)
    cek("vonis None", hasil["vonis"], None)
    cek("sampel 0", hasil["sampel"], 0)

    print("\n" + "=" * 78)
    print("3. latensi_maks_ms mengambil nilai TERTINGGI, bukan rata-rata")
    print("=" * 78)
    device(10, "LatensiTinggi")
    isi(10, gagal_n=5, latensi_maks=987.6)
    hasil = rs.hitung_kualitas_sambungan(db, 10, "uji10", t0)
    cek("latensi_maks_ms = nilai tertinggi yang disisipkan",
        hasil["latensi_maks_ms"], 987.6)

    print("\n   PENJAGA ARAH SEBALIKNYA")
    benar("latensi_maks_ms BUKAN nilai kecil (rata-rata 10.0)",
          hasil["latensi_maks_ms"] != 10.0,
          f"-> dapat {hasil['latensi_maks_ms']}, seharusnya bukan rata-rata")

    print()
    print("=" * 78)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 78)
    return gagal == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)

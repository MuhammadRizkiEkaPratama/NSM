"""Tests for hourly rollups: save space without changing what the numbers mean.
Checks:
 1. An hourly rollup matches a recompute from raw rows.
 2. The combined average over several hours matches the average over all raw rows (not an average of averages).
 3. The current, running hour is never rolled up.
 4. Rebuilding does not duplicate rows and gives identical results.
 5. An hour with no samples produces no zero row.
 6. `sampel_naik` and `latency_sampel` may differ: a device proven alive by TCP is reachable without latency.
 7. `pangkas_data` refuses to delete raw rows not yet rolled up.
 8. The shrinkage is large.
Run: py uji_rollup.py
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


def dekat(nama, dapat, harap, toleransi=1e-9):
    global lolos, gagal
    if dapat is not None and harap is not None and abs(dapat - harap) <= toleransi:
        lolos += 1
        print(f"  LOLOS  {nama}: {dapat}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama}: dapat {dapat!r}, harusnya {harap!r}")


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print(f"  LOLOS  {nama}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama} {ket}")


def uji():
    print("=" * 74)
    print("Ringkasan per jam: hemat ruang tanpa mengubah arti angkanya")
    print("=" * 74)

    from sqlalchemy import create_engine, func, case
    from sqlalchemy.orm import sessionmaker
    import database

    mesin = create_engine("sqlite://")
    original_engine, original_session = database.engine, database.SessionLocal
    database.engine = mesin
    database.SessionLocal = sessionmaker(bind=mesin)

    import models
    models.Base.metadata.create_all(mesin)
    db = database.SessionLocal()

    import rollup

    db.add(models.Device(id=1, name="Uji rollup", ip_address="10.0.0.1",
                         device_type="server", platform="linux", aktif=1))
    db.commit()

    # Test data is deliberately uneven (100 samples in the first hour, 4 in the second); equal counts would hide the average-of-averages mistake.
    jam1 = datetime(2026, 8, 1, 10, 0, 0)
    jam2 = datetime(2026, 8, 1, 11, 0, 0)

    for i in range(100):
        db.add(models.StatusLog(device_id=1, timestamp=jam1 + timedelta(seconds=i * 30),
                                is_reachable=True, response_time_ms=10.0,
                                sumber="icmp"))
    for i in range(4):
        db.add(models.StatusLog(device_id=1, timestamp=jam2 + timedelta(seconds=i * 30),
                                is_reachable=True, response_time_ms=100.0,
                                sumber="icmp"))
    db.commit()

    print("\n1. Ringkasan satu jam cocok dengan baris mentahnya")
    written, sampai = rollup.bangun(db, sampai=jam2 + timedelta(hours=1))
    db.commit()
    cek("dua jam diringkas", written, 2)

    r1 = (db.query(models.StatusRollupJam)
          .filter(models.StatusRollupJam.jam == jam1).first())
    cek("sampel jam pertama", r1.sampel, 100)
    cek("sampel naik jam pertama", r1.sampel_naik, 100)
    dekat("jumlah latency jam pertama", r1.latency_jumlah, 1000.0)
    cek("cacah latency jam pertama", r1.latency_sampel, 100)
    dekat("latency terkecil", r1.latency_min, 10.0)
    dekat("latency terbesar", r1.latency_maks, 10.0)

    # ==================================================================
    print("\n2. JEBAKAN RATA-RATA DARI RATA-RATA")
    # Correct: (100 x 10 + 4 x 100) / 104 = 13.46. Wrong (average of hourly averages): (10 + 100) / 2 = 55.0.
    raw_count = db.query(func.sum(models.StatusLog.response_time_ms)).scalar()
    raw_tally = db.query(func.count(models.StatusLog.response_time_ms)).scalar()
    correct_average = round(raw_count / raw_tally, 2)
    print(f"       dari baris mentah  : {raw_count} / {raw_tally} "
          f"= {correct_average}")
    print(f"       kalau dirata-ratakan lagi: (10 + 100) / 2 = 55.0  <- SALAH")

    ring = rollup.ringkas_periode(db, 1, jam1, jam2 + timedelta(hours=1))
    cek("total sampel gabungan", ring["sampel"], 104)
    dekat("rata latency dari ringkasan COCOK dengan dari mentah",
          ring["latency_rata"], correct_average, 0.01)
    benar("dan BUKAN 55,0 yang keluar dari merata-ratakan rata-rata",
          abs(ring["latency_rata"] - 55.0) > 1,
          f"-> dapat {ring['latency_rata']}, itu angka dari cara yang salah")
    dekat("latency terkecil gabungan", ring["latency_min"], 10.0)
    dekat("latency terbesar gabungan", ring["latency_maks"], 100.0)

    print("\n3. Jam yang SEDANG BERJALAN tidak pernah diringkas")
    sekarang = datetime.now()
    db.add(models.StatusLog(device_id=1, timestamp=sekarang,
                            is_reachable=True, response_time_ms=5.0,
                            sumber="icmp"))
    db.commit()
    rollup.bangun(db)
    db.commit()
    jam_ini = rollup.awal_jam(sekarang)
    ada = (db.query(models.StatusRollupJam)
           .filter(models.StatusRollupJam.jam == jam_ini).count())
    cek("tidak ada baris ringkasan untuk jam berjalan", ada, 0)
    print("       (barisnya belum lengkap; angka setengah jadi yang tersimpan")
    print("        permanen lebih berbahaya daripada angka yang belum ada)")

    print("\n4. Membangun ulang: tidak menggandakan, hasilnya sama")
    before = db.query(func.count(models.StatusRollupJam.id)).scalar()
    value_before = (r1.sampel, r1.latency_jumlah, r1.latency_sampel)
    rollup.bangun(db, sampai=jam2 + timedelta(hours=1), ulang_dari=jam1)
    db.commit()
    after = db.query(func.count(models.StatusRollupJam.id)).scalar()
    cek("jumlah baris tidak bertambah", after, before)
    r1b = (db.query(models.StatusRollupJam)
           .filter(models.StatusRollupJam.jam == jam1).first())
    cek("angkanya sama persis",
        (r1b.sampel, r1b.latency_jumlah, r1b.latency_sampel), value_before)

    print("\n5. Jam tanpa sampel tidak menghasilkan baris nol")
    jam3 = datetime(2026, 8, 1, 12, 0, 0)
    empty = rollup.compute_hour(db, 1, jam3)
    cek("jam tanpa sampel dijawab None", empty, None)
    ada3 = (db.query(models.StatusRollupJam)
            .filter(models.StatusRollupJam.jam == jam3).count())
    cek("dan tidak meninggalkan baris di tabel", ada3, 0)
    print("       (\"nol sampel\" dan \"nol sampel berhasil\" dua keadaan yang")
    print("        sangat berbeda; menyimpannya sebagai nol membuat jam ketika")
    print("        POLLER mati terbaca sebagai jam ketika PERANGKAT mati)")

    print("\n6. Device yang hidup lewat TCP: terjangkau, tanpa latency")
    jam4 = datetime(2026, 8, 2, 9, 0, 0)
    for i in range(6):
        db.add(models.StatusLog(device_id=1, timestamp=jam4 + timedelta(seconds=i * 60),
                                is_reachable=True, response_time_ms=None,
                                sumber="tcp"))
    # Dead rows may still carry rtt 0.0 (icmplib returns zero when there is no reply); including them would make latency_min 0.0 ms for every device.
    for i in range(5):
        db.add(models.StatusLog(device_id=1,
                                timestamp=jam4 + timedelta(seconds=1500 + i * 60),
                                is_reachable=False, response_time_ms=0.0,
                                sumber="icmp"))
    for i in range(4):
        db.add(models.StatusLog(device_id=1,
                                timestamp=jam4 + timedelta(seconds=600 + i * 60),
                                is_reachable=True, response_time_ms=20.0,
                                sumber="icmp"))
    db.commit()
    rollup.bangun(db, sampai=jam4 + timedelta(hours=1), ulang_dari=jam4)
    db.commit()
    r4 = (db.query(models.StatusRollupJam)
          .filter(models.StatusRollupJam.jam == jam4).first())
    cek("lima belas sampel, sepuluh terjangkau", (r4.sampel, r4.sampel_naik), (15, 10))
    cek("tetapi hanya empat yang punya latency", r4.latency_sampel, 4)
    print()
    print("   PENJAGA: baris MATI ber-rtt 0.0 tidak boleh ikut terhitung")
    dekat("latency terkecil bukan 0,0 melainkan 20,0", r4.latency_min, 20.0)
    r4r = rollup.ringkas_periode(db, 1, jam4, jam4 + timedelta(hours=1))
    dekat("rata latency dihitung dari 4, bukan dari 10",
          r4r["latency_rata"], 20.0, 0.01)
    print("       (kalau dibagi 10 hasilnya 8,0 — device yang ICMP-nya diblokir")
    print("        akan terlihat DUA SETENGAH KALI lebih cepat dari kenyataan)")

    print("\n7. Pemangkas MENOLAK membuang yang belum sempat diringkas")
    # The guard function is actually called, not imitated; in the lab it can never trigger naturally (oldest data is far younger than the prune limit).
    import pangkas_data
    last = rollup.jam_terakhir_diringkas(db)
    benar("ringkasan punya jam terakhir", last is not None)

    # Dangerous state: old rows to delete, but the rollup has not reached the limit.
    limit_danger = last + timedelta(days=10)
    boleh, sampai, tua = pangkas_data.boleh_pangkas_status_logs(db, limit_danger)
    benar("ada baris tua yang jadi sasaran pembuangan", tua > 0, f"-> {tua}")
    cek("ringkasan tertinggal -> TIDAK boleh membuang", boleh, False)

    # SAFE state: the summary is already past the purge boundary.
    limit_safe = last - timedelta(days=1)
    boleh2, _s, tua2 = pangkas_data.boleh_pangkas_status_logs(db, limit_safe)
    cek("ringkasan sudah melewati batas -> boleh membuang", boleh2, True)

    boleh3, _s3, tua3 = pangkas_data.boleh_pangkas_status_logs(
        db, datetime(2020, 1, 1))
    cek("tidak ada baris tua -> tidak ada yang perlu dijaga",
        (boleh3, tua3), (True, 0))

    print("\n   PENJAGA ARAH SEBALIKNYA")
    # A guard that always refuses is as useless as one that always allows: pruning would silently stop and the database would grow.
    benar("penjaga tidak menolak semua keadaan",
          boleh2 is True and boleh3 is True,
          "-> penjaga yang selalu menolak membuat pemangkasan berhenti "
          "bekerja diam-diam")

    # ==================================================================
    print("\n7b. Gabungan ringkasan + mentah COCOK PERSIS dengan mentah saja")
    # Decides whether reports may read rollups at all. Rollups hold only completed, already-rolled hours, so reading them alone drops the partial first hour, the running hour and unrolled hours. Windows vary: on the hour, mid-hour, very short, across a gap, past the rollup boundary.
    jendela = [
        (jam1, jam2 + timedelta(hours=1)),
        (jam1 + timedelta(minutes=17), jam2 + timedelta(minutes=41)),
        (jam1 + timedelta(minutes=59), jam1 + timedelta(minutes=61)),
        (jam1 - timedelta(hours=3), datetime.now()),       # melewati batas ringkasan
        (datetime(2026, 8, 1, 12), datetime(2026, 8, 1, 13)),
        (jam4, jam4 + timedelta(hours=1)),
        (jam1, datetime.now()),                            # seluruhnya
    ]
    all_match = True
    print("       %-46s %10s %10s" % ("jendela", "gabungan", "mentah"))
    for a, b in jendela:
        jum, cac, small, large = rollup.latency_periode(db, 1, a, b)
        m = (db.query(func.sum(models.StatusLog.response_time_ms),
                      func.count(models.StatusLog.response_time_ms),
                      func.min(models.StatusLog.response_time_ms),
                      func.max(models.StatusLog.response_time_ms))
             .filter(models.StatusLog.device_id == 1,
                     models.StatusLog.timestamp >= a,
                     models.StatusLog.timestamp < b,
                     models.StatusLog.is_reachable == True).first())
        m_jum, m_cac = float(m[0] or 0.0), int(m[1] or 0)
        cocok = (abs(jum - m_jum) < 1e-6 and cac == m_cac
                 and small == m[2] and large == m[3])
        all_match = all_match and cocok
        label = a.strftime("%d/%m %H:%M") + " s.d. " + b.strftime("%d/%m %H:%M")
        print("       %-46s %10s %10s  %s"
              % (label, "%.1f/%d" % (jum, cac), "%.1f/%d" % (m_jum, m_cac),
                 "" if cocok else "<-- BEDA"))
    benar("ketujuh jendela memberi angka yang sama persis", all_match,
          "-> gabungan berselisih dengan hitungan mentah; laporan TIDAK boleh "
          "membaca ringkasan sampai ini cocok")

    # ------------------------------------------------------------------
    print("\n   sampel_periode() (Bagian E, kualitas sambungan) -- "
          "jendela yang sama, kali ini menghitung SEMUA ping, bukan cuma "
          "yang berhasil")
    # ------------------------------------------------------------------
    all_match_sample = True
    for a, b in jendela:
        sampel, sampel_naik = rollup.sampel_periode(db, 1, a, b)
        m = (db.query(func.count(models.StatusLog.id),
                      func.sum(case((models.StatusLog.is_reachable == True, 1),  # noqa: E712
                                    else_=0)))
             .filter(models.StatusLog.device_id == 1,
                     models.StatusLog.timestamp >= a,
                     models.StatusLog.timestamp < b).first())
        m_sample, m_rise = int(m[0] or 0), int(m[1] or 0)
        cocok = (sampel == m_sample and sampel_naik == m_rise)
        all_match_sample = all_match_sample and cocok
        if not cocok:
            label = a.strftime("%d/%m %H:%M") + " s.d. " + b.strftime("%d/%m %H:%M")
            print(f"       <-- BEDA di {label}: gabungan {sampel}/{sampel_naik}, "
                  f"mentah {m_sample}/{m_rise}")
    benar("sampel_periode(): ketujuh jendela cocok dengan hitungan mentah",
          all_match_sample,
          "-> kehilangan paket (Bagian E) akan salah hitung di batas jam")

    print("\n   PENJAGA ARAH SEBALIKNYA")
    # If the rollup is empty, the combined result must fall back entirely to raw rows, not return zero.
    saved = db.query(models.StatusRollupJam).all()
    copy_of = [(x.device_id, x.jam, x.sampel, x.sampel_naik, x.latency_jumlah,
                x.latency_sampel, x.latency_min, x.latency_maks) for x in saved]
    db.query(models.StatusRollupJam).delete()
    db.commit()
    jum0, cac0, _k0, _b0 = rollup.latency_periode(db, 1, jam1, datetime.now())
    m0 = (db.query(func.sum(models.StatusLog.response_time_ms),
                   func.count(models.StatusLog.response_time_ms))
          .filter(models.StatusLog.device_id == 1,
                  models.StatusLog.timestamp >= jam1,
                  models.StatusLog.is_reachable == True).first())
    benar("tanpa ringkasan sama sekali, jawabannya tetap dari baris mentah",
          cac0 == int(m0[1] or 0) and abs(jum0 - float(m0[0] or 0)) < 1e-6,
          f"-> dapat {jum0}/{cac0}, seharusnya {m0[0]}/{m0[1]}")
    for d_ in copy_of:
        db.add(models.StatusRollupJam(
            device_id=d_[0], jam=d_[1], sampel=d_[2], sampel_naik=d_[3],
            latency_jumlah=d_[4], latency_sampel=d_[5],
            latency_min=d_[6], latency_maks=d_[7], dihitung=datetime.now()))
    db.commit()

    # --- 8. penyusutan -------------------------------------------------
    print("\n8. Penyusutan")
    lap = rollup.laporkan(db)
    print(f"       {lap['baris_mentah']:,} baris mentah -> "
          f"{lap['baris_ringkasan']:,} baris ringkasan "
          f"({lap['penyusutan']}x)")
    benar("ringkasan jauh lebih sedikit daripada mentah",
          lap["baris_ringkasan"] < lap["baris_mentah"],
          f"-> {lap['baris_ringkasan']} vs {lap['baris_mentah']}")

    db.close()
    database.engine, database.SessionLocal = original_engine, original_session


if __name__ == "__main__":
    uji()
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

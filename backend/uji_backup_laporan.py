"""Test the backup report from another machine.

The Backup Monitor page on `nsm-app` cannot inspect backup files: backups run on a
Windows laptop and `C:\\...` paths cannot exist on a Linux machine. The laptop now
REPORTS its state to the shared database and the page shows that report.

The key tests are the failure states, which fail silently if unguarded:
1. A STALE report showing green: it convinces people backups run when only a
   three-day-old report does. The page must flag it.
2. A problem the reporter saw but that is lost along the way (e.g. "restore
   verification failed" shown as a green page).

Run: py uji_backup_laporan.py
"""
import json
import os
import tempfile
from datetime import datetime, timedelta

lolos = 0
gagal = 0


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print("  LOLOS  %s" % nama)
    else:
        gagal += 1
        print("  GAGAL  %s %s" % (nama, ket))


import models          # noqa: E402
import backup_status   # noqa: E402


def siapkan():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    berkas = os.path.join(tempfile.mkdtemp(prefix="uji_bkp_"), "coba.db")
    mesin = create_engine("sqlite:///" + berkas)
    models.Base.metadata.create_all(mesin)
    return mesin, sessionmaker(bind=mesin)


CONTOH = {
    "sehat": True, "masalah": [], "folder_utama": r"C:\Users\<user>\NSM\backup",
    "folder_kedua": r"C:\Users\<user>\OneDrive\NSM-backup",
    "umur_jam": 10.7, "umur_teks": "10 jam 42 menit lalu",
    "terbaru": "nsm-backup-20260824-020000.zip",
    "jumlah_berkas": 10, "jumlah_berkas_kedua": 10, "total_mb": 311.28,
    "simpan_maksimal": 14,
    "berkas": [{"nama": "nsm-backup-20260824-020000.zip", "ukuran_mb": 31.2,
                "hasil": "lengkap", "salinan_kedua": True, "umur_teks": "10 jam lalu"}],
    "berkas_kedua": [], "riwayat": [], "jadwal": {"keadaan": "Ready"},
    "isi_terbaru": [{"nama": "nsm.sql", "ada": True}],
}


def write_report(Sesi, umur_jam, isi=None, mesin_nama="LAB-PC"):
    d = dict(CONTOH if isi is None else isi)
    with Sesi() as db:
        db.query(models.BackupLaporan).delete()
        db.add(models.BackupLaporan(
            waktu_lapor=datetime.now() - timedelta(hours=umur_jam),
            mesin=mesin_nama,
            isi=json.dumps(d, ensure_ascii=False),
            sehat=bool(d.get("sehat")), jumlah_berkas=d.get("jumlah_berkas"),
            total_mb=d.get("total_mb")))
        db.commit()


mesin, Sesi = siapkan()

# `laporan_terbaru()` and `ringkasan()` open the database via `database`; point it at this temporary database so the test never touches the primary lab instance.
import database  # noqa: E402
database.engine = mesin

# =============================================================================
print("=" * 74)
print("1. PEMBEDANYA HARUS BENAR-BENAR MEMBEDAKAN")
print("=" * 74)

with Sesi() as db:
    db.query(models.BackupLaporan).delete()
    db.commit()
benar("tanpa laporan, laporan_terbaru() mengembalikan None",
      backup_status.laporan_terbaru() is None)

write_report(Sesi, umur_jam=1)
lap = backup_status.laporan_terbaru()
benar("dengan laporan, ia mengembalikan isinya", lap is not None)
benar("nama mesin pelapor ikut", lap and lap.get("_mesin") == "LAB-PC",
      "-> %r" % (lap or {}).get("_mesin"))
benar("waktu lapor ikut sebagai datetime",
      lap and isinstance(lap.get("_waktu_lapor"), datetime))

# =============================================================================
print()
print("=" * 74)
print("2. LAPORAN SEGAR: DETAILNYA TAMPIL, DAN DITANDAI SEBAGAI LAPORAN")
print("=" * 74)

# Forced into the "other machine" branch regardless of the OS running the test.
asli = backup_status.bukan_mesin_backup
backup_status.bukan_mesin_backup = lambda folder: True
try:
    write_report(Sesi, umur_jam=1)
    r = backup_status.ringkasan()

    benar("jumlah berkas dari laporan TAMPIL, bukan nol",
          r.get("jumlah_berkas") == 10, "-> %r" % r.get("jumlah_berkas"))
    benar("total MB dari laporan tampil", r.get("total_mb") == 311.28,
          "-> %r" % r.get("total_mb"))
    benar("daftar berkasnya tampil, bukan kosong",
          len(r.get("berkas") or []) == 1, "-> %r" % len(r.get("berkas") or []))
    benar("isi zip terbaru ikut tampil", len(r.get("isi_terbaru") or []) == 1)
    benar("ditandai `dari_laporan`, bukan menyamar sebagai pemeriksaan langsung",
          r.get("dari_laporan") is True)
    benar("nama mesin pelapor disebut di halaman",
          r.get("laporan_mesin") == "LAB-PC", "-> %r" % r.get("laporan_mesin"))
    benar("umur laporan disebut", bool(r.get("laporan_umur_teks")),
          "-> %r" % r.get("laporan_umur_teks"))

    # `teks_umur()` takes SECONDS, not hours. Tested with a literal, since a `bool(text)`
    # check would pass for wrong but non-empty text.
    benar("laporan berumur 1 JAM tertulis dalam JAM, bukan detik",
          "jam" in r.get("laporan_umur_teks", "") and
          "detik" not in r.get("laporan_umur_teks", ""),
          "-> %r" % r.get("laporan_umur_teks"))
    benar("tidak ditandai basi", r.get("laporan_basi") is False)
    benar("sehat, karena pelapor bilang sehat dan laporannya segar",
          r.get("sehat") is True, "-> masalah %r" % r.get("masalah"))
    benar("keterangan menyebut ini LAPORAN, bukan pemeriksaan langsung",
          "LAPORAN" in (r.get("mesin_lain_ket") or ""),
          "-> %r" % (r.get("mesin_lain_ket") or "")[:70])

    # =========================================================================
    print()
    print("=" * 74)
    print("3. LAPORAN BASI: DITANDAI, BUKAN DITAMPILKAN HIJAU")
    print("=" * 74)

    write_report(Sesi, umur_jam=80)
    r = backup_status.ringkasan()
    benar("ditandai basi", r.get("laporan_basi") is True)
    benar("TIDAK sehat, walau pelapor bilang sehat",
          r.get("sehat") is False, "-> %r" % r.get("sehat"))
    benar("masalahnya menjelaskan bahwa angkanya keadaan SAAT ITU",
          any("SAAT ITU" in m for m in (r.get("masalah") or [])),
          "-> %r" % (r.get("masalah") or []))
    benar("masalahnya menyebut nama mesin yang harus dijalankan ulang",
          any("LAB-PC" in m for m in (r.get("masalah") or [])))
    benar("detailnya TETAP tampil (basi bukan alasan menyembunyikan)",
          r.get("jumlah_berkas") == 10)

    # Right at the threshold: 25 hours is still fine, 27 hours is stale.
    write_report(Sesi, umur_jam=25)
    benar("25 jam belum dianggap basi (harian yang lambat sedikit)",
          backup_status.ringkasan().get("laporan_basi") is False)
    write_report(Sesi, umur_jam=27)
    benar("27 jam sudah dianggap basi",
          backup_status.ringkasan().get("laporan_basi") is True)

    # =========================================================================
    print()
    print("=" * 74)
    print("4. MASALAH YANG DILIHAT PELAPOR TIDAK BOLEH HILANG DI JALAN")
    print("=" * 74)

    rusak = dict(CONTOH)
    rusak["sehat"] = False
    rusak["masalah"] = ["Verifikasi pemulihan Minggu lalu GAGAL",
                        "Salinan kedua tertinggal 3 berkas"]
    write_report(Sesi, umur_jam=1, isi=rusak)
    r = backup_status.ringkasan()
    benar("halaman TIDAK hijau saat pelapor melaporkan masalah",
          r.get("sehat") is False)
    benar("kedua masalahnya dibawa apa adanya",
          len(r.get("masalah") or []) == 2, "-> %r" % (r.get("masalah") or []))
    benar("kalimatnya tidak diubah-ubah",
          "Verifikasi pemulihan Minggu lalu GAGAL" in (r.get("masalah") or []))

    # =========================================================================
    print()
    print("=" * 74)
    print("5. BELUM ADA LAPORAN: KATAKAN CARANYA, BUKAN CUMA 'TIDAK BISA'")
    print("=" * 74)

    with Sesi() as db:
        db.query(models.BackupLaporan).delete()
        db.commit()
    r = backup_status.ringkasan()
    benar("dari_laporan False", r.get("dari_laporan") is False)
    benar("ada masalah yang menjelaskan keadaannya",
          len(r.get("masalah") or []) >= 1, "-> %r" % (r.get("masalah") or []))
    benar("masalahnya MENYEBUT skrip yang harus dijalankan",
          any("lapor_backup.py" in m for m in (r.get("masalah") or [])),
          "-> %r" % (r.get("masalah") or []))
finally:
    backup_status.bukan_mesin_backup = asli

# =============================================================================
print()
print("=" * 74)
print("6. BENTUK KELUARAN SAMA DI KEDUA CABANG")
print("=" * 74)

# The page must not have to guess whether a key exists; branch-dependent shapes make the page show "undefined".
r_normal = backup_status.ringkasan()
for k in ("dari_laporan", "laporan_mesin", "laporan_waktu",
          "laporan_umur_teks", "laporan_basi"):
    benar("jalur normal juga memuat '%s'" % k, k in r_normal)

# =============================================================================
print()
print("=" * 74)
print("%d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
raise SystemExit(1 if gagal else 0)

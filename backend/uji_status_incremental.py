"""Tests that the Backup page understands incremental backups as the primary method.
The page used to count only `nsm-backup-*.zip`, and `daftar_berkas()` is not recursive, so it could not see `backup/incremental/induk.zip`. The cases that must not fail silently:
  1. No full backup at all: still healthy (no false alarms).
  2. A stale induk.zip: problem, even if its size looks reasonable.
  3. An induk.zip with no `.sql` inside: problem, it cannot be restored.
  4. Missing `induk.meta.json`: problem, the next run would duplicate data.
Run: py uji_status_incremental.py
"""
import json
import os
import shutil
import tempfile
import zipfile
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


import config          # noqa: E402
import backup_status   # noqa: E402


AKAR = tempfile.mkdtemp(prefix="uji_inc_status_")
FOLDER_INC = os.path.join(AKAR, "incremental")


def create_parent(umur_jam=1.0, isi_sql=True, dengan_meta=True, salinan_umur_hari=None):
    """Build a fake incremental folder shaped like the real one."""
    shutil.rmtree(FOLDER_INC, ignore_errors=True)
    os.makedirs(FOLDER_INC, exist_ok=True)

    jalur = os.path.join(FOLDER_INC, "induk.zip")
    with zipfile.ZipFile(jalur, "w") as z:
        if isi_sql:
            # Large enough that `_mb()` does not round it to 0.0, so the test checks that the size is read.
            z.writestr("status_logs.sql",
                       "INSERT INTO status_logs VALUES (1);\n" * 20000)
            z.writestr("_lain_full.sql",
                       "INSERT INTO devices VALUES (1);\n" * 2000)
        else:
            # A valid zip with no .sql inside: plausible size, but not restorable.
            z.writestr("catatan.txt", "kosong")
    old = datetime.now() - timedelta(hours=umur_jam)
    os.utime(jalur, (old.timestamp(), old.timestamp()))

    if dengan_meta:
        with open(os.path.join(FOLDER_INC, "induk.meta.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"posisi": {"status_logs": 1250192,
                                  "bandwidth_samples": 972802},
                       "diperbarui": old.isoformat(),
                       "bootstrap_pada": "2026-08-20T00:54:19"}, f)

    if salinan_umur_hari is not None:
        for sub in ("mingguan", "bulanan"):
            d = os.path.join(FOLDER_INC, sub)
            os.makedirs(d, exist_ok=True)
            j = os.path.join(d, "induk-%s.zip" % sub)
            with zipfile.ZipFile(j, "w") as z:
                z.writestr("status_logs.sql", "x")
            t = (datetime.now() - timedelta(days=salinan_umur_hari)).timestamp()
            os.utime(j, (t, t))


# Point the main backup folder at a temp folder so real backups are never touched.
# The second location and manifest.log are also prepared: `ringkasan()` checks them separately from incremental, and their absence produces legitimate complaints.
LOKASI2 = os.path.join(AKAR, "salinan-kedua")
os.makedirs(LOKASI2, exist_ok=True)
with open(os.path.join(AKAR, "manifest.log"), "w", encoding="utf-8") as f:
    f.write("2026-08-24 03:00:29 induk.zip OK\n")

config.get_backup_dir = lambda: AKAR
config.get_backup_dir2 = lambda: LOKASI2

# =============================================================================
print("=" * 74)
print("1. PEMBEDANYA HARUS BENAR-BENAR MEMBEDAKAN")
print("=" * 74)

shutil.rmtree(FOLDER_INC, ignore_errors=True)
kosong = backup_status.keadaan_incremental()
benar("folder incremental TIDAK ada -> ada=False", kosong["ada"] is False)
benar("dan induk-nya None", kosong["induk"] is None)

create_parent(umur_jam=1)
isi = backup_status.keadaan_incremental()
benar("folder ADA -> ada=True", isi["ada"] is True)
benar("induk terbaca", isi["induk"] is not None)
benar("ukurannya terbaca, bukan nol",
      isi["induk"] and isi["induk"]["ukuran_mb"] > 0,
      "-> %r" % (isi["induk"] or {}).get("ukuran_mb"))

# =============================================================================
print()
print("=" * 74)
print("2. UMUR DITULIS DALAM SATUAN YANG BENAR")
print("=" * 74)

# `teks_umur()` takes SECONDS; tested against literal text, not just `bool(teks)`.
create_parent(umur_jam=3)
t = backup_status.keadaan_incremental()["induk"]["umur_teks"]
benar("induk berumur 3 JAM tertulis dalam jam, bukan detik",
      "jam" in t and "detik" not in t, "-> %r" % t)

# =============================================================================
print()
print("=" * 74)
print("3. TANPA BACKUP PENUH SAMA SEKALI -> TETAP SEHAT")
print("=" * 74)

# The main folder deliberately holds no `nsm-backup-*.zip`; only the incremental subfolder.
create_parent(umur_jam=2, salinan_umur_hari=3)
r = backup_status.ringkasan()
benar("nol berkas backup penuh terhitung", r["jumlah_berkas"] == 0,
      "-> %r" % r["jumlah_berkas"])
benar("TETAP sehat, karena incremental segar", r["sehat"] is True,
      "-> masalah %r" % r["masalah"])
benar("tidak ada keluhan 'belum ada satu pun berkas backup'",
      not any("Belum ada satu pun berkas" in m for m in r["masalah"]),
      "-> %r" % r["masalah"])
benar("keadaan incremental ikut dikirim ke halaman", "incremental" in r)
benar("induk-nya ikut", r["incremental"]["induk"] is not None)
benar("isi induk disebut per berkas SQL",
      any(x["nama"].endswith(".sql") for x in r["incremental"]["induk"]["isi"]))
benar("kedua salinan berkala ikut", len(r["incremental"]["salinan"]) == 2,
      "-> %d" % len(r["incremental"]["salinan"]))
benar("posisi per tabel ikut, untuk membuktikan incremental melacak sesuatu",
      len(r["incremental"]["posisi"]) == 2,
      "-> %r" % r["incremental"]["posisi"])

# =============================================================================
print()
print("=" * 74)
print("4. INDUK BASI -> BERMASALAH, WALAU BERKASNYA ADA")
print("=" * 74)

create_parent(umur_jam=80)
r = backup_status.ringkasan()
benar("TIDAK sehat", r["sehat"] is False, "-> %r" % r["sehat"])
benar("masalahnya menyebut umurnya",
      any("incremental terakhir berumur" in m for m in r["masalah"]),
      "-> %r" % r["masalah"])
benar("detailnya TETAP tampil (basi bukan alasan menyembunyikan)",
      r["incremental"]["induk"] is not None)

# Right at the threshold: 25 hours is fine, 27 hours is a problem.
create_parent(umur_jam=25)
benar("25 jam belum dianggap basi (harian yang lambat sedikit)",
      backup_status.ringkasan()["sehat"] is True)
create_parent(umur_jam=27)
benar("27 jam sudah dianggap basi",
      backup_status.ringkasan()["sehat"] is False)

# =============================================================================
print()
print("=" * 74)
print("5. INDUK YANG ISINYA TIDAK BISA DIPULIHKAN -> BERMASALAH")
print("=" * 74)

create_parent(umur_jam=1, isi_sql=False)
r = backup_status.ringkasan()
benar("zip tanpa satu pun .sql -> TIDAK sehat", r["sehat"] is False)
benar("masalahnya menyebut isinya, bukan umurnya",
      any(".sql" in m for m in r["masalah"]), "-> %r" % r["masalah"])

# =============================================================================
print()
print("=" * 74)
print("6. META HILANG -> BERMASALAH (putaran berikutnya akan menggandakan)")
print("=" * 74)

create_parent(umur_jam=1, dengan_meta=False)
r = backup_status.ringkasan()
benar("tanpa induk.meta.json -> TIDAK sehat", r["sehat"] is False)
benar("masalahnya menjelaskan akibatnya, bukan cuma 'berkas hilang'",
      any("sampai baris mana" in m for m in r["masalah"]),
      "-> %r" % r["masalah"])

# =============================================================================
print()
print("=" * 74)
print("7. SALINAN BERKALA YANG TERLAMBAT DISEGARKAN -> DITANDAI")
print("=" * 74)

create_parent(umur_jam=1, salinan_umur_hari=40)
inc = backup_status.keadaan_incremental()
benar("salinan mingguan berumur 40 hari ditandai terlambat",
      any(x["jenis"] == "mingguan" and x["terlambat"] for x in inc["salinan"]))
benar("salinan bulanan berumur 40 hari juga ditandai",
      any(x["jenis"] == "bulanan" and x["terlambat"] for x in inc["salinan"]))

create_parent(umur_jam=1, salinan_umur_hari=3)
inc = backup_status.keadaan_incremental()
benar("salinan berumur 3 hari TIDAK ditandai terlambat",
      not any(x["terlambat"] for x in inc["salinan"]))

shutil.rmtree(AKAR, ignore_errors=True)

# =============================================================================
print()
print("=" * 74)
print("%d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
raise SystemExit(1 if gagal else 0)

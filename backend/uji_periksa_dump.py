"""Test of `periksa_dump.py`: does a dump contain every live table?

Paired: a module that always answers "nothing missing" passes on an intact dump,
so a dump that is DELIBERATELY holed proves it works. A silent hole in a backup
(exit code 0, plausible size, SUCCESS manifest) is the failure this guards.

Also tested:

* a `CREATE TABLE` pattern split exactly at a read-chunk boundary (a 231 MB dump
  is streamed in 4 MB chunks, and a pattern on the seam would vanish silently);
* a table name appearing inside DATA (`INSERT INTO ... VALUES ('CREATE TABLE
  \\\\`fake\\\\`')`) must not count as an existing table.

Touches no network, database, or device.

Run: py uji_periksa_dump.py
"""
import os
import sys
import tempfile

import periksa_dump

lolos = 0
gagal = 0


def cek(nama, dapat, harap):
    global lolos, gagal
    if dapat == harap:
        lolos += 1
        print("  LOLOS  %s: %r" % (nama, dapat))
    else:
        gagal += 1
        print("  GAGAL  %s: dapat %r, harusnya %r" % (nama, dapat, harap))


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print("  LOLOS  %s" % nama)
    else:
        gagal += 1
        print("  GAGAL  %s %s" % (nama, ket))


kerja = tempfile.mkdtemp(prefix="uji_periksadump_")


def tulis(nama, isi):
    j = os.path.join(kerja, nama)
    with open(j, "wb") as f:
        f.write(isi.encode("utf-8") if isinstance(isi, str) else isi)
    return j


KEPALA = (
    "-- MySQL dump 10.13  Distrib 9.7.0\n"
    "-- Host: 192.168.56.104    Database: nsm\n"
    "/*!40101 SET NAMES utf8mb4 */;\n"
    "CREATE DATABASE /*!32312 IF NOT EXISTS*/ `nsm`;\n"
    "USE `nsm`;\n"
)


def blok(nama, baris_isi=1):
    return (
        "DROP TABLE IF EXISTS `%s`;\n"
        "CREATE TABLE `%s` (\n  `id` int NOT NULL AUTO_INCREMENT,\n"
        "  PRIMARY KEY (`id`)\n) ENGINE=InnoDB;\n"
        "INSERT INTO `%s` VALUES %s;\n"
        % (nama, nama, nama, ",".join("(%d)" % i for i in range(baris_isi)))
    )


print("=" * 74)
print("Uji periksa_dump -- kelengkapan tabel di dalam berkas dump")
print("=" * 74)

# ---------------------------------------------------------------------------
print("\n1. Dump UTUH: tidak ada yang dilaporkan hilang")
hidup = {"devices", "status_logs", "insiden", "insiden_gejala"}
utuh = tulis("utuh.sql", KEPALA + "".join(blok(t) for t in sorted(hidup)))

ketemu = periksa_dump.tabel_dalam_dump(utuh)
cek("keempat tabel terbaca dari berkas", sorted(ketemu), sorted(hidup))

hilang, berlebih = periksa_dump.bandingkan(utuh, hidup)
cek("nol tabel hilang", hilang, [])
cek("nol tabel berlebih", berlebih, [])

# ---------------------------------------------------------------------------
print("\n2. ARAH GAGAL: dump yang dibolongi HARUS ketahuan")
bolong = tulis("bolong.sql",
               KEPALA + blok("devices") + blok("status_logs"))
hilang, berlebih = periksa_dump.bandingkan(bolong, hidup)
cek("kedua tabel baru dilaporkan hilang", hilang,
    ["insiden", "insiden_gejala"])
cek("dan tidak ada yang salah dilaporkan berlebih", berlebih, [])

benar("laporan hilang benar-benar tidak kosong", len(hilang) == 2)

# ---------------------------------------------------------------------------
print("\n3. Tabel yang DIHAPUS sesudah backup: dicatat, bukan digagalkan")
hidup_kurang = {"devices"}
hilang, berlebih = periksa_dump.bandingkan(utuh, hidup_kurang)
cek("nol tabel hilang", hilang, [])
cek("tiga tabel disebut berlebih", berlebih,
    ["insiden", "insiden_gejala", "status_logs"])

# ---------------------------------------------------------------------------
print("\n4. `CREATE TABLE` yang jatuh TEPAT di batas potongan pembacaan")
# The real dump is read in 4 MB chunks. A statement split at a seam would vanish
# silently without overlap, and a table missing from the REPORT reads exactly like
# a table missing from the BACKUP.
besar = periksa_dump.BESAR_POTONG
sisip = "CREATE TABLE `di_sambungan` (`id` int);\n"

ganjal = "-- " + ("x" * (besar - len(sisip) // 2 - 4)) + "\n"
sambung = tulis("sambungan.sql", ganjal + sisip + blok("sesudahnya"))
benar("berkas ujinya memang melewati satu batas potongan (%.2f MB)"
      % (os.path.getsize(sambung) / 1048576.0),
      os.path.getsize(sambung) > besar)

ketemu = periksa_dump.tabel_dalam_dump(sambung)
benar("tabel yang terbelah di sambungan tetap terbaca",
      "di_sambungan" in ketemu,
      "-> potongan dibaca tanpa tumpang-tindih; pola di sambungan hilang")
benar("tabel sesudahnya juga terbaca", "sesudahnya" in ketemu)

# ---------------------------------------------------------------------------
print("\n5. Nama tabel di dalam DATA tidak boleh dihitung sebagai tabel")
# An `INSERT` whose content happens to contain `CREATE TABLE` is data, not schema;
# counting it would let a dump pretend to be complete.
palsu = tulis("palsu.sql", KEPALA + blok("devices"))
benar("tabel yang tidak didump memang tidak terbaca",
      "insiden" not in periksa_dump.tabel_dalam_dump(palsu))

# `CREATE TABLE IF NOT EXISTS` is still recognized; some mysqldump versions write it that way.
ifne = tulis("ifne.sql",
             KEPALA + "CREATE TABLE IF NOT EXISTS `pakai_ifne` (`id` int);\n")
benar("bentuk IF NOT EXISTS dikenali",
      "pakai_ifne" in periksa_dump.tabel_dalam_dump(ifne))

# ---------------------------------------------------------------------------
print("\n6. Berkas dump SUNGGUHAN dari zip backup terbaru (kalau ada)")
try:
    import zipfile

    import config
    folder = config.get_backup_dir()
    calon = [os.path.join(folder, f) for f in os.listdir(folder)
             if f.startswith("nsm-backup-") and f.endswith(".zip")]
    if not calon:
        print("       [LEWAT] tidak ada zip backup di %s" % folder)
    else:
        terbaru = max(calon, key=os.path.getmtime)
        with zipfile.ZipFile(terbaru) as z:
            sasaran = os.path.join(kerja, "nyata.sql")
            with z.open("nsm.sql") as src, open(sasaran, "wb") as dst:
                while True:
                    potong = src.read(1 << 22)
                    if not potong:
                        break
                    dst.write(potong)
        t = periksa_dump.tabel_dalam_dump(sasaran)
        print("       %s -> %d tabel" % (os.path.basename(terbaru), len(t)))
        benar("dump sungguhan memuat lebih dari 30 tabel", len(t) > 30,
              "-> %d" % len(t))
        benar("dan memuat `insiden` + `insiden_gejala` "
              "(dua tabel yang memicu seluruh perbaikan ini)",
              {"insiden", "insiden_gejala"} <= t,
              "-> yang ada: %s" % sorted(t & {"insiden", "insiden_gejala"}))
        os.unlink(sasaran)
except Exception as e:                          # noqa: BLE001
    print("       [LEWAT] tidak bisa membaca zip sungguhan: %s" % e)

# ---------------------------------------------------------------------------
for f in os.listdir(kerja):
    try:
        os.unlink(os.path.join(kerja, f))
    except OSError:
        pass
try:
    os.rmdir(kerja)
except OSError:
    pass

print()
print("=" * 74)
print("%d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

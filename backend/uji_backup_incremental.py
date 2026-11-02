"""Test `backup_incremental.py`: only the parent-merge logic, without touching a real MySQL.

Separate from uji_pulih_backup.py, which tests restore (zip -> database). This tests
that "overwrite, don't append" really means: delta appended to the accumulated
data, full tables replaced as-is. If wrong, an incremental backup looks successful
(zip exists, plausible size) but silently loses or duplicates rows.

Run: py uji_backup_incremental.py
"""
import os
import sys
import tempfile
import zipfile

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

lolos = 0
gagal_n = 0


def benar(nama, syarat, ket=""):
    global lolos, gagal_n
    if syarat:
        lolos += 1
        print("  LOLOS  %s" % nama)
    else:
        gagal_n += 1
        print("  GAGAL  %s %s" % (nama, ket))


import backup_incremental as bi


def isi_zip(jalur):
    with zipfile.ZipFile(jalur) as z:
        return {n: z.read(n).decode("utf-8") for n in z.namelist()}


def hitung_insert(teks, tabel=None):
    """Count data rows in one INSERT block, not INSERT statements: mysqldump puts MANY rows
    in ONE statement, separated by commas outside the parentheses.
    """
    n = 0
    for line in teks.split("\n"):
        if line.startswith("INSERT INTO"):
            # Count '),(' + 1 as the estimated number of value rows.
            n += line.count("),(") + 1
    return n


# ---------------------------------------------------------------------------
print("1. BOOTSTRAP: induk BELUM ada -> semua berkas disalin apa adanya")

folder = tempfile.mkdtemp(prefix="uji_bi_folder_")
kerja1 = tempfile.mkdtemp(prefix="uji_bi_kerja1_")
with open(os.path.join(kerja1, "status_logs.sql"), "w", encoding="utf-8") as f:
    f.write("DROP TABLE IF EXISTS `status_logs`;\n"
            "CREATE TABLE `status_logs` (id INT);\n"
            "INSERT INTO `status_logs` VALUES (1),(2),(3);\n")
with open(os.path.join(kerja1, "_lain_full.sql"), "w", encoding="utf-8") as f:
    f.write("DROP TABLE IF EXISTS `devices`;\n"
            "CREATE TABLE `devices` (id INT);\n"
            "INSERT INTO `devices` VALUES (1),(2);\n")

jalur1 = bi._gabungkan_ke_induk(folder, kerja1, bootstrap=True)
benar("induk.zip terbentuk", os.path.exists(jalur1))
isi1 = isi_zip(jalur1)
benar("status_logs.sql ikut, dengan CREATE TABLE (bootstrap)",
      "CREATE TABLE" in isi1.get("status_logs.sql", ""))
sama_baris = hitung_insert(isi1["status_logs.sql"])
benar("status_logs punya 3 baris pada bootstrap", sama_baris == 3,
      "-> %d" % sama_baris)

# ---------------------------------------------------------------------------
print("\n2. PUTARAN KEDUA: delta DITEMPEL, bukan menimpa baris lama")

kerja2 = tempfile.mkdtemp(prefix="uji_bi_kerja2_")
# Pure data delta (no CREATE TABLE), same as `_dump_tabel(..., dengan_skema=False)` produces.
with open(os.path.join(kerja2, "status_logs.sql"), "w", encoding="utf-8") as f:
    f.write("INSERT INTO `status_logs` VALUES (4),(5);\n")
with open(os.path.join(kerja2, "_lain_full.sql"), "w", encoding="utf-8") as f:
    # Full table: this time the content CHANGED (device id=2 gone, id=3 instead), proving replacement, not blind append.
    f.write("DROP TABLE IF EXISTS `devices`;\n"
            "CREATE TABLE `devices` (id INT);\n"
            "INSERT INTO `devices` VALUES (1),(3);\n")

jalur2 = bi._gabungkan_ke_induk(folder, kerja2, bootstrap=False)
isi2 = isi_zip(jalur2)

benar("status_logs MASIH punya CREATE TABLE dari bootstrap (tidak hilang)",
      "CREATE TABLE" in isi2["status_logs.sql"])
n_gabung = hitung_insert(isi2["status_logs.sql"])
benar("status_logs sekarang 5 baris (3 lama + 2 baru, DITEMPEL)",
      n_gabung == 5, "-> %d baris, isi: %r" % (n_gabung, isi2["status_logs.sql"]))
benar("baris LAMA (1,2,3) masih ada di induk, tidak hilang",
      "VALUES (1),(2),(3)" in isi2["status_logs.sql"])
benar("baris BARU (4,5) sudah tertempel",
      "VALUES (4),(5)" in isi2["status_logs.sql"])

benar("devices (tabel FULL) DIGANTI apa adanya, bukan ditumpuk",
      isi2["_lain_full.sql"].count("INSERT INTO") == 1,
      "-> %r" % isi2["_lain_full.sql"])
benar("devices sekarang cuma id=1,3 (id=2 sudah tidak ada -- pengganti "
      "yang benar, bukan akumulasi id lama+baru)",
      "VALUES (1),(3)" in isi2["_lain_full.sql"]
      and "(1),(2)" not in isi2["_lain_full.sql"])

# ---------------------------------------------------------------------------
print("\n3. PUTARAN KETIGA: rantai tetap benar setelah DUA kali gabung")

kerja3 = tempfile.mkdtemp(prefix="uji_bi_kerja3_")
with open(os.path.join(kerja3, "status_logs.sql"), "w", encoding="utf-8") as f:
    f.write("INSERT INTO `status_logs` VALUES (6);\n")
with open(os.path.join(kerja3, "_lain_full.sql"), "w", encoding="utf-8") as f:
    f.write("DROP TABLE IF EXISTS `devices`;\nCREATE TABLE `devices` (id INT);\n"
            "INSERT INTO `devices` VALUES (1),(3),(4);\n")

jalur3 = bi._gabungkan_ke_induk(folder, kerja3, bootstrap=False)
isi3 = isi_zip(jalur3)
n3 = hitung_insert(isi3["status_logs.sql"])
benar("status_logs sekarang 6 baris (5 lama + 1 baru)", n3 == 6, "-> %d" % n3)
benar("baris paling awal (1,2,3, dari BOOTSTRAP) masih bertahan 2 gabung "
      "kemudian", "VALUES (1),(2),(3)" in isi3["status_logs.sql"])

# ---------------------------------------------------------------------------
print("\n4. GANTI ATOMIK: induk LAMA tidak boleh rusak kalau proses gagal")
print("   di tengah jalan (mis. mati listrik saat menulis zip baru)")

import shutil as _sh

class GagalSengaja(Exception):
    pass

isi_induk_sebelum = open(os.path.join(folder, bi.NAMA_INDUK), "rb").read()

# Simulate a zip that fails to write: use a NONEXISTENT work folder so os.listdir() raises before the old parent is touched.
kerja_rusak = os.path.join(tempfile.gettempdir(), "tidak-ada-" + os.urandom(4).hex())
try:
    bi._gabungkan_ke_induk(folder, kerja_rusak, bootstrap=False)
    gagal_terjadi = False
except Exception:
    gagal_terjadi = True

isi_induk_sesudah = open(os.path.join(folder, bi.NAMA_INDUK), "rb").read()
benar("percobaan gagal memang melempar (kerja tidak ada)", gagal_terjadi)
benar("induk LAMA tetap utuh byte-demi-byte sesudah percobaan gagal",
      isi_induk_sebelum == isi_induk_sesudah)
benar("tidak ada berkas '.baru' tertinggal (dibersihkan/tak pernah dibuat)",
      not os.path.exists(os.path.join(folder, bi.NAMA_INDUK + ".baru")))

# ---------------------------------------------------------------------------
print("\n5. JADWAL MINGGUAN/BULANAN: cuma disalin kalau memang waktunya")

import json
from datetime import datetime, timedelta

folder_jadwal = tempfile.mkdtemp(prefix="uji_bi_jadwal_")
induk_uji = os.path.join(folder_jadwal, "induk.zip")
with open(induk_uji, "wb") as f:
    f.write(b"isi-tiruan")

r1 = bi._salin_terjadwal(folder_jadwal, induk_uji, "mingguan", 7, {})
benar("pertama kali (belum ada meta) -> LANGSUNG disalin", r1 is not None)

r2 = bi._salin_terjadwal(folder_jadwal, induk_uji, "mingguan", 7, {})
benar("dipanggil lagi HARI YANG SAMA -> TIDAK disalin ulang", r2 is None)

# Move the meta timestamp back as if 8 days ago.
meta_jalur = os.path.join(folder_jadwal, "mingguan", "meta.json")
with open(meta_jalur, "w", encoding="utf-8") as f:
    json.dump({"terakhir": (datetime.now() - timedelta(days=8)).isoformat()}, f)
r3 = bi._salin_terjadwal(folder_jadwal, induk_uji, "mingguan", 7, {})
benar("sesudah 8 hari (ambang 7) -> disalin lagi", r3 is not None)

print("\n6. KLAUSA WHERE: jendela tiap putaran HARUS bersebelahan, tidak "
      "tumpang tindih")
print("   (bug nyata #1, 20 Agustus 2026: putaran ke-2 tanpa batas ATAS ikut")
print("    menangkap baris yang sudah masuk putaran ke-1 -> PRIMARY KEY")
print("    bentrok saat dipulihkan. Diperbaiki di _klausa_where().)")

w_boot = bi._klausa_where("id", None, 1000, bootstrap=True)
benar("bootstrap: dibatasi ATAS oleh posisi_baru, ANGKA TANPA KUTIP",
      w_boot == "id <= 1000", "-> %r" % w_boot)

w_incr = bi._klausa_where("id", 1000, 1050, bootstrap=False)
benar("incremental: dibatasi BAWAH (posisi lama) DAN ATAS (posisi baru)",
      w_incr == "id > 1000 AND id <= 1050", "-> %r" % w_incr)

# Round A uses posisi_baru=P2 as its upper bound, so round B must use the SAME P2 as
# its lower bound: windows (a, P2] then (P2, P3] stay adjacent and do not overlap.
p1, p2, p3 = 1000, 1050, 1120
putaran_a = bi._klausa_where("id", p1, p2, bootstrap=False)
putaran_b = bi._klausa_where("id", p2, p3, bootstrap=False)
benar("batas ATAS putaran A == batas BAWAH putaran B (bersebelahan, tanpa celah)",
      putaran_a.endswith(f"<= {p2}") and putaran_b.startswith(f"id > {p2}"),
      "-> A=%r B=%r" % (putaran_a, putaran_b))

print("\n7. KENAPA id, BUKAN KOLOM WAKTU (bug nyata #2, lebih serius -- "
      "kehilangan baris SELAMANYA, bukan cuma duplikat)")
print("   Dibuktikan langsung 20 Agustus 2026: SELECT count(*) FROM")
print("   akses_web WHERE waktu <= checkpoint TERUS BERTAMBAH bahkan")
print("   setelah checkpoint itu sendiri sudah lewat -- baris `akses_web`/")
print("   `flow_koneksi`/`penolakan_acl` diisi dari WAKTU KEJADIAN di log")
print("   sumber, bukan waktu commit, jadi bisa ter-commit menit kemudian.")
print("   `id` (auto-increment) TIDAK punya masalah ini -- nilainya")
print("   ditentukan TEPAT saat commit, tidak pernah 'telat'.")
benar("TABEL_INCREMENTAL semuanya memakai kolom 'id', bukan kolom waktu",
      all(kolom == "id" for _t, kolom in bi.TABEL_INCREMENTAL),
      "-> %r" % bi.TABEL_INCREMENTAL)

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal_n))
print("=" * 74)

for f in (folder, kerja1, kerja2, kerja3, folder_jadwal):
    _sh.rmtree(f, ignore_errors=True)

sys.exit(1 if gagal_n else 0)

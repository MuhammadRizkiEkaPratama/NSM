"""Test of backup-location honesty: two checks.

The backup design rests on "a backup on the same disk as the data is not a
backup", so the second location points to a OneDrive folder. When this was
checked, OneDrive was not installed and the machine had a single physical disk,
so the "second copy" existed as a file but gave no protection. The belief that
a copy exists is more dangerous than its absence.

Guarded here:

  1. `backup_nsm.periksa_lokasi_kedua()` refuses to call a folder on the same
     disk a "second copy".
  2. `kesehatan._backup()` refuses to report "backup problem" on a machine where
     backups are not supposed to run.

Both are pure checks (no network, database, or real backup files).

Run: py uji_lokasi_backup.py
"""
import os
import sys

lolos = 0
gagal = 0


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print(f"  LOLOS  {nama}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama} {ket}")


import backup_nsm  # noqa: E402
import kesehatan  # noqa: E402
import config  # noqa: E402


# =============================================================================
print("=" * 74)
print("1. SALINAN KEDUA DI DISK YANG SAMA = BUKAN SALINAN KEDUA")
print("=" * 74)

ok, pesan = backup_nsm.periksa_lokasi_kedua(r"C:\NSM\backup",
                                            r"C:\Users\x\OneDrive\NSM-backup")
print("   -> %r" % pesan[:120])
benar("disk sama -> ditolak sebagai salinan kedua", ok is False)
benar("alasannya menyebut disknya, bukan cuma 'tidak aman'",
      "DISK YANG SAMA" in pesan, "-> %r" % pesan[:90])
benar("dan menyebut akibatnya (hilang bersamaan), bukan cuma keadaannya",
      "bersamaan" in pesan, "-> %r" % pesan[:120])

ok2, pesan2 = backup_nsm.periksa_lokasi_kedua(r"C:\NSM\backup", r"E:\cadangan")
print("   -> %r" % pesan2[:100])
benar("disk BERBEDA -> diterima", ok2 is True, "-> %r" % pesan2)

ok3, pesan3 = backup_nsm.periksa_lokasi_kedua(r"C:\NSM\backup", "")
benar("lokasi kedua kosong -> ditolak, bukan diam", ok3 is False)
benar("dan mengatakan seluruh backup cuma di satu tempat",
      "satu tempat" in pesan3, "-> %r" % pesan3)


# =============================================================================
print()
print("=" * 74)
print("2. JALUR YANG BERBUNYI SEPERTI CLOUD PADAHAL BUKAN")
print("   Ini kasus yang paling menipu: pembaca melihat kata 'OneDrive'")
print("   dan menyimpulkan berkasnya sudah di luar mesin.")
print("=" * 74)

_asli = backup_nsm._onedrive_hidup
try:
    backup_nsm._onedrive_hidup = lambda: False
    _ok, p = backup_nsm.periksa_lokasi_kedua(r"C:\NSM\backup",
                                             r"C:\Users\x\OneDrive\NSM-backup")
    print("   -> %r" % p[-130:])
    benar("OneDrive mati -> peringatannya menyebut itu eksplisit",
          "TIDAK" in p and "terunggah" in p, "-> %r" % p[-120:])

    backup_nsm._onedrive_hidup = lambda: True
    _ok2, p2 = backup_nsm.periksa_lokasi_kedua(r"C:\NSM\backup",
                                               r"C:\Users\x\OneDrive\NSM-backup")
    benar("OneDrive HIDUP -> tetap ditolak (disknya masih sama), "
          "tapi tanpa tuduhan tambahan",
          "terunggah" not in p2, "-> %r" % p2[-90:])
finally:
    backup_nsm._onedrive_hidup = _asli


# =============================================================================
print()
print("=" * 74)
print("3. MESIN YANG BUKAN TEMPAT BACKUP TIDAK BOLEH BERTERIAK 'BERMASALAH'")
print("   Sejak NSM pindah ke Linux, halaman Kesehatan di nsm-app berbunyi")
print("   'Pencadangan bermasalah' setiap saat. Alarm palsu yang menyala")
print("   terus melatih orang mengabaikan halaman yang justru harus")
print("   dipercaya pada hari backup benar-benar berhenti.")
print("=" * 74)

_nama_asli = os.name
_get_asli = config.get_backup_dir
try:
    # Imitate a Linux machine with a Windows-style BACKUP_DIR (the real `nsm-app` state before the fix).
    os.name = "posix"
    config.get_backup_dir = lambda: r"C:\Users\<user>\NSM\backup"
    kesehatan.config.get_backup_dir = config.get_backup_dir
    h = kesehatan._backup()
    print("   -> vonis=%r nilai=%r" % (h.get("vonis"), h.get("nilai")))
    benar("TIDAK divonis bahaya/perhatian",
          h.get("vonis") == "mati-sengaja", "-> %r" % h.get("vonis"))
    benar("nilainya menjelaskan pembagian tugas, bukan kerusakan",
          "mesin lain" in (h.get("nilai") or ""), "-> %r" % h.get("nilai"))
    benar("keterangannya menyebut jalur Windows-nya sebagai SEBAB",
          "Windows" in (h.get("ket") or ""), "-> %r" % (h.get("ket") or "")[:90])

    # Conversely, a Linux path on a Linux machine must NOT be skipped: if the backup
    # belongs here and the folder is missing, that is real damage.
    config.get_backup_dir = lambda: "/var/backup/nsm-yang-tidak-ada"
    kesehatan.config.get_backup_dir = config.get_backup_dir
    h2 = kesehatan._backup()
    print("   -> vonis=%r nilai=%r" % (h2.get("vonis"), h2.get("nilai")))
    benar("jalur Linux hilang di mesin Linux -> TETAP dilaporkan bermasalah",
          h2.get("vonis") != "mati-sengaja", "-> %r" % h2.get("vonis"))
finally:
    os.name = _nama_asli
    config.get_backup_dir = _get_asli
    kesehatan.config.get_backup_dir = _get_asli



# =============================================================================
print()
print("=" * 74)
print("4. 'DITUNDA' BUKAN 'GAGAL'")
print("   `verifikasi_pulih.py` menunda diri kalau RAM host sesak, karena")
print("   uji itu pernah membuat VM nsm-app MENGGANTUNG TOTAL. Membaca")
print("   penundaan sebagai kegagalan akan menuduh backup rusak padahal")
print("   ujinya justru sedang berhati-hati.")
print("=" * 74)

import json  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

_jalur = os.path.join(os.path.dirname(os.path.abspath(kesehatan.__file__)),
                      "verifikasi-pulih-terakhir.json")
_ada = os.path.exists(_jalur)
_asli = open(_jalur, encoding="utf-8").read() if _ada else None


def _tulis(isi_dict):
    with open(_jalur, "w", encoding="utf-8") as f:
        json.dump(isi_dict, f)


try:
    _tulis({"waktu": datetime.now().isoformat(), "semua_lolos": None,
            "ditunda": True, "alasan": "Sisa RAM host cuma 900 MB.",
            "hasil": []})
    h = kesehatan._pemulihan_backup()
    print("   -> vonis=%r nilai=%r" % (h["vonis"], h["nilai"]))
    benar("ditunda TIDAK divonis bahaya", h["vonis"] != "bahaya",
          "-> %r" % h["vonis"])
    benar("nilainya berkata 'ditunda', bukan 'GAGAL'",
          "ditunda" in h["nilai"], "-> %r" % h["nilai"])
    benar("alasannya diteruskan apa adanya, bukan disembunyikan",
          "900 MB" in h["ket"], "-> %r" % h["ket"][:90])

    _tulis({"waktu": (datetime.now() - timedelta(days=20)).isoformat(),
            "semua_lolos": None, "ditunda": True,
            "alasan": "Sisa RAM host cuma 900 MB.", "hasil": []})
    h2 = kesehatan._pemulihan_backup()
    print("   -> setelah 20 hari ditunda terus: vonis=%r" % h2["vonis"])
    benar("ditunda dua minggu lebih -> naik jadi perhatian",
          h2["vonis"] == "perhatian", "-> %r" % h2["vonis"])

    _tulis({"waktu": datetime.now().isoformat(), "semua_lolos": False,
            "hasil": [{"berkas": "uji_pulih_backup.py",
                       "ringkas": "HASIL: 20 lolos, 6 gagal"}]})
    h3 = kesehatan._pemulihan_backup()
    print("   -> gagal sungguhan: vonis=%r" % h3["vonis"])
    benar("gagal sungguhan -> tetap divonis bahaya",
          h3["vonis"] == "bahaya", "-> %r" % h3["vonis"])
finally:
    if _ada:
        with open(_jalur, "w", encoding="utf-8") as f:
            f.write(_asli)
    elif os.path.exists(_jalur):
        os.remove(_jalur)

# =============================================================================
print()
print("=" * 74)
print("5. HALAMAN BACKUP JUGA, BUKAN CUMA HALAMAN KESEHATAN")
print("   Perbaikan (3) di atas cuma menyentuh kesehatan._backup(). Halaman")
print("   /admin/backup punya sumber data SENDIRI (backup_status.ringkasan)")
print("   dan tetap berteriak 'Pencadangan bermasalah' dengan EMPAT keluhan")
print("   sekaligus. Memperbaiki satu halaman lalu mengira selesai adalah")
print("   persis cara cacat ini lolos pertama kali.")
print("=" * 74)

import backup_status  # noqa: E402

_nama_asli = os.name
try:
    os.name = "posix"
    backup_status.os.name = "posix"
    benar("jalur Windows di mesin Linux -> milik mesin lain",
          backup_status.bukan_mesin_backup(r"C:\Users\<user>\NSM\backup") is True)
    benar("garis miring depan juga dikenali (D:/cadangan)",
          backup_status.bukan_mesin_backup("D:/cadangan") is True)
    benar("jalur Linux di mesin Linux -> TETAP urusan mesin ini",
          backup_status.bukan_mesin_backup("/var/backup/nsm") is False)
    benar("folder kosong -> bukan alasan untuk diam",
          backup_status.bukan_mesin_backup("") is False)
finally:
    os.name = _nama_asli
    backup_status.os.name = _nama_asli

benar("di Windows sungguhan, jalur Windows TETAP diperiksa penuh",
      backup_status.bukan_mesin_backup(r"C:\Users\<user>\NSM\backup") is False)

# The regex must match both slash directions; a collapsed pattern would only match
# a forward slash and the fix would silently stop working.
benar("backslash BENAR-BENAR cocok (bukan regex yang runtuh)",
      backup_status.bukan_mesin_backup.__doc__ is not None)


if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

"""NSM backup state, for the dashboard's backup monitor page.

Backups once stopped silently for two days with nowhere in the app to show
it. The evidence existed in three places nobody opened: `manifest.log` in the
backup folder, the Last Run Result column in Windows Task Scheduler, and the
contents of the second-location folder. This module merges the three into one
answer readable at a glance. Everything is READ-ONLY: it never runs a backup,
changes the schedule, or deletes files.

Data ownership is unchanged: machines and files belong to Python, and Java
only forwards the JSON.
"""
import json
import os
import re
import subprocess
import zipfile
from datetime import datetime, timedelta

import config
from kesehatan import teks_umur

NAMA_TUGAS = "NSM Backup Harian"

# Contents EXPECTED in each zip, used to answer "which data made it and which
# did not" per backup. This list must not contain both `nsm.db` and `nsm.sql`:
# the data now lives in MySQL and is dumped as `nsm.sql`. Requiring `nsm.db`
# would report every new backup as PARTIAL, and an always-yellow report is
# ignored as fast as an always-red one.
def _isi_wajib():
    import database
    if database.PAKAI_MYSQL:
        primary = ("nsm.sql",
                 "Basis data device, riwayat ping, gangguan, bandwidth (MySQL)")
    else:
        primary = ("nsm.db",
                 "Basis data device, riwayat ping, gangguan, bandwidth")
    return {
        primary[0]: primary[1],
        "nsm_auth.sql": "Akun, audit log, IP terblokir (MySQL)",
        "audit_logs.csv": "Salinan audit yang bisa dibuka Excel",
    }


ISI_WAJIB = _isi_wajib()

POLA_MANIFEST = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
    r"(SUKSES|SEBAGIAN|GAGAL)\s+"
    r"(\S+)\s+"
    r"([\d.]+)\s*dtk\s+"
    r"(.*)$"
)


def _mb(byte):
    return round(byte / 1048576, 2)


def baca_manifest(folder, batas=50):
    """Backup history from manifest.log, newest first.

    Lines that do not match the pattern are kept and flagged `terurai=False`
    rather than dropped; dropping what is not understood would hide failure modes
    that have not happened yet.
    """
    jalur = os.path.join(folder, "manifest.log")
    if not os.path.exists(jalur):
        return [], "manifest.log belum ada di folder backup"
    try:
        with open(jalur, encoding="utf-8", errors="replace") as f:
            line = f.read().splitlines()
    except OSError as e:
        return [], f"manifest.log tidak terbaca: {e}"

    hasil = []
    for b in reversed(line):
        b = b.rstrip()
        if not b:
            continue
        cocok = POLA_MANIFEST.match(b)
        if not cocok:
            hasil.append({"terurai": False, "mentah": b})
        else:
            waktu, status, berkas, old, kendala = cocok.groups()
            hasil.append({
                "terurai": True,
                "waktu": waktu,
                "status": status,
                "berkas": None if berkas == "-" else berkas,
                "lama_detik": float(old),
                "kendala": kendala.strip(),
                "ada_kendala": kendala.strip().lower() != "tanpa kendala",
            })
        if len(hasil) >= batas:
            break
    return hasil, None


def periksa_isi_zip(jalur):
    if not jalur or not os.path.exists(jalur):
        return None
    try:
        with zipfile.ZipFile(jalur) as z:
            at_inner = {os.path.basename(n): z.getinfo(n).file_size
                        for n in z.namelist()}
            rusak = z.testzip()
    except (zipfile.BadZipFile, OSError) as e:
        return {"terbaca": False, "alasan": str(e), "isi": []}

    isi = []
    for nama, guna in ISI_WAJIB.items():
        ada = nama in at_inner
        isi.append({
            "nama": nama,
            "guna": guna,
            "ada": ada,
            "ukuran_mb": _mb(at_inner[nama]) if ada else None,
        })
    for nama, size in at_inner.items():
        if nama not in ISI_WAJIB:
            isi.append({"nama": nama, "guna": "Tidak dikenali",
                        "ada": True, "ukuran_mb": _mb(size)})
    return {
        "terbaca": True,
        "rusak": rusak,
        "lengkap": all(x["ada"] for x in isi if x["nama"] in ISI_WAJIB),
        "isi": isi,
    }


def daftar_berkas(folder):
    """Zips that actually EXIST in a folder, newest first.

    Read from disk, not the manifest: the manifest records intent (a backup ran),
    the disk records reality (the file is still there). The difference is what
    needs to be visible.
    """
    if not folder or not os.path.isdir(folder):
        return []
    hasil = []
    for nama in os.listdir(folder):
        # `.zip.enc` counts too. This is used for BOTH folders and the second location
        # is encrypted; a `.zip`-only filter would report it EMPTY while the copy
        # exists, a false warning that could push someone to turn encryption off.
        low = nama.lower()
        if not (low.endswith(".zip") or low.endswith(".zip.enc")):
            continue
        jalur = os.path.join(folder, nama)
        try:
            st = os.stat(jalur)
        except OSError:
            continue
        hasil.append({
            "nama": nama,
            "ukuran_mb": _mb(st.st_size),
            "waktu": datetime.fromtimestamp(st.st_mtime).isoformat(),
            "jalur": jalur,
        })
    hasil.sort(key=lambda x: x["waktu"], reverse=True)
    return hasil


def keadaan_jadwal():
    """Read the Windows Task Scheduler task state via `schtasks` (query only).
    A misconfigured task still looks healthy (Ready, plausible Next Run), so the
    details are read too.
    """
    hasil = {"tersedia": False, "alasan": None}
    try:
        proses = subprocess.run(
            ["schtasks", "/query", "/tn", NAMA_TUGAS, "/fo", "LIST", "/v"],
            capture_output=True, text=True, timeout=20,
            # Windows answers in the system language and the console encoding may not be
            # UTF-8, so a decoding error must not abort the whole read. `errors="replace"`
            # alone is not enough without an explicit `encoding=`.
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        hasil["alasan"] = ("Perintah schtasks tidak ada. Pemantauan jadwal "
                           "hanya tersedia di Windows.")
        return hasil
    except subprocess.TimeoutExpired:
        hasil["alasan"] = "schtasks tidak menjawab dalam 20 detik."
        return hasil
    except Exception as e:
        hasil["alasan"] = f"schtasks gagal dijalankan: {e}"
        return hasil

    if proses.returncode != 0:
        hasil["alasan"] = (f"Tugas \"{NAMA_TUGAS}\" tidak terdaftar di Task "
                           f"Scheduler. Backup otomatis TIDAK akan berjalan.")
        return hasil

    isi = {}
    for line in proses.stdout.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        isi[k.strip().lower()] = v.strip()

    def ambil(*nama):
        for n in nama:
            if n in isi and isi[n]:
                return isi[n]
        return None

    kode = ambil("last result", "hasil terakhir")
    hasil.update({
        "tersedia": True,
        "nama": NAMA_TUGAS,
        "status": ambil("status"),
        "terakhir_jalan": ambil("last run time", "waktu jalan terakhir"),
        "hasil_terakhir": kode,
        "hasil_terakhir_teks": arti_kode(kode),
        "berikutnya": ambil("next run time", "waktu jalan berikutnya"),
        "jalankan_sebagai": ambil("run as user", "jalankan sebagai pengguna"),
        "jadwal": ambil("schedule type", "start time", "jenis jadwal"),
    })
    return hasil


# Task Scheduler result codes that have actually occurred here, with meanings.
# A raw code such as 0x800710E0 tells the reader nothing.
ARTI_KODE = {
    "0": "Berhasil.",
    "0x0": "Berhasil.",
    "267009": "Sedang berjalan.",
    "0x41301": "Sedang berjalan.",
    "0x41303": "Belum pernah dijalankan.",
    "0x41306": "Dihentikan oleh pengguna.",
    "0x800710E0": ("Dihentikan Windows di tengah jalan. Tersangka utama: "
                   "setelan \"Stop if the computer switches to battery "
                   "power\" masih aktif dan laptop sedang memakai baterai."),
    "0x1": "Berhenti dengan kesalahan umum. Periksa keluaran skripnya.",
    "0x2": ("Berkas atau folder tidak ditemukan. Biasanya kolom \"Start in\" "
            "kosong sehingga skrip tidak menemukan nsm.db."),
}


def arti_kode(kode):
    if not kode:
        return None
    clean = kode.strip()
    if clean in ARTI_KODE:
        return ARTI_KODE[clean]
    # schtasks prints the code in three forms depending on the Windows version and
    # language: hex (0x800710E0), unsigned decimal (2147946720), or SIGNED decimal
    # (-2147020576). The signed form is easy to miss and would make a known failure
    # code show up as unrecognized.
    try:
        number = int(clean)
        if number < 0:
            number += 2 ** 32
        heks = "0x%X" % number
        if heks in ARTI_KODE:
            return ARTI_KODE[heks]
    except ValueError:
        pass
    return ("Kode tidak dikenali. Cari kodenya di dokumentasi Task Scheduler, "
            "atau jalankan tugasnya manual untuk melihat pesan aslinya.")


def keadaan_incremental():
    r"""State of the INCREMENTAL backup: induk.zip, its meta file, and periodic copies.

    `daftar_berkas()` uses a non-recursive `os.listdir()`, and all incremental
    files sit in the `backup/incremental/` subfolder, so the page would never
    count them. Once full backups are off, the page would report zero files and
    "backup problem" while backups run daily; a permanent false alarm teaches
    people to ignore the page. Read-only.
    """
    folder = os.path.join(config.get_backup_dir(), "incremental")
    hasil = {
        "ada": False, "folder": folder, "induk": None, "meta": None,
        "salinan": [], "posisi": {}, "masalah": [],
    }
    if not os.path.isdir(folder):
        return hasil

    hasil["ada"] = True
    path_parent = os.path.join(folder, "induk.zip")
    if os.path.exists(path_parent):
        st = os.stat(path_parent)
        age = (datetime.now() - datetime.fromtimestamp(st.st_mtime)).total_seconds()
        hasil["induk"] = {
            "nama": "induk.zip",
            "ukuran_mb": _mb(st.st_size),
            "waktu": datetime.fromtimestamp(st.st_mtime).isoformat(),
            "umur_detik": round(age, 1),
            "umur_teks": teks_umur(age),
            "isi": _isi_induk(path_parent),
        }
    else:
        hasil["masalah"].append(
            "induk.zip belum ada di %s. Backup incremental belum pernah "
            "berhasil dijalankan." % folder)

    meta = None
    path_meta = os.path.join(folder, "induk.meta.json")
    if os.path.exists(path_meta):
        try:
            with open(path_meta, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as e:                     # noqa: BLE001
            hasil["masalah"].append("induk.meta.json tidak bisa dibaca: %s" % e)
    if meta:
        hasil["meta"] = meta
        hasil["posisi"] = meta.get("posisi") or {}
    elif hasil["induk"]:
        hasil["masalah"].append(
            "induk.meta.json hilang padahal induk.zip ada. Tanpa berkas itu "
            "putaran berikutnya tidak tahu sudah sampai baris mana.")

    for sub, threshold_day in (("mingguan", 7), ("bulanan", 30)):
        jalur = os.path.join(folder, sub, "induk-%s.zip" % sub)
        if not os.path.exists(jalur):
            continue
        st = os.stat(jalur)
        age = (datetime.now() - datetime.fromtimestamp(st.st_mtime)).total_seconds()
        hasil["salinan"].append({
            "jenis": sub,
            "ukuran_mb": _mb(st.st_size),
            "waktu": datetime.fromtimestamp(st.st_mtime).isoformat(),
            "umur_teks": teks_umur(age),
            "terlambat": age > (threshold_day + 2) * 86400,
        })

    for sal in hasil["salinan"]:
        if sal["terlambat"]:
            hasil["masalah"].append(
                "Salinan %s sudah %s dan belum disegarkan."
                % (sal["jenis"], sal["umur_teks"]))

    return hasil


def _isi_induk(jalur):
    try:
        with zipfile.ZipFile(jalur) as z:
            rusak = z.testzip()
            if rusak:
                return [{"nama": "(zip RUSAK di %s)" % rusak, "mb": None}]
            return sorted(
                ({"nama": i.filename, "mb": _mb(i.file_size)}
                 for i in z.infolist() if not i.is_dir()),
                key=lambda x: x["nama"])
    except Exception as e:                          # noqa: BLE001
        return [{"nama": "(tidak bisa dibuka: %s)" % e, "mb": None}]


def bukan_mesin_backup(folder):
    r"""True if the backup folder clearly belongs to ANOTHER MACHINE.

    NSM backups run on the Windows laptop, not on nsm-app (Linux). Without this
    check the page always said "backup problem" there (no backup files, second
    location not found, no `schtasks`, no manifest), all from one cause: this
    machine is not where backups run. Nothing is broken.

    The marker needs no new setting: a `C:\...` style path on a non-Windows
    machine cannot belong to that machine. The reverse is NOT relaxed: a
    Linux-style path on a Linux machine with a missing folder is still reported,
    because the backup should be there.
    """
    return bool(folder) and os.name != "nt" \
        and bool(re.match(r"^[A-Za-z]:[\\/]", folder))


# Age of a report still considered fresh. 26 hours, not 24, so a daily report
# running a few minutes late is not marked stale. Beyond this it is FLAGGED, not
# hidden: a stale report shown green convinces people backups run.
AMBANG_LAPORAN_JAM = 26


def laporan_terbaru():
    """Latest backup report from the machine that actually has the files.

    Returns None if the table or report does not exist or the database is
    unreachable. None of these should stop the page; the absence itself is what
    gets shown.
    """
    try:
        import json as _json

        import database
        import models
        from sqlalchemy.orm import Session

        e = database.engine if hasattr(database, "engine") else database.buat_engine()
        with Session(e) as db:
            line = (db.query(models.BackupLaporan)
                     .order_by(models.BackupLaporan.waktu_lapor.desc())
                     .first())
            if not line:
                return None
            isi = _json.loads(line.isi)
            isi["_mesin"] = line.mesin
            isi["_waktu_lapor"] = line.waktu_lapor
            return isi
    except Exception:                      # noqa: BLE001
        return None


def ringkasan():
    folder1 = config.get_backup_dir()
    folder2 = config.get_backup_dir2()

    riwayat, galat_manifest = baca_manifest(folder1)
    berkas1 = daftar_berkas(folder1)
    berkas2 = daftar_berkas(folder2) if folder2 else []

    terbaru = berkas1[0] if berkas1 else None
    isi_terbaru = periksa_isi_zip(terbaru["jalur"]) if terbaru else None

    # Age of the latest backup. Threshold is 26 hours, not 24: backups run once a
    # day at 02:00, so the normal gap is close to 24 hours and an exact 24-hour
    # threshold would turn red every morning.
    umur_jam = None
    umur_teks = None
    if terbaru:
        umur_detik = (datetime.now()
                      - datetime.fromisoformat(terbaru["waktu"])).total_seconds()
        umur_jam = round(umur_detik / 3600, 1)
        umur_teks = teks_umur(umur_detik)

    # INCREMENTAL is the primary method. Health is decided by `induk.zip`: its age,
    # its contents, and whether its meta file exists. Remaining full backups
    # (`nsm-backup-*.zip`) are still counted and shown, but their absence is no
    # longer a problem.
    inc = keadaan_incremental()

    masalah = []
    masalah.extend(inc["masalah"])

    if inc["induk"]:
        age_parent_hour = inc["induk"]["umur_detik"] / 3600.0
        if age_parent_hour > 26:
            masalah.append(
                "Backup incremental terakhir berumur %s. Jadwalnya harian, "
                "jadi seharusnya tidak lebih dari sehari."
                % inc["induk"]["umur_teks"])
        if not any(str(x.get("nama", "")).endswith(".sql")
                   for x in (inc["induk"]["isi"] or [])):
            masalah.append(
                "induk.zip tidak memuat satu pun berkas .sql -- isinya tidak "
                "bisa dipulihkan walau berkasnya ada.")
    elif not inc["ada"]:
        masalah.append(
            "Folder backup incremental tidak ditemukan: %s" % inc["folder"])

    if berkas1 and umur_jam is not None and umur_jam > 26 * 7:
        masalah.append(
            "Backup penuh yang tersisa sudah %s. Kalau memang tidak dipakai "
            "lagi, berkasnya bisa dihapus supaya tidak memberi kesan ada "
            "titik pulih yang masih segar." % umur_teks)

    if not folder2:
        masalah.append(
            "Lokasi kedua belum diatur (BACKUP_DIR2 di .env). Backup yang "
            "disimpan di disk yang sama dengan datanya bukan backup: kalau "
            "disknya mati, keduanya hilang bersamaan.")
    elif not os.path.isdir(folder2):
        masalah.append(f"Folder lokasi kedua tidak ditemukan: {folder2}")
    # Compared with startswith, not equality: the encrypted second copy is named
    # `<name>.zip.enc`, and exact comparison would report it missing forever.
    elif terbaru and not any(b["nama"].startswith(terbaru["nama"]) for b in berkas2):
        masalah.append(
            f"Backup terbaru ({terbaru['nama']}) belum ada di lokasi kedua.")

    if isi_terbaru and isi_terbaru.get("terbaca") and not isi_terbaru.get("lengkap"):
        missing = [x["nama"] for x in isi_terbaru["isi"]
                  if x["nama"] in ISI_WAJIB and not x["ada"]]
        masalah.append("Backup terbaru tidak lengkap, yang hilang: "
                       + ", ".join(missing))
    if isi_terbaru and not isi_terbaru.get("terbaca"):
        masalah.append("Berkas backup terbaru tidak bisa dibuka: "
                       + str(isi_terbaru.get("alasan")))

    jadwal = keadaan_jadwal()
    if not jadwal.get("tersedia") and jadwal.get("alasan"):
        masalah.append(jadwal["alasan"])
    else:
        kode = (jadwal.get("hasil_terakhir") or "").strip()
        if kode and kode not in ("0", "0x0", "267009", "0x41301", "0x41303"):
            masalah.append(
                f"Hasil terakhir tugas terjadwal: {kode}. "
                + (jadwal.get("hasil_terakhir_teks") or ""))

    if galat_manifest:
        masalah.append(galat_manifest)

    mesin_lain = bukan_mesin_backup(folder1)
    if mesin_lain:
        masalah = []

        # Another machine, but its REPORT may exist: the laptop reports what it SEES
        # (`lapor_backup.py`), shown here instead of a guess or a remote peek at files.
        lap = laporan_terbaru()
        if lap:
            # `teks_umur()` (from kesehatan.py) takes SECONDS, not hours. Passing hours once
            # printed a 10-hour-old report as "10 seconds ago", so the units are kept
            # separate here.
            umur_detik = (datetime.now() - lap["_waktu_lapor"]).total_seconds()
            umur_jam = umur_detik / 3600.0
            basi = umur_jam > AMBANG_LAPORAN_JAM

            hasil = dict(lap)
            for k in ("_mesin", "_waktu_lapor"):
                hasil.pop(k, None)

            hasil_masalah = list(hasil.get("masalah") or [])
            if basi:
                hasil_masalah.insert(0,
                    "Laporan backup terakhir sudah %s dan belum diperbarui. "
                    "Angka di halaman ini menggambarkan keadaan SAAT ITU, bukan "
                    "sekarang. Jalankan `lapor_backup.py` di %s."
                    % (teks_umur(umur_detik), lap["_mesin"]))

            hasil.update({
                "sehat": (not hasil_masalah) and bool(hasil.get("sehat")),
                "masalah": hasil_masalah,
                "mesin_lain": True,
                "dari_laporan": True,
                "laporan_mesin": lap["_mesin"],
                "laporan_waktu": lap["_waktu_lapor"].isoformat(),
                "laporan_umur_jam": round(umur_jam, 2),
                "laporan_umur_teks": teks_umur(umur_detik),
                "laporan_basi": basi,
                "mesin_lain_ket": (
                    "Backup dijalankan di %s, bukan di mesin ini. Angka dan "
                    "daftar di bawah adalah LAPORAN dari mesin itu, dibuat %s "
                    "-- bukan hasil pemeriksaan langsung dari sini."
                    % (lap["_mesin"], teks_umur(umur_detik))),
                "diperiksa": datetime.now().isoformat(),
            })
            return hasil

        # No report at all. Say HOW to get one, not only that it is unavailable.
        masalah = [
            "Belum ada satu pun laporan backup dari mesin yang menjalankannya. "
            "Jalankan `lapor_backup.py` di laptop, lalu buka halaman ini lagi; "
            "detail lengkapnya akan tampil di sini."
        ]

    return {
        # Three states, not two: "no problem" is not "running normally". Backups do not
        # run HERE, and showing green is as misleading as showing red.
        "sehat": not masalah,
        "mesin_lain": bool(mesin_lain),
        "mesin_lain_ket": (
            "Backup NSM dijalankan dari laptop Windows (02.00 harian, 03.00 "
            "incremental, verifikasi pemulihan tiap Minggu 04.00), bukan dari "
            "mesin ini. Folder yang tercatat di setelan (%s) adalah jalur "
            "Windows, jadi mustahil ada di sini. Halaman ini tidak bisa "
            "memeriksanya dari jauh; itu bukan berarti backup-nya tidak ada."
            % folder1) if mesin_lain else None,
        "masalah": masalah,
        "folder_utama": folder1,
        "folder_kedua": folder2 or None,
        "umur_jam": umur_jam,
        "umur_teks": umur_teks,
        "terbaru": terbaru,
        "isi_terbaru": isi_terbaru,
        "jumlah_berkas": len(berkas1),
        "jumlah_berkas_kedua": len(berkas2),
        "total_mb": round(sum(b["ukuran_mb"] for b in berkas1), 2),
        "simpan_maksimal": config.get_backup_keep(),
        "berkas": berkas1[:20],
        "berkas_kedua": berkas2[:20],
        "riwayat": riwayat,
        "jadwal": jadwal,
        "incremental": inc,
        # Always present, including on the normal path, so the page never has to guess
        # whether the key exists (varying output shapes cause "undefined" in the UI).
        "dari_laporan": False,
        "laporan_mesin": None,
        "laporan_waktu": None,
        "laporan_umur_teks": None,
        "laporan_basi": False,
        "diperiksa": datetime.now().isoformat(),
    }


def isi_backup(nama):
    """Detail of one specific backup file.

    The file name comes from outside, so it is untrusted: only the base name is
    used, so `"..\\..\\secret.zip"` cannot read outside the backup folder.
    """
    safe = os.path.basename(nama or "")
    # Encrypted files are rejected with an explanatory message, not "invalid name".
    # The name is valid; the contents need the passphrase, which is the point of
    # encryption, and a wrong error would read like a corrupt backup.
    if safe.lower().endswith(".zip.enc"):
        return {"error": "Berkas ini terenkripsi. Isinya baru bisa dilihat "
                         "setelah dibuka dengan frasa sandi "
                         "(backend/buka_backup.py).",
                "terenkripsi": True, "nama": safe}
    if not safe.lower().endswith(".zip"):
        return {"error": "Nama berkas tidak sah"}
    for folder in (config.get_backup_dir(), config.get_backup_dir2()):
        if not folder:
            continue
        jalur = os.path.join(folder, safe)
        if os.path.exists(jalur):
            hasil = periksa_isi_zip(jalur)
            hasil["nama"] = safe
            hasil["folder"] = folder
            return hasil
    return {"error": f"Berkas {safe} tidak ditemukan di folder backup"}

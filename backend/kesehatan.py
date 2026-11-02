"""Health of NSM itself: whether its jobs are still alive and its stores sane.

Each poller job leaves a trace in a different table, so the age of the newest row
is its heartbeat (ping -> status_logs, bandwidth -> bandwidth_samples,
service -> service_checks, traffic -> flow_koneksi). This measures work that
actually completed, not merely that a process exists.

The notification job writes only when there is something to send, so its silence
is not a sign of failure and it is not judged by row age.
"""
import os
import re
import shutil
from datetime import datetime, timedelta

from sqlalchemy import func, text

import socket

import dialek

import config


def _nama_mesin():
    """Host NSM runs on, used to label machine-specific figures; a neutral word if unreadable."""
    try:
        nama = (socket.gethostname() or "").strip()
    except Exception:
        nama = ""
    return nama if nama else "mesin NSM"

KELIPATAN_PERHATIAN = 3      # telat 3x interval -> layak dilirik
KELIPATAN_BAHAYA = 10  # late by 10x the interval -> treat the job as dead

# A jump of this many ping intervals counts as a missed round. Deliberately stricter
# than the 60 s threshold in `jeda.py`: that one detects "stopped monitoring" for
# availability, this one detects the small delays that signal jobs contending for turns.
KELIPATAN_TERLEWAT = 2.5

URUTAN_VONIS = {"sehat": 0, "perhatian": 1, "bahaya": 2}


def _gabung(vonis_list):
    """Overall verdict = the worst among its parts."""
    worst = "sehat"
    for v in vonis_list:
        if URUTAN_VONIS.get(v, 0) > URUTAN_VONIS[worst]:
            worst = v
    return worst


def _umur(db, tabel, kolom="timestamp"):
    """Age of a table's newest row in seconds; None if the table is empty."""
    if not dialek.tabel_ada(db, tabel):
        return None, None
    nilai = db.execute(text(f"SELECT MAX({kolom}) FROM {tabel}")).scalar()
    if not nilai:
        return None, None
    if isinstance(nilai, str):
        nilai = datetime.fromisoformat(nilai)
    return (datetime.now() - nilai).total_seconds(), nilai


def teks_umur(detik):
    """How long ago something happened, in readable form. Shared by the Health and Backup
    pages so both show the same wording.
    """
    if detik is None:
        return "belum pernah"
    return teks_durasi(detik) + " lalu"


def teks_durasi(detik):
    """Length of a time span WITHOUT the trailing "lalu" (ago), so it also fits
    differences such as clock skew.
    """
    if detik is None:
        return "-"
    detik = int(detik)
    if detik < 60:
        return f"{detik} detik"
    if detik < 3600:
        return f"{detik // 60} menit"
    if detik < 86400:
        return f"{detik // 3600} jam {detik % 3600 // 60} menit"
    return f"{detik // 86400} hari"


_teks_umur = teks_umur


def _periksa_job(db, nama, tabel, interval, hidup, kolom="timestamp",
                 catatan=None):
    if not hidup:
        return {
            "nama": nama, "vonis": "mati-sengaja",
            "nilai": "dimatikan",
            "ket": f"Job ini dimatikan lewat .env. Tabel `{tabel}` "
                   f"tidak akan bertambah, dan itu memang yang diminta.",
        }

    detik, waktu = _umur(db, tabel, kolom)
    if detik is None:
        return {
            "nama": nama, "vonis": "perhatian", "nilai": "belum ada data",
            "ket": f"Tabel `{tabel}` masih kosong. Wajar kalau job ini baru "
                   f"dinyalakan; kalau sudah lama begini, jobnya tidak pernah "
                   f"berhasil sekali pun.",
        }

    if detik > interval * KELIPATAN_BAHAYA:
        vonis = "bahaya"
        ket = (f"Baris terbaru di `{tabel}` sudah {_teks_umur(detik)}, "
               f"padahal job ini seharusnya menulis tiap {interval} detik. "
               f"Job ini hampir pasti tidak berjalan.")
    elif detik > interval * KELIPATAN_PERHATIAN:
        vonis = "perhatian"
        ket = (f"Terlambat: baris terbaru {_teks_umur(detik)}, sedangkan "
               f"intervalnya {interval} detik. Bisa berarti device-nya sedang "
               f"lambat menjawab, bisa juga jobnya baru saja tersendat.")
    else:
        vonis = "sehat"
        ket = f"Menulis tiap {interval} detik, sesuai jadwal."

    if catatan:
        ket += " " + catatan

    return {
        "nama": nama, "vonis": vonis,
        "nilai": _teks_umur(detik),
        "detik": round(detik),
        "interval": interval,
        "terakhir": waktu.isoformat() if waktu else None,
        "ket": ket,
    }


def _periksa_konfig(db):
    """Heartbeat of the config backup job.

    Not judged by newest-row age like `_periksa_job()`: it stores a snapshot only when
    the config changes, so a stable router can legitimately have weeks-old rows. What
    is judged is whether any device that should have a snapshot has none at all.
    """
    from models import Device, KonfigSnapshot
    from connectors import konfig as _konfig

    try:
        semua = db.query(Device).all()
    except Exception as e:
        return {"nama": "Job konfigurasi", "vonis": "perhatian",
                "nilai": "tidak terbaca", "ket": f"Gagal membaca daftar device: {e}"}

    layak = [d for d in semua
             if d.aktif != 0 and d.platform in _konfig.PERINTAH
             and d.username and d.password]

    if not layak:
        return {
            "nama": "Job konfigurasi", "vonis": "mati-sengaja",
            "nilai": "tidak ada perangkat",
            "ket": ("Belum ada perangkat yang platformnya mendukung backup "
                    "konfigurasi (saat ini Cisco IOS dan MikroTik RouterOS) "
                    "sekaligus punya kredensial. Job ini tidak punya pekerjaan, "
                    "dan itu bukan kesalahan."),
        }

    try:
        has = {r[0] for r in db.query(KonfigSnapshot.device_id).distinct().all()}
        total = db.query(func.count(KonfigSnapshot.id)).scalar() or 0
    except Exception as e:
        return {"nama": "Job konfigurasi", "vonis": "perhatian",
                "nilai": "tabel belum ada",
                "ket": ("Tabel `konfig_snapshots` belum bisa dibaca "
                        f"({e}). Migrasi `migrate_konfig.py` mungkin belum "
                        "dijalankan.")}

    not_yet = [d.name for d in layak if d.id not in has]

    if not_yet:
        return {
            "nama": "Job konfigurasi", "vonis": "perhatian",
            "nilai": f"{len(not_yet)} perangkat belum terpotret",
            "ket": ("Perangkat berikut seharusnya punya potret konfigurasi "
                    "tetapi belum punya satu pun: " + ", ".join(not_yet)
                    + ". Wajar kalau poller baru dinyalakan; kalau sudah lama "
                    "begini, pengambilannya selalu gagal (periksa kredensial "
                    "dan apakah SSH ke perangkat itu bisa dibuka)."),
        }

    return {
        "nama": "Job konfigurasi", "vonis": "sehat",
        "nilai": f"{total} potret, {len(layak)} perangkat",
        "ket": ("Semua perangkat yang mendukung sudah punya potret. Potret "
                "baru hanya ditambahkan saat konfigurasinya berubah, jadi "
                "angka yang lama tidak bertambah adalah keadaan yang normal."),
    }


def _jam_perangkat(db):
    """Whether the web server's clock agrees with NSM's clock.

    `akses_web` timestamps come from the Apache log content, not NSM's clock. A skewed
    VM clock puts every new row outside the Traffic page's period window, so the page
    quietly shows "0 requests" while data keeps arriving.

    Detected without touching the device: if the log read-position marker keeps
    advancing while the newest row's timestamp lags far behind, the gap can only come
    from the device clock.
    """
    from models import AksesWeb, PosisiLog, Device

    try:
        read_last = db.query(func.max(PosisiLog.diperbarui)).scalar()
        if read_last is None:
            return {
                "nama": "Jam perangkat", "vonis": "mati-sengaja",
                "nilai": "belum ada web server",
                "ket": ("Belum ada perangkat yang access log-nya dibaca, jadi "
                        "tidak ada jam yang bisa dibandingkan."),
            }

        line = (db.query(AksesWeb.device_id, func.max(AksesWeb.waktu))
                 .group_by(AksesWeb.device_id).all())
    except Exception as e:
        return {"nama": "Jam perangkat", "vonis": "perhatian",
                "nilai": "tidak terbaca", "ket": f"Gagal memeriksa: {e}"}

    if not line:
        return {
            "nama": "Jam perangkat", "vonis": "perhatian",
            "nilai": "belum ada baris log",
            "ket": ("Penanda posisi baca sudah diperbarui, tetapi belum ada "
                    "satu pun baris access log yang tersimpan."),
        }

    name_dev = {d.id: d.name for d in db.query(Device).all()}
    sekarang = datetime.now()
    meleset = []
    for did, time_last in line:
        w = _ke_waktu_lokal(time_last)
        if w is None:
            continue
        difference = (sekarang - w).total_seconds()
        # Threshold is five minutes. The service check hits `/hello.php` every 30 s, so the
        # access log is never idle: worst-case newest-row age is about 60 s (traffic job
        # interval) + 30 s (service check interval) + slack. Five minutes leaves nearly 2x
        # margin and still catches multi-minute skew.
        if difference > 300:
            meleset.append((name_dev.get(did, f"device {did}"), difference))

    if not meleset:
        return {
            "nama": "Jam perangkat", "vonis": "sehat",
            "nilai": "sejalan",
            "ket": ("Cap waktu di access log sejalan dengan jam NSM, jadi "
                    "baris yang masuk jatuh di jendela periode yang benar."),
        }

    rincian = ", ".join(f"{n} tertinggal {teks_durasi(s)}" for n, s in meleset)
    return {
        "nama": "Jam perangkat", "vonis": "bahaya",
        "nilai": f"{len(meleset)} perangkat melenceng",
        "ket": (f"{rincian}. Cap waktu baris access log diambil dari isi log "
                "perangkat, jadi selisih jam membuat barisnya jatuh DI LUAR "
                "jendela periode: halaman Lalu Lintas akan kehilangan baris "
                "itu padahal datanya masuk dengan benar.\n\n"
                "Menyetel jam sekali dengan `date -s` TIDAK cukup kalau "
                "selisihnya terus bertambah — itu tanda jam tamu melar, "
                "biasanya karena VM kekurangan jatah CPU. Yang memperbaikinya "
                "terus-menerus: nyalakan penyelaras waktu VirtualBox "
                "(`sudo systemctl enable --now vboxadd-service`) atau pasang "
                "penyelaras NTP sungguhan (`sudo apt install systemd-timesyncd` "
                "lalu `sudo timedatectl set-ntp true`). Perlu diperiksa juga "
                "apakah `timedatectl` melaporkan NTPSynchronized=yes; NTP=yes "
                "saja tidak berarti apa-apa kalau daemonnya tidak terpasang."),
    }


def _ke_waktu_lokal(nilai):
    """SQLite may return a datetime or a string; both are handled."""
    if nilai is None or isinstance(nilai, datetime):
        return nilai
    for pattern in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(nilai), pattern)
        except ValueError:
            continue
    return None


def _putaran_terlewat(db, interval, jam=1):
    limit = datetime.now() - timedelta(hours=jam)
    line = db.execute(text("""
        SELECT sebelum, sesudah FROM (
            SELECT LAG(timestamp) OVER (ORDER BY timestamp) AS sebelum,
                   timestamp AS sesudah
            FROM (SELECT DISTINCT timestamp FROM status_logs
                  WHERE timestamp >= :b) AS D
        ) AS L
        WHERE sebelum IS NOT NULL
          AND %s > :amb
    """ % dialek.selisih_detik_sql(db, "sebelum", "sesudah")),
        {"b": limit, "amb": interval * KELIPATAN_TERLEWAT}).all()

    lompatan = []
    for a, b in line:
        if isinstance(a, str):
            a = datetime.fromisoformat(a)
        if isinstance(b, str):
            b = datetime.fromisoformat(b)
        lompatan.append(round((b - a).total_seconds(), 1))

    n = len(lompatan)
    if n == 0:
        vonis, ket = "sehat", (
            f"Tidak ada putaran ping yang melar dalam {jam} jam terakhir.")
    elif n <= 3:
        vonis, ket = "perhatian", (
            f"{n} putaran melar, terlama {max(lompatan)} detik. Sesekali "
            f"terjadi saat banyak device jatuh berbarengan.")
    else:
        vonis, ket = "bahaya", (
            f"{n} putaran melar dalam {jam} jam, terlama {max(lompatan)} "
            f"detik. Ini pola berebut giliran menulis, bukan kebetulan.")

    return {
        "nama": "Kerapatan putaran ping",
        "vonis": vonis,
        "nilai": f"{n} melar / {jam} jam",
        "ket": ket,
        "lompatan": sorted(lompatan, reverse=True)[:5],
    }


def _replikasi():
    """Whether the database copy at Site B is still following.

    Asked over SSH to `.101` instead of connecting to port 3306: cross-site SSH is
    already allowed, while cross-site 3306 is deliberately blocked. The MySQL account
    there uses `auth_socket` and holds only `REPLICATION CLIENT`, so NSM stores no
    password and the account can read no data.
    """
    from connectors import replikasi as _repl
    from connectors.ssh import SshConnector

    if not config.get_replikasi_enabled():
        return {"nama": "Replika basis data (Lokasi B)",
                "vonis": "mati-sengaja",
                "nilai": "tidak diperiksa",
                "ket": "Dimatikan lewat .env (REPLIKASI_ENABLED).",
                "rincian": []}

    host = config.get_replikasi_host()
    try:
        c = SshConnector(host, username=config.get_ssh_user(),
                         password=config.get_ssh_pass())
        output = c.jalankan_perintah(_repl.PERINTAH, timeout=8)
    except Exception as e:
        return _repl.vonis({}, terjangkau=False, galat=type(e).__name__)
    return _repl.vonis(_repl.urai(output))


def _pemulihan_backup():
    """When the last backup was PROVEN restorable.

    `_backup()` above only answers "does the file exist and is it fresh". A backup can
    be fresh and still unrestorable. The source is the JSON written by
    `verifikasi_pulih.py`, not a database row, so the record stays readable even if the
    database itself is what broke.
    """
    import json

    jalur = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "verifikasi-pulih-terakhir.json")
    if not os.path.exists(jalur):
        return {
            "nama": "Pemulihan backup", "vonis": "perhatian",
            "nilai": "belum pernah dibuktikan",
            "ket": ("Belum ada satu pun catatan uji pemulihan. Backup yang "
                    "belum pernah diuji pulih adalah harapan, bukan cadangan. "
                    "Jalankan `verifikasi_pulih.py`, atau daftarkan tugas "
                    "terjadwalnya."),
        }
    try:
        with open(jalur, encoding="utf-8") as f:
            c = json.load(f)
        waktu = datetime.fromisoformat(c["waktu"])
    except Exception as e:
        return {"nama": "Pemulihan backup", "vonis": "perhatian",
                "nilai": "catatan rusak",
                "ket": "Catatan uji pemulihan tidak bisa dibaca: %s"
                       % str(e)[:120]}

    age = (datetime.now() - waktu).total_seconds()
    teks_umur = _teks_umur(age)
    detail = "; ".join("%s %s" % (h.get("berkas"), h.get("ringkas"))
                      for h in (c.get("hasil") or []))

    # Postponed is not failed: `verifikasi_pulih.py` postpones itself when host RAM is
    # tight, so `semua_lolos: None` must not be read as a failed backup.
    if c.get("ditunda"):
        old_age = age > 14 * 86400
        return {"nama": "Pemulihan backup",
                "vonis": "perhatian" if old_age else "sehat",
                "nilai": "ditunda %s" % teks_umur,
                "ket": ("Uji pemulihan terakhir DITUNDA, bukan gagal. %s%s"
                        % (c.get("alasan") or "",
                           " Sudah lebih dari dua minggu ditunda terus -- "
                           "periksa apakah host memang selalu sesak."
                           if old_age else ""))}

    if not c.get("semua_lolos"):
        return {"nama": "Pemulihan backup", "vonis": "bahaya",
                "nilai": "GAGAL dipulihkan",
                "ket": ("Uji pemulihan terakhir (%s) GAGAL. Backup-nya ada, "
                        "tetapi belum tentu bisa dikembalikan. %s"
                        % (teks_umur, detail))}

    if age > 10 * 86400:
        return {"nama": "Pemulihan backup", "vonis": "perhatian",
                "nilai": "terakhir %s" % teks_umur,
                "ket": ("Terakhir dibuktikan %s. Jadwalnya mingguan, jadi "
                        "setidaknya satu kali terlewat. %s"
                        % (teks_umur, detail))}

    return {"nama": "Pemulihan backup", "vonis": "sehat",
            "nilai": "terbukti %s" % teks_umur,
            "ket": ("Backup terbukti BISA DIPULIHKAN %s -- dipulihkan sungguhan "
                    "ke basis data pembuangan lalu dibandingkan jumlah "
                    "barisnya. %s" % (teks_umur, detail))}


def _pagar_otomasi(db):
    """State of the automation gate (`pagar`): armed or not, and how many decisions are
    recorded. Disabled automation is the intentional default; automation that is
    enabled without anyone noticing is what deserves attention.
    """
    from sqlalchemy import select, func
    from models import PagarTindakan
    import pagar_otomasi as _pg

    try:
        allow = config.get_pagar_daftar_putih()
        saklar = {
            "gns3": config.get_pemulih_gns3_aktif(),
            "layanan": config.get_pemulih_layanan_aktif(),
            "interface": config.get_pemulih_interface_aktif(),
            "konfig": config.get_pemulih_konfig_aktif(),
        }
        nyala = [k for k, v in saklar.items() if v]

        total = db.execute(
            select(func.count()).select_from(PagarTindakan)).scalar() or 0
        permission = db.execute(
            select(func.count()).select_from(PagarTindakan)
            .where(PagarTindakan.keputusan == _pg.IZIN)).scalar() or 0
        fail = db.execute(
            select(func.count()).select_from(PagarTindakan)
            .where(PagarTindakan.status_verifikasi.is_(False))).scalar() or 0
    except Exception as e:
        return {"nama": "Pagar otomasi", "vonis": "perhatian",
                "nilai": "tidak terbaca",
                "ket": "Keadaan pagar otomasi tidak bisa dibaca: %s" % str(e)[:120]}

    if not allow and not nyala:
        return {
            "nama": "Pagar otomasi", "vonis": "sehat",
            "nilai": "terkunci penuh",
            "ket": ("Tidak ada kunci di daftar putih DAN keempat kill-switch "
                    "pemulih mati. NSM tidak akan menyentuh perangkat mana pun "
                    "secara otomatis. Ini keadaan bawaan dan disengaja. "
                    "Tercatat %d keputusan (%d izin, %d verifikasi gagal)."
                    % (total, permission, fail)),
        }

    return {
        "nama": "Pagar otomasi", "vonis": "perhatian",
        "nilai": "AKTIF sebagian",
        "ket": ("Daftar putih: %s. Kill-switch menyala: %s. Artinya NSM BOLEH "
                "menyentuh perangkat sendiri untuk hal-hal itu. Tercatat %d "
                "keputusan (%d izin, %d verifikasi gagal). Kalau ini tidak "
                "disengaja, kosongkan `PAGAR_DAFTAR_PUTIH` di `.env`."
                % (", ".join(sorted(allow)) or "(kosong)",
                   ", ".join(nyala) or "(tidak ada)", total, permission, fail)),
    }


def _basis_data(db):
    rincian = []
    vonis = "sehat"
    record = []

    simpan = dialek.keterangan_penyimpanan(db)
    rincian.append({"label": simpan["label"], "nilai": simpan["nilai"],
                    "ket": simpan["ket"]})

    # Shown even when empty: a row that only appears when something is wrong is not
    # recognized when the problem finally arrives.
    try:
        import penyangga
        held = penyangga.jumlah_tertahan()
        total = sum(held.values())
        if total:
            rincian.append({
                "label": "Penyangga lokal",
                "nilai": "%d baris menunggu" % total,
                "ket": ("Basis data sempat tidak terjangkau. Baris ini "
                        "tersimpan di penyangga.db dan akan dikirim sendiri "
                        "pada putaran poller berikutnya yang berhasil: %s"
                        % ", ".join("%s=%d" % kv
                                    for kv in sorted(held.items()))),
            })
            vonis = "perhatian"
            record.append("%d baris masih menunggu di penyangga lokal. Kalau "
                         "angkanya tidak turun, sambungan ke basis data belum "
                         "pulih." % total)
        else:
            rincian.append({
                "label": "Penyangga lokal",
                "nilai": "kosong",
                "ket": ("Tidak ada hasil pengukuran yang tertahan. Penyangga "
                        "menampung sementara kalau basis data tidak "
                        "terjangkau, supaya pemantauan tidak berhenti justru "
                        "saat jaringan bermasalah."),
            })
    except Exception as e:
        rincian.append({"label": "Penyangga lokal", "nilai": "tidak terbaca",
                        "ket": str(e)[:120]})

    if not simpan["sehat"]:
        vonis = "perhatian"
        record.append("Basis data TIDAK dalam mode WAL. Halaman akan terasa "
                     "tersendat setiap kali poller menulis.")

    # Size is read from the anchored path, not a relative name: if uvicorn starts from
    # the wrong folder, a relative `os.path.exists` returns False and the page would show
    # 0.0 MB, a plausible-looking number.
    #
    # `database` is imported inside the function and its attribute read at call time
    # (not `from database import JALUR_DB`) because `uji_kesehatan.py` replaces
    # `database.JALUR_DB`; a from-import binds the value at load time and the test would
    # silently measure the wrong file.
    import database
    folder_db = os.path.dirname(database.JALUR_DB)

    size = {}
    for nama in ("nsm.db", "nsm.db-wal", "nsm.db-shm"):
        jalur = os.path.join(folder_db, nama)
        size[nama] = os.path.getsize(jalur) if os.path.exists(jalur) else 0

    if dialek._mysql(db):
        mb = db.execute(text(
            "SELECT SUM(data_length + index_length) / 1024 / 1024 "
            "FROM information_schema.tables WHERE table_schema = DATABASE()"
        )).scalar() or 0
        size_primary_mb = float(mb)
        rincian.append({
            "label": "Ukuran basis data",
            "nilai": f"{size_primary_mb:.1f} MB",
            "ket": f"Di {database.keterangan()}. Tumbuh terutama dari "
                   f"status_logs. `pangkas_data.py` yang memangkasnya.",
        })
    else:
        size_primary_mb = size["nsm.db"] / 1024 / 1024
        rincian.append({
            "label": "Ukuran nsm.db",
            "nilai": f"{size_primary_mb:.1f} MB",
            "ket": "Tumbuh terutama dari status_logs. `pangkas_data.py` yang "
                   "memangkasnya.",
        })

    wal_mb = size["nsm.db-wal"] / 1024 / 1024
    if not dialek._mysql(db):
      rincian.append({
        "label": "Ukuran nsm.db-wal",
        "nilai": f"{wal_mb:.1f} MB",
        "ket": "Normal beberapa MB. Kalau terus membesar, ada transaksi yang "
               "dibuka lama tanpa di-commit.",
      })
    if not dialek._mysql(db) and wal_mb > 64:
        vonis = _gabung([vonis, "perhatian"])
        record.append(f"Berkas WAL sudah {wal_mb:.0f} MB. Biasanya berarti ada "
                     f"transaksi panjang yang menahan pemangkasan WAL.")

    try:
        total, used, remaining = shutil.disk_usage(folder_db)
        remaining_gb = remaining / 1024 ** 3
        rincian.append({
            # Machine name is read from the system, not hardcoded: after the move to the
            # `nsm-app` VM a fixed "laptop" label would name the wrong machine.
            "label": "Sisa disk %s" % _nama_mesin(),
            "nilai": f"{remaining_gb:.1f} GB",
            "ket": ("Yang menampung penyangga lokal, bukan basis datanya. "
                    "Disk server basis data tidak terbaca dari sini."
                    if dialek._mysql(db) else
                    "Disk penuh membuat SQLite gagal menulis, dan pemantauan "
                    "berhenti tanpa pesan yang jelas."),
        })
        if remaining_gb < 1:
            vonis = "bahaya"
            record.append(f"Sisa ruang disk cuma {remaining_gb:.1f} GB.")
        elif remaining_gb < 5:
            vonis = _gabung([vonis, "perhatian"])
            record.append(f"Sisa ruang disk tinggal {remaining_gb:.1f} GB.")
    except OSError:
        pass

    jumlah = {}
    for t in ("devices", "status_logs", "device_events", "bandwidth_samples",
              "services", "service_events"):
        try:
            jumlah[t] = db.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
        except Exception:
            jumlah[t] = None

    return {
        "nama": "Basis data",
        "vonis": vonis,
        "nilai": f"{size_primary_mb:.1f} MB",
        "ket": " ".join(record) if record else
               ("Terbaca, penyangga kosong, ruang cukup."
                if dialek._mysql(db) else
                "Terbaca, mode WAL aktif, ruang disk cukup."),
        "rincian": rincian,
        "jumlah_baris": jumlah,
    }


def _backup():
    folder = config.get_backup_dir()

    # This machine is not where backups run. On the `nsm-app` VM (Linux), a Windows-style
    # backup path cannot belong to this host; that is a division of labor, not a fault.
    # Reporting "no backup files" there would be a false alarm that trains people to
    # ignore this page.
    if folder and os.name != "nt" and re.match(r"^[A-Za-z]:[\\/]", folder):
        return {
            "nama": "Backup", "vonis": "mati-sengaja",
            "nilai": "dijalankan di mesin lain",
            "ket": ("`BACKUP_DIR` menunjuk jalur Windows (`%s`), sedangkan "
                    "mesin ini bukan Windows. Pencadangan NSM memang "
                    "dijalankan dari laptop yang menjadi induk seluruh VM, "
                    "bukan dari sini -- jadi tidak ada yang bisa diperiksa "
                    "dari mesin ini. Keadaan backup yang sebenarnya dilihat "
                    "di laptop tersebut." % folder),
        }

    if not folder or not os.path.isdir(folder):
        return {"nama": "Backup", "vonis": "perhatian",
                "nilai": "folder tidak ada",
                "ket": f"BACKUP_DIR menunjuk `{folder}` yang tidak ditemukan."}

    berkas = [os.path.join(folder, f) for f in os.listdir(folder)
              if f.lower().endswith(".zip")]
    if not berkas:
        return {"nama": "Backup", "vonis": "bahaya", "nilai": "belum ada",
                "ket": "Tidak ada satu pun berkas backup di folder utama."}

    latest = max(berkas, key=os.path.getmtime)
    age = (datetime.now()
            - datetime.fromtimestamp(os.path.getmtime(latest))).total_seconds()

    note_secondary = ""
    try:
        import backup_nsm as _bn
        _ok2, _message2 = _bn.periksa_lokasi_kedua(folder, config.get_backup_dir2())
        if not _ok2:
            note_secondary = " CATATAN: " + _message2
    except Exception:
        pass

    if age > 36 * 3600:
        vonis = "bahaya"
        ket = (f"Backup terbaru {_teks_umur(age)}. Setidaknya satu jadwal "
               f"02:00 terlewat. Periksa halaman Backup.")
    elif age > 26 * 3600:
        vonis = "perhatian"
        ket = f"Backup terbaru {_teks_umur(age)}, sedikit lewat dari sehari."
    else:
        vonis = "sehat"
        ket = f"Backup terbaru {_teks_umur(age)}."

    ket = ket + note_secondary

    # Deliberately does not downgrade the verdict when backups sit on a single disk: the
    # owner has acknowledged there is no second disk, so a yellow flag could never go
    # green and would only train people to ignore the color. The condition stays fully
    # visible in `ket`. If `BACKUP_DIR2` is ever pointed at a truly separate disk, the
    # sentence disappears by itself.
    return {"nama": "Backup", "vonis": vonis, "nilai": _teks_umur(age),
            "ket": ket, "berkas": os.path.basename(latest),
            "jumlah_berkas": len(berkas)}


def ringkasan(db):
    """Full contents of the System Health page, already graded."""
    interval = config.get_interval()

    bagian = []

    poller = _periksa_job(
        db, "Poller (job ping)", "status_logs", interval, True,
        catatan="Ini denyut nadi utama NSM: kalau job ini berhenti, tidak ada "
                "data yang dicatat sama sekali.")
    bagian.append(poller)

    bagian.append(_putaran_terlewat(db, interval))

    bagian.append(_periksa_job(
        db, "Job bandwidth", "bandwidth_samples",
        config.get_bandwidth_interval(), config.get_bandwidth_enabled()))

    bagian.append(_periksa_job(
        db, "Job layanan", "service_checks",
        config.get_service_interval(), config.get_service_enabled()))

    bagian.append(_periksa_job(
        db, "Job lalu lintas", "flow_koneksi",
        config.get_traffic_interval(), config.get_traffic_enabled(),
        kolom="waktu"))

    # Config backup job. Judged by whether its table has ever been populated, not by
    # newest-row age, because it writes only when the config changes.
    bagian.append(_periksa_konfig(db))

    bagian.append(_jam_perangkat(db))

    bagian.append(_basis_data(db))

    bagian.append(_replikasi())

    bagian.append(_backup())

    bagian.append(_pemulihan_backup())

    bagian.append(_pagar_otomasi(db))

    hidup_notif = config.get_notif_enabled()
    bagian.append({
        "nama": "Job notifikasi",
        "vonis": "sehat" if hidup_notif else "mati-sengaja",
        "nilai": "aktif" if hidup_notif else "dimatikan",
        "ket": ("Berjalan tiap " + str(config.get_notif_interval())
                + " detik, tetapi hanya menulis saat ada gangguan yang perlu "
                  "dikirim. Karena itu keadaannya tidak bisa disimpulkan dari "
                  "umur data, dan tidak dinilai di sini. Bukti pengiriman yang "
                  "sungguhan ada di Audit Log.")
        if hidup_notif else
        "Dimatikan lewat .env (NOTIF_ENABLED).",
    })

    dinilai = [b["vonis"] for b in bagian if b["vonis"] != "mati-sengaja"]
    vonis = _gabung(dinilai)
    masalah = [b["ket"] for b in bagian if b["vonis"] in ("perhatian", "bahaya")]

    if vonis == "sehat":
        ringkas = "Semua bagian NSM berjalan sesuai jadwal."
    elif vonis == "perhatian":
        ringkas = f"{len(masalah)} hal perlu dilirik, belum ada yang berhenti."
    else:
        ringkas = f"{len(masalah)} hal bermasalah, ada bagian yang berhenti."

    return {
        "waktu": datetime.now().isoformat(),
        "vonis": vonis,
        "ringkas": ringkas,
        "masalah": masalah,
        "bagian": bagian,
    }

"""Tiered email notifications (docs/design/TIERED-NOTIFICATIONS.md).

Unlike `notifikasi.py` (`proses_antrean`, which emails immediately on a DOWN event and keeps
running alongside), this path holds back: a device must be down CONTINUOUSLY for
`NOTIF_PUTARAN_BUTUH x NOTIF_PUTARAN_MENIT` minutes (default 3x5 = 15) before any email.

Three kinds, one evaluator:
    mati  : down for the full window, not yet emailed for this outage.
    pulih : device already emailed as "mati" is now confirmed up (a successful ping). A
            device never emailed as "mati" gets no recovery email either.
    flap  : DOWN >= NOTIF_FLAP_AMBANG times within 1 hour; one email, then silence until
            calm for NOTIF_FLAP_TENANG_JAM hours. Covers devices that flap too fast to
            ever satisfy "mati".

State is recomputed from `status_logs` each round instead of kept as a counter, which could
silently drift from its source; only "already sent for THIS condition" is stored.
Devices meeting the same kind in one round are merged into ONE email via the Java endpoint
`/internal/notifikasi-gabungan`, which takes the UNION of subscribers across devices.
"""
from datetime import datetime, timedelta

from sqlalchemy import text

import config
from models import Device, DeviceEvent
from notifikasi import (
    _esc, _tabel_html, _pill_html, _tombol_html, format_durasi, _HIJAU,
)

gagal = []


# ---------------------------------------------------------------------------
# Evaluation: pure functions as far as possible (db + time in, data out, no side effects),
# so they can be tested without network or email.
# ---------------------------------------------------------------------------
def _down_terus_penuh(db, device_id, sekarang, menit, sampel_min):
    """True  = no successful ping in the window (fully down).
    False = at least one successful ping (recovered, or not down long enough).
    None  = fewer than `sampel_min` samples: NOT "down", just not enough data to judge (a dead
            poller must not read as "all devices down").
    """
    mulai = sekarang - timedelta(minutes=menit)
    line = db.execute(text(
        "SELECT COUNT(*) total, "
        "SUM(CASE WHEN is_reachable = 1 THEN 1 ELSE 0 END) berhasil "
        "FROM status_logs WHERE device_id = :did "
        "AND timestamp > :mulai AND timestamp <= :sekarang"
    ), {"did": device_id, "mulai": mulai, "sekarang": sekarang}).first()
    total = line[0] or 0
    succeed = line[1] or 0
    if total < sampel_min:
        return None
    return succeed == 0


def _hitung_down_1jam(db, device_id, sekarang):
    mulai = sekarang - timedelta(hours=1)
    n = db.execute(text(
        "SELECT COUNT(*) FROM device_events WHERE device_id = :did "
        "AND event_type = 'DOWN' AND timestamp > :mulai AND timestamp <= :sekarang"
    ), {"did": device_id, "mulai": mulai, "sekarang": sekarang}).scalar()
    return n or 0


def _mulai_gangguan_terakhir(db, device_id, sekarang):
    """When the device STARTED being down, taken from device_events (precise, 5 consecutive
    failures) rather than guessed from the notification window.
    """
    line = (db.query(DeviceEvent)
             .filter(DeviceEvent.device_id == device_id,
                     DeviceEvent.event_type == "DOWN")
             .order_by(DeviceEvent.timestamp.desc())
             .first())
    return line.timestamp if line else None


def nilai_semua(db, sekarang=None):
    """Evaluate ALL active devices against the three rules. Returns
    {"mati": [...], "pulih": [...], "flap": [...]} of Device objects.
    Sends and changes nothing; the caller (`proses`) sends and marks.
    """
    sekarang = sekarang or datetime.now()
    menit = config.get_notif_putaran_menit()
    require = config.get_notif_putaran_butuh()
    sampel_min = config.get_notif_sampel_min()
    threshold_flap = config.get_notif_flap_ambang()
    tenang = timedelta(hours=config.get_notif_flap_tenang_jam())
    window_total = menit * require

    hasil = {"mati": [], "pulih": [], "flap": []}
    devices = db.query(Device).filter(Device.aktif != 0).all()

    for d in devices:
        status = _down_terus_penuh(db, d.id, sekarang, window_total, sampel_min)
        if status is True and d.notif_mati_dikirim is None:
            hasil["mati"].append(d)
        elif status is False and d.notif_mati_dikirim is not None:
            hasil["pulih"].append(d)
        # status is None -> too few samples, skipped entirely this round (judged again next round).

        jumlah = _hitung_down_1jam(db, d.id, sekarang)
        if jumlah >= threshold_flap:
            if (d.notif_flap_dikirim is None
                    or (sekarang - d.notif_flap_dikirim) >= tenang):
                d._notif_flap_jumlah = jumlah
                hasil["flap"].append(d)

    return hasil


# ---------------------------------------------------------------------------
# Menyusun isi pesan gabungan
# ---------------------------------------------------------------------------
def susun_pesan_gabungan(jenis, daftar, cfg, sekarang=None, db=None):
    """Return (subject, html_content) for ONE kind, covering ALL devices in `daftar`."""
    sekarang = sekarang or datetime.now()
    n = len(daftar)

    if jenis == "mati":
        subjek = (f"[NSM] {daftar[0].name} TIDAK MERESPONS" if n == 1 else
                   f"[NSM] {n} device TIDAK MERESPONS")
        title = "Device bermasalah" + ("" if n == 1 else f" ({n} device)")
        pill = _pill_html("TIDAK MERESPONS", "#fde8e8", "#b42318")
        catatan = (f"Peringatan ini baru dikirim setelah device down TERUS "
                   f"selama {config.get_notif_putaran_menit() * config.get_notif_putaran_butuh()} "
                   f"menit penuh -- gangguan sesaat yang pulih sendiri "
                   f"sebelum itu TIDAK memicu email, supaya kotak masuk "
                   f"tidak penuh alarm palsu.")
        line = []
        for d in daftar:
            mulai = _mulai_gangguan_terakhir(db, d.id, sekarang) if db else None
            waktu = mulai.strftime("%d %B %Y, %H:%M:%S") if mulai else "-"
            line.append((_esc(d.name),
                          f"{_esc(d.ip_address)} &middot; {_esc(d.location) or '-'} "
                          f"&middot; mulai {waktu}"))
    elif jenis == "pulih":
        subjek = (f"[NSM] {daftar[0].name} kembali normal" if n == 1 else
                   f"[NSM] {n} device kembali normal")
        title = "Device pulih" + ("" if n == 1 else f" ({n} device)")
        pill = _pill_html("KEMBALI NORMAL", "#e7f4ec", "#1a7f37")
        catatan = "Rincian lengkap gangguan tersimpan di halaman riwayat tiap device."
        line = []
        for d in daftar:
            mulai = _mulai_gangguan_terakhir(db, d.id, sekarang) if db else None
            old = format_durasi((sekarang - mulai).total_seconds()) if mulai else "-"
            line.append((_esc(d.name),
                          f"{_esc(d.ip_address)} &middot; {_esc(d.location) or '-'} "
                          f"&middot; gangguan berlangsung {old}"))
    elif jenis == "flap":
        subjek = (f"[NSM] {daftar[0].name} tidak stabil" if n == 1 else
                   f"[NSM] {n} device tidak stabil")
        title = "Device tidak stabil (kedip-kedip)" + ("" if n == 1 else f" ({n} device)")
        pill = _pill_html("TIDAK STABIL", "#fef3cd", "#93670a")
        catatan = (f"Device ini sudah mati-hidup >= {config.get_notif_flap_ambang()} "
                   f"kali dalam 1 jam terakhir -- terlalu cepat untuk kena "
                   f"peringatan 'tidak merespons' biasa, tapi jelas ada "
                   f"masalah. Peringatan ini TIDAK akan diulang selama "
                   f"{config.get_notif_flap_tenang_jam()} jam ke depan, "
                   f"walau kedipannya berlanjut.")
        line = [(_esc(d.name),
                 f"{_esc(d.ip_address)} &middot; {_esc(d.location) or '-'} "
                 f"&middot; {getattr(d, '_notif_flap_jumlah', '?')} kali dalam 1 jam")
                 for d in daftar]
    else:
        raise ValueError(f"jenis notifikasi tidak dikenal: {jenis!r}")

    konten = (
        f'<h2 style="margin:0 0 10px;font-size:18px;color:#1a1a1a;">{title}</h2>'
        f'{pill}'
        f'{_tabel_html(line)}'
        f'<p style="color:#6b7280;font-size:13px;margin:14px 0 0;">{catatan}</p>'
        f'{_tombol_html(cfg["base_url"] + "/report", "Buka halaman Report")}'
    )
    return subjek, konten


def titip_gabungan_ke_java(cfg, subjek, isi, device_ids):
    """Like `notifikasi.titip_ke_java` but takes MANY device_ids; Java computes the union of
    subscribers so one user gets one email per round.
    """
    import json
    import urllib.error
    import urllib.request

    data = json.dumps({
        "subjek": subjek, "isi": isi, "device_ids": device_ids,
    }).encode("utf-8")
    permintaan = urllib.request.Request(
        cfg["url_gabungan"], data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(permintaan, timeout=20) as balasan:
            return json.loads(balasan.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"tidak bisa menghubungi Spring Boot di {cfg['url_gabungan']} ({e})")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Spring Boot membalas {e.code}: {e.read()[:200]}")


def proses(db, pengirim=titip_gabungan_ke_java, sekarang=None):
    sekarang = sekarang or datetime.now()
    if not config.get_notif_enabled():
        return {"mati": 0, "pulih": 0, "flap": 0, "alasan": "dimatikan"}

    cfg = config.get_notif_config()
    hasil = nilai_semua(db, sekarang)
    summary = {"mati": 0, "pulih": 0, "flap": 0}

    for jenis in ("mati", "pulih", "flap"):
        daftar = hasil[jenis]
        if not daftar:
            continue
        subjek, isi = susun_pesan_gabungan(jenis, daftar, cfg, sekarang, db)
        ids = [d.id for d in daftar]
        try:
            balasan = pengirim(cfg, subjek, isi, ids)
            for d in daftar:
                if jenis == "mati":
                    d.notif_mati_dikirim = sekarang
                elif jenis == "pulih":
                    d.notif_mati_dikirim = None
                elif jenis == "flap":
                    d.notif_flap_dikirim = sekarang
            db.commit()
            summary[jenis] = len(daftar)
            terkirim = balasan.get("terkirim") if isinstance(balasan, dict) else "?"
            print(f"[notif-jenjang] {subjek} -> {len(daftar)} device, "
                  f"{terkirim} email terkirim")
        except Exception as e:
            # Deliberately NOT marked: re-evaluated from `status_logs` next round, so it is retried
            # without a separate failure marker (unlike `notifikasi.py`, which has backoff).
            db.rollback()
            gagal.append(f"{jenis}: {e}")
            print(f"[notif-jenjang] GAGAL kirim {jenis} ({len(daftar)} device): {e}")

    return summary


# =============================================================================
# Auto-recovery tie-in (docs/design/CLOSED-LOOP-AUTOMATION.md).
#
# A problem that heals itself inside the 15-minute window never becomes an email; that is
# already the behavior of `nilai_semua()`. This function adds the other half: faster
# escalation when a recoverer FAILS. It is called directly by `pemulih/*.py` when
# `catat_verifikasi(..., False)` happens, instead of waiting for the normal `proses()` window.
# =============================================================================

def eskalasi_segera(db, device_id, ringkas, alasan, pengirim=titip_gabungan_ke_java):
    """Send ONE email IMMEDIATELY, outside the normal window/backoff; called by recoverers when
    automatic-fix verification FAILS.

    Does not touch `notif_mati_dikirim`/`notif_flap_dikirim`: this is an extra, faster email
    saying "NSM tried to fix it and failed", separate from `proses()`. Send failures are NOT
    raised, so they cannot break the caller's verification bookkeeping.
    """
    from models import Device
    d = db.get(Device, device_id)
    name_device = d.name if d else ("device #%s" % device_id)

    if not config.get_notif_enabled():
        return {"terkirim": False, "alasan": "notifikasi berjenjang dimatikan"}

    cfg = config.get_notif_config()
    subjek = "[NSM] Perbaikan otomatis GAGAL: %s" % name_device
    isi = (
        "NSM mendeteksi masalah pada %s dan mencoba memperbaikinya secara "
        "otomatis, TAPI PERBAIKANNYA GAGAL.\n\n"
        "Ringkasan: %s\n"
        "Alasan: %s\n\n"
        "Perlu pemeriksaan manual sekarang -- ini bukan notifikasi "
        "terjadwal biasa, dikirim segera karena NSM sudah mencoba sendiri "
        "dan tidak berhasil." % (name_device, ringkas, alasan)
    )
    try:
        balasan = pengirim(cfg, subjek, isi, [device_id])
        print("[pemulih->notif] eskalasi segera terkirim untuk %s" % name_device)
        return {"terkirim": True, "balasan": balasan}
    except Exception as e:
        print("[pemulih->notif] GAGAL mengirim eskalasi segera untuk %s: %s"
             % (name_device, e))
        return {"terkirim": False, "alasan": str(e)}

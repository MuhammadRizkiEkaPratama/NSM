"""Device alerts for all NSM users.

    poller records a transition -> one `device_events` row
    notification job checks     -> builds message -> hands it to Spring Boot
    Spring Boot                 -> finds active users -> sends email

Python does not send email itself: the user email list lives in Java's MySQL, and the
rule is "accounts are Java's, devices are Python's".
The job is separate from the ping loop so a hanging mail server cannot stall monitoring;
a failed row is left unmarked and retried next round. The sent marker is in the database,
not in memory, so a restarted poller does not resend old alerts.
"""
import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from sqlalchemy import desc

import config
from models import Device, DeviceEvent

TEKS_SEBAB = {
    "dead": "Tidak ada respons sama sekali: ping gagal dan tidak ada port TCP "
            "yang menjawab. Device kemungkinan mati atau terputus dari jaringan.",
    "ping_blocked": "Ping tidak dibalas, tetapi port TCP masih menjawab. "
                    "Device kemungkinan HIDUP dan ICMP-nya sedang diblokir "
                    "atau dibatasi.",
}


def format_durasi(detik):
    if detik is None:
        return "-"
    detik = int(detik)
    if detik < 60:
        return f"{detik} detik"
    menit, remaining = divmod(detik, 60)
    if menit < 60:
        return f"{menit} menit {remaining} detik" if remaining else f"{menit} menit"
    jam, remaining_minute = divmod(menit, 60)
    return f"{jam} jam {remaining_minute} menit" if remaining_minute else f"{jam} jam"


_HIJAU = "#2B6049"


def _esc(s):
    """Cegah karakter khusus (nama/lokasi device) merusak tata letak HTML."""
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _tabel_html(pasangan):
    tr = []
    for label, value in pasangan:
        tr.append(
            '<tr>'
            f'<td style="padding:4px 16px 4px 0;color:#6b7280;white-space:nowrap;'
            f'vertical-align:top;">{label}</td>'
            f'<td style="padding:4px 0;color:#1a1a1a;">{value}</td>'
            '</tr>')
    return ('<table cellpadding="0" cellspacing="0" '
            'style="margin:14px 0;font-size:14px;">' + "".join(tr) + "</table>")


def _pill_html(teks, latar, warna):
    return (f'<span style="display:inline-block;background:{latar};color:{warna};'
            f'font-weight:bold;font-size:12px;padding:3px 10px;border-radius:12px;">'
            f'{teks}</span>')


def _tombol_html(url, teks):
    return (f'<p style="margin:20px 0 6px;"><a href="{url}" '
            f'style="display:inline-block;background:{_HIJAU};color:#ffffff;'
            f'text-decoration:none;font-size:14px;font-weight:bold;padding:10px 22px;'
            f'border-radius:6px;">{teks}</a></p>')


# ---------------------------------------------------------------------------
# Menyusun isi pesan
# ---------------------------------------------------------------------------
def susun_pesan(d, ev, cfg):
    """Return (subject, html_content).

    The content is only the BODY fragment; the Java side wraps it in the shared email shell
    via `EmailService.shell()`.
    """
    fall = ev.event_type == "DOWN"
    waktu = ev.timestamp.strftime("%d %B %Y, %H:%M:%S") if ev.timestamp else "-"
    tautan = f"{cfg['base_url']}/report/device/{d.id}?period=24h"
    nama = _esc(d.name)

    if fall:
        subjek = f"[NSM] {d.name} TIDAK MERESPONS"
        title = f"Device bermasalah: {nama}"
        pill = _pill_html("TIDAK MERESPONS", "#fde8e8", "#b42318")
        line = [
            ("Alamat IP", _esc(d.ip_address)),
            ("Lokasi", _esc(d.location) or "-"),
            ("Mulai bermasalah", waktu),
            ("Hasil pemeriksaan",
             _esc(TEKS_SEBAB.get(ev.category, "Penyebab belum dapat ditentukan."))),
        ]
        catatan = ("Pemeriksaan ini hanya dari sisi jaringan. Penyebab fisik "
                   "seperti listrik padam, kabel lepas, atau perangkat yang "
                   "hang tidak bisa dibedakan dari jarak jauh.")
    else:
        subjek = f"[NSM] {d.name} kembali normal"
        title = f"Device pulih: {nama}"
        pill = _pill_html("KEMBALI NORMAL", "#e7f4ec", "#1a7f37")
        start = "-"
        if ev.timestamp and ev.duration_sec is not None:
            start = (ev.timestamp - timedelta(seconds=int(ev.duration_sec))
                     ).strftime("%d %B %Y, %H:%M:%S")
        line = [
            ("Alamat IP", _esc(d.ip_address)),
            ("Lokasi", _esc(d.location) or "-"),
            ("Mulai bermasalah", start),
            ("Pulih pada", waktu),
            ("Lama gangguan", format_durasi(ev.duration_sec)),
        ]
        catatan = "Rincian lengkap gangguan tersimpan di halaman riwayat device."

    konten = (
        f'<h2 style="margin:0 0 10px;font-size:18px;color:#1a1a1a;">{title}</h2>'
        f'{pill}'
        f'{_tabel_html(line)}'
        f'<p style="color:#6b7280;font-size:13px;margin:0;">{catatan}</p>'
        f'{_tombol_html(tautan, "Lihat riwayat device")}'
    )
    return subjek, konten


def titip_ke_java(cfg, subjek, isi, nama_device, device_id):
    """Send to Spring Boot to forward to this device's subscribers.

    Java holds the user list and subscriptions; Python only names the device.
    Raises if Java is unreachable OR there are subscribers but no email went out, so the event
    stays unmarked and is retried. A device with NO subscribers is not a failure: the event is
    marked done.
    """
    data = json.dumps({
        "subjek": subjek, "isi": isi, "device": nama_device,
        "device_id": device_id,
    }).encode("utf-8")
    permintaan = urllib.request.Request(
        cfg["url"], data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(permintaan, timeout=20) as reply:
            hasil = json.loads(reply.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"tidak bisa menghubungi Spring Boot di {cfg['url']} "
            f"({getattr(e, 'reason', e)}) — peringatan ditunda sampai hidup lagi")
    if hasil.get("pelanggan", 0) > 0 and not hasil.get("terkirim"):
        raise RuntimeError(f"Spring Boot tidak berhasil mengirim ke siapa pun: {hasil}")
    return hasil


# ---------------------------------------------------------------------------
# Increasing delay after failed sends
#
# A failed event is left unmarked and retried, but at a fixed interval that would hammer an
# unreachable SMTP server (and each attempt blocks the job for the connection timeout).
# Each failure doubles the wait: 30 s, 1 min, 5, 15, 30, capped at 1 hour.
# Kept in memory on purpose: after a restart everything pending is retried at once, which is
# wanted because restarts usually follow a fix.
# ---------------------------------------------------------------------------
TANGGA_JEDA_DETIK = [30, 60, 300, 900, 1800, 3600]
_tunda = {}  # event id -> (failure count, when it may be retried)


def _boleh_dicoba(event_id, sekarang):
    """True while the event is still in its wait period after a failure."""
    isi = _tunda.get(event_id)
    return isi is None or sekarang >= isi[1]


def _catat_gagal(event_id, sekarang):
    """Increment the failure count and return the delay used (seconds)."""
    fail_to = _tunda.get(event_id, (0, sekarang))[0] + 1
    pause_second = TANGGA_JEDA_DETIK[min(fail_to - 1, len(TANGGA_JEDA_DETIK) - 1)]
    _tunda[event_id] = (fail_to, sekarang + timedelta(seconds=pause_second))
    return fail_to, pause_second


def _lupakan(event_id):
    _tunda.pop(event_id, None)


def proses_antrean(db, pengirim=titip_ke_java):
    """Return a summary (sent, skipped, failed).

    `pengirim` can be replaced in tests so neither Spring Boot nor a mail server is contacted.
    """
    if not config.get_notif_enabled():
        return {"terkirim": 0, "dilewati": 0, "gagal": 0, "alasan": "dimatikan"}

    cfg = config.get_notif_config()
    pause = timedelta(minutes=config.get_notif_jeda_menit())
    sekarang = datetime.now()
    terkirim = dilewati = gagal = 0

    # All devices that are not paused are checked. Whether email goes out is decided by per-user
    # subscriptions on the Java side; with no subscribers Java answers "0 subscribers" and the
    # event is marked done without email. Paused devices stay skipped.
    devices = {d.id: d for d in db.query(Device).all() if d.aktif != 0}
    if not devices:
        return {"terkirim": 0, "dilewati": 0, "gagal": 0,
                "alasan": "tidak ada device aktif"}

    queue = (
        db.query(DeviceEvent)
        .filter(DeviceEvent.notif_terkirim.is_(None),
                DeviceEvent.device_id.in_(list(devices.keys())),
                DeviceEvent.category != "baseline")
        .order_by(DeviceEvent.timestamp, DeviceEvent.id)
        .all()
    )

    # If per-INCIDENT notification is on, events covered by an open incident are marked done
    # WITHOUT email (`notifikasi_insiden.proses()` sends for them). Marked rather than left
    # pending, so turning the switch off later does not release a flood of old events.
    tercakup = set()
    if config.get_notif_per_insiden():
        try:
            import notifikasi_insiden
            tercakup = notifikasi_insiden.device_events_tercakup(db)
        except Exception as e:                       # noqa: BLE001
            # A failure reading incidents must not silence notifications: fall back to the old path
            # (extra email is better than an unreported outage).
            print("[notif] tidak bisa membaca insiden, jalur per-kejadian "
                  "dipakai apa adanya: %s" % e)
            tercakup = set()

    tertunda = 0
    dicakup_insiden = 0
    for ev in queue:
        d = devices[ev.device_id]

        if ev.device_id in tercakup:
            ev.notif_terkirim = sekarang
            ev.note = ((ev.note or "") +
                       " [notifikasi dilewati: sudah dicakup insiden]").strip()
            db.commit()
            dicakup_insiden += 1
            continue

        # Still in the wait period after a failure? Skip without touching the network, so the
        # increasing delay actually reduces load.
        if not _boleh_dicoba(ev.id, sekarang):
            tertunda += 1
            continue

        # Flood guard: if this device just triggered an alert, mark the event done WITHOUT sending,
        # so a flapping device does not fill every inbox.
        last = (
            db.query(DeviceEvent.notif_terkirim)
            .filter(DeviceEvent.device_id == d.id,
                    DeviceEvent.notif_terkirim.isnot(None))
            .order_by(desc(DeviceEvent.notif_terkirim))
            .first()
        )
        if last and last[0] and (sekarang - last[0]) < pause:
            ev.notif_terkirim = sekarang
            ev.note = ((ev.note or "") +
                       " [notifikasi dilewati: terlalu berdekatan]").strip()
            db.commit()
            dilewati += 1
            continue

        subjek, isi = susun_pesan(d, ev, cfg)
        try:
            hasil = pengirim(cfg, subjek, isi, d.name, d.id)
            ev.notif_terkirim = sekarang
            # Commit per event, not once at the end: `pengirim` is an HTTP call to Spring Boot with a 20 s
            # timeout, and one hanging mail server would otherwise hold the SQLite write lock for 20 s and
            # block the ping job.
            db.commit()
            _lupakan(ev.id)
            terkirim += 1
            jumlah = hasil.get("terkirim") if isinstance(hasil, dict) else "?"
            print(f"[notif] {subjek} -> {jumlah} pelanggan")
        except Exception as e:
            # Deliberately NOT marked, so it is retried next round.
            gagal += 1
            fail_to, pause_second = _catat_gagal(ev.id, sekarang)
            print(f"[notif] tertunda untuk {d.name} (gagal ke-{fail_to}, "
                  f"dicoba lagi {pause_second} dtk lagi): {e}")

    still_queue = {ev.id for ev in queue}
    for kunci in [k for k in _tunda if k not in still_queue]:
        _lupakan(kunci)

    db.commit()
    return {"terkirim": terkirim, "dilewati": dilewati, "gagal": gagal,
            "tertunda": tertunda,
            # Reported separately from `dilewati`: `dilewati` = flapping device suppressed,
            # `dicakup_insiden` = already covered by one per-incident email.
            "dicakup_insiden": dicakup_insiden}

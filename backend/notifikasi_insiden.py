r"""One email per INCIDENT, not per event.

Rules:
1. New incident -> one email.
2. Severity RISES (`perhatian` -> `bahaya`) -> one follow-up email.
3. Severity unchanged -> silent, however many new symptoms arrive.
4. Incident closed -> one closing email, if `NOTIF_INSIDEN_PULIH=1` (set 0 to disable). The
   per-event path this replaces already sent recovery notices, so dropping them would
   silently remove a notification people rely on.

Recipients: the UNION of subscribers of ALL involved devices (root and downstream),
deduplicated per account by `/internal/notifikasi-gabungan` on the Java side. Using the
root only would be tidier but wrong: someone subscribed to LDAP cares that LDAP is unusable.

This module never touches devices, never reads `users`, and never sends email itself; it
hands off to Spring Boot like `notifikasi.py` and `notifikasi_berjenjang.py`.
"""
from datetime import datetime

from sqlalchemy import select

import config
import models
from korelasi import KEPARAHAN_URUT
from notifikasi import _esc, _pill_html, _tabel_html, _tombol_html
from notifikasi_berjenjang import titip_gabungan_ke_java

# Severity pill colors; same as other emails so a level always has the same color.
_PIL = {
    "bahaya":    ("#fee2e2", "#b91c1c", "BAHAYA"),
    "perhatian": ("#fef3c7", "#92400e", "PERHATIAN"),
    "info":      ("#e5e7eb", "#374151", "INFO"),
}


def _durasi(detik):
    """Duration in words; used in the email body, so it must read without explanation."""
    if detik is None:
        return "-"
    detik = max(0, int(detik))
    if detik < 60:
        return "%d detik" % detik
    minute, remaining = divmod(detik, 60)
    if minute < 60:
        return "%d menit %d detik" % (minute, remaining) if remaining else "%d menit" % minute
    hour, remaining_minute = divmod(minute, 60)
    if hour < 24:
        return ("%d jam %d menit" % (hour, remaining_minute) if remaining_minute
                else "%d jam" % hour)
    day, remaining_hour = divmod(hour, 24)
    return "%d hari %d jam" % (day, remaining_hour)


def _gejala(db, ins):
    return db.execute(select(models.InsidenGejala).where(
        models.InsidenGejala.insiden_id == ins.id
    ).order_by(models.InsidenGejala.waktu)).scalars().all()


def device_ids_insiden(db, ins):
    """Involved devices: the root plus every device with a symptom. The root is included even
    without symptom rows of its own, since its subscribers most need to know.
    """
    ids = {g.device_id for g in _gejala(db, ins) if g.device_id}
    if ins.akar_device_id:
        ids.add(ins.akar_device_id)
    return sorted(ids)


def susun_pesan(db, ins, cfg, jenis="baru"):
    """(subject, html_content) for one incident.

    `jenis`: 'baru' | 'naik' | 'pulih'. Subjects differ on purpose so the messages do not read
    as repeats in one inbox thread.
    """
    root_cause = (db.get(models.Device, ins.akar_device_id)
            if ins.akar_device_id else None)
    name_root_cause = root_cause.name if root_cause else "perangkat yang belum bisa dipastikan"
    symptom = _gejala(db, ins)
    severe = ins.keparahan if ins.keparahan in _PIL else "info"
    latar, warna, text_pil = _PIL[severe]

    if jenis == "pulih":
        subject = "[NSM] PULIH: %s (insiden #%d)" % (name_root_cause, ins.id)
        title = "Insiden #%d sudah pulih" % ins.id
        pil = _pill_html("PULIH", "#dcfce7", "#166534")
    elif jenis == "naik":
        subject = "[NSM] MEMBURUK: %s (insiden #%d)" % (name_root_cause, ins.id)
        title = "Insiden #%d naik jadi %s" % (ins.id, severe)
        pil = _pill_html(text_pil, latar, warna)
    else:
        subject = "[NSM] GANGGUAN: %s (insiden #%d)" % (name_root_cause, ins.id)
        title = "Gangguan pada %s" % name_root_cause
        pil = _pill_html(text_pil, latar, warna)

    line = [
        ("Akar", _esc(name_root_cause) + ("" if ins.akar_pasti is not False
                                    else " <i>(belum pasti)</i>")),
        ("Mulai", ins.mulai.strftime("%d %B %Y, %H:%M:%S") if ins.mulai else "-"),
        ("Keparahan", _esc(severe)),
        ("Perangkat terdampak", str(len({g.device_id for g in symptom
                                         if g.device_id}))),
        ("Gejala tercatat", str(len(symptom))),
    ]
    if jenis == "pulih":
        line.append(("Selesai", ins.selesai.strftime("%d %B %Y, %H:%M:%S")
                      if ins.selesai else "-"))
        line.append(("Lama gangguan (MTTR)", _durasi(ins.mttr_detik)))

    # The symptom list is included so recipients need not open the page to see which devices are affected.
    content_symptom = []
    for g in symptom:
        d = db.get(models.Device, g.device_id) if g.device_id else None
        mark = " <b>(akar)</b>" if (d and ins.akar_device_id == d.id) else ""
        state = "sudah pulih" if g.pulih else "masih bermasalah"
        content_symptom.append(
            '<li style="margin:3px 0;">%s%s &mdash; <span style="color:#6b7280;">'
            '%s, %s</span></li>'
            % (_esc(d.name if d else "?"), mark, _esc(g.detail or ""), state))
    daftar = ('<ul style="margin:12px 0;padding-left:20px;font-size:14px;'
              'color:#1a1a1a;">%s</ul>' % "".join(content_symptom)) if content_symptom else ""

    catatan = (
        "Empat alarm untuk satu gangguan menjadi satu pesan ini. "
        "Penyatuannya memakai graf ketergantungan NSM: perangkat yang berada "
        "di hilir perangkat yang rusak tidak dilaporkan sebagai rusak sendiri."
    )

    konten = (
        f'<h2 style="margin:0 0 10px;font-size:18px;color:#1a1a1a;">'
        f'{_esc(title)}</h2>'
        f'{pil}'
        f'<p style="font-size:14px;color:#1a1a1a;margin:14px 0 0;">'
        f'{_esc(ins.ringkas or "")}</p>'
        f'{_tabel_html(line)}'
        f'{daftar}'
        f'<p style="color:#6b7280;font-size:13px;margin:14px 0 0;">{catatan}</p>'
        f'{_tombol_html(cfg["base_url"] + "/insiden/" + str(ins.id), "Buka garis waktu insiden")}'
    )
    return subject, konten


def _kirim(db, ins, cfg, jenis, pengirim):
    ids = device_ids_insiden(db, ins)
    subject, content = susun_pesan(db, ins, cfg, jenis=jenis)
    hasil = pengirim(cfg, subject, content, ids)
    return hasil, ids


def proses(db, pengirim=titip_gabungan_ke_java, sekarang=None):
    """One per-incident notification round.

    Idempotent: each send marks its own column before the next round can see it.
    Returns a count summary for the poller's one-line log.
    """
    if not config.get_notif_enabled():
        return {"baru": 0, "naik": 0, "pulih": 0, "gagal": 0,
                "alasan": "notifikasi dimatikan"}
    if not config.get_notif_per_insiden():
        return {"baru": 0, "naik": 0, "pulih": 0, "gagal": 0,
                "alasan": "NOTIF_PER_INSIDEN=0"}

    sekarang = sekarang or datetime.now()
    cfg = config.get_notif_config()
    baru = naik = pulih = gagal = 0

    # 1. OPEN incidents: new, or severity rose
    for ins in db.execute(select(models.Insiden).where(
            models.Insiden.status == "terbuka"
    ).order_by(models.Insiden.mulai)).scalars().all():
        level_current = KEPARAHAN_URUT.get(ins.keparahan or "info", 0)
        level_past = KEPARAHAN_URUT.get(ins.notif_keparahan or "", -1)

        if not ins.notif_terkirim:
            jenis = "baru"
        elif level_current > level_past:
            jenis = "naik"
        else:
            # Silent: new symptoms that do not raise severity produce no email. This is the point of the module.
            continue

        try:
            _kirim(db, ins, cfg, jenis, pengirim)
            ins.notif_terkirim = True
            ins.notif_keparahan = ins.keparahan or "info"
            # Commit per incident, not once at the end: `pengirim` is an HTTP call with a 20 s timeout,
            # and holding a transaction that long blocks the poller's writes. See `notifikasi.proses_antrean`.
            db.commit()
            baru += 1 if jenis == "baru" else 0
            naik += 1 if jenis == "naik" else 0
        except Exception as e:                       # noqa: BLE001
            # Deliberately NOT marked: retried next round. Marking a failed send as sent would leave an
            # ongoing outage unannounced.
            db.rollback()
            gagal += 1
            print("[notif-insiden] gagal mengirim insiden #%s: %s" % (ins.id, e))

    # 2. Incidents already CLOSED: one closing email
    if config.get_notif_insiden_pulih():
        for ins in db.execute(select(models.Insiden).where(
                models.Insiden.status == "pulih",
                models.Insiden.notif_terkirim == True,          # noqa: E712
        ).order_by(models.Insiden.selesai)).scalars().all():
            if ins.notif_pulih_terkirim:
                continue
            try:
                _kirim(db, ins, cfg, "pulih", pengirim)
                ins.notif_pulih_terkirim = True
                db.commit()
                pulih += 1
            except Exception as e:                   # noqa: BLE001
                db.rollback()
                gagal += 1
                print("[notif-insiden] gagal mengirim pulih #%s: %s"
                      % (ins.id, e))

    return {"baru": baru, "naik": naik, "pulih": pulih, "gagal": gagal}


def device_events_tercakup(db, sejak=None):
    """device_ids currently covered by an open incident.

    Used by `notifikasi.proses_antrean()` to mark events done WITHOUT email when
    `NOTIF_PER_INSIDEN=1`; left pending they would pile up and flood out when B4 is switched off.
    """
    ids = set()
    for ins in db.execute(select(models.Insiden).where(
            models.Insiden.status == "terbuka")).scalars().all():
        ids.update(device_ids_insiden(db, ins))
    return ids

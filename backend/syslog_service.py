r"""Store syslog, map it to devices, and use it as evidence.

Split from `syslog_terima.py`, which holds PURE parsing (testable without network or
database); this file holds everything that touches the database.

Three decisions:
1. Address -> device mapping is a GUESS. UDP syslog is unauthenticated and the sender
   address can be spoofed, so `alamat` is stored as-is and `device_id` is only a hint.
   Unknown senders are still stored (`device_id` NULL) because they deserve attention.
2. A message NEVER acts on a device directly. Syslog is evidence and a trigger for CHECKS;
   the decision belongs to `pagar_otomasi`, which verifies real state first. Otherwise one
   forged UDP packet could make NSM act.
3. Floods are limited per template, not per message: a flapping interface can send hundreds
   per minute, and a plain cap would drop OTHER important messages. Limiting per template
   fingerprint drops repeats and lets different messages through.
"""
from datetime import datetime, timedelta

from sqlalchemy import case, func, select

import models
from syslog_terima import AMBANG_PENTING, penting

# Damping window: messages with the same template fingerprint from the same device are stored
# once per interval. Short enough to keep truly repeating events, long enough to damp flapping.
JENDELA_REDAM_DETIK = 30

# Tags that TRIGGER A CHECK (not an action). See decision 2.
PEMICU_PERIKSA_KONFIG = ("%SYS-5-CONFIG_I", "%SYS-6-CFG_CHG",
                         "%SYS-5-CONFIG_NV_I")


def peta_alamat(db):
    """{ip_address: device_id} for all active devices.

    Built once and reused by the receiver: a lookup per message would be one query per
    datagram, and syslog can arrive thousands of times per minute.
    """
    peta = {}
    for d in db.execute(
        select(models.Device).where(models.Device.aktif == True)  # noqa: E712
    ).scalars().all():
        if d.ip_address:
            peta[d.ip_address.strip()] = d.id
    return peta


def _baru_saja_sama(db, device_id, alamat, sidik, sekarang):
    """Whether a message with the same template was just stored."""
    if not sidik:
        return False
    batas = sekarang - timedelta(seconds=JENDELA_REDAM_DETIK)
    q = select(func.count(models.SyslogPesan.id)).where(
        models.SyslogPesan.sidik_templat == sidik,
        models.SyslogPesan.waktu >= batas)
    q = (q.where(models.SyslogPesan.device_id == device_id)
         if device_id is not None
         else q.where(models.SyslogPesan.alamat == alamat))
    return (db.execute(q).scalar() or 0) > 0


def simpan(db, hasil, peta=None, redam=True):
    """Store one `urai()` result. Returns the row, or None if damped.

    Does not raise for expected conditions: the receiver must not stop because one message failed to store.
    """
    peta = peta if peta is not None else peta_alamat(db)
    alamat = hasil.get("alamat") or "?"
    device_id = peta.get(alamat)
    sekarang = hasil.get("waktu") or datetime.now()

    if redam and _baru_saja_sama(db, device_id, alamat,
                                 hasil.get("sidik_templat"), sekarang):
        return None

    line = models.SyslogPesan(
        waktu=sekarang,
        device_id=device_id,
        alamat=alamat[:45],
        facility=hasil.get("facility"),
        severity=hasil.get("severity"),
        tag=(hasil.get("tag") or None),
        pesan=(hasil.get("pesan") or "")[:8000],
        sidik_templat=hasil.get("sidik_templat"),
        jadi_event=None,
    )
    db.add(line)
    db.commit()
    return line


def templat_baru(db, sidik, sejak_hari=30):
    """True if this template fingerprint has NEVER been seen before.

    The most valuable signal in the stream: the device said something it never said before.
    It is the basis of log pattern mining.
    """
    if not sidik:
        return False
    batas = datetime.now() - timedelta(days=sejak_hari)
    n = db.execute(select(func.count(models.SyslogPesan.id)).where(
        models.SyslogPesan.sidik_templat == sidik,
        models.SyslogPesan.waktu >= batas)).scalar() or 0
    return n <= 1


def perlu_periksa_konfig(hasil):
    """Whether this message indicates someone just changed the configuration.

    `%SYS-5-CONFIG_I: Configured from console by vty0 (<ip>)` is the only way NSM learns WHO
    changed the configuration and FROM WHERE. It only triggers an earlier drift CHECK, never
    an action (decision 2 in the module docstring).
    """
    tag = (hasil.get("tag") or "").upper()
    return any(tag.startswith(p) for p in PEMICU_PERIKSA_KONFIG)


def ringkas(db, jam=24):
    """Summary for the page: how many messages, from whom, which templates."""
    batas = datetime.now() - timedelta(hours=jam)
    total = db.execute(select(func.count(models.SyslogPesan.id)).where(
        models.SyslogPesan.waktu >= batas)).scalar() or 0
    gawat = db.execute(select(func.count(models.SyslogPesan.id)).where(
        models.SyslogPesan.waktu >= batas,
        models.SyslogPesan.severity <= AMBANG_PENTING)).scalar() or 0
    not_known = db.execute(select(func.count(models.SyslogPesan.id)).where(
        models.SyslogPesan.waktu >= batas,
        models.SyslogPesan.device_id.is_(None))).scalar() or 0
    template = db.execute(
        select(models.SyslogPesan.sidik_templat,
               func.count(models.SyslogPesan.id).label("n"))
        .where(models.SyslogPesan.waktu >= batas)
        .group_by(models.SyslogPesan.sidik_templat)
        .order_by(func.count(models.SyslogPesan.id).desc())
        .limit(10)).all()
    return {
        "jam": jam,
        "total": total,
        "penting": gawat,
        "dari_pengirim_tak_dikenal": not_known,
        "templat_teratas": [{"sidik": s, "jumlah": n} for s, n in template],
    }





# FOR THE SYSLOG PAGE
#
# `ringkas()` only gives three counts and ten template fingerprints, enough for a summary
# card but not for a page. The four functions below complete it; all are read-only.

# Syslog severity names (RFC 3164). Numbers are inverted from intuition: 0 is the most
# severe, 7 the most trivial. Named once here so no page translates them differently.
NAMA_SEVERITY = {
    0: "darurat", 1: "peringatan keras", 2: "kritis", 3: "galat",
    4: "peringatan", 5: "perlu dicatat", 6: "informasi", 7: "penelusuran",
}


def deret_jam(db, jam=24):
    """Message count per hour, split into important and ordinary.

    Used by the page chart. Grouped in the database rather than counting rows in Python, since
    this table grows every second and the page is opened when the network is in trouble.
    """
    batas = datetime.now() - timedelta(hours=jam)

    # Hour rounding must be done by the database, and the two databases name it differently:
    # MySQL uses `DATE_FORMAT`, while the tests run on SQLite, which only has `strftime`.
    dialek = db.get_bind().dialect.name
    if dialek == "sqlite":
        column = func.strftime("%Y-%m-%d %H:00", models.SyslogPesan.waktu)
    else:
        column = func.date_format(models.SyslogPesan.waktu, "%Y-%m-%d %H:00")

    line = db.execute(
        select(column.label("jam"),
               func.count(models.SyslogPesan.id).label("semua"),
               func.sum(case(
                   (models.SyslogPesan.severity <= AMBANG_PENTING, 1), else_=0
               )).label("penting"))
        .where(models.SyslogPesan.waktu >= batas)
        .group_by(column).order_by(column)).all()
    return [{"jam": j, "semua": int(s or 0), "penting": int(p or 0)}
            for j, s, p in line]


def per_device(db, jam=24):
    """Who talks most, and how severe it is.

    Unknown senders are reported by their address, not dropped: UDP syslog is unauthenticated
    and a foreign sender deserves attention.
    """
    batas = datetime.now() - timedelta(hours=jam)
    line = db.execute(
        select(models.SyslogPesan.device_id,
               models.SyslogPesan.alamat,
               func.count(models.SyslogPesan.id).label("n"),
               func.min(models.SyslogPesan.severity).label("terparah"))
        .where(models.SyslogPesan.waktu >= batas)
        .group_by(models.SyslogPesan.device_id, models.SyslogPesan.alamat)
        .order_by(func.count(models.SyslogPesan.id).desc())).all()

    nama = {d.id: d.name for d in db.execute(select(models.Device)).scalars()}
    hasil = []
    for did, alamat, n, terparah in line:
        hasil.append({
            "device_id": did,
            "nama": nama.get(did) or ("pengirim tak dikenal (%s)" % alamat),
            "dikenal": did is not None,
            "alamat": alamat,
            "jumlah": int(n),
            "terparah": int(terparah) if terparah is not None else None,
            "terparah_nama": NAMA_SEVERITY.get(terparah, "tidak diketahui"),
        })
    return hasil


def per_tag(db, jam=24, batas_baris=12):
    """Messages grouped by Cisco tag, not by full sentence.

    A single tag can dominate the stream (one tag held 96.5% in this lab), which a scrolling
    message list would never reveal.
    """
    batas = datetime.now() - timedelta(hours=jam)
    line = db.execute(
        select(models.SyslogPesan.tag,
               func.count(models.SyslogPesan.id).label("n"),
               func.min(models.SyslogPesan.severity).label("terparah"),
               func.max(models.SyslogPesan.waktu).label("terakhir"))
        .where(models.SyslogPesan.waktu >= batas)
        .group_by(models.SyslogPesan.tag)
        .order_by(func.count(models.SyslogPesan.id).desc())
        .limit(batas_baris)).all()
    total = sum(int(n) for _, n, _, _ in line) or 1
    return [{
        "tag": t or "(tanpa tag)",
        "jumlah": int(n),
        "persen": round(int(n) * 100.0 / total, 1),
        "terparah": int(s) if s is not None else None,
        "terparah_nama": NAMA_SEVERITY.get(s, "tidak diketahui"),
        "terakhir": w.isoformat(sep=" ", timespec="seconds") if w else None,
    } for t, n, s, w in line]


def daftar(db, jam=24, device_id=None, tag=None, hanya_penting=False,
           cari=None, halaman=1, per_halaman=5):
    """Paginated message list.

    `per_halaman` defaults to 5 per NSM's display rule: history tables sit below the summary,
    and ten rows already push the page past one screen (see `js/halaman-tabel.js`).
    """
    batas = datetime.now() - timedelta(hours=jam)
    saring = [models.SyslogPesan.waktu >= batas]
    if device_id is not None:
        saring.append(models.SyslogPesan.device_id == device_id)
    if tag:
        saring.append(models.SyslogPesan.tag == tag)
    if hanya_penting:
        saring.append(models.SyslogPesan.severity <= AMBANG_PENTING)
    if cari:
        saring.append(models.SyslogPesan.pesan.like("%" + cari + "%"))

    total = db.execute(select(func.count(models.SyslogPesan.id))
                       .where(*saring)).scalar() or 0

    halaman = max(1, int(halaman))
    per_halaman = max(1, min(100, int(per_halaman)))
    line = db.execute(
        select(models.SyslogPesan)
        .where(*saring)
        .order_by(models.SyslogPesan.waktu.desc(), models.SyslogPesan.id.desc())
        .offset((halaman - 1) * per_halaman)
        .limit(per_halaman)).scalars().all()

    nama = {d.id: d.name for d in db.execute(select(models.Device)).scalars()}
    return {
        "total": total,
        "halaman": halaman,
        "per_halaman": per_halaman,
        "jumlah_halaman": max(1, (total + per_halaman - 1) // per_halaman),
        "pesan": [{
            "id": p.id,
            "waktu": p.waktu.isoformat(sep=" ", timespec="seconds"),
            "device_id": p.device_id,
            "nama": nama.get(p.device_id) or ("tak dikenal (%s)" % p.alamat),
            "dikenal": p.device_id is not None,
            "alamat": p.alamat,
            "severity": p.severity,
            "severity_nama": NAMA_SEVERITY.get(p.severity, "tidak diketahui"),
            "penting": (p.severity is not None and p.severity <= AMBANG_PENTING),
            "tag": p.tag or "",
            "pesan": p.pesan,
            "sidik": p.sidik_templat,
        } for p in line],
    }


def dasbor(db, jam=24):
    """Everything the Syslog page needs in ONE request.

    The page has five parts; five separate requests risk a half-filled page where the user
    cannot tell which part failed. One request: either everything is there, or clearly nothing.
    """
    r = ringkas(db, jam=jam)
    r["deret"] = deret_jam(db, jam=jam)
    r["per_device"] = per_device(db, jam=jam)
    r["per_tag"] = per_tag(db, jam=jam)
    r["ambang_penting"] = AMBANG_PENTING
    return r


__all__ = ["peta_alamat", "simpan", "templat_baru", "perlu_periksa_konfig",
           "ringkas", "penting", "JENDELA_REDAM_DETIK", "deret_jam", "per_device",
           "per_tag", "daftar", "dasbor", "NAMA_SEVERITY"]

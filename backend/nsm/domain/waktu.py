"""Time and unit rules. PURE: no database, no network, no `.env`.

These are business rules, not technical details: how long a "period" is,
how a duration is read out to a human, and which sentence stands for an
outage category. Keeping them out of `report_service.py` (SQL queries, a
global cache, an `ubah_acl_router` import) means a test that "2 jam 5 menit"
prints correctly does not have to load SQLAlchemy and every model.

Behavior is deliberately kept exact, including its oddities:
  * an unknown period falls back to "24h" instead of raising; the old pages
    rely on that;
  * `format_durasi` TRUNCATES, it does not round. Callers must pass a value
    they have already `round()`ed, or a card and a table can differ by
    1 second for the same outage;
  * service categories still come from `connectors/layanan.py` and are not
    copied here. A cause sentence may have only one owner.

`uji_arsitektur_baru.py` keeps this identical to `report_service`.
"""
from datetime import datetime, timedelta

PERIODE = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

TEKS_KATEGORI = {
    "dead": "Tidak ada respons sama sekali (kemungkinan mati/terputus)",
    "ping_blocked": "Ping diblokir, tapi device menjawab di port TCP (kemungkinan hidup)",
    "recovered": "Kembali normal",
    "baseline": "Awal pemantauan",
    "pulih": "Layanan kembali menjawab dengan benar",
}


def rentang(period, sekarang=None):
    """Return (start, end, label). Defaults to 24 hours for an unknown value.

    `sekarang` is an OPTIONAL parameter so tests do not depend on the wall
    clock. Without it, behavior is unchanged.
    """
    delta = PERIODE.get(period, PERIODE["24h"])
    selesai = sekarang or datetime.now()
    return selesai - delta, selesai, period if period in PERIODE else "24h"


def format_durasi(detik):
    """Convert seconds to readable Indonesian text (e.g. '2 jam 5 menit')."""
    if detik is None:
        return "-"
    detik = int(detik)
    if detik < 60:
        return f"{detik} detik"
    menit, remaining_second = divmod(detik, 60)
    if menit < 60:
        return f"{menit} menit {remaining_second} detik" if remaining_second else f"{menit} menit"
    jam, remaining_minute = divmod(menit, 60)
    if jam < 24:
        return f"{jam} jam {remaining_minute} menit" if remaining_minute else f"{jam} jam"
    hari, remaining_hour = divmod(jam, 24)
    return f"{hari} hari {remaining_hour} jam" if remaining_hour else f"{hari} hari"


def teks_kategori(kategori):
    """Translate a category code into a human-readable sentence."""
    if not kategori:
        return "Tidak diketahui"
    if kategori in TEKS_KATEGORI:
        return TEKS_KATEGORI[kategori]
    from connectors.layanan import TEKS_SEBAB
    if kategori in TEKS_SEBAB:
        return TEKS_SEBAB[kategori]
    return kategori

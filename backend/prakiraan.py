r"""Extended forecasts: bandwidth saturation, latency trend, error-budget burn rate.

`kapasitas.py` already forecasts disk-full with linear regression + R^2; the
regression is imported and shared rather than copied. This module is separate
because the three questions use different data sources (`bandwidth_samples`,
`status_rollup_jam`, `slo.hitung`).

Honesty rules, same as `kapasitas.py`:
1. Too little or too short data is not forecast.
2. Noisy trends are flagged (low R^2 -> verdict `tidak_yakin`).
3. No far extrapolation: beyond 365 days the answer is "more than a year".

Bandwidth only: NSM does not know link capacity, and guessing it from the peak
seen would make an idle link look 100% full. Trends are reported in bit/s, and
"days until full" is computed only when the caller supplies the capacity;
otherwise the verdict is `kapasitas_tak_diketahui`.
"""
from datetime import datetime, timedelta

from sqlalchemy import func, select

import models
from kapasitas import (CUKUP, HORIZON_MAKS_HARI, MENURUN, R2_MIN_YAKIN,
                       STABIL, TIDAK_CUKUP, TIDAK_YAKIN, _hari_menuju,
                       _regresi)

# Bandwidth observation window. Longer than disk (7 days) because traffic has a
# strong weekly rhythm; a 7-day window containing a holiday would show a false downward trend.
JENDELA_BW_HARI = 14
MIN_SAMPEL_BW = 48
MIN_RENTANG_JAM_BW = 24.0

# Latency is read from HOURLY rollups, not raw `status_logs`, which are pruned at
# 35 days while multi-week trends need a longer range.
JENDELA_LAT_HARI = 28
MIN_SAMPEL_LAT = 48

KAPASITAS_TAK_DIKETAHUI = "kapasitas_tak_diketahui"


def _vonis_dari(kemiringan, r2):
    """Shared verdict for all three forecasts so meanings do not drift."""
    if kemiringan is None:
        return TIDAK_CUKUP
    if kemiringan < 0:
        return MENURUN
    if r2 is not None and r2 < R2_MIN_YAKIN:
        return TIDAK_YAKIN
    return CUKUP


def _horizon(hari):
    """Cap the horizon and say so when the answer is out of range."""
    if hari is None:
        return None, None
    if hari > HORIZON_MAKS_HARI:
        return None, "lebih dari setahun"
    return hari, "%.0f hari" % hari


# ===========================================================================
# C3a -- SATURASI BANDWIDTH
# ===========================================================================

def puncak_harian_semua(db, sejak, iface=None):
    """Peak bit/s per DAY per DEVICE in a single query.

    One `GROUP BY device_id, tanggal` scans the table once; calling
    `bandwidth_device()` per device took 6.3 s for eleven devices, one scan each.
    """
    tanggal = func.date(models.BandwidthSample.timestamp)
    q = (select(models.BandwidthSample.device_id,
                tanggal.label("hari"),
                func.max(models.BandwidthSample.in_bps),
                func.max(models.BandwidthSample.out_bps),
                func.count(models.BandwidthSample.id))
         .where(models.BandwidthSample.timestamp >= sejak)
         .group_by(models.BandwidthSample.device_id, tanggal)
         .order_by(models.BandwidthSample.device_id, tanggal))
    if iface:
        q = q.where(models.BandwidthSample.iface == iface)

    per_device = {}
    for did, hari, enter, keluar, tally in db.execute(q).all():
        if did is None or hari is None:
            continue
        if isinstance(hari, str):           # SQLite mengembalikan teks
            from datetime import date as _date
            hari = _date.fromisoformat(hari[:10])
        d = per_device.setdefault(did, {"per_hari": {}, "sampel": 0})
        d["sampel"] += int(tally or 0)
        bps = max(float(enter or 0.0), float(keluar or 0.0))
        if bps > 0:
            d["per_hari"][hari] = max(d["per_hari"].get(hari, 0.0), bps)
    return per_device


def _bandwidth_dari_puncak(db, device_id, per_hari, n_sampel, kapasitas_bps,
                           jendela_hari, iface=None):
    """Pure computation, separated from data fetching, shared by `bandwidth_device()`
    and `semua()` so there is only one formula.
    """
    d = db.get(models.Device, device_id)
    base = {"device_id": device_id, "nama": d.name if d else None,
             "iface": iface, "sampel": n_sampel,
             "jendela_hari": jendela_hari, "kapasitas_bps": kapasitas_bps}

    if n_sampel < MIN_SAMPEL_BW or len(per_hari) < 3:
        base.update({"vonis": TIDAK_CUKUP, "laju_bps_per_hari": None,
                      "puncak_bps": max(per_hari.values()) if per_hari else None,
                      "hari_menuju_penuh": None,
                      "alasan": "Baru %d sampel pada %d hari berbeda dalam %d "
                                "hari terakhir; butuh minimal %d sampel dan 3 "
                                "hari sebelum trennya pantas disebut tren."
                                % (n_sampel, len(per_hari), jendela_hari,
                                   MIN_SAMPEL_BW)})
        return base

    day0 = min(per_hari)
    point = [((h - day0).days, v) for h, v in sorted(per_hari.items())]
    kemiringan, _b, r2 = _regresi(point)
    peak = point[-1][1]

    base.update({"puncak_bps": peak, "laju_bps_per_hari": kemiringan,
                  "r2": r2, "hari_diamati": len(per_hari)})

    vonis = _vonis_dari(kemiringan, r2)
    if kapasitas_bps is None:
        mutu = ("Trennya terukur" if vonis == CUKUP
                else "Trennya terukur tetapi titiknya BERSERAK (R2 %.2f), "
                     "jadi angkanya kasar" % (r2 or 0.0))
        base.update({
            "vonis": KAPASITAS_TAK_DIKETAHUI if vonis == CUKUP else vonis,
            "hari_menuju_penuh": None, "pakai_persen": None,
            "alasan": "%s (%s), tetapi kapasitas link ini tidak pernah "
                      "dinyatakan di NSM, jadi 'penuh dalam berapa hari' "
                      "tidak bisa dijawab tanpa menebak."
                      % (mutu, _laju_teks(kemiringan))})
        return base

    pakai_persen = 100.0 * peak / kapasitas_bps if kapasitas_bps else None
    rate_percent = (100.0 * kemiringan / kapasitas_bps) if kapasitas_bps else None
    hari = _hari_menuju(pakai_persen or 0.0, rate_percent, 100.0)
    hari, teks = _horizon(hari)
    base.update({"vonis": vonis, "pakai_persen": pakai_persen,
                  "laju_persen_per_hari": rate_percent,
                  "hari_menuju_penuh": hari, "horizon_teks": teks,
                  "alasan": _kalimat_bw(base, vonis, hari, teks,
                                        pakai_persen, kemiringan)})
    return base


def bandwidth_device(db, device_id, iface=None, kapasitas_bps=None,
                     sekarang=None, jendela_hari=JENDELA_BW_HARI):
    """Traffic trend for one interface. Always a dict, never raises.

    `kapasitas_bps` is supplied by the caller, not guessed; see the module docstring.
    """
    sekarang = sekarang or datetime.now()
    sejak = sekarang - timedelta(days=jendela_hari)

    # Single device: aggregation still happens in the database (see
    # `puncak_harian_semua`) and the computation is shared via `_bandwidth_dari_puncak`.
    all_peak = puncak_harian_semua(db, sejak, iface=iface)
    d = all_peak.get(device_id, {"per_hari": {}, "sampel": 0})
    return _bandwidth_dari_puncak(db, device_id, d["per_hari"], d["sampel"],
                                  kapasitas_bps, jendela_hari, iface=iface)


def _laju_teks(bps_per_hari):
    if bps_per_hari is None:
        return "tidak terukur"
    a = abs(bps_per_hari)
    direction = "naik" if bps_per_hari > 0 else "turun"
    if a >= 1e6:
        return "%s %.2f Mbit/s per hari" % (direction, a / 1e6)
    if a >= 1e3:
        return "%s %.1f kbit/s per hari" % (direction, a / 1e3)
    return "%s %.0f bit/s per hari" % (direction, a)


def _kalimat_bw(d, vonis, hari, teks, pakai, kemiringan):
    nama = d.get("nama") or "device"
    if vonis == MENURUN:
        return ("Lalu lintas puncak %s justru %s. Tidak ada saturasi yang "
                "menuju." % (nama, _laju_teks(kemiringan)))
    if hari is None and teks:
        return ("Puncaknya %.1f%% dari kapasitas dan %s, tetapi kejenuhannya "
                "lebih jauh dari setahun -- terlalu jauh untuk berarti."
                % (pakai, _laju_teks(kemiringan)))
    if hari is None:
        return ("Puncaknya %.1f%% dari kapasitas; trennya belum cukup jelas "
                "untuk memprakirakan kapan penuh." % (pakai or 0.0))
    prefix = "" if vonis == CUKUP else "Titiknya berserak, jadi angka ini kasar: "
    return ("%sPuncak lalu lintas %s kini %.1f%% dari kapasitas dan %s -- "
            "penuh dalam sekitar %s." % (prefix, nama, pakai,
                                         _laju_teks(kemiringan), teks))


# ===========================================================================
# C3b -- TREN LATENCY
# ===========================================================================

def latency_device(db, device_id, sekarang=None,
                   jendela_hari=JENDELA_LAT_HARI):
    """"Up 8% per week for 4 weeks", from hourly rollups rather than raw rows.

    `status_logs` is pruned at 35 days; `status_rollup_jam` is kept indefinitely.
    The rate is reported as percent per week, not ms per day: 0.7 ms/day means
    nothing without the baseline (negligible at 400 ms, doubling in days at 2 ms).
    """
    sekarang = sekarang or datetime.now()
    sejak = sekarang - timedelta(days=jendela_hari)

    line = db.execute(
        select(models.StatusRollupJam)
        .where(models.StatusRollupJam.device_id == device_id,
               models.StatusRollupJam.jam >= sejak)
        .order_by(models.StatusRollupJam.jam.asc())).scalars().all()

    d = db.get(models.Device, device_id)
    base = {"device_id": device_id, "nama": d.name if d else None,
             "sampel": len(line), "jendela_hari": jendela_hari}

    # Hourly average is SUM divided by COUNT, not the average column: an average of
    # averages is wrong when hours have different counts (see `models.StatusRollupJam`).
    # The columns are named directly rather than via `getattr(..., default)`: a wrong
    # column name with a safe default silently skipped every row and the module
    # always answered "not enough data". Named directly, it raises AttributeError.
    point = []
    for r in line:
        tally = r.latency_sampel or 0
        jumlah = r.latency_jumlah
        if not tally or jumlah is None:
            continue
        hari = (r.jam - sejak).total_seconds() / 86400.0
        point.append((hari, float(jumlah) / float(tally)))

    if len(point) < MIN_SAMPEL_LAT:
        base.update({"vonis": TIDAK_CUKUP, "laju_persen_per_minggu": None,
                      "latency_kini_ms": point[-1][1] if point else None,
                      "alasan": "Baru %d jam terukur dalam %d hari terakhir; "
                                "butuh minimal %d sebelum trennya pantas "
                                "disebut tren." % (len(point), jendela_hari,
                                                   MIN_SAMPEL_LAT)})
        return base

    kemiringan, deviation, r2 = _regresi(point)
    kini = point[-1][1]
    begin = kemiringan * point[0][0] + deviation if kemiringan is not None else None

    # Percent per week is relative to the line's STARTING value, not the current one,
    # so the same change reads the same size regardless of trend direction.
    rate_percent_week = None
    if kemiringan is not None and begin and begin > 0:
        rate_percent_week = 100.0 * (kemiringan * 7.0) / begin

    vonis = _vonis_dari(kemiringan, r2)

    # The verdict and the sentence must not contradict each other. If the percent
    # rate is unavailable (starting value zero or negative), the verdict must not be
    # `cukup`, and this applies to every verdict: otherwise the page shows a green or
    # yellow badge next to "trend cannot be measured yet". The percent rate is the
    # only number the page and SOC agent use from this function.
    if rate_percent_week is None:
        vonis = TIDAK_CUKUP

    base.update({
        "latency_kini_ms": kini, "latency_awal_ms": begin,
        "laju_ms_per_hari": kemiringan, "r2": r2,
        "laju_persen_per_minggu": rate_percent_week,
        "vonis": vonis,
        "alasan": _kalimat_lat(base.get("nama"), vonis, kini,
                               rate_percent_week, jendela_hari),
    })
    return base


def _kalimat_lat(nama, vonis, kini, laju_minggu, jendela_hari):
    nama = nama or "device"
    if laju_minggu is None:
        return "%s: trennya belum bisa diukur." % nama
    week = jendela_hari / 7.0
    if vonis == MENURUN:
        return ("Latency %s justru MEMBAIK %.1f%% per minggu selama %.0f "
                "minggu terakhir (kini %.1f ms)."
                % (nama, abs(laju_minggu), week, kini))
    if abs(laju_minggu) < 1.0:
        return ("Latency %s datar dalam %.0f minggu terakhir (kini %.1f ms)."
                % (nama, week, kini))
    prefix = "" if vonis == CUKUP else "Titiknya berserak, jadi angka ini kasar: "
    return ("%sLatency %s naik %.1f%% per minggu selama %.0f minggu terakhir "
            "-- kini %.1f ms." % (prefix, nama, laju_minggu, week, kini))


# ===========================================================================
# C3c -- LAJU HABISNYA ANGGARAN GALAT
# ===========================================================================

def anggaran_device(db, device, period="30d"):
    """"Error budget runs out in N days at this rate."

    The rate is budget already consumed divided by the span observed, not a
    regression: budget is consumed in jumps (one long incident can use half of it
    in ten minutes), and a line fitted to steps gives low R^2 for a very clear rate.
    """
    import slo

    start, finish, _ = _rentang(period)
    h = slo.hitung(db, device, start, finish)
    if not h:
        return {"device_id": getattr(device, "id", None),
                "nama": getattr(device, "name", None),
                "vonis": TIDAK_CUKUP,
                "alasan": "Pengamatannya belum cukup panjang untuk "
                          "menerbitkan angka anggaran galat."}

    jendela_hari = (h.get("jendela_detik") or 0) / 86400.0
    terpakai = h.get("terpakai_detik") or 0.0
    anggaran = h.get("anggaran_detik") or 0.0
    remaining = h.get("sisa_detik") or 0.0

    hasil = {
        "device_id": h.get("device_id"), "nama": h.get("device"),
        "target_persen": h.get("target_persen"),
        "sisa_persen": h.get("sisa_persen"),
        "vonis_slo": h.get("vonis"),
        "jendela_hari": jendela_hari,
    }

    if jendela_hari <= 0 or anggaran <= 0:
        hasil.update({"vonis": TIDAK_CUKUP, "hari_menuju_habis": None,
                      "alasan": "Jendela atau anggarannya nol; laju tidak "
                                "bisa dihitung."})
        return hasil

    rate_per_day = terpakai / jendela_hari  # budget seconds per day
    hasil["laju_detik_per_hari"] = rate_per_day

    if remaining <= 0:
        hasil.update({"vonis": "habis", "hari_menuju_habis": 0.0,
                      "alasan": "Anggaran galat sudah habis terlampaui. "
                                "Prakiraan tidak lagi relevan -- yang "
                                "dibutuhkan keputusan, bukan angka."})
        return hasil

    if rate_per_day <= 0:
        hasil.update({"vonis": STABIL, "hari_menuju_habis": None,
                      "alasan": "Belum ada waktu mati sama sekali dalam "
                                "jendela ini, jadi anggarannya tidak sedang "
                                "menuju habis."})
        return hasil

    hari = remaining / rate_per_day
    hari, teks = _horizon(hari)
    hasil.update({
        "vonis": CUKUP, "hari_menuju_habis": hari, "horizon_teks": teks,
        "alasan": ("Sisa anggaran %.1f%%, terpakai rata-rata %s per hari -- "
                   "habis dalam %s kalau lajunya tetap."
                   % (h.get("sisa_persen") or 0.0,
                      _detik_teks(rate_per_day), teks or "waktu yang lama")),
    })
    return hasil


def _detik_teks(detik):
    detik = abs(detik)
    if detik < 60:
        return "%.0f detik" % detik
    if detik < 3600:
        return "%.1f menit" % (detik / 60.0)
    return "%.1f jam" % (detik / 3600.0)


def _rentang(period):
    import report_service
    return report_service.rentang(period)



def semua(db, sekarang=None, dengan_anggaran=True):
    """All three forecasts for every active device, most urgent first. A list sorted
    alphabetically hides the one row that matters (same lesson as `slo.semua()`).
    """
    sekarang = sekarang or datetime.now()
    devs = db.execute(select(models.Device).where(
        models.Device.aktif == True)).scalars().all()          # noqa: E712

    bw, lat, ang = [], [], []
    # One aggregate query for ALL devices, not one per device.
    since_bw = sekarang - timedelta(days=JENDELA_BW_HARI)
    peak = puncak_harian_semua(db, since_bw)

    for d in devs:
        p = peak.get(d.id, {"per_hari": {}, "sampel": 0})
        b = _bandwidth_dari_puncak(db, d.id, p["per_hari"], p["sampel"],
                                   None, JENDELA_BW_HARI)
        if b.get("sampel"):
            bw.append(b)
        l = latency_device(db, d.id, sekarang=sekarang)
        if l.get("sampel"):
            lat.append(l)
        try:
            # The error budget calls `report_service.hitung_device()`, which touches many
            # tables (about 8.5 s for 11 devices). The page loads it separately (see
            # `/prakiraan/anggaran`) so the fast parts show first.
            if not dengan_anggaran:
                continue
            a = anggaran_device(db, d)
            if a.get("vonis") != TIDAK_CUKUP:
                ang.append(a)
        except Exception as e:                   # noqa: BLE001
            # The error budget touches many tables; its failure must not erase the other two forecasts.
            ang.append({"device_id": d.id, "nama": d.name,
                        "vonis": TIDAK_CUKUP,
                        "alasan": "gagal dihitung: %s" % str(e)[:120]})

    def urut(x, kunci):
        v = x.get(kunci)
        return v if v is not None else 1e9

    bw.sort(key=lambda x: urut(x, "hari_menuju_penuh"))
    lat.sort(key=lambda x: -(x.get("laju_persen_per_minggu") or -1e9))
    ang.sort(key=lambda x: urut(x, "hari_menuju_habis"))

    return {"bandwidth": bw, "latency": lat, "anggaran": ang,
            "waktu": sekarang.isoformat()}

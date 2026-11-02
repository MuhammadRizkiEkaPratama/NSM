"""Traffic baseline and anomaly detection.

Moves NSM from recording to judging: not "203 MB went out" but which file it
was, whether that is normal for this network, and if not, why.

Every finding must carry its comparison number: "203 MB in one hour vs. a
24-hour habit of 0.3 MB/hour (677x)", not "traffic spike". A label without a
number gets ignored after two sightings.

The baseline refuses to compute when there is too little data. An average of
6 hourly samples is a coincidence, not a habit, and a tool that states what it
does not know with confidence is worse than a silent one. Below the minimum
hour count it answers "cannot compute yet, N more hours needed".

Detectors fall into two groups:
    need a baseline:  volume spike, never-seen client
    do not need one:  large single download, error burst, off-hours access,
                      non-browser agent, sensitive file
The second group works from day one; holding everything back until the
baseline is ready would leave the tool silent exactly when it is watched most.

Limit: everything is read from server logs, not packet capture. File names
fetched over HTTP are visible; the contents of SSH or HTTPS connections are
not, by design.
"""
import re
from datetime import datetime, timedelta

# Hours of data required before the baseline may be computed. 24 covers both
# day and night habits; fewer would turn one afternoon's coincidence into an
# official-looking number.
MIN_JAM_GARIS_DASAR = 24

LIPAT_LONJAKAN = 5.0

AMBANG_UNDUHAN_BESAR = 50 * 1024 * 1024

JAM_KERJA_MULAI = 7
JAM_KERJA_SELESAI = 18

AMBANG_LEDAKAN_GALAT = 20

AGEN_BUKAN_PERAMBAN = ("curl", "wget", "python-requests", "python-urllib",
                       "libwww", "httpie", "go-http-client", "java/",
                       "okhttp", "postman", "scrapy", "nikto", "sqlmap")

# Files whose contents are rarely meant to be public.
#
# A bare "/admin" is deliberately excluded: E-Canteen has a legitimate admin
# area that staff use daily, and the bare pattern flagged 15 of 16 findings on a
# normal day as ordinary staff work. `/wp-admin` and `/phpmyadmin` stay because
# they target apps that are not installed in this lab, so any request for them
# means someone is probing.
POLA_SENSITIF = (".sql", ".bak", ".backup", ".zip", ".tar", ".tar.gz", ".tgz",
                 ".env", ".pem", ".key", ".p12", ".log", ".dump", ".old",
                 "/.git", "/.svn", "/phpmyadmin", "/wp-admin",
                 "/config", "/backup")

TINGGI, SEDANG, RENDAH = "tinggi", "sedang", "rendah"


def _mb(b):
    return (b or 0) / 1048576.0


def _teks_byte(b):
    b = float(b or 0)
    for unit, limit in (("GB", 1073741824), ("MB", 1048576), ("KB", 1024)):
        if b >= limit:
            return "%.2f %s" % (b / limit, unit)
    return "%d B" % int(b)


def _jam(w):
    if isinstance(w, str):
        return w[:13]
    return w.strftime("%Y-%m-%d %H")


# ---------------------------------------------------------------------------
# Garis dasar
# ---------------------------------------------------------------------------

def per_jam(baris):
    hasil = {}
    for r in baris:
        k = _jam(r["waktu"])
        d = hasil.setdefault(k, {"permintaan": 0, "byte": 0.0})
        d["permintaan"] += 1
        d["byte"] += float(r.get("byte_kirim") or 0)
    return hasil


def garis_dasar(ringkas_jam, min_jam=MIN_JAM_GARIS_DASAR):
    """Hourly habit: returns a dict, or the reason it cannot be computed yet.

    Refuses to compute with fewer than `min_jam` hours of data. Uses the MEDIAN,
    not the mean: one 200 MB hour would pull the mean up so far that the next
    200 MB hour looks normal.
    """
    jam = sorted(ringkas_jam)
    if len(jam) < min_jam:
        return {
            "siap": False,
            "jam_terkumpul": len(jam),
            "jam_dibutuhkan": min_jam,
            "alasan": ("Garis dasar belum bisa dihitung: baru %d jam berisi "
                       "data, dibutuhkan %d. Rata-rata dari sampel sesedikit "
                       "ini bukan kebiasaan melainkan kebetulan."
                       % (len(jam), min_jam)),
        }

    byte = sorted(ringkas_jam[j]["byte"] for j in jam)
    permintaan = sorted(ringkas_jam[j]["permintaan"] for j in jam)

    def median(x):
        n = len(x)
        return x[n // 2] if n % 2 else (x[n // 2 - 1] + x[n // 2]) / 2.0

    return {
        "siap": True,
        "jam_terkumpul": len(jam),
        "byte_median": median(byte),
        "byte_median_teks": _teks_byte(median(byte)),
        "permintaan_median": median(permintaan),
        "byte_tertinggi": byte[-1],
        "byte_tertinggi_teks": _teks_byte(byte[-1]),
    }


# ---------------------------------------------------------------------------
# Detektor
# ---------------------------------------------------------------------------

def _iso_jam(kunci_jam):
    """Turn an hour key '2026-07-29 16' into '2026-07-29T16:00:00'.

    Hour keys are for grouping, not display. `new Date('2026-07-29 16')` is not
    valid in browsers and rendered "Invalid Date" on every hour-based card.
    """
    return "%sT%s:00:00" % (kunci_jam[:10], kunci_jam[11:13])


def _teks_rentang_jam(jam_awal, jam_akhir):
    jam1 = int(jam_awal[11:13])
    jam2 = int(jam_akhir[11:13])
    if jam_awal[:10] == jam_akhir[:10]:
        return "%s %02d:00–%02d:00" % (jam_awal[:10], jam1, (jam2 + 1) % 24)
    return "%s %02d:00 – %s %02d:00" % (jam_awal[:10], jam1,
                                        jam_akhir[:10], (jam2 + 1) % 24)


def _temuan(jenis, keparahan, judul, kapan, angka, pembanding, kenapa,
            bukti=None, kapan_teks=None):
    """Standard shape of a finding.

    `pembanding` is required: a finding without a comparison number is only a
    label. `kapan` must be a form browsers can parse; `kapan_teks` is used when
    the time is a range rather than a single point.
    """
    return {
        "jenis": jenis, "keparahan": keparahan, "judul": judul,
        "kapan": kapan, "kapan_teks": kapan_teks, "angka": angka,
        "pembanding": pembanding, "kenapa": kenapa, "bukti": bukti or [],
    }


def lonjakan_volume(ringkas_jam, dasar, lipat=LIPAT_LONJAKAN):
    if not dasar.get("siap"):
        return []
    reference = dasar["byte_median"]
    if reference <= 0:
        return []
    hasil = []
    for jam in sorted(ringkas_jam):
        b = ringkas_jam[jam]["byte"]
        if b < reference * lipat:
            continue
        hasil.append(_temuan(
            "lonjakan_volume", TINGGI,
            "Volume jauh di atas kebiasaan",
            _iso_jam(jam),
            "%s dalam satu jam" % _teks_byte(b),
            "kebiasaan %s per jam (median dari %d jam)"
            % (dasar["byte_median_teks"], dasar["jam_terkumpul"]),
            "%.0f kali lipat kebiasaan. Layak ditanyakan apa yang diambil dan "
            "oleh siapa." % (b / reference),
            kapan_teks=_teks_rentang_jam(jam, jam),
        ))
    return hasil


def unduhan_besar(baris, ambang=AMBANG_UNDUHAN_BESAR):
    """Requests that pull a lot of data; no baseline needed.

    Grouped per (address, file), not one finding per request: the same file
    fetched four times in five minutes would otherwise produce four identical rows.
    """
    per = {}
    for r in baris:
        b = float(r.get("byte_kirim") or 0)
        if b < ambang:
            continue
        k = (r.get("ip_klien"), r.get("path"))
        d = per.setdefault(k, {"n": 0, "byte": 0.0, "awal": None, "akhir": None})
        d["n"] += 1
        d["byte"] += b
        w = str(r["waktu"])
        d["awal"] = min(d["awal"] or w, w)
        d["akhir"] = max(d["akhir"] or w, w)

    hasil = []
    for (ip, path), d in sorted(per.items(), key=lambda x: -x[1]["byte"]):
        berulang = ("" if d["n"] == 1 else
                    " (%d kali, %s sampai %s)"
                    % (d["n"], d["awal"][11:16], d["akhir"][11:16]))
        hasil.append(_temuan(
            "unduhan_besar", SEDANG,
            "Berkas besar ditarik" + ("" if d["n"] == 1 else " berulang kali"),
            d["akhir"],
            "%s oleh %s%s" % (_teks_byte(d["byte"]), ip, berulang),
            "ambang %s per permintaan" % _teks_byte(ambang),
            "Berkas sebesar ini bukan bagian dari pemakaian web biasa."
            + ("" if d["n"] == 1 else
               " Ditarik berulang kali dalam waktu dekat — layak ditanyakan "
               "apakah itu memang disengaja."),
            [{"ip": ip, "path": path, "jumlah": d["n"],
              "byte": d["byte"], "byte_teks": _teks_byte(d["byte"])}],
        ))
    return hasil


def ledakan_galat(baris, ambang=AMBANG_LEDAKAN_GALAT):
    """Many 4xx/5xx responses within one hour.

    Takes ALL rows, including NSM's own requests; this is the only detector that
    does. A 5xx is a server failure regardless of who asked, and NSM asks most
    often (the one real outage on record was found only through NSM's requests).

    4xx and 5xx are kept separate because they mean opposite things: 4xx means
    the requester asked for something missing or forbidden (possibly probing),
    5xx means the server itself failed. Merging them would make an outage look
    like a scan.
    """
    per = {}
    for r in baris:
        st = int(r.get("status") or 0)
        if st < 400:
            continue
        golongan = "5xx" if st >= 500 else "4xx"
        k = (_jam(r["waktu"]), golongan)
        d = per.setdefault(k, {"n": 0, "nsm": 0, "path": {}})
        d["n"] += 1
        if r.get("dari_nsm"):
            d["nsm"] += 1
        d["path"][r.get("path")] = d["path"].get(r.get("path"), 0) + 1

    # Consecutive hours are merged into one incident. Splitting an outage at hour
    # boundaries hides its tail and makes "how long did this last" unanswerable.
    def _urut_jam(k):
        return datetime.strptime(k, "%Y-%m-%d %H")

    hasil = []
    for golongan in ("5xx", "4xx"):
        hour_exists = sorted((j for (j, g) in per if g == golongan), key=_urut_jam)
        jangkar = {j for j in hour_exists if per[(j, golongan)]["n"] >= ambang}
        if not jangkar:
            continue

        cluster = []
        for j in hour_exists:
            if cluster and _urut_jam(j) - _urut_jam(cluster[-1][-1]) == timedelta(hours=1):
                cluster[-1].append(j)
            else:
                cluster.append([j])

        for g in cluster:
            if not any(j in jangkar for j in g):
                continue
            n = sum(per[(j, golongan)]["n"] for j in g)
            nsm = sum(per[(j, golongan)]["nsm"] for j in g)
            path = {}
            for j in g:
                for p, c in per[(j, golongan)]["path"].items():
                    path[p] = path.get(p, 0) + c
            upper = sorted(path.items(), key=lambda x: -x[1])[:3]

            if golongan == "5xx":
                judul = "Server gagal berulang kali"
                kenapa = ("Server sendiri yang gagal menjawab, bukan "
                          "pemintanya yang salah. Ini gangguan layanan.")
                severe = TINGGI
            else:
                judul = "Banyak permintaan ditolak atau tidak ditemukan"
                kenapa = ("Bisa berarti tautan rusak, bisa juga berarti "
                          "seseorang menebak-nebak alamat yang tidak "
                          "seharusnya ada.")
                severe = SEDANG

            origin = ""
            if nsm:
                origin = (" — semuanya terlihat lewat pemeriksaan NSM"
                        if nsm == n else
                        " — %d di antaranya lewat pemeriksaan NSM" % nsm)
            old = ("dalam satu jam" if len(g) == 1
                    else "selama %d jam berturut-turut" % len(g))

            hasil.append(_temuan(
                "ledakan_galat_" + golongan, severe, judul,
                _iso_jam(g[0]),
                "%d jawaban %s %s%s" % (n, golongan, old, origin),
                "ambang %d per jam" % ambang, kenapa,
                [{"path": p, "jumlah": c} for p, c in upper],
                kapan_teks=_teks_rentang_jam(g[0], g[-1]),
            ))
    return hasil


def di_luar_jam_kerja(baris, mulai=JAM_KERJA_MULAI, selesai=JAM_KERJA_SELESAI,
                      min_byte=1024 * 1024):
    per = {}
    for r in baris:
        w = r["waktu"]
        hour_number = int(str(w)[11:13]) if isinstance(w, str) else w.hour
        if mulai <= hour_number < selesai:
            continue
        k = _jam(w)
        d = per.setdefault(k, {"byte": 0.0, "n": 0, "ip": set()})
        d["byte"] += float(r.get("byte_kirim") or 0)
        d["n"] += 1
        d["ip"].add(r.get("ip_klien"))

    hasil = []
    for jam, d in sorted(per.items()):
        if d["byte"] < min_byte:
            continue
        hasil.append(_temuan(
            "di_luar_jam_kerja", RENDAH,
            "Pengambilan data di luar jam kerja", _iso_jam(jam),
            "%s oleh %d alamat" % (_teks_byte(d["byte"]), len(d["ip"])),
            "jam kerja %02d:00–%02d:00" % (mulai, selesai),
            "Belum tentu salah — banyak pekerjaan sah terjadi malam hari — "
            "tetapi layak dilihat.",
            [{"ip": ip} for ip in sorted(x for x in d["ip"] if x)],
            kapan_teks=_teks_rentang_jam(jam, jam),
        ))
    return hasil


def agen_bukan_peramban(baris, min_byte=1024 * 1024):
    per = {}
    for r in baris:
        agen = (r.get("user_agent") or "").lower()
        if not any(a in agen for a in AGEN_BUKAN_PERAMBAN):
            continue
        k = (r.get("ip_klien"), r.get("user_agent"))
        d = per.setdefault(k, {"byte": 0.0, "n": 0, "path": set(),
                               "awal": None, "akhir": None})
        d["byte"] += float(r.get("byte_kirim") or 0)
        d["n"] += 1
        d["path"].add(r.get("path"))
        w = str(r["waktu"])
        d["awal"] = min(d["awal"] or w, w)
        d["akhir"] = max(d["akhir"] or w, w)

    hasil = []
    for (ip, agen), d in sorted(per.items(), key=lambda x: -x[1]["byte"]):
        if d["byte"] < min_byte:
            continue
        hasil.append(_temuan(
            "agen_bukan_peramban", SEDANG,
            "Data ditarik oleh alat, bukan peramban", d["akhir"],
            "%s dalam %d permintaan oleh %s" % (_teks_byte(d["byte"]), d["n"], ip),
            "user-agent %r" % (agen or "")[:60],
            "curl dan wget dipakai setiap hari oleh orang yang sah. Yang "
            "pantas ditanyakan adalah gabungannya: alat, volume, dan jamnya.",
            [{"path": p} for p in sorted(x for x in d["path"] if x)[:5]],
        ))
    return hasil


def berkas_sensitif(baris, pola=POLA_SENSITIF):
    hasil = []
    for r in baris:
        p = (r.get("path") or "").lower()
        cocok = [x for x in pola if x in p]
        if not cocok:
            continue
        st = int(r.get("status") or 0)
        succeed = 200 <= st < 400
        hasil.append(_temuan(
            "berkas_sensitif", TINGGI if succeed else RENDAH,
            "Berkas sensitif diminta" + ("" if succeed else " (ditolak)"),
            r["waktu"],
            "%s -> %s" % (r.get("path"), st),
            "cocok pola %s" % ", ".join(cocok),
            ("BERHASIL diambil — isinya benar-benar keluar."
             if succeed else
             "Ditolak server, jadi penjagaannya bekerja. Tetap dicatat karena "
             "yang menarik adalah ada yang mencobanya."),
            [{"ip": r.get("ip_klien"), "agen": r.get("user_agent")}],
        ))
    return hasil


def klien_baru(baris, baris_sejarah, min_byte=1024 * 1024):
    """Address never seen before that immediately pulls a lot.

    Needs history: without a comparison period every address looks new, and an
    alert that fires for everything is as useless as one that never fires.
    """
    old = {r.get("ip_klien") for r in baris_sejarah}
    if not old:
        return []
    per = {}
    for r in baris:
        ip = r.get("ip_klien")
        if ip in old:
            continue
        d = per.setdefault(ip, {"byte": 0.0, "n": 0, "akhir": None})
        d["byte"] += float(r.get("byte_kirim") or 0)
        d["n"] += 1
        d["akhir"] = max(d["akhir"] or str(r["waktu"]), str(r["waktu"]))

    hasil = []
    for ip, d in sorted(per.items(), key=lambda x: -x[1]["byte"]):
        if d["byte"] < min_byte:
            continue
        hasil.append(_temuan(
            "klien_baru", SEDANG,
            "Alamat yang belum pernah terlihat menarik banyak data",
            d["akhir"],
            "%s dalam %d permintaan oleh %s" % (_teks_byte(d["byte"]), d["n"], ip),
            "belum pernah muncul di %d alamat yang tercatat sebelumnya" % len(old),
            "Alamat baru itu biasa. Alamat baru yang langsung menarik banyak "
            "data pada kunjungan pertamanya tidak.",
        ))
    return hasil


# ---------------------------------------------------------------------------
# Perakit
# ---------------------------------------------------------------------------

URUT_PARAH = {TINGGI: 0, SEDANG: 1, RENDAH: 2}


def periksa(baris, baris_sejarah=None, min_jam=MIN_JAM_GARIS_DASAR):
    """Run all detectors; returns findings plus the baseline state.

    `baris` is the period examined; `baris_sejarah` is the preceding period, used
    to recognize genuinely new addresses.

    NSM's own rows are dropped here: monitoring heartbeats would produce an
    "error burst" whenever a service is down. Their count is still reported so
    nothing disappears silently.
    """
    semua = list(baris or [])
    dari_nsm = [r for r in semua if r.get("dari_nsm")]
    clean = [r for r in semua if not r.get("dari_nsm")]

    summarize = per_jam(clean)
    dasar = garis_dasar(summarize, min_jam=min_jam)

    temuan = []
    temuan += lonjakan_volume(summarize, dasar)
    temuan += unduhan_besar(clean)
    temuan += ledakan_galat(semua)
    temuan += di_luar_jam_kerja(clean)
    temuan += agen_bukan_peramban(clean)
    temuan += berkas_sensitif(clean)
    temuan += klien_baru(clean, [r for r in (baris_sejarah or [])
                                  if not r.get("dari_nsm")])

    temuan.sort(key=lambda t: (URUT_PARAH.get(t["keparahan"], 9),
                               str(t["kapan"])), reverse=False)

    return {
        "temuan": temuan,
        "cacah": {
            "tinggi": sum(1 for t in temuan if t["keparahan"] == TINGGI),
            "sedang": sum(1 for t in temuan if t["keparahan"] == SEDANG),
            "rendah": sum(1 for t in temuan if t["keparahan"] == RENDAH),
        },
        "garis_dasar": dasar,
        "diperiksa": len(clean),
        "dilewati_dari_nsm": len(dari_nsm),
        "jam_berisi_data": len(summarize),
    }

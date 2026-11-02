r"""SOC agent: triage, evidence enrichment, narrative, and proposed actions.

Architecture rule: this agent never touches devices. No SSH, no GNS3 API
calls, no firewall writes. It only PROPOSES, and every proposal goes through
`pagar_otomasi.putuskan()`, the same function the regular auto-remediator
uses. All existing safeguards therefore apply to the AI with no new safety
code: risk classification, evidence for `wajib_manusia`, operator allowlist,
freeze window, working hours, circuit breaker, rate limit, and blast radius.
The AI is one more requester, not an exception.

Three switches, all defaulting to the safe value:
    AGEN_SOC_AKTIF=0     the agent does nothing
    AGEN_SOC_MODE=usul   only records what it WOULD do
    AGEN_SOC_NARASI=0    no data leaves the lab network
The third is separate because it answers a different question: not "may it
analyze" but "may it send device names, IP addresses, and event sequences
outside the lab network".

Mode 'usul' uses `simulasi=True` because the gate's rate limit counts rows
with `keputusan='izin'`. Repeated what-if queries would otherwise use up the
real remediator's quota. `simulasi=True` runs every gate but writes no row.

The narrative has two paths. The default is built from templates, is always
available, and every sentence traces to one evidence field. The LLM API is
optional and only rewrites the same evidence as a readable paragraph; if the
call fails, the template narrative is used.
"""
import json
from datetime import datetime, timedelta

from sqlalchemy import func, select

import config
import models
import pagar_otomasi

# Runbooks the agent may propose, mapped from the shape of the symptoms.
# Deliberately short: each entry is an action a machine can request.
KATEGORI_PAGAR = "pemulih"
RUNBOOK_GNS3 = "gns3_restart"
RUNBOOK_LAYANAN = "layanan_restart"
RUNBOOK_INTERFACE = "interface_up"

# How far back syslog is collected as evidence.
JENDELA_SYSLOG_MENIT = 5

JENDELA_SERUPA_HARI = 30



def triase(db, insiden, sekarang=None):
    sekarang = sekarang or datetime.now()
    akar = (db.get(models.Device, insiden.akar_device_id)
            if insiden.akar_device_id else None)

    batas = sekarang - timedelta(days=JENDELA_SERUPA_HARI)
    serupa = db.execute(select(models.Insiden).where(
        models.Insiden.id != insiden.id,
        models.Insiden.akar_device_id == insiden.akar_device_id,
        models.Insiden.mulai >= batas)).scalars().all()

    recover_own = [i for i in serupa
                     if i.status == "pulih" and i.mttr_detik is not None]
    mttr_average = (sum(i.mttr_detik for i in recover_own) / len(recover_own)
                 if recover_own else None)

    symptom = db.execute(select(models.InsidenGejala).where(
        models.InsidenGejala.insiden_id == insiden.id)).scalars().all()
    jenis = sorted({g.jenis for g in symptom})

    if not serupa:
        riwayat = ("Pola ini BELUM PERNAH terjadi dalam %d hari terakhir."
                   % JENDELA_SERUPA_HARI)
        kebiasaan = "belum_pernah"
    elif recover_own and len(recover_own) == len(serupa):
        riwayat = ("Pola ini terjadi %dx dalam %d hari terakhir, dan "
                   "SEMUANYA pulih sendiri (rata-rata %s)."
                   % (len(serupa), JENDELA_SERUPA_HARI, _durasi(mttr_average)))
        kebiasaan = "selalu_pulih_sendiri"
    else:
        riwayat = ("Pola ini terjadi %dx dalam %d hari terakhir; %d di "
                   "antaranya pulih sendiri."
                   % (len(serupa), JENDELA_SERUPA_HARI, len(recover_own)))
        kebiasaan = "kadang_pulih_sendiri"

    return {
        "insiden_id": insiden.id,
        "keparahan": insiden.keparahan or "info",
        "akar": akar.name if akar else None,
        "akar_id": insiden.akar_device_id,
        "akar_pasti": insiden.akar_pasti,
        "jenis_gejala": jenis,
        "device_terdampak": sorted({g.device_id for g in symptom if g.device_id}),
        "serupa_30_hari": len(serupa),
        "serupa_pulih_sendiri": len(recover_own),
        "mttr_rata_detik": mttr_average,
        "kebiasaan": kebiasaan,
        "riwayat": riwayat,
    }


def _durasi(detik):
    if detik is None:
        return "-"
    detik = max(0, int(detik))
    if detik < 60:
        return "%d detik" % detik
    minute, remaining = divmod(detik, 60)
    if minute < 60:
        return "%d menit %d detik" % (minute, remaining) if remaining else "%d menit" % minute
    jam, remaining_minute = divmod(minute, 60)
    return "%d jam %d menit" % (jam, remaining_minute)



def kumpulkan_bukti(db, insiden, sekarang=None):
    """Collect what an analyst would gather first: syslog, neighbors, config
    snapshot, upstream, error budget, baseline, and new log patterns. Items that
    fail to collect are reported as failed, not dropped, so the chain never looks
    complete when it is not.
    """
    sekarang = sekarang or datetime.now()
    bukti = {"waktu": sekarang.isoformat(), "insiden_id": insiden.id,
             "gagal_dikumpulkan": []}

    symptom = db.execute(select(models.InsidenGejala).where(
        models.InsidenGejala.insiden_id == insiden.id)).scalars().all()
    device_ids = sorted({g.device_id for g in symptom if g.device_id})
    if insiden.akar_device_id:
        device_ids = sorted(set(device_ids) | {insiden.akar_device_id})
    bukti["device_ids"] = device_ids

    try:
        mulai = (insiden.mulai or sekarang) - timedelta(
            minutes=JENDELA_SYSLOG_MENIT)
        pesan = db.execute(
            select(models.SyslogPesan)
            .where(models.SyslogPesan.waktu >= mulai,
                   models.SyslogPesan.waktu <= sekarang)
            .order_by(models.SyslogPesan.waktu.desc()).limit(40)).scalars().all()
        bukti["syslog"] = [
            {"waktu": p.waktu.isoformat() if p.waktu else None,
             "device_id": p.device_id, "severity": p.severity,
             "tag": p.tag, "pesan": (p.pesan or "")[:200],
             "dari_terdampak": p.device_id in device_ids}
            for p in pesan]
        bukti["syslog_terdampak"] = sum(1 for p in bukti["syslog"]
                                        if p["dari_terdampak"])
    except Exception as e:                       # noqa: BLE001
        bukti["syslog"] = []
        bukti["gagal_dikumpulkan"].append("syslog: %s" % str(e)[:100])

    try:
        snapshot = []
        for did in device_ids:
            s = db.execute(
                select(models.KonfigSnapshot)
                .where(models.KonfigSnapshot.device_id == did)
                .order_by(models.KonfigSnapshot.id.desc())
                .limit(1)).scalars().first()
            if s is not None:
                snapshot.append({
                    "device_id": did,
                    "waktu": s.waktu.isoformat() if getattr(s, "waktu", None)
                    else None,
                    "umur_jam": (((sekarang - s.waktu).total_seconds() / 3600.0)
                                 if getattr(s, "waktu", None) else None)})
        bukti["potret_konfig"] = snapshot
    except Exception as e:                       # noqa: BLE001
        bukti["potret_konfig"] = []
        bukti["gagal_dikumpulkan"].append("potret konfig: %s" % str(e)[:100])

    # ---- keadaan HULU menurut graf ketergantungan -----------------------
    try:
        import ketergantungan
        import korelasi
        g = ketergantungan.graf(db)
        mati = korelasi.device_mati(db, sekarang)
        hulu = []
        for did in device_ids:
            h = ketergantungan.penyebab_hulu(db, did, g=g, mati=mati)
            hulu.append({"device_id": did, "status": h.get("status"),
                         "hulu_mati": [x.get("id") for x in
                                       (h.get("hulu_mati") or [])]})
        bukti["hulu"] = hulu
    except Exception as e:                       # noqa: BLE001
        bukti["hulu"] = []
        bukti["gagal_dikumpulkan"].append("graf hulu: %s" % str(e)[:100])

    # ---- sisa anggaran galat device akar --------------------------------
    try:
        if insiden.akar_device_id:
            import slo
            d = db.get(models.Device, insiden.akar_device_id)
            import report_service
            start_slo, finish_slo, _ = report_service.rentang("30d")
            h = slo.hitung(db, d, start_slo, finish_slo)
            bukti["anggaran"] = ({"sisa_persen": h.get("sisa_persen"),
                                  "vonis": h.get("vonis")} if h else None)
        else:
            bukti["anggaran"] = None
    except Exception as e:                       # noqa: BLE001
        bukti["anggaran"] = None
        bukti["gagal_dikumpulkan"].append("anggaran galat: %s" % str(e)[:100])

    # ---- baseline perilaku (Paket C1) ------------------------------------
    try:
        import baseline
        b = []
        for did in device_ids:
            h = baseline.nilai_sekarang(db, did)
            if h.get("layak"):
                b.append({"device_id": did, "sigma": h.get("sigma"),
                          "kalimat": h.get("kalimat")})
        bukti["baseline"] = b
    except Exception as e:                       # noqa: BLE001
        bukti["baseline"] = []
        bukti["gagal_dikumpulkan"].append("baseline: %s" % str(e)[:100])

    try:
        import pola_log
        r = pola_log.ringkas(db, jam=24, batas=5)
        bukti["pola_baru"] = r.get("baru", [])
        bukti["pola_riwayat_muda"] = bool(r.get("riwayat_muda"))
        bukti["pola_riwayat_jam"] = r.get("riwayat_jam")
    except Exception as e:                       # noqa: BLE001
        bukti["pola_baru"] = []
        bukti["pola_riwayat_muda"] = False
        bukti["pola_riwayat_jam"] = None
        bukti["gagal_dikumpulkan"].append("pola log: %s" % str(e)[:100])

    return bukti


# ===========================================================================
# C4c -- NARASI
# ===========================================================================

def narasi_templat(db, insiden, tri, bukti):
    line = []
    akar = tri.get("akar") or "Perangkat yang belum bisa dipastikan"
    mulai = insiden.mulai.strftime("%H.%M") if insiden.mulai else "?"

    n_dev = len(tri.get("device_terdampak") or [])
    if n_dev > 1:
        line.append("%s bermasalah sejak %s, dan %d perangkat lain ikut "
                     "terdampak." % (akar, mulai, n_dev - 1))
    else:
        line.append("%s bermasalah sejak %s." % (akar, mulai))

    if insiden.akar_pasti is False:
        line.append("Graf ketergantungan TIDAK yakin mana akarnya, jadi "
                     "penunjukan di atas belum pasti.")
    elif tri.get("akar"):
        line.append("Perangkat di hilirnya tidak dilaporkan rusak sendiri "
                     "-- graf ketergantungan menunjuk %s sebagai akarnya."
                     % akar)

    n_syslog = bukti.get("syslog_terdampak") or 0
    if n_syslog:
        example = next((p for p in bukti.get("syslog", [])
                       if p.get("dari_terdampak")), None)
        if example:
            line.append("Perangkatnya sendiri mengirim %d pesan syslog "
                         "sekitar waktu itu, di antaranya: %s"
                         % (n_syslog, (example.get("pesan") or "")[:120]))
    else:
        line.append("Tidak ada satu pun pesan syslog dari perangkat "
                     "terdampak di sekitar waktu itu -- yang berarti ia "
                     "berhenti berbicara, bukan mengeluh.")

    for b in (bukti.get("baseline") or [])[:2]:
        if b.get("kalimat"):
            line.append(b["kalimat"])

    ang = bukti.get("anggaran")
    if ang and ang.get("sisa_persen") is not None:
        line.append("Anggaran galat perangkat ini tersisa %.0f%% (%s)."
                     % (ang["sisa_persen"], ang.get("vonis")))

    line.append(tri.get("riwayat") or "")

    pattern = bukti.get("pola_baru") or []
    if pattern:
        if bukti.get("pola_riwayat_muda"):
            line.append("Ada %d pola log yang belum pernah terlihat, tetapi "
                         "NSM baru mendengar syslog selama %s jam sehingga "
                         "hampir semua pola masih terhitung baru -- ini belum "
                         "bisa dijadikan petunjuk."
                         % (len(pattern),
                            bukti.get("pola_riwayat_jam") or "beberapa"))
        else:
            line.append("Ada %d pola log yang BELUM PERNAH terlihat "
                         "sebelumnya dalam 24 jam terakhir -- layak dilihat "
                         "manusia." % len(pattern))

    if bukti.get("gagal_dikumpulkan"):
        line.append("Catatan: %d bagian bukti tidak bisa dikumpulkan (%s)."
                     % (len(bukti["gagal_dikumpulkan"]),
                        "; ".join(bukti["gagal_dikumpulkan"])[:200]))

    return " ".join(b for b in line if b)


def narasi_ai(db, insiden, tri, bukti, _panggil=None):
    """Rewrite the evidence chain as a paragraph via the LLM API.

    Returns (text, source), where source is 'ai', 'templat', or a failure reason.
    Falls back to the template narrative on every failure. `_panggil` can be
    replaced in tests so they never touch the network.
    """
    templat = narasi_templat(db, insiden, tri, bukti)

    if not config.get_agen_soc_narasi():
        return templat, "templat (AGEN_SOC_NARASI=0)"
    kunci = config.get_anthropic_api_key()
    if not kunci and _panggil is None:
        return templat, "templat (ANTHROPIC_API_KEY kosong)"

    summarize_evidence = {
        "triase": tri,
        "syslog": (bukti.get("syslog") or [])[:12],
        "hulu": bukti.get("hulu"),
        "anggaran": bukti.get("anggaran"),
        "baseline": bukti.get("baseline"),
        "pola_baru": [p.get("templat") for p in (bukti.get("pola_baru") or [])],
        "narasi_templat": templat,
    }

    SISTEM = (
        "Kamu asisten SOC jaringan. Tulis SATU paragraf bahasa Indonesia "
        "yang menjelaskan insiden ini kepada seorang teknisi.\n"
        "ATURAN KERAS:\n"
        "- Pakai HANYA fakta di dalam JSON yang diberikan. Jangan menambah "
        "sebab, angka, atau perangkat yang tidak ada di sana.\n"
        "- Kalau sebuah bukti tidak ada, KATAKAN tidak ada -- jangan "
        "menyimpulkan dari ketiadaannya.\n"
        "- Jangan memakai tanda hubung panjang (em dash).\n"
        "- Maksimal 6 kalimat. Tanpa daftar berpoin, tanpa judul.\n"
        "- Jangan menyarankan tindakan; usulan tindakan ditangani bagian lain "
        "yang punya pengamannya sendiri."
    )

    try:
        if _panggil is not None:
            teks = _panggil(SISTEM, summarize_evidence)
        else:
            import anthropic
            client = anthropic.Anthropic(api_key=kunci)
            reply = client.messages.create(
                model="claude-opus-5",
                max_tokens=1500,
                output_config={"effort": "low"},
                system=SISTEM,
                messages=[{"role": "user",
                           "content": json.dumps(summarize_evidence,
                                                 ensure_ascii=False,
                                                 default=str)}],
            )
            if reply.stop_reason == "refusal":
                return templat, "templat (permintaan ditolak model)"
            teks = "".join(b.text for b in reply.content
                           if getattr(b, "type", None) == "text").strip()
        # Strip before checking: a whitespace-only reply passes `if not teks` and would
        # be published as a blank narrative, while the template fallback goes unused.
        teks = (teks or "").strip()
        if not teks:
            return templat, "templat (balasan AI kosong)"
        return teks, "ai"
    except Exception as e:                       # noqa: BLE001
        return templat, "templat (AI gagal: %s)" % str(e)[:120]



def pilih_runbook(db, insiden, bukti):
    """Pick the runbook that fits this incident, or None. Chosen only from symptom
    shape and device capability; whether it is allowed is the gate's job.
    """
    if not insiden.akar_device_id:
        return None, "akar insiden tidak diketahui, tidak ada sasaran tindakan"
    d = db.get(models.Device, insiden.akar_device_id)
    if d is None:
        return None, "device akar tidak ada di basis data"

    # Read twice: live symptoms, then all symptoms. The second read separates "no
    # symptoms at all" (nothing recognizable) from "all symptoms recovered" (nothing
    # left to do), so the recorded rejection reason is accurate.
    all_symptom = db.execute(select(models.InsidenGejala).where(
        models.InsidenGejala.insiden_id == insiden.id,
        models.InsidenGejala.device_id == insiden.akar_device_id
    )).scalars().all()
    symptom = [g for g in all_symptom if not g.pulih]
    jenis = {g.jenis for g in symptom}

    if all_symptom and not symptom:
        return None, ("semua gejala di %s sudah pulih, jadi tidak ada lagi "
                      "yang perlu dilakukan -- bukan karena runbooknya tidak "
                      "ada" % (d.name or "device akar"))

    if "device" in jenis:
        if d.gns3_node:
            return RUNBOOK_GNS3, ("device akar tidak terjangkau dan ia node "
                                  "GNS3, jadi bisa dinyalakan ulang lewat "
                                  "controller")
        return None, ("device akar tidak terjangkau, tetapi ia bukan node "
                      "GNS3 -- tidak ada runbook yang aman untuk perangkat "
                      "yang tidak bisa dihubungi")
    if "layanan" in jenis:
        return RUNBOOK_LAYANAN, "layanan di device akar tidak melayani"
    if "interface" in jenis:
        return RUNBOOK_INTERFACE, "interface di device akar mati"
    return None, "bentuk gejalanya tidak cocok dengan satu pun runbook"


def usul_tindakan(db, insiden, bukti, sekarang=None, _pelaksana=None):
    """Propose one action and let the gate decide.

    Outcomes: all gates allow -> runs (mode 'jalan'), logged with
    `diminta_oleh='agen_soc'`; a gate rejects -> does not run, the proposal is
    shown with the reason; evidence insufficient -> falls to a human.
    `_pelaksana` can be replaced in tests so no real device is touched.
    """
    sekarang = sekarang or datetime.now()
    mode = config.get_agen_soc_mode()

    runbook, alasan_pilih = pilih_runbook(db, insiden, bukti)
    if runbook is None:
        return _catat_usulan(db, insiden, "tindakan", mode, None,
                             "tidak_diminta", alasan_pilih,
                             {"alasan": alasan_pilih}, 0.0, sekarang)

    simulasi = (mode != "jalan")
    kep = pagar_otomasi.putuskan(
        db, insiden.akar_device_id, KATEGORI_PAGAR, runbook,
        oleh="agen_soc", sekarang=sekarang, simulasi=simulasi)

    isi = {"runbook": runbook, "alasan_pilih": alasan_pilih,
           "simulasi": simulasi, "tindakan_id": kep.tindakan_id}

    if not kep.izin:
        return _catat_usulan(db, insiden, "tindakan", mode, runbook, "tolak",
                             kep.alasan, isi, 0.6, sekarang)

    if simulasi:
        isi["catatan"] = ("Pagar akan MENGIZINKAN tindakan ini, tetapi mode "
                          "masih 'usul' -- tidak ada yang dijalankan.")
        return _catat_usulan(db, insiden, "tindakan", mode, runbook, "izin",
                             kep.alasan, isi, 0.8, sekarang)

    # Mode 'jalan' hands off to the remediator; the agent only acts as requester
    # (`oleh='agen_soc'`). The remediator calls the gate again with
    # `simulasi=False`. The gates therefore run twice on purpose: state can change
    # in between, and the call that immediately precedes the action is the binding one.
    hasil = None
    try:
        hasil = _jalankan(db, insiden, runbook, sekarang, _pelaksana)
        isi["hasil"] = hasil
    except Exception as e:                       # noqa: BLE001
        isi["hasil"] = {"berhasil": False, "galat": str(e)[:200]}
    return _catat_usulan(db, insiden, "tindakan", mode, runbook, "izin",
                         kep.alasan, isi, 0.8, sekarang)


def _jalankan(db, insiden, runbook, sekarang, _pelaksana=None):
    if _pelaksana is not None:
        return _pelaksana(db, insiden, runbook, sekarang)

    d = db.get(models.Device, insiden.akar_device_id)
    if runbook == RUNBOOK_GNS3:
        if not config.get_pemulih_gns3_aktif():
            return {"berhasil": False,
                    "alasan": "kill-switch PEMULIH_GNS3_AKTIF mati"}
        from pemulih import gns3
        kep = gns3.coba_pulihkan(db, d, oleh="agen_soc", sekarang=sekarang)
        return {"berhasil": bool(kep.izin), "alasan": kep.alasan}
    return {"berhasil": False,
            "alasan": "runbook '%s' belum punya pelaksana di agen" % runbook}


def _catat_usulan(db, insiden, jenis, mode, tindakan, vonis, alasan, isi,
                  keyakinan, sekarang):
    u = models.UsulanAgen(
        waktu=sekarang, insiden_id=insiden.id,
        device_id=insiden.akar_device_id, jenis=jenis, mode=mode,
        tindakan=tindakan, vonis_pagar=vonis, alasan_pagar=alasan,
        isi=json.dumps(isi, ensure_ascii=False, default=str),
        keyakinan=keyakinan)
    db.add(u)
    db.commit()
    return u


# ===========================================================================
# Orkestrasi
# ===========================================================================

def tangani(db, insiden, sekarang=None, _panggil_ai=None, _pelaksana=None):
    sekarang = sekarang or datetime.now()
    tri = triase(db, insiden, sekarang=sekarang)
    bukti = kumpulkan_bukti(db, insiden, sekarang=sekarang)
    teks, sumber = narasi_ai(db, insiden, tri, bukti, _panggil=_panggil_ai)

    mode = config.get_agen_soc_mode()
    _catat_usulan(db, insiden, "triase", mode, None, "tidak_diminta", None,
                  tri, 1.0, sekarang)
    _catat_usulan(db, insiden, "bukti", mode, None, "tidak_diminta", None,
                  {"ringkas": {k: v for k, v in bukti.items()
                               if k != "syslog"},
                   "syslog_jumlah": len(bukti.get("syslog") or [])},
                  1.0, sekarang)
    _catat_usulan(db, insiden, "narasi", mode, None, "tidak_diminta", None,
                  {"teks": teks, "sumber": sumber}, 1.0, sekarang)

    usulan = usul_tindakan(db, insiden, bukti, sekarang=sekarang,
                           _pelaksana=_pelaksana)
    return {"triase": tri, "bukti": bukti, "narasi": teks,
            "sumber_narasi": sumber,
            "usulan": {"tindakan": usulan.tindakan,
                       "vonis": usulan.vonis_pagar,
                       "alasan": usulan.alasan_pagar}}


def proses(db, sekarang=None, _panggil_ai=None, _pelaksana=None):
    """One agent round: handle OPEN incidents not yet handled.

    Idempotent: an incident that already has a 'triase' proposal row is skipped.
    Otherwise each round would add a new narrative for the same fault and flood
    the proposals page.
    """
    sekarang = sekarang or datetime.now()
    if not config.get_agen_soc_aktif():
        return {"jalan": False, "alasan": "AGEN_SOC_AKTIF=0", "ditangani": 0}

    already = set(db.execute(
        select(models.UsulanAgen.insiden_id).where(
            models.UsulanAgen.jenis == "triase")).scalars().all())

    ditangani = 0
    for ins in db.execute(select(models.Insiden).where(
            models.Insiden.status == "terbuka"
    ).order_by(models.Insiden.mulai)).scalars().all():
        if ins.id in already:
            continue
        try:
            tangani(db, ins, sekarang=sekarang, _panggil_ai=_panggil_ai,
                    _pelaksana=_pelaksana)
            ditangani += 1
        except Exception as e:                   # noqa: BLE001
            db.rollback()
            print("[agen-soc] gagal menangani insiden #%s: %s"
                  % (ins.id, str(e)[:200]))
    return {"jalan": True, "ditangani": ditangani,
            "mode": config.get_agen_soc_mode()}


def ringkas(db, jam=24, batas=50):
    limit_time = datetime.now() - timedelta(hours=jam)
    line = db.execute(select(models.UsulanAgen).where(
        models.UsulanAgen.waktu >= limit_time
    ).order_by(models.UsulanAgen.waktu.desc()).limit(batas)).scalars().all()

    def bentuk(u):
        try:
            isi = json.loads(u.isi) if u.isi else {}
        except ValueError:
            isi = {"mentah": (u.isi or "")[:500]}
        return {"id": u.id, "waktu": u.waktu.isoformat() if u.waktu else None,
                "insiden_id": u.insiden_id, "device_id": u.device_id,
                "jenis": u.jenis, "mode": u.mode, "tindakan": u.tindakan,
                "vonis_pagar": u.vonis_pagar, "alasan_pagar": u.alasan_pagar,
                "keyakinan": u.keyakinan, "isi": isi}

    return {
        "jam": jam,
        "aktif": config.get_agen_soc_aktif(),
        "mode": config.get_agen_soc_mode(),
        "narasi_ai": config.get_agen_soc_narasi(),
        "usulan": [bentuk(u) for u in line],
        "diusulkan": sum(1 for u in line if u.jenis == "tindakan"
                         and u.tindakan),
        "diizinkan_pagar": sum(1 for u in line if u.vonis_pagar == "izin"),
        "ditolak_pagar": sum(1 for u in line if u.vonis_pagar == "tolak"),
    }

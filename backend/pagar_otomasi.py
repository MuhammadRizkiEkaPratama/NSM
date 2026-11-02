"""Automation guardrail (layer L3 of docs/design/CLOSED-LOOP-AUTOMATION.md): the
mandatory single entry point for all automatic recovery (stages 4-7: dead GNS3
node, dead service, dead interface, drifted config).

Every recovery MUST call `putuskan()` before touching a device, and the check
happens AT THE POINT OF EXECUTION. This module never assumes the caller already
checked; it re-checks everything itself, every time.

Six gates. The order matters, and the first rejection ends the check so that
two different reasons are never reported for one refusal:
  1. RISK        wajib_manusia categories/keys are refused absolutely and cannot
                 be overridden via .env (changing it requires a code edit in
                 `sot/katalog.py`).
  2. ALLOWLIST   the operator must explicitly enable each key via
                 `PAGAR_DAFTAR_PUTIH`. Empty by default (kill switch).
  3. FREEZE      `PAGAR_JENDELA_BEKU`: no automatic action at all in this window.
  4. HOURS       only when a human can check soon (default 08-17).
  5. BREAKER     the last N attempts for (device, action) all failed in a row ->
                 stop that action on that device. Self-healing: one success
                 resets the count.
  6. RATE LIMIT  at most N/hour per device AND N/hour overall.

Why gate 5 exists besides gate 6: the rate limit counts `keputusan='izin'` rows,
so it bounds how OFTEN to try but does not stop a fix that never works; it would
still be retried every hour forever.

Every decision is recorded, allowed or refused, so "why did the system NOT fix
this automatically" can always be answered from data.
"""
from datetime import datetime, timedelta

from sqlalchemy import select, func

import config
from models import Device, PagarTindakan
from sot import katalog

IZIN = "izin"
TOLAK = "tolak"


class Keputusan:
    """Result of one `putuskan()` call. `alasan` is always filled (allow or deny).
    `tindakan_id` references the new `PagarTindakan` row, used later by
    `catat_verifikasi()`.
    """

    def __init__(self, izin, alasan, tindakan_id):
        self.izin = izin
        self.alasan = alasan
        self.tindakan_id = tindakan_id

    def __repr__(self):
        return "Keputusan(izin=%r, alasan=%r)" % (self.izin, self.alasan)


# Risk classification for the 'pemulih' category (stages 4-7). Separate from
# `sot.katalog.RISIKO_KUNCI` because these are not SoT intent keys.
# Order: GNS3 (low), service (medium), interface (medium), config (high). The
# guardrail's risk system is binary, so only "low" maps to aman_otomatis and both
# medium and high map to wajib_manusia: when in doubt, require a human.
RISIKO_PEMULIH = {
    "gns3_restart": (katalog.RISIKO_AMAN,
        "Menyalakan ulang node GNS3 yang SUDAH TERBUKTI mati (device_events "
        "mencatat DOWN). Tidak ada trafik hidup yang dipertaruhkan -- "
        "keadaan sebelumnya sudah 'tidak ada apa-apa', jadi risiko "
        "tindakannya lebih rendah daripada risiko membiarkannya mati."),
    "layanan_restart": (katalog.RISIKO_MANUSIA,
        "Restart layanan lewat SSH+sudo bisa memutus SESI AKTIF yang "
        "sedang dipakai orang lain di layanan itu, dan penyebab layanan "
        "mati (mis. disk penuh, config rusak) bisa membuat restart "
        "berulang tanpa pernah benar-benar pulih."),
    "interface_up": (katalog.RISIKO_MANUSIA,
        "Interface yang mati bisa sengaja dimatikan seseorang (maintenance, "
        "isolasi keamanan) -- menyalakannya kembali otomatis bisa "
        "membatalkan keputusan manusia yang belum sempat dicatat di mana "
        "pun yang bisa dibaca sistem."),
    "konfig_kembalikan": (katalog.RISIKO_MANUSIA,
        "RISIKO TERTINGGI (§5.1): mendorong perubahan konfigurasi ke "
        "perangkat sungguhan. Jaring pengaman `kirim_perintah.py` "
        "menahan kegagalan teknis, tapi keputusan APA yang dikirim tetap "
        "harus disetujui manusia."),
}


# GATE 1b: evidence that allows a `wajib_manusia` action to run automatically.
# Simply flipping the classifications in `RISIKO_PEMULIH` would be wrong: each
# stated reason names a real way automation can cause harm. Instead each reason
# gets a CONDITION provable from data NSM already has. Two keys, both required:
#   1. the operator enables the `OTOMASI_PENUH_*` switch in .env, AND
#   2. the evidence for the condition exists at that moment.
# A switch without evidence does nothing.

BATAS_JAM_RESTART = 24


def _terbukti_tidak_dimatikan_sengaja(db, device_id, nama_if):
    """interface_up: down because of a FAULT, not a human decision.
    Deliberately shutting an interface on Cisco leaves a `shutdown` line in the
    running-config, which NSM records (`KonfigSnapshot`), so "was this deliberate"
    can be answered rather than guessed.

        trace present -> someone decided this; a machine must not undo it.
        trace absent  -> down with nobody asking for it; a fault.

    No snapshot at all also means NOT allowed: unanswered is not the same as safe.
    """
    if not nama_if:
        return False, ("nama interface tidak diberikan, jadi jejak `shutdown` "
                       "tidak bisa dicari")
    try:
        from models import KonfigSnapshot
        snap = (db.query(KonfigSnapshot)
                .filter(KonfigSnapshot.device_id == device_id)
                .order_by(KonfigSnapshot.waktu.desc()).first())
    except Exception as e:
        return False, "potret konfigurasi tidak terbaca (%s)" % type(e).__name__
    if snap is None or not (snap.teks or "").strip():
        return False, ("belum ada potret konfigurasi untuk device ini, jadi "
                       "'dimatikan orang' tidak bisa dibedakan dari 'mati "
                       "sendiri'")

    # Extract the given interface block, stopping at the next unindented line.
    # Names are compared ignoring case and spaces, since `Fa1/1`, `fa1/1` and
    # `FastEthernet1/1` name the same thing.
    #
    # Substring matching is not enough and fails in the dangerous direction:
    # `"fa1/1" in "interfacefastethernet1/1"` is False, so the block is never found,
    # the `shutdown` trace is missed, and the guardrail concludes "not deliberate".
    # Cisco abbreviates only the LETTER part of the name (`FastEthernet1/1` ->
    # `Fa1/1`), so split letters from the rest: the letters match if one is a prefix
    # of the other, and the rest must be identical.
    def _belah(nama):
        t = nama.strip().lower().replace(" ", "")
        i = 0
        while i < len(t) and t[i].isalpha():
            i += 1
        return t[:i], t[i:]

    t_letter, t_number = _belah(nama_if)

    def _interface_sama(kepala_baris):
        k_letter, k_number = _belah(kepala_baris)
        if not t_number or t_number != k_number:
            return False
        return k_letter.startswith(t_letter) or t_letter.startswith(k_letter)

    at_block = False
    for b in (snap.teks or "").splitlines():
        if b.strip() and not b[:1].isspace():
            header = b.strip().lower().replace(" ", "")
            at_block = (header.startswith("interface")
                       and _interface_sama(header[len("interface"):]))
            continue
        if at_block and b.strip().lower() == "shutdown":
            return False, ("running-config menyebut `shutdown` pada %s -- ini "
                           "keputusan seseorang, bukan gangguan. Tidak "
                           "dibatalkan otomatis." % nama_if)
    return True, ("tidak ada `shutdown` pada %s di potret terakhir (%s), jadi "
                  "matinya bukan karena disuruh" % (nama_if, snap.waktu))


def _terbukti_belum_kebanyakan_restart(db, device_id, kunci, sekarang):
    """layanan_restart: a restart that does not heal must not be repeated.
    The cause of a dead service (full disk, broken config) can make restarts repeat
    without ever recovering. The answer is a hard limit per 24 hours, counted from
    `PagarTindakan`, which already records every ALLOWED action.
    """
    batas = config.get_batas_restart_layanan_harian()
    try:
        from models import PagarTindakan
        since = sekarang - timedelta(hours=BATAS_JAM_RESTART)
        n = (db.query(PagarTindakan)
             .filter(PagarTindakan.device_id == device_id,
                     PagarTindakan.kunci == kunci,
                     PagarTindakan.keputusan == IZIN,
                     PagarTindakan.waktu >= since).count())
    except Exception as e:
        return False, "riwayat tindakan tidak terbaca (%s)" % type(e).__name__
    if n >= batas:
        return False, ("sudah %d kali di-restart otomatis dalam %d jam "
                       "terakhir (batas %d). Restart yang tidak menyembuhkan "
                       "berhenti menjadi pemulihan; ini butuh orang."
                       % (n, BATAS_JAM_RESTART, batas))
    return True, ("baru %d dari %d restart otomatis dalam %d jam terakhir"
                  % (n, batas, BATAS_JAM_RESTART))


def _terbukti_tanpa_korban_hilir(db, device_id, bukti):
    """konfig_kembalikan: must not take other devices offline.
    Highest risk of the four, so the strictest condition: the blast radius must be
    ZERO downstream devices, and that number must be certain, not estimated. If the
    dependency graph itself is unsure, the answer is "human", not "probably safe".
    """
    b = bukti or {}
    jumlah = b.get("dampak_hilir_jumlah")
    certain = b.get("dampak_hilir_pasti")
    if jumlah is None:
        try:
            import ketergantungan
            hilir = ketergantungan.hilir(db, device_id) or []
            jumlah, certain = len(hilir), True
        except Exception as e:
            return False, "radius dampak tidak bisa dihitung (%s)" % type(e).__name__
    if not certain:
        return False, ("radius dampak tidak pasti. Mengembalikan konfigurasi "
                       "tanpa tahu siapa lagi yang ikut gelap bukan risiko "
                       "yang boleh diambil mesin.")
    if jumlah:
        return False, ("ada %d perangkat HILIR yang ikut terdampak. Selama "
                       "bukan nol, ini keputusan manusia." % jumlah)
    return True, "radius dampak nol perangkat hilir (pasti)"


def _bukti_cukup(db, device_id, kunci, bukti, sekarang):
    """(allowed, note): is the `wajib_manusia` risk proven absent?
    Defaults to DENY: an unknown key, a switch that is off, or unreadable data all
    end in "no". The only path to "allowed" is evidence that was actually collected.
    """
    if kunci == "layanan_restart":
        if not config.get_otomasi_penuh_layanan():
            return False, "saklar OTOMASI_PENUH_LAYANAN mati"
        return _terbukti_belum_kebanyakan_restart(db, device_id, kunci, sekarang)
    if kunci == "interface_up":
        if not config.get_otomasi_penuh_interface():
            return False, "saklar OTOMASI_PENUH_INTERFACE mati"
        return _terbukti_tidak_dimatikan_sengaja(
            db, device_id, (bukti or {}).get("interface"))
    if kunci == "konfig_kembalikan":
        if not config.get_otomasi_penuh_konfig():
            return False, "saklar OTOMASI_PENUH_KONFIG mati"
        return _terbukti_tanpa_korban_hilir(db, device_id, bukti)
    return False, "tidak ada syarat yang didefinisikan untuk kunci ini"


def _risiko(kategori, kunci):
    if kategori == "nilai":
        return katalog.risiko_kunci(kunci)
    if kategori == "pemulih":
        return RISIKO_PEMULIH.get(kunci, (katalog.RISIKO_MANUSIA,
                                          "jenis pemulih '%s' belum diklasifikasikan "
                                          "-- default aman" % kunci))
    return katalog.risiko_kategori(kategori)


def _dalam_jendela_beku(sekarang):
    for mulai, selesai in config.get_pagar_jendela_beku():
        if mulai <= sekarang <= selesai:
            return True, mulai, selesai
    return False, None, None


def _dalam_jam_kerja(sekarang):
    jam_mulai, jam_selesai = config.get_pagar_jam_kerja()
    return jam_mulai <= sekarang.hour < jam_selesai


def _hitung_izin_sejam_terakhir(db, device_id, sekarang):
    """(device_count, global_count): `keputusan='izin'` rows in the last 60 minutes.
    Computed from `PagarTindakan` on every call rather than kept as a separate
    counter (same pattern as `jeda.py`), so it cannot drift from its source.
    """
    sejam_lalu = sekarang - timedelta(hours=1)
    base = select(func.count(PagarTindakan.id)).where(
        PagarTindakan.keputusan == IZIN,
        PagarTindakan.waktu >= sejam_lalu,
        PagarTindakan.waktu <= sekarang,
    )

    # The "global" limit is scoped per tenant. Otherwise one tenant's failing devices
    # would use up another tenant's automatic-action quota. A device without a tenant
    # counts across all devices, exactly as before, so enabling tenants does not
    # silently change behavior for labs that do not use them.
    tenant_id = None
    if device_id is not None:
        d = db.get(Device, device_id)
        tenant_id = getattr(d, "tenant_id", None) if d else None

    if tenant_id is not None:
        sesama = select(Device.id).where(Device.tenant_id == tenant_id)
        global_n = db.execute(
            base.where(PagarTindakan.device_id.in_(sesama))).scalar() or 0
    else:
        global_n = db.execute(base).scalar() or 0

    device_n = 0
    if device_id is not None:
        device_n = db.execute(
            base.where(PagarTindakan.device_id == device_id)
        ).scalar() or 0
    return device_n, global_n


def _hitung_gagal_beruntun(db, device_id, kategori, kunci):
    """How many of the LAST actions for this (device, category, key) failed
    CONSECUTIVELY, counted back from the newest.

    Consecutive, not total, which makes the breaker self-healing: one success resets
    the count. A lifetime failure total would block a device that once had trouble
    from ever being fixed automatically again.

    Rows not yet verified (`status_verifikasi IS NULL`) are skipped, counted as
    neither failure nor success: that state is "unknown" (a two-phase recovery still
    waiting for the next verification round).
    """
    line = db.execute(
        select(PagarTindakan.status_verifikasi, PagarTindakan.diminta_oleh).where(
            PagarTindakan.device_id == device_id,
            PagarTindakan.kategori == kategori,
            PagarTindakan.kunci == kunci,
            PagarTindakan.keputusan == IZIN,
            PagarTindakan.status_verifikasi.isnot(None),
        ).order_by(PagarTindakan.waktu.desc(), PagarTindakan.id.desc()).limit(50)
    ).all()

    consecutive = 0
    for status, oleh in line:
        # A HUMAN RESET stops the count, like a success.
        # The breaker's rejection message says "until one succeeds OR A HUMAN INTERVENES",
        # but there was no way to declare the intervention, so an open breaker locked
        # itself: it refused every attempt, so no success could ever heal it.
        # The reset is not disguised as a success; it is its own audit row with
        # `diminta_oleh` starting with `reset_pemutus:` and a reason naming who and why.
        # See `reset_pemutus()`.
        if (oleh or "").startswith(PREFIKS_RESET):
            break
        if status:
            break
        consecutive += 1
    return consecutive


PREFIKS_RESET = "reset_pemutus:"


def reset_pemutus(db, device_id, kategori, kunci, oleh, alasan,
                  sekarang=None):
    """Record that a HUMAN intervened, so the breaker may close.
    Does not erase history: earlier failure rows stay. One new row states who fixed
    what, so "why may this breaker close" has a written answer.
    `alasan` is REQUIRED: a safety that can be disabled without a trace is not a safety.
    """
    if not (alasan or "").strip():
        raise ValueError("alasan wajib diisi: reset tanpa keterangan sama "
                         "dengan mematikan pengaman tanpa jejak")
    sekarang = sekarang or datetime.now()
    line = PagarTindakan(
        device_id=device_id, kategori=kategori, kunci=kunci,
        keputusan=IZIN,
        alasan="RESET PEMUTUS oleh manusia: " + alasan.strip(),
        diminta_oleh=PREFIKS_RESET + str(oleh),
        waktu=sekarang,
        # True so that older readers that do not know the reset prefix also stop counting.
        status_verifikasi=True,
        verifikasi_bukti="reset manual, bukan hasil tindakan otomatis",
        verifikasi_waktu=sekarang,
    )
    db.add(line)
    db.commit()
    return line


def _catat(db, device_id, kategori, kunci, keputusan, alasan, oleh, sekarang):
    # `waktu=sekarang`, not `datetime.now()`: this row must use the same clock that
    # `_hitung_izin_sejam_terakhir()` uses for its window, otherwise the rate limit
    # can silently miscount.
    line = PagarTindakan(
        device_id=device_id, kategori=kategori, kunci=kunci,
        keputusan=keputusan, alasan=alasan, diminta_oleh=oleh,
        waktu=sekarang,
    )
    db.add(line)
    db.commit()
    db.refresh(line)
    return line.id


# Categories whose risk differs PER KEY. The allowlist for these is checked by KEY
# name (e.g. 'ntp_server', 'gns3_restart'). 'interface'/'vlan'/'rute' are
# deliberately absent: their risk is uniformly wajib_manusia per category (see
# `sot.katalog.RISIKO_KATEGORI`), so their allowlist is checked by category name.
_KATEGORI_PER_KUNCI = {"nilai", "pemulih"}


def _kunci_putih(kategori, kunci, putih):
    """Allowlist format: KEY name for categories whose risk differs per key ('nilai',
    'pemulih', e.g. 'gns3_restart'), CATEGORY name for uniform ones
    ('interface'/'vlan'/'rute').
    This once only distinguished 'nilai' from everything else, so an entry such as
    `{"gns3_restart"}` never matched. A test caught it, which is why every gate
    needs a test proving it can both refuse and allow.
    """
    if kategori in _KATEGORI_PER_KUNCI:
        return kunci in putih
    return kategori in putih


def putuskan(db, device_id, kategori, kunci, oleh=None, sekarang=None,
             bukti=None, simulasi=False):
    """Decide whether ONE candidate automatic action may run NOW.

    `simulasi=True` asks without requesting: all gates run identically, only the
    `PagarTindakan` row is not written. The rate limit counts `izin` rows, so an
    agent asking repeatedly would use up the quota of the real recovery jobs, which
    would then be refused for actions that never happened. It skips no gate and
    adds no second decision path; the SOC agent is just another requester.
    With `simulasi=True`, `Keputusan.tindakan_id` is None. Callers that actually
    act must use `simulasi=False`, since without the row nothing can be verified.

    `kategori`: 'nilai' / 'interface' / 'vlan' / 'rute' (same as
    `drift.service.bandingkan()`). `kunci`: the intent key name, or a row
    identifier (interface name, VLAN number) for repeated categories.

    Writes ONE `PagarTindakan` row (allow or deny) and returns `Keputusan`. Does not
    raise for normal outcomes: callers check `.izin`.
    """
    sekarang = sekarang or datetime.now()

    def _rekam(keputusan, alasan):
        """Write the audit row, unless this is only a question (`simulasi`)."""
        if simulasi:
            return None
        return _catat(db, device_id, kategori, kunci, keputusan, alasan,
                      oleh, sekarang)

    level, reason_risk = _risiko(kategori, kunci)
    via_evidence = None
    if level == katalog.RISIKO_MANUSIA:
        # GATE 1b. `wajib_manusia` used to be a dead end. Now it can be opened only by
        # evidence that the stated risk is gone, and only if the operator enabled the
        # switch first (see `_bukti_cukup()`).
        # Evidence is checked HERE, before the allowlist, freeze window, working hours,
        # rate limit and blast radius. Passing this gate is NOT permission; it only moves
        # the action from "never" to "checked like the others".
        allowed_evidence, note_evidence = _bukti_cukup(db, device_id, kunci, bukti, sekarang)
        if not allowed_evidence:
            alasan = ("Diklasifikasikan wajib_manusia (Tahap 2): %s "
                      "[gerbang 1b: %s]" % (reason_risk, note_evidence))
            tid = _rekam(TOLAK, alasan)
            return Keputusan(False, alasan, tid)
        via_evidence = note_evidence

    putih = config.get_pagar_daftar_putih()
    if not _kunci_putih(kategori, kunci, putih):
        alasan = ("'%s' (%s) belum ada di daftar putih operator "
                  "(PAGAR_DAFTAR_PUTIH di .env). Aman secara klasifikasi "
                  "risiko TIDAK cukup -- operator harus menyalakannya "
                  "eksplisit." % (kunci, kategori))
        tid = _rekam(TOLAK, alasan)
        return Keputusan(False, alasan, tid)

    frozen, start_frozen, finish_frozen = _dalam_jendela_beku(sekarang)
    if frozen:
        alasan = ("Sedang jendela beku (%s s.d. %s) -- tidak ada tindakan "
                  "otomatis apa pun selama rentang ini."
                  % (start_frozen.isoformat(), finish_frozen.isoformat()))
        tid = _rekam(TOLAK, alasan)
        return Keputusan(False, alasan, tid)

    if not _dalam_jam_kerja(sekarang):
        jam_mulai, jam_selesai = config.get_pagar_jam_kerja()
        alasan = ("Di luar jam kerja (%02d:00-%02d:00), sekarang %02d:%02d. "
                  "Tindakan otomatis hanya berjalan saat manusia bisa "
                  "segera memeriksa." % (jam_mulai, jam_selesai,
                                        sekarang.hour, sekarang.minute))
        tid = _rekam(TOLAK, alasan)
        return Keputusan(False, alasan, tid)

    # GATE 5: circuit breaker. Checked BEFORE the rate limit on purpose: when both
    # would refuse, "this action ALWAYS fails" is more useful to a human than
    # "too often".
    fail_consecutive = _hitung_gagal_beruntun(db, device_id, kategori, kunci)
    limit_fail = config.get_pagar_gagal_beruntun_maks()
    if fail_consecutive >= limit_fail:
        alasan = ("PEMUTUS TERBUKA: %d percobaan terakhir untuk '%s' di "
                  "device ini GAGAL semua BERUNTUN (batas %d). Tindakan "
                  "otomatis jenis ini dihentikan sampai ada yang berhasil "
                  "atau manusia turun tangan -- terus mencoba hal yang "
                  "tidak pernah berhasil hanya menyembunyikan masalah yang "
                  "sebenarnya." % (fail_consecutive, kunci, limit_fail))
        tid = _rekam(TOLAK, alasan)
        return Keputusan(False, alasan, tid)

    device_n, global_n = _hitung_izin_sejam_terakhir(db, device_id, sekarang)
    limit_device = config.get_pagar_batas_per_device_per_jam()
    limit_global = config.get_pagar_batas_global_per_jam()
    if device_id is not None and device_n >= limit_device:
        alasan = ("Batas laju PER DEVICE tercapai: %d tindakan sudah "
                  "diizinkan untuk device ini dalam 1 jam terakhir "
                  "(batas %d). Tanda ada masalah yang berulang, bukan "
                  "alasan untuk terus mencoba." % (device_n, limit_device))
        tid = _rekam(TOLAK, alasan)
        return Keputusan(False, alasan, tid)
    if global_n >= limit_global:
        alasan = ("Batas laju GLOBAL tercapai: %d tindakan sudah diizinkan "
                  "di SELURUH perangkat dalam 1 jam terakhir (batas %d)."
                  % (global_n, limit_global))
        tid = _rekam(TOLAK, alasan)
        return Keputusan(False, alasan, tid)

    alasan = ("Diizinkan: risiko %s, ada di daftar putih, di luar jendela "
              "beku, di jam kerja, dan di bawah batas laju (%d/%d device, "
              "%d/%d global)." % (level, device_n, limit_device,
                                  global_n, limit_global))
    if via_evidence:
        # A risky action that passes must carry its reason in its own audit row, so "why
        # was the machine allowed to do this" is answered by the same row.
        alasan += (" Klasifikasi aslinya wajib_manusia, dilewatkan gerbang 1b "
                   "karena: %s." % via_evidence)
    tid = _rekam(IZIN, alasan)
    return Keputusan(True, alasan, tid)


def record_verification(db, tindakan_id, berhasil, bukti=None):
    """Record the verification result AFTER a recovery attempt.
    Recovery jobs (stages 4-7) MUST call this after each allowed action; without a
    passing verification the action counts as FAILED. A row never reported stays
    `status_verifikasi IS NULL`, a third state meaning "the recovery never reported
    back", not "succeeded silently".
    """
    line = db.get(PagarTindakan, tindakan_id)
    if line is None:
        raise katalog.Ditolak("tindakan pagar id=%s tidak ditemukan." % tindakan_id)
    line.status_verifikasi = bool(berhasil)
    line.verifikasi_bukti = bukti
    line.verifikasi_waktu = datetime.now()
    db.commit()


def riwayat(db, device_id=None, batas=100):
    """Guardrail decision history, newest first. `device_id=None` -> all devices (used
    by the summary page).
    """
    q = select(PagarTindakan).order_by(PagarTindakan.waktu.desc()).limit(batas)
    if device_id is not None:
        q = q.where(PagarTindakan.device_id == device_id)
    line = db.execute(q).scalars().all()
    return [{
        "id": b.id, "device_id": b.device_id, "kategori": b.kategori,
        "kunci": b.kunci, "keputusan": b.keputusan, "alasan": b.alasan,
        "diminta_oleh": b.diminta_oleh,
        "waktu": b.waktu.isoformat() if b.waktu else None,
        "status_verifikasi": b.status_verifikasi,
        "verifikasi_bukti": b.verifikasi_bukti,
        "verifikasi_waktu": b.verifikasi_waktu.isoformat() if b.verifikasi_waktu else None,
    } for b in line]


def status_pagar():
    """Current guardrail settings, so the web page can show the operator what is
    active without opening `.env`.
    """
    jam_mulai, jam_selesai = config.get_pagar_jam_kerja()
    frozen = config.get_pagar_jendela_beku()
    return {
        "daftar_putih": sorted(config.get_pagar_daftar_putih()),
        "batas_per_device_per_jam": config.get_pagar_batas_per_device_per_jam(),
        "batas_global_per_jam": config.get_pagar_batas_global_per_jam(),
        "gagal_beruntun_maks": config.get_pagar_gagal_beruntun_maks(),
        "jam_mulai": jam_mulai, "jam_selesai": jam_selesai,
        "jendela_beku": [{"mulai": m.isoformat(), "selesai": s.isoformat()}
                        for m, s in frozen],
        "sedang_jam_kerja": _dalam_jam_kerja(datetime.now()),
    }

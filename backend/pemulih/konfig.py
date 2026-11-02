"""Stage 7: drifted config -> send a fix through the existing command catalog.

Highest risk; built after `pemulih/rollback.py`.

Fixes every key classified `aman_otomatis` (nine of thirteen):
    single-value: hostname, banner_masuk, zona_waktu, snmp_lokasi, snmp_kontak
    list:         ntp_server, dns_server, logging_server (reconciled by
                  add/remove, not delete-all-and-rewrite)
    boolean:      layanan_http_mati (one direction only, see `_perbaiki_bool`)
The other four (`domain`, `exec_timeout_menit`, `vty_izin`, `ssh_saja`) are
`wajib_manusia` in `sot/katalog.py`, so guardrail gate 1 always refuses them;
building commands for them would only create a path never taken. Reasons are in
`ALASAN_TIDAK_DIDUKUNG` and shown through the API. `KUNCI_DIDUKUNG` is derived
from the three maps below.

Two phases, as in stage 4: verification needs a NEW snapshot, and
`poll_konfig()` refreshes it only on its own schedule (900 s), so verifying
right after `kirim()` would read the old snapshot.
  Phase 1 (`coba_perbaiki`)       gate -> save observed BEFORE -> send via
                                  catalog -> record action, no verification.
  Phase 2 (`verifikasi_tertunda`) next round: rerun `drift.service.bandingkan()`
                                  for the key. Match -> success. Still different
                                  past the deadline -> FAILURE and automatic
                                  ROLLBACK.

Rollback uses `kirim_perintah.putuskan('batalkan_sekarang')` instead of a
hand-made inverse command (rationale in `kirim_perintah.putuskan()`). In this lab
every intent-bearing cisco_ios device is a GNS3 node, so the real path is always
`batalkan_sekarang`: restore via the controller API, and the device reboots from
its saved startup-config. A `reload in N` is never installed for GNS3 nodes.
"""
from datetime import datetime, timedelta

from sqlalchemy import select

import dialek_perangkat
import kirim_perintah
import pagar_otomasi
from drift import service as drift_svc
from models import Device, PagarTindakan
from pemulih import rollback
from sot import katalog

KATEGORI_PAGAR = "pemulih"
KUNCI_PAGAR = "konfig_kembalikan"

# {SoT key: (single command_id, function(intended value) -> dict of values)}
# Only for single scalar keys. `ntp_server` (a list) is handled separately because
# it needs add/remove reconciliation.
_PEMETAAN_TUNGGAL = {
    "hostname": ("hostname", lambda v: {"nama": v}),
    "banner_masuk": ("banner", lambda v: {"teks": v}),
    # `zona_waktu` is stored as IANA ('Asia/Jakarta') but the device needs Cisco
    # syntax ('WIB 7 0'). Translated HERE with the same map used by the renderer and
    # parser, so there is a single source.
    "zona_waktu": ("zona_waktu", lambda v: {"zona": katalog.zona_cisco(v)}),
    "snmp_lokasi": ("snmp_lokasi", lambda v: {"teks": v}),
    "snmp_kontak": ("snmp_kontak", lambda v: {"teks": v}),
}

# LIST keys: need add/remove reconciliation, not a single replacement value.
# {key: (add_command, remove_command)}
_PEMETAAN_DAFTAR = {
    "ntp_server": ("ntp_tambah", "ntp_hapus"),
    "dns_server": ("dns_tambah", "dns_hapus"),
    "logging_server": ("logging_tambah", "logging_hapus"),
}

# BOOLEAN keys with a command in one direction only: turning on sends the command,
# turning off sends NOTHING. {key: command_when_intent_True}
_PEMETAAN_BOOL = {
    # Intent `layanan_http_mati=True` -> send `no ip http server` and
    # `no ip http secure-server`. The reverse (intent False, HTTP may be on) has no
    # command on purpose: enabling a stopped service widens the attack surface and
    # must not be automatic even if intent allows it.
    "layanan_http_mati": "http_mati",
}

KUNCI_DIDUKUNG = frozenset(
    list(_PEMETAAN_TUNGGAL) + list(_PEMETAAN_DAFTAR) + list(_PEMETAAN_BOOL))

# The four keys deliberately NOT supported, with a reason per key. Used by
# `main.py` to explain why a drift is detected but never fixed automatically.
ALASAN_TIDAK_DIDUKUNG = {
    "domain": "Mengubah nama domain memengaruhi kunci RSA (prasyarat SSH). "
              "Diklasifikasikan wajib_manusia -- pagar otomasi akan selalu "
              "menolaknya, jadi perintah otomatisnya tidak dibuat.",
    "exec_timeout_menit": "Mengubahnya bisa memutus SESI ADMIN yang sedang "
                          "berlangsung, termasuk sesi orang yang menerapkannya. "
                          "Wajib manusia.",
    "vty_izin": "`access-class` yang salah bisa MENGUNCI SELURUH akses "
                "manajemen ke perangkat, termasuk jalur NSM sendiri. "
                "Wajib manusia, tanpa perkecualian.",
    "ssh_saja": "Mematikan telnet bisa memutus sesi telnet yang sedang aktif. "
                "Tindakannya benar, tapi waktunya harus dipilih manusia.",
}

BATAS_TUNGGU_VERIFIKASI_DETIK = 1200  # enough for one poll_konfig cycle (900 s) plus slack


def cari_kandidat(db):
    """[(device, kunci, temuan_drift), ...] -- HANYA temuan `status='beda'`
    pada kunci yang ada di `KUNCI_DIDUKUNG`. Temuan `tidak_terbaca`/
    `hilang` TIDAK disertakan: itu berarti potret tidak punya baris untuk
    dibandingkan sama sekali, dan mengirim 'perbaikan' untuk sesuatu yang
    keadaannya sendiri tidak jelas lebih berisiko daripada diam."""
    hasil = []
    for d in db.execute(
        select(Device).where(
            Device.platform.in_(
                dialek_perangkat.platform_dengan("firewall", "acl")),
            Device.aktif == 1)
    ).scalars().all():
        r = drift_svc.bandingkan(db, d.id)
        if not (r.get("didukung") and r.get("punya_intent") and r.get("punya_potret")):
            continue
        for h in r.get("nilai", []):
            if h["status"] == drift_svc.BEDA and h["kunci"] in KUNCI_DIDUKUNG:
                hasil.append((d, h["kunci"], h))
    return hasil


def _kirim_satu(db, device, perintah_id, nilai, oleh):
    return kirim_perintah.kirim(db, device.id, perintah_id, nilai,
                                oleh=oleh, sungguhan=True)


def _perbaiki_tunggal(db, device, kunci, temuan, oleh):
    perintah_id, build_value = _PEMETAAN_TUNGGAL[kunci]
    hasil = _kirim_satu(db, device, perintah_id, build_value(temuan["intended"]), oleh)
    return [hasil]


def _perbaiki_daftar(db, device, kunci, temuan, oleh):
    """List reconciliation: add what is missing, remove what is extra. NOT delete-all
    then re-add, which would open a brief window with no service for addresses that
    were already correct.
    Shared by `ntp_server`, `dns_server` and `logging_server`, which are all address
    lists reconciled the same way.
    """
    add_id, delete_id = _PEMETAAN_DAFTAR[kunci]
    intended = set(temuan["intended"] or [])
    observed = set(temuan["observed"] or [])
    hasil = []
    for alamat in sorted(intended - observed):
        hasil.append(_kirim_satu(db, device, add_id, {"alamat": alamat}, oleh))
    for alamat in sorted(observed - intended):
        hasil.append(_kirim_satu(db, device, delete_id, {"alamat": alamat}, oleh))
    return hasil


def _perbaiki_bool(db, device, kunci, temuan, oleh):
    """One-direction boolean key: send the command ONLY when intent is True.
    Intent False means "may be on", not "turn it on"; enabling a stopped service
    widens the attack surface and must not be automatic. So the opposite direction
    returns an EMPTY list, which `coba_perbaiki()` treats as "nothing to send", not
    as a failure.
    """
    if not temuan["intended"]:
        return []
    return [_kirim_satu(db, device, _PEMETAAN_BOOL[kunci], {}, oleh)]


def coba_perbaiki(db, device, kunci, temuan, oleh="pemulih_konfig", sekarang=None):
    """Phase 1: guardrail gate (ONE decision for the whole key, even if `ntp_server`
    means several commands) -> save observed BEFORE -> send via catalog.
    No verification; see `verifikasi_tertunda()`.
    """
    # Blast radius is computed HERE and passed to the guardrail, not recomputed inside
    # it. If the computation fails, that must be visible as a failure rather than
    # silently becoming "radius zero" elsewhere, which would OPEN the riskiest action.
    try:
        import ketergantungan
        _downstream = ketergantungan.hilir(db, device.id) or []
        _bukti = {"dampak_hilir_jumlah": len(_downstream), "dampak_hilir_pasti": True}
    except Exception:
        _bukti = {"dampak_hilir_jumlah": None, "dampak_hilir_pasti": False}
    kep = pagar_otomasi.putuskan(db, device.id, KATEGORI_PAGAR, KUNCI_PAGAR,
                                 oleh=oleh, sekarang=sekarang, bukti=_bukti)
    if not kep.izin:
        return kep

    rollback.simpan_state_sebelum(db, kep.tindakan_id, {
        "device_id": device.id, "kunci": kunci,
        "observed_sebelum": temuan["observed"], "intended": temuan["intended"],
    })

    try:
        if kunci in _PEMETAAN_DAFTAR:
            result_all = _perbaiki_daftar(db, device, kunci, temuan, oleh)
        elif kunci in _PEMETAAN_BOOL:
            result_all = _perbaiki_bool(db, device, kunci, temuan, oleh)
        elif kunci in _PEMETAAN_TUNGGAL:
            result_all = _perbaiki_tunggal(db, device, kunci, temuan, oleh)
        else:
            # Cannot happen via the normal path (`cari_kandidat()` filters to
            # `KUNCI_DIDUKUNG`), but is recorded as a readable failure instead of an
            # unexplained KeyError; the caller is an unattended poller job.
            pagar_otomasi.record_verification(
                db, kep.tindakan_id, False,
                bukti="Kunci '%s' tidak punya perintah katalog. %s"
                     % (kunci, ALASAN_TIDAK_DIDUKUNG.get(kunci, "")))
            return kep
    except kirim_perintah.Ditolak as e:
        pagar_otomasi.record_verification(
            db, kep.tindakan_id, False, bukti="Ditolak penjaga: %s" % e)
        return kep

    all_sent = all(h.get("terkirim") for h in result_all)
    if not all_sent:
        galat = "; ".join(str(h.get("galat")) for h in result_all if not h.get("terkirim"))
        pagar_otomasi.record_verification(
            db, kep.tindakan_id, False, bukti="Gagal terkirim: %s" % galat)
    # If everything was sent: NOT recorded as success here. That is only proven when a
    # NEW snapshot confirms it (phase 2).
    return kep


def _batalkan(db, device_id, oleh):
    """Real rollback through the existing kirim_perintah mechanism: `batalkan_sekarang`
    for GNS3 nodes (the only path that runs in this lab); `batalkan` (let
    `reload in N` expire) for physical devices, if any.
    """
    from models import Device as _D
    d = db.get(_D, device_id)
    action = "batalkan_sekarang" if d and d.gns3_node else "batalkan"
    hasil = kirim_perintah.putuskan(db, device_id, action, sungguhan=True)
    if action == "batalkan":
        # `batalkan` for non-GNS3 devices does nothing actively: it deliberately lets the
        # installed `reload in N` expire (see `kirim_perintah.putuskan()`). That is not a
        # rollback failure.
        return hasil
    if not hasil.get("terkirim", True):
        raise RuntimeError("gagal memulihkan lewat API GNS3: %s" % hasil)
    return hasil


def verifikasi_tertunda(db, sekarang=None, batas_detik=BATAS_TUNGGU_VERIFIKASI_DETIK):
    """Phase 2: re-compare (stage 2) the keys whose action is still pending.
    Match now -> success. Still different AND past the deadline -> FAILURE, and
    `_batalkan()` is triggered automatically.
    """
    sekarang = sekarang or datetime.now()
    pending = db.execute(
        select(PagarTindakan).where(
            PagarTindakan.kategori == KATEGORI_PAGAR,
            PagarTindakan.kunci == KUNCI_PAGAR,
            PagarTindakan.keputusan == pagar_otomasi.IZIN,
            PagarTindakan.status_verifikasi.is_(None),
        )
    ).scalars().all()

    verified = 0
    for t in pending:
        if t.device_id is None:
            continue
        state = rollback.ambil_state_sebelum(db, t.id)
        kunci = state["kunci"] if state else None
        r = drift_svc.bandingkan(db, t.device_id)
        if not (r.get("didukung") and r.get("punya_potret")):
            continue
        finding_now = next(
            (h for h in r.get("nilai", []) if h["kunci"] == kunci), None)

        if finding_now is not None and finding_now["status"] == drift_svc.COCOK:
            pagar_otomasi.record_verification(
                db, t.id, True, bukti="Potret baru membuktikan '%s' sudah sesuai." % kunci)
            rollback.simpan_state_sesudah(db, t.id, {"observed_sesudah": finding_now["observed"]})
            verified += 1
            continue

        if sekarang - t.waktu >= timedelta(seconds=batas_detik):
            observed_now = finding_now["observed"] if finding_now else None
            try:
                bukti_rollback = _batalkan(db, t.device_id, oleh="pemulih_konfig")
                rollback_ok = True
            except Exception as e:
                bukti_rollback = {"galat": str(e)}
                rollback_ok = False
            bukti = ("Masih '%s' sesudah %d detik (observed=%r). Rollback %s."
                    % (kunci, batas_detik, observed_now,
                       "berhasil dipicu" if rollback_ok else "GAGAL dipicu"))
            pagar_otomasi.record_verification(db, t.id, False, bukti=bukti)
            t.rollback_dilakukan = rollback_ok
            rollback.simpan_state_sesudah(db, t.id, {
                "observed_sesudah_gagal": observed_now, "rollback": bukti_rollback})
            # Most important case in the whole recovery system when rollback_ok is False: the
            # automatic fix failed AND the way back failed. The summary says so explicitly
            # instead of using the generic failure sentence.
            ringkas = ("Konfigurasi '%s' dicoba diperbaiki otomatis" % kunci
                      if rollback_ok else
                      "Konfigurasi '%s' GAGAL diperbaiki DAN rollback OTOMATIS-NYA JUGA GAGAL" % kunci)
            _eskalasi(db, t.device_id, ringkas, bukti)
            verified += 1
    return verified


def _eskalasi(db, device_id, ringkas, alasan):
    try:
        import notifikasi_berjenjang
        notifikasi_berjenjang.eskalasi_segera(db, device_id, ringkas, alasan)
    except Exception as e:
        print("[pemulih:konfig] gagal eskalasi notifikasi (dilewati): %s" % e)

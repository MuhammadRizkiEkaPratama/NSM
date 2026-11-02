"""Poller entry point for the four recoverers: ONE function per stage, called by
scheduled jobs in `poller.py`.

Each function checks its own kill switch first and returns immediately if it is
off. The check is repeated every round (not once at poller start) so a `.env`
change applies without a restart, same as `poller.poll_auto_ban()`.

Four separate kill switches (`config.get_pemulih_*_aktif()`), all OFF by
default. Even with one on, an empty `PAGAR_DAFTAR_PUTIH` makes gate 2 refuse
every action: two layered switches for anything that touches a device, by design.
"""
import config
import ketergantungan
from pemulih import gns3, layanan, interface, konfig


def _saring_hulu(db, nama_tahap, kandidat, ambil_device):
    """Drop candidates that are down BECAUSE an upstream device is also down.

    This prevents an "automation storm": when R1 died it took R2, SW-B and LDAP down
    with it. Without this filter one root cause would trigger four repair attempts,
    three of them bound to fail because the path is cut, then three escalation
    emails, then use up the rate limit and open the breaker for devices that have no
    problem of their own.

    Held-back candidates are printed, not silently dropped, so "why did NSM not fix
    this" stays traceable.
    """
    try:
        forwarded, withheld = ketergantungan.filter_candidate(
            db, kandidat, ambil_device)
    except Exception as e:
        # This filter is a safety, not a prerequisite. If it fails itself (e.g.
        # `device_link` is broken), the recoverer does not stop: the guardrail
        # (`pagar_otomasi.putuskan`) still applies in full underneath.
        print("[pemulih:%s] saringan hulu gagal, diteruskan tanpa saringan: %s"
             % (nama_tahap, str(e)[:120]))
        return list(kandidat)

    for t in withheld:
        print("[pemulih:%s] DITAHAN %s -- %s"
             % (nama_tahap, t["device"].name, t["alasan"]))
    return forwarded


def _untuk_tiap_kandidat(nama_tahap, kandidat, coba_satu):
    """Run `coba_satu(*kandidat_item)` for each candidate; one error does not stop the
    others (same pattern as `poll_auto_ban()`).
    """
    for item in kandidat:
        try:
            coba_satu(*item if isinstance(item, tuple) else (item,))
        except Exception as e:
            print("[pemulih:%s] satu kandidat gagal (dicoba lagi putaran "
                 "berikutnya kalau masih jadi kandidat): %s"
                 % (nama_tahap, str(e)[:160]))


def jalankan_gns3(db):
    """Stage 4: dead GNS3 node -> restart. Two phases: new candidates are tried, and
    old pending actions are rechecked.
    """
    if not config.get_pemulih_gns3_aktif():
        return
    _untuk_tiap_kandidat("gns3",
                        _saring_hulu(db, "gns3", gns3.cari_kandidat(db), lambda d: d),
                        lambda d: gns3.coba_pulihkan(db, d, oleh="poller_pemulih_gns3"))
    gns3.verifikasi_tertunda(db)


def run_service(db):
    """Stage 5: dead service -> restart (see `pemulih/layanan.py`). Its kill switch is
    checked separately, so the order of enabling does not depend on the order of
    code here.
    """
    if not config.get_pemulih_layanan_aktif():
        return
    _untuk_tiap_kandidat("layanan",
                        _saring_hulu(db, "layanan", layanan.cari_kandidat(db), lambda it: it[0]),
                        lambda d, s: layanan.coba_restart(db, d, s, oleh="poller_pemulih_layanan"))
    layanan.verifikasi_tertunda(db)


def run_interface(db):
    """Stage 6: interface down although intent says up -> bring it up. Verification is
    synchronous inside `coba_nyalakan()`, so there is no separate "pending" function
    (unlike GNS3/service/config; see `pemulih/interface.py`).
    """
    if not config.get_pemulih_interface_aktif():
        return
    _untuk_tiap_kandidat("interface",
                        _saring_hulu(db, "interface", interface.cari_kandidat(db), lambda it: it[0]),
                        lambda d, nm: interface.coba_nyalakan(db, d, nm, oleh="poller_pemulih_interface"))


def run_config(db):
    """Stage 7: drifted config -> send a fix (keys in `KUNCI_DIDUKUNG`). Two phases,
    with automatic rollback if verification fails (stage 8).
    """
    if not config.get_pemulih_konfig_aktif():
        return
    _untuk_tiap_kandidat("konfig",
                        _saring_hulu(db, "konfig", konfig.cari_kandidat(db), lambda it: it[0]),
                        lambda d, kc, tm: konfig.coba_perbaiki(db, d, kc, tm, oleh="poller_pemulih_konfig"))
    konfig.verifikasi_tertunda(db)


def jalankan_semua(db):
    """Called by ONE poller job; all four stages are checked every round, each with its
    own kill switch. One job rather than four because they are cheap (a query plus a
    guardrail decision) and the rising-risk order (GNS3 first, config last) is easier
    to guarantee in one place than through the registration order of four separate
    APScheduler jobs.

    One failing stage must not take down the other three: a technical error in one
    candidate or stage is logged and skipped, same as `poll_auto_ban()`.
    """
    for nama, function in (("gns3", jalankan_gns3), ("layanan", run_service),
                        ("interface", run_interface), ("konfig", run_config)):
        try:
            function(db)
        except Exception as e:
            print("[pemulih:%s] lewati putaran: %s" % (nama, str(e)[:160]))

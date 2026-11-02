from datetime import datetime, timedelta
import penyangga
from database import SessionLocal
from models import (Flow, NamaAlamat, OrangLdap)
from config import (get_ldap_url, get_ldap_basis)
import notifikasi
import notifikasi_berjenjang
import rollup
import report_service
from connectors import (ldapdir)


def poll_person():
    """Copy names and titles from the LDAP directory to `orang_ldap`.
    Runs rarely (30 min). People removed from the directory are NOT deleted here,
    on purpose: their `transfer_berkas` history stays, and it is most useful after
    someone leaves; deleting would turn old rows into bare uids. Pruning unused
    rows is the job of `pangkas_data.py`.
    """
    url = get_ldap_url()
    if not url:
        return

    try:
        person = ldapdir.baca(url, get_ldap_basis())
    except Exception as e:
        # A dead directory is not a reason to empty the copy. The page keeps using the
        # old copy: history must not change because another server is down.
        print(f"[ldap] gagal membaca direktori ({str(e)[:80]})")
        return

    db, _buffered = penyangga.sesi()
    try:
        waktu = datetime.now()
        baru = 0
        for o in person:
            line = db.query(OrangLdap).filter(OrangLdap.uid == o["uid"]).first()
            if line is None:
                line = OrangLdap(uid=o["uid"])
                db.add(line)
                baru += 1
            line.nama = o["nama"]
            line.jabatan = o["jabatan"]
            line.email = o["email"]
            line.grup = o["grup"]
            line.diperbarui = waktu
        db.commit()
        if baru:
            print(f"[ldap] {len(person)} orang dibaca ({baru} baru)")
    except Exception as e:
        db.rollback()
        print(f"[ldap] gagal menyimpan ({e})")
    finally:
        db.close()


def poll_rollup():
    """Summarize `status_logs` per hour so history survives pruning.
    Raw rows are pruned at 35 days; the rollup is never pruned (one row replaces
    about 720 raw rows). Only READS `status_logs` and WRITES `status_rollup_jam`.
    The current hour is never touched: a half-finished figure stored permanently
    looks like fact.
    """
    db, _buffered = penyangga.sesi()
    try:
        written, sampai = rollup.bangun(db)
        db.commit()
        if written:
            print(f"[rollup] {written} jam diringkas, sampai {sampai}")
    except Exception as e:
        db.rollback()
        print(f"[rollup] gagal ({e})")
    finally:
        db.close()


def poll_nama_alamat(batas=8):
    """Look up DNS names for addresses seen in network conversations.
    A separate job because a reverse lookup takes 4.5-9 s here (failures are
    slowest, waiting for the timeout) and the Traffic page refreshes every 30 s with
    up to 25 addresses. Limited to eight addresses per round: not urgent, and
    hanging lookups would delay the next round. Only queries the resolver this
    machine already uses, not the lab network.
    """
    import socket

    db, _buffered = penyangga.sesi()
    try:
        # Addresses that actually appeared in conversations in the last 7 days.
        since = datetime.now() - timedelta(days=7)
        visible = {r[0] for r in db.query(Flow.ip_lawan)
                    .filter(Flow.waktu >= since).distinct().all() if r[0]}
        if not visible:
            return

        # Normalize `::ffff:x.x.x.x` first, as the page does, so one machine is not
        # stored and looked up twice.
        visible = {report_service._ip_bersih(ip) for ip in visible}

        already = {n.ip: n for n in db.query(NamaAlamat)
                 .filter(NamaAlamat.ip.in_(visible)).all()}

        # Never looked up first, then oldest stale. Names can move, so old results are
        # rechecked, but less often for those already found.
        queue = [ip for ip in visible if ip not in already]
        limit_retry = datetime.now() - timedelta(days=7)
        limit_retry_fail = datetime.now() - timedelta(days=1)
        for ip, n in already.items():
            tenggat = limit_retry if n.ditemukan else limit_retry_fail
            if n.diperiksa is None or n.diperiksa < tenggat:
                queue.append(ip)

        for ip in queue[:batas]:
            nama = None
            try:
                nama = socket.gethostbyaddr(ip)[0]
            except Exception:
                # An address without PTR is normal, not an error. Store it as "not found";
                # otherwise it would be looked up again every round, and those are the most
                # expensive lookups.
                pass

            line = already.get(ip)
            if line is None:
                line = NamaAlamat(ip=ip)
                db.add(line)
            line.nama = nama
            line.ditemukan = 1 if nama else 0
            line.diperiksa = datetime.now()

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[dns] gagal ({e})")
    finally:
        db.close()


def poll_notifikasi():
    """Hand device outages to Java for delivery to subscribers.
    All active devices are checked; Java decides recipients from per-user
    subscriptions. A separate job, not part of the ping round, so a slow mail
    server only delays this job.
    """
    db, _buffered = penyangga.sesi()
    try:
        hasil = notifikasi.proses_antrean(db)
        if hasil.get("terkirim") or hasil.get("gagal") or hasil.get("dilewati"):
            print(f"[notif] terkirim={hasil['terkirim']} "
                  f"dilewati={hasil['dilewati']} gagal={hasil['gagal']}")
    except Exception as e:
        # A failing notification must not bring down the poller process
        print(f"[notif] kesalahan tak terduga: {e}")
    finally:
        db.close()


def poll_notifikasi_berjenjang():
    """Tiered notification evaluator: a SEPARATE path from `poll_notifikasi`, running
    alongside it (see `notifikasi_berjenjang.py` and docs/design/TIERED-NOTIFICATIONS.md).
    Its own job because it runs far less often (5 min vs 30 s) and recomputes from
    status_logs instead of reading the device_events queue.
    """
    db, _buffered = penyangga.sesi()
    try:
        hasil = notifikasi_berjenjang.proses(db)
        if hasil.get("mati") or hasil.get("pulih") or hasil.get("flap"):
            print(f"[notif-jenjang] mati={hasil.get('mati', 0)} "
                  f"pulih={hasil.get('pulih', 0)} flap={hasil.get('flap', 0)}")
    except Exception as e:
        # Like poll_notifikasi: a notification failure must not take down the poller.
        print(f"[notif-jenjang] kesalahan tak terduga: {e}")
    finally:
        db.close()


def poll_correlation():
    """Group symptoms with a common root into one incident.
    Only READS recorded events and builds the `insiden` table; touches no device and
    sends nothing.
    """
    db = SessionLocal()
    try:
        import korelasi
        h = korelasi.proses(db)
        if h.get("insiden_baru") or h.get("ditutup"):
            print("[korelasi] mati=%d insiden_baru=%d ditutup=%d"
                  % (h.get("mati", 0), h.get("insiden_baru", 0),
                     h.get("ditutup", 0)))
    except Exception as e:
        # A correlation failure must not take down the poller; monitoring matters more
        # than grouping.
        print("[korelasi] kesalahan tak terduga: %s" % str(e)[:200])
    finally:
        db.close()


def poll_baseline():
    """Fold new latency samples into the per-hour-of-week baseline.
    Only READS `status_logs` and writes its own summary table. Runs every 5 minutes:
    it computes habits, which do not change in ten seconds.
    """
    db = SessionLocal()
    try:
        import baseline
        h = baseline.perbarui_latency(db)
        if h.get("dibaca"):
            print("[baseline] %d sampel -> %d slot"
                  % (h["dibaca"], h["slot_disentuh"]))
    except Exception as e:
        print("[baseline] kesalahan tak terduga: %s" % str(e)[:200])
    finally:
        db.close()


def poll_pola_log():
    """Mine syslog message patterns with Drain3.
    Returns immediately if drain3 is not installed, and says so only once, not every
    round.
    """
    db = SessionLocal()
    try:
        import pola_log
        if not pola_log.tersedia():
            if not getattr(poll_pola_log, "_sudah_bilang", False):
                print("[pola-log] drain3 belum terpasang; penambangan pola "
                      "dilewati (pasang dengan: pip install drain3)")
                poll_pola_log._sudah_bilang = True
            return
        h = pola_log.tambang(db)
        if h.get("dibaca"):
            print("[pola-log] %d pesan -> %d templat, %d pola BARU"
                  % (h["dibaca"], h.get("templat", 0),
                     len(h.get("pola_baru") or [])))
        for pb in (h.get("pola_baru") or [])[:3]:
            # A never-seen pattern is the most valuable syslog signal; it belongs in the
            # poller log as-is.
            print("[pola-log] BARU: %s" % (pb.get("templat") or "")[:110])
    except Exception as e:
        print("[pola-log] kesalahan tak terduga: %s" % str(e)[:200])
    finally:
        db.close()


def poll_agen_soc():
    """SOC agent: triage, evidence, narrative, proposals.
    Does NOT touch devices. Proposals go through `pagar_otomasi.putuskan()` like the
    recovery jobs, and in the default 'usul' mode it asks with `simulasi=True` so it
    does not use up the real recovery rate limit.
    Returns immediately if `AGEN_SOC_AKTIF` is off (default); re-read every round so
    a `.env` change applies without a restart.
    """
    db = SessionLocal()
    try:
        import agen_soc
        h = agen_soc.proses(db)
        if h.get("ditangani"):
            print("[agen-soc] %d insiden ditangani (mode %s)"
                  % (h["ditangani"], h.get("mode")))
    except Exception as e:
        print("[agen-soc] kesalahan tak terduga: %s" % str(e)[:200])
    finally:
        db.close()


def poll_notifikasi_insiden():
    """One email per INCIDENT, not per event.
    A separate job from `poll_notifikasi` so a slow mail server on one path cannot
    hold up the other. Returns immediately if `NOTIF_PER_INSIDEN=0` (default);
    re-read every round so a `.env` change applies without a restart.
    """
    db = SessionLocal()
    try:
        import notifikasi_insiden
        h = notifikasi_insiden.proses(db)
        if h.get("baru") or h.get("naik") or h.get("pulih") or h.get("gagal"):
            print("[notif-insiden] baru=%d naik=%d pulih=%d gagal=%d"
                  % (h.get("baru", 0), h.get("naik", 0),
                     h.get("pulih", 0), h.get("gagal", 0)))
    except Exception as e:
        # A notification failure must not take down the poller; monitoring matters more
        # than notifying.
        print("[notif-insiden] kesalahan tak terduga: %s" % str(e)[:200])
    finally:
        db.close()

from datetime import datetime

import dialek_perangkat
import penyangga
import report_service
from config import get_auto_ban_enabled, get_auto_ban_maks_per_putaran
from connectors import firewall as fw
from connectors import ufwlog
from connectors.ssh import SshConnector
from database import SessionLocal
from models import (
    Device,
    FirewallAturan,
    FirewallSnapshot,
    IdentitasPerangkat,
    PenolakanAcl,
)

from ._inti import kerjakan_bersamaan, posisi_log, sasaran, status_terakhir

# ufw block log path (Ubuntu default). A constant rather than `services.log_akses`,
# because ufw denials belong to the machine, not to a single service.
JALUR_UFW_LOG = "/var/log/ufw.log"


def baca_firewall_device(tugas):
    """Network work only: read firewall rules and the ufw block log over ONE SSH session.
    ufw.log is read with the same account as `ufw status`; if it lacks the `adm`
    group the read fails and is reported per device without discarding the rules.
    No database access (runs in a worker thread).
    """
    import paramiko
    s, position_ufw = tugas

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    sambung = {"timeout": 20, "allow_agent": False, "look_for_keys": False}
    if s.ssh_key_path:
        client.connect(s.ip_address, username=s.username,
                       key_filename=s.ssh_key_path, **sambung)
    else:
        client.connect(s.ip_address, username=s.username,
                       password=s.password, **sambung)
    try:
        keadaan = fw.ambil(client)
        try:
            entri, posisi_baru, rotated, _n, exists = ufwlog.ambil(
                client, JALUR_UFW_LOG, position_ufw)
            if not exists:
                ufw_result = {"galat": "berkas ufw.log belum ada di perangkat",
                            "entri": [], "posisi_baru": position_ufw}
            else:
                ufw_result = {"galat": None, "entri": entri,
                            "posisi_baru": posisi_baru}
        except Exception as e:
            # A ufw.log read failure must not discard the rules already read; an account
            # without the `adm` group always fails here.
            ufw_result = {"galat": str(e), "entri": [], "posisi_baru": position_ufw}
        return keadaan, ufw_result
    finally:
        client.close()


def save_firewall(db, s, keadaan):
    """Store firewall state only when it changed.
    Returns (snapshot, changed); snapshot is None when nothing changed. Rules rarely
    change, and storing every read would bury the one row that matters.
    """
    last = (db.query(FirewallSnapshot)
                .filter(FirewallSnapshot.device_id == s.id)
                .order_by(FirewallSnapshot.id.desc())
                .first())
    if last is not None and last.sidik == keadaan["sidik"]:
        return None, False

    snap = FirewallSnapshot(
        device_id=s.id,
        waktu=datetime.now(),
        sidik=keadaan["sidik"],
        aktif=keadaan["aktif"],
        kebijakan_masuk=keadaan.get("kebijakan_masuk"),
        kebijakan_keluar=keadaan.get("kebijakan_keluar"),
        kebijakan_rute=keadaan.get("kebijakan_rute"),
        logging=keadaan.get("logging"),
        jumlah_aturan=len(keadaan.get("aturan") or []),
        teks=keadaan.get("teks"),
    )
    db.add(snap)
    db.flush()  # so snap.id exists before the rules are written

    for a in keadaan.get("aturan") or []:
        db.add(FirewallAturan(snapshot_id=snap.id, device_id=s.id, **a))

    return snap, last is not None


def poll_kedaluwarsa_ban():
    """Lift temporary bans (stage 3) that have expired. Never raises.
    If the `ban_aktif` table is missing or anything fails, it is skipped silently:
    maintenance must not break monitoring.
    """
    try:
        import penjaga_aksi
    except Exception:
        return
    db = SessionLocal()
    try:
        dibuka = penjaga_aksi.kedaluwarsa(db)
        if dibuka:
            print(f"[ban] {dibuka} ban kedaluwarsa dibuka")
    except Exception as e:
        print(f"[ban] lewati kedaluwarsa: {str(e)[:120]}")
    finally:
        db.close()


def poll_auto_ban():
    """Auto-ban without a click: blocks `blokir-otomatis` candidates itself.
    OFF by default (`config.get_auto_ban_enabled()`), re-checked every round so a
    `.env` change applies next round. ufw only, deliberately not router ACLs, which
    affect a whole site and still need a human click.
    Safeguards:
    1. the kill switch above
    2. mandatory rate limit (`get_auto_ban_maks_per_putaran`); leftovers retry next round
    3. `penjaga_aksi.blokir()` has its own allowlist check at execution time
    4. idempotent per (ip, device_id)
    5. one failed candidate does not stop the others
    6. notifications are sent by `blokir()`
    """
    if not get_auto_ban_enabled():
        return
    try:
        import penjaga_aksi
    except Exception:
        return
    db = SessionLocal()
    try:
        rejection = report_service.penolakan_acl(db)
        pembobolan = report_service.deteksi_pembobolan(db)
        plan = report_service.rencana_penjagaan(db, rejection, pembobolan)
        kandidat = [k for k in plan.get("kandidat", [])
                   if k.get("aksi_saran") == "blokir-otomatis"
                   and k.get("target_ids")]
        if not kandidat:
            return

        maks = get_auto_ban_maks_per_putaran()
        diproses = diblokir = 0
        for k in kandidat:
            if diproses >= maks:
                print("[auto-ban] batas laju %d/putaran tercapai, %d "
                      "kandidat ditunda ke putaran berikutnya"
                      % (maks, len(kandidat) - diproses))
                break
            diproses += 1
            asal = k["asal"]
            device_id = k["target_ids"][0]
            try:
                r = penjaga_aksi.blokir(db, asal, device_id=device_id,
                                        alasan=k.get("alasan", ""),
                                        pola=k.get("pola", "auto"),
                                        oleh="auto")
            except penjaga_aksi.DitolakPengaman as e:
                print("[auto-ban] %s ditolak pengaman: %s" % (asal, e))
                continue
            except Exception as e:
                print("[auto-ban] %s galat (dicoba lagi putaran berikutnya): "
                     "%s" % (asal, str(e)[:120]))
                continue
            if not r.get("ok"):
                print("[auto-ban] %s gagal: %s" % (asal, r.get("error")))
            elif not r.get("sudah_diban"):
                diblokir += 1
                print("[auto-ban] %s -> device %s diblokir otomatis (%s)"
                     % (asal, device_id, k.get("pola")))
        if diblokir:
            print("[auto-ban] %d IP diblokir otomatis putaran ini" % diblokir)
    except Exception as e:
        print("[auto-ban] lewati putaran: %s" % str(e)[:120])
    finally:
        db.close()


def poll_penolakan_acl():
    """Read ACL denials from the Cisco router and store the ones not seen before.
    Only an ACL ending in `deny ip any any log` shows WHO was denied.
    `show logging` returns the whole buffer on every call and has no read position,
    so rows are deduplicated by a per-line fingerprint instead.
    """
    from connectors import aclog as _aclog

    db, _buffered = penyangga.sesi()
    try:
        choice = []
        for d in db.query(Device).all():
            if (d.aktif == 0
                    or dialek_perangkat.ambil(d.platform).firewall != "acl"):
                continue
            choice.append(sasaran(d))
        if not choice:
            return

        def baca(t):
            c = SshConnector(t.ip_address, platform=t.platform,
                             username=t.username, password=t.password,
                             key_path=t.ssh_key_path)
            # `include` filters ON the router: pulling the whole buffer over the 0.11 Mbit/s
            # inter-site link just to discard most of it would be wasteful.
            return c.jalankan_perintah(
                "show logging | include IPACCESSLOG", timeout=30)

        already = {x[0] for x in db.query(PenolakanAcl.sidik).all()}
        baru = 0
        for t, teks, galat in kerjakan_bersamaan(choice, baca):
            if galat:
                print(f"   [acl] {t.name}: gagal dibaca ({str(galat)[:60]})")
                continue
            for x in _aclog.urai(teks):
                sd = _aclog.sidik(x)
                if sd in already:
                    continue
                already.add(sd)
                db.add(PenolakanAcl(
                    device_id=t.id, waktu=datetime.now(),
                    cap_router=x["cap_router"], acl=x["acl"], aksi=x["aksi"],
                    proto=x["proto"], dari=x["dari"], port_dari=x["port_dari"],
                    ke=x["ke"], port_ke=x["port_ke"], jumlah=x["jumlah"],
                    sidik=sd, baris=x["baris"]))
                baru += 1
                print("   [acl] %s: %s %s %s:%s -> %s:%s x%s"
                      % (t.name, x["aksi"], x["proto"], x["dari"],
                         x["port_dari"], x["ke"], x["port_ke"], x["jumlah"]))
        if baru:
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"   [acl] job gagal: {e}")
    finally:
        db.close()


def poll_firewall_lokal():
    """Read Windows Firewall on the laptop that runs NSM.
    A separate job from `poll_firewall()` on purpose: that function returns early
    when no Linux device is active, which would cancel this read too.
    Not over SSH; see `connectors/winfw.py` (`netsh` is far faster than the cmdlets).
    """
    from connectors import winfw as _wfw

    db, _buffered = penyangga.sesi()
    try:
        laptop = (db.query(Device)
                  .filter(Device.platform.in_(
                      dialek_perangkat.platform_dengan("firewall", "netsh")),
                          Device.aktif != 0)
                  .first())
        if laptop is None:
            return

        try:
            keadaan = _wfw.baca_keadaan()
        except Exception as e:
            print(f"[fw ] {laptop.name}: gagal membaca Windows Firewall ({e})")
            return

        try:
            snap, changed = save_firewall(db, laptop, keadaan)
            db.commit()
            if snap is not None and changed:
                print(f"[fw ] {laptop.name}: ATURAN FIREWALL BERUBAH "
                      f"({snap.jumlah_aturan} aturan, aktif={snap.aktif})")
            elif snap is not None:
                print(f"[fw ] {laptop.name}: {snap.jumlah_aturan} aturan "
                      f"(pembacaan pertama)")
        except Exception as e:
            db.rollback()
            print(f"[fw ] {laptop.name}: gagal menyimpan ({e})")

        p = posisi_log(db, laptop.id, _wfw.JALUR_LOG)
        try:
            entri, posisi_baru, rotated, exists = _wfw.baca_log_potongan(p.posisi or 0)
            if not exists:
                # No file yet is not "zero denials": LogBlocked may be off in the Windows
                # profile and must be enabled manually (Set-NetFirewallProfile).
                # See `connectors/winfw.py`.
                return
            already = {x[0] for x in db.query(PenolakanAcl.sidik)
                     .filter(PenolakanAcl.device_id == laptop.id).all()
                     if x[0] is not None}
            baru = 0
            for x in entri:
                if x["sidik"] in already:
                    continue
                db.add(PenolakanAcl(
                    device_id=laptop.id, waktu=datetime.now(),
                    cap_router=x["cap_router"], acl=x["acl"],
                    aksi=x["aksi"], proto=x["proto"], dari=x["dari"],
                    port_dari=x["port_dari"], ke=x["ke"], port_ke=x["port_ke"],
                    jumlah=x["jumlah"], sidik=x["sidik"], baris=x["baris"]))
                already.add(x["sidik"])
                baru += 1
            p.posisi = posisi_baru
            p.diperbarui = datetime.now()
            db.commit()
            if baru:
                print(f"[winfw] {laptop.name}: {baru} paket ditolak baru")
            elif rotated:
                print(f"[winfw] {laptop.name}: berkas log berputar ulang, "
                      f"posisi disetel ulang")
        except Exception as e:
            db.rollback()
            print(f"[winfw] {laptop.name}: gagal membaca log ({e})")
    finally:
        db.close()


def poll_firewall():
    """Read firewall rules and the ufw block log from SSH-reachable Linux devices.
    Three phases: select (DB), read (network, concurrent), save (DB).
    Failures are reported, not swallowed: an unreadable firewall and an empty one
    both look blank on screen but mean opposite things.
    ufw.log rows go to `penolakan_acl` with `acl='ufw'`, so the Firewall page shows
    both router and ufw denials.
    """
    db, _buffered = penyangga.sesi()
    try:
        # Hostname -> device_id map from `identitas_perangkat`.
        # Required: `.104` (nsm-data) receives syslog through a shared socket, so its
        # ufw.log also holds messages written by `.103`; without this map those lines
        # would be attributed to `.104`.
        hostname_map = {}
        for row in (db.query(IdentitasPerangkat)
                    .filter(IdentitasPerangkat.jenis == "hostname").all()):
            hostname_map[row.nilai] = row.device_id

        choice = []
        for d in db.query(Device).all():
            if (d.aktif == 0
                    or dialek_perangkat.ambil(d.platform).firewall != "ufw"):
                continue
            if not (d.username and (d.password or d.ssh_key_path)):
                continue
            last = status_terakhir(db, d.id)
            if last is not None and last.event_type == "DOWN":
                continue
            p = posisi_log(db, d.id, JALUR_UFW_LOG)
            choice.append((sasaran(d), p.posisi or 0))
        if not choice:
            return

        hasil = kerjakan_bersamaan(choice, baca_firewall_device)

        # Fingerprints already stored, read once up front. The same line can be seen via
        # two SSH sessions (original on .103, copy on .104); this keeps it stored once.
        already = {x[0] for x in db.query(PenolakanAcl.sidik).all()
                 if x[0] is not None}

        for (s, _pos), (_, package, galat) in zip(choice, hasil):
            if galat is not None:
                print(f"[fw ] {s.name}: gagal membaca ({str(galat)[:90]})")
                continue
            keadaan, ufw_result = package
            try:
                snap, changed = save_firewall(db, s, keadaan)
                db.commit()
                if snap is not None and changed:
                    print(f"[fw ] {s.name}: ATURAN FIREWALL BERUBAH "
                          f"({snap.jumlah_aturan} aturan, masuk="
                          f"{snap.kebijakan_masuk}, aktif={snap.aktif})")
                elif snap is not None:
                    print(f"[fw ] {s.name}: {snap.jumlah_aturan} aturan "
                          f"(pembacaan pertama)")
            except Exception as e:
                db.rollback()
                print(f"[fw ] {s.name}: gagal menyimpan ({e})")

            if ufw_result.get("galat"):
                print(f"[ufw] {s.name}: gagal membaca ufw.log "
                      f"({str(ufw_result['galat'])[:90]})")
                continue
            entri = ufw_result.get("entri") or []
            try:
                baru = 0
                for x in entri:
                    if x["sidik"] in already:
                        # Already stored via another device's copy. The read position still advances.
                        continue
                    # Attribute to the device whose HOSTNAME wrote the line. Unknown hostnames are
                    # skipped rather than guessed.
                    owner = hostname_map.get(x["_hostname"])
                    if owner is None:
                        continue
                    db.add(PenolakanAcl(
                        device_id=owner, waktu=x["_waktu_baca"],
                        cap_router=x["cap_router"], acl=x["acl"],
                        aksi=x["aksi"], proto=x["proto"], dari=x["dari"],
                        port_dari=x["port_dari"], ke=x["ke"],
                        port_ke=x["port_ke"], jumlah=x["jumlah"],
                        sidik=x["sidik"], baris=x["baris"]))
                    already.add(x["sidik"])
                    baru += 1
                p = posisi_log(db, s.id, JALUR_UFW_LOG)
                p.posisi = ufw_result["posisi_baru"]
                p.diperbarui = datetime.now()
                db.commit()
                if baru:
                    print(f"[ufw] {s.name}: {baru} paket ditolak baru")
            except Exception as e:
                db.rollback()
                print(f"[ufw] {s.name}: gagal menyimpan ({e})")
    finally:
        db.close()

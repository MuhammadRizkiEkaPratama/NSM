"""REAL FAULT INJECTION #2: stop the real `smbd`, proving the service recovery.

Counterpart of `injeksi_r1.py` for the SERVICE recovery. Procedure, pitfalls and
fixed rules are the same; see docs/FAULT-INJECTION.md.

RUN ON `nsm-app`, NOT ON THE MONITORING MACHINE, and that is not optional. The
service recovery logs into devices over SSH using `device.ssh_key_path`, which
holds `/home/nsmapp/.ssh/nsm_vm`, a path on `nsm-app`. That key is not on the
monitoring machine and MUST NOT be copied there. Unlike the R1 injection (which
goes through the GNS3 controller HTTP API and can run from anywhere), this one
only makes sense on the nsm-app VM itself. A side benefit: it tests the
environment actually in use, not a copy of it.

WHY `smbd` ON `.105`, NOT `apache2` ON `.103`. Four services have a
`unit_systemd` and can therefore be recovered automatically: apache2 + ecanteen
on device 6 (.103), smbd + auditd on device 12 (.105).

  * device 6 HAS NOTIFICATION SUBSCRIPTIONS: stopping it would send real email to
    other people's addresses. Device 12 has none.
  * `apache2`/`ecanteen` serve E-Canteen; `smbd` only shares files, and nobody
    uses it at 2 AM.
  * `auditd` is DELIBERATELY NOT chosen even though it is the least risky as a
    service: stopping it stops recording who deleted/copied files, and that
    record is one of the things the project is meant to show. Losing audit data
    to test the recovery is the wrong trade.

HOW TO STOP IT, AND WHY VIA ANOTHER ACCOUNT. The account used by the recovery
(`nsmro`) may deliberately run only one file, `/usr/local/sbin/nsm-restart-layanan`,
and that wrapper accepts only `restart` and `status`. No `stop`. Verified:

    User nsmro may run the following commands on file-server:
        (root) NOPASSWD: /usr/local/sbin/nsm-restart-layanan

So the recovery CANNOT stop any service, only bring it back. That is the design,
and a good one. Consequently, to inject the fault this script must use a separate
admin account, which is clearly NOT the path the automation uses.

Run ON nsm-app:
    cd /home/nsmapp/NSM/backend && ./venv/bin/python -u injeksi_layanan.py
"""
import sys
import time
from datetime import datetime

import paramiko
from sqlalchemy import select, desc, text

import config
import database
import models
import pagar_otomasi
from pemulih import layanan as pemulih_layanan

SERVICE_ID = 9  # SMB shared folder
DEVICE_ID = 12  # SMB file server (Site A)
UNIT = "smbd"
ADMIN_USER = "labadmin"
ADMIN_SANDI = config.get_uji_105_sandi()
if not ADMIN_SANDI:
    raise SystemExit(
        "UJI_105_PASS kosong di backend/.env -- isi dulu.\n"
        "Skrip ini mematikan smbd di 192.168.56.105 sungguhan, jadi ia\n"
        "berhenti daripada menebak sandi.")

lolos = 0
gagal = 0


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print("  LOLOS  %s" % nama)
    else:
        gagal += 1
        print("  GAGAL  %s %s" % (nama, ket))


def judul(t):
    print()
    print("=" * 70)
    print(t)
    print("=" * 70)


def admin(ip, perintah, timeout=30):
    """Run a command on the target device as admin (NOT nsmro).

    Used ONLY to inject the fault and for the safety net. This path is deliberately
    different from the automation path, so there is no doubt that whatever recovers
    later is the recovery, not this script.
    """
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(ip, username=ADMIN_USER, password=ADMIN_SANDI,
                  timeout=timeout, allow_agent=False, look_for_keys=False)
        i, o, e = c.exec_command("sudo -S -p '' " + perintah, timeout=timeout)
        i.write(ADMIN_SANDI + "\n")
        i.flush()
        code = o.channel.recv_exit_status()
        return code, o.read().decode(errors="replace").strip(), \
            e.read().decode(errors="replace").strip()
    finally:
        c.close()


def katalog_manusia():
    from sot import katalog as _k
    return _k.RISIKO_MANUSIA


def katalog_aman():
    from sot import katalog as _k
    return _k.RISIKO_AMAN


def segarkan(db):
    """End the transaction so the next query sees the poller's writes.

    MySQL REPEATABLE READ: `expire_all()` is not enough. See the long note in
    `injeksi_r1.py`; same lesson.
    """
    db.commit()


def status_resmi(db, service_id=SERVICE_ID):
    ev = db.execute(
        select(models.ServiceEvent)
        .where(models.ServiceEvent.service_id == service_id)
        .order_by(desc(models.ServiceEvent.timestamp),
                  desc(models.ServiceEvent.id)).limit(1)).scalars().first()
    return (ev.event_type, ev.timestamp) if ev else (None, None)


def tunggu_resmi(db, mau, batas_detik):
    start = time.time()
    while time.time() - start < batas_detik:
        segarkan(db)
        tipe, ts = status_resmi(db)
        if tipe == mau:
            return True, int(time.time() - start), ts
        time.sleep(10)
    segarkan(db)
    tipe, ts = status_resmi(db)
    return False, int(time.time() - start), ts


db = database.SessionLocal()
patch_asli = {}

try:
    judul("0. DASAR -- keadaan sebelum apa pun disentuh")
    dev = db.get(models.Device, DEVICE_ID)
    svc = db.get(models.Service, SERVICE_ID)
    print("  device : #%s %s (%s)" % (dev.id, dev.name, dev.ip_address))
    print("  layanan: #%s %s  unit=%s" % (svc.id, svc.nama, svc.unit_systemd))
    benar("layanan sasaran punya unit_systemd (syarat pemulih)",
          svc.unit_systemd == UNIT, "-> %r" % svc.unit_systemd)

    code, keluar, _ = admin(dev.ip_address, "systemctl is-active %s" % UNIT)
    print("  %s di perangkat: %s" % (UNIT, keluar))
    benar("%s menyala sebelum uji dimulai" % UNIT, keluar == "active",
          "-> %r" % keluar)

    tipe, ts = status_resmi(db)
    print("  vonis resmi NSM: %s @ %s" % (tipe, ts))
    benar("NSM melihat layanan ini HIDUP sebelum uji", tipe == "UP",
          "-> %r" % tipe)

    n = db.execute(text("select count(*) from nsm_auth.notif_langganan "
                        "where device_id = :d"), {"d": DEVICE_ID}).scalar()
    print("  langganan notifikasi untuk device ini: %s" % n)
    benar("device ini TIDAK berlangganan email -> tidak ada alarm palsu keluar",
          n == 0, "-> %s langganan" % n)

    judul("1. GERBANG MANA YANG SEBENARNYA MENOLAK -- dan ini berbeda dari Tahap 4")
    # Read this as is: for `layanan_restart`, gate 1 (risk classification) fires FIRST,
    # so the allow-list and working-hours gates are NEVER reached. Saying this refusal
    # is "because the allow-list is empty" would be wrong, and wrong in a reassuring
    # way: people would think filling in `.env` is enough to enable it.
    print("  Sekarang %s. Jam kerja %s. Daftar putih %r."
          % (datetime.now().strftime("%H:%M"), config.get_pagar_jam_kerja(),
             config.get_pagar_daftar_putih()))
    level, alasan_risiko = pagar_otomasi._risiko(pemulih_layanan.KATEGORI,
                                                 pemulih_layanan.KUNCI)
    print("  klasifikasi risiko %s = %s" % (pemulih_layanan.KUNCI, level))
    benar("`layanan_restart` diklasifikasikan wajib_manusia",
          level == katalog_manusia(), "-> %r" % level)

    k1 = pagar_otomasi.putuskan(db, DEVICE_ID, pemulih_layanan.KATEGORI,
                                pemulih_layanan.KUNCI, oleh="injeksi_layanan")
    print("  ->", k1.alasan[:170])
    benar("ditolak, dan yang menolak adalah GERBANG 1 (bukan daftar putih)",
          k1.izin is False and "wajib_manusia" in k1.alasan,
          "-> %s" % k1.alasan[:110])

    patch_asli["putih"] = config.get_pagar_daftar_putih
    config.get_pagar_daftar_putih = lambda: {pemulih_layanan.KUNCI}
    k2 = pagar_otomasi.putuskan(db, DEVICE_ID, pemulih_layanan.KATEGORI,
                                pemulih_layanan.KUNCI, oleh="injeksi_layanan")
    print("  ->", k2.alasan[:170])
    benar("mengisi daftar putih TIDAK menolongnya -- gerbang 1 tidak bisa "
          "dibuka lewat .env", k2.izin is False and "wajib_manusia" in k2.alasan,
          "-> %s" % k2.alasan[:110])

    judul("2. SUNTIK GANGGUAN -- matikan %s sungguhan" % UNIT)
    print("  lewat akun admin (%s), BUKAN lewat jalur otomasi" % ADMIN_USER)
    code, keluar, galat = admin(dev.ip_address, "systemctl stop %s" % UNIT)
    print("  kode=%s %s" % (code, (keluar or galat)[:120]))
    time.sleep(3)
    _k, aktif, _e = admin(dev.ip_address, "systemctl is-active %s" % UNIT)
    print("  %s sekarang: %s" % (UNIT, aktif))
    benar("%s benar-benar MATI di perangkat" % UNIT, aktif != "active",
          "-> %r" % aktif)

    judul("3. POLLER HARUS MELIHATNYA SENDIRI")
    print("  ambang %s pemeriksaan gagal beruntun, tiap %s detik -- maks 5 menit"
          % (config.get_service_down_threshold(), config.get_service_interval()))
    ok, detik, ts = tunggu_resmi(db, "DOWN", 300)
    print("  -> setelah %ds, vonis resmi @ %s" % (detik, ts))
    benar("NSM mendeteksi layanan MATI tanpa diberi tahu", ok,
          "-> belum ada peristiwa DOWN setelah %ds" % detik)

    judul("4a. GERBANG 1 HARUS MENOLAK WALAU SEMUA GERBANG LAIN DIBUKA")
    # This is the core of the service recovery. `layanan_restart` is classified
    # `wajib_manusia` (human required) in `pagar_otomasi.RISIKO_PEMULIH`, and gate 1
    # CANNOT be opened through `.env`, only by editing code. So the service recovery
    # is designed to NEVER run by itself, however loose the operator's settings.
    patch_asli["jam"] = config.get_pagar_jam_kerja
    config.get_pagar_jam_kerja = lambda: (0, 24)
    patch_asli["aktif"] = config.get_pemulih_layanan_aktif
    config.get_pemulih_layanan_aktif = lambda: True

    segarkan(db)
    kandidat = pemulih_layanan.cari_kandidat(db)
    print("  kandidat: %r" % [(s.id, s.nama, s.unit_systemd)
                              for _d, s in kandidat])
    benar("layanan ini dikenali sebagai kandidat pemulihan",
          any(s.id == SERVICE_ID for _d, s in kandidat))

    kep = pemulih_layanan.coba_restart(db, dev, svc, oleh="injeksi_layanan")
    print("  keputusan pagar: izin=%s" % kep.izin)
    print("  ->", kep.alasan[:200])
    benar("SEMUA gerbang lain dibuka, gerbang 1 TETAP menolak",
          kep.izin is False, "-> %s" % kep.alasan[:120])
    benar("  alasannya menyebut wajib_manusia",
          "wajib_manusia" in kep.alasan, "-> %s" % kep.alasan[:90])
    benar("penolakannya tetap tercatat di pagar_tindakan",
          kep.tindakan_id is not None)

    time.sleep(4)
    _k, aktif_a, _e = admin(dev.ip_address, "systemctl is-active %s" % UNIT)
    print("  %s sesudah pemulih dipanggil: %s" % (UNIT, aktif_a))
    benar("layanan TETAP MATI -- tidak ada yang disentuh otomatis",
          aktif_a != "active", "-> %r" % aktif_a)

    judul("4b. KALAU MANUSIA MEMUTUSKAN LAIN, JALURNYA HARUS BENAR-BENAR JALAN")
    # Gate 1 can only be changed by editing code, so the classification is patched
    # TEMPORARILY here to imitate a deliberate operator decision lowering the risk.
    # Without this round, the file would only prove the recovery does nothing, and a
    # TOTALLY BROKEN recovery would pass such a test too.
    patch_asli["risiko"] = pagar_otomasi.RISIKO_PEMULIH[pemulih_layanan.KUNCI]
    pagar_otomasi.RISIKO_PEMULIH[pemulih_layanan.KUNCI] = (
        katalog_aman(), "DITAMBAL SEMENTARA oleh injeksi_layanan.py")

    kep2 = pemulih_layanan.coba_restart(db, dev, svc, oleh="injeksi_layanan")
    print("  keputusan pagar: izin=%s tindakan_id=%s" % (kep2.izin, kep2.tindakan_id))
    print("  ->", kep2.alasan[:180])
    benar("sesudah risikonya diturunkan -> DIIZINKAN", kep2.izin is True,
          "-> %s" % kep2.alasan[:120])

    time.sleep(6)
    _k, aktif2, _e = admin(dev.ip_address, "systemctl is-active %s" % UNIT)
    print("  %s setelah pemulih dipanggil: %s" % (UNIT, aktif2))
    benar("pemulih benar-benar MENGHIDUPKAN kembali layanannya "
          "(lewat pembungkus sudo, sebagai nsmro)",
          aktif2 == "active", "-> %r" % aktif2)
    kep = kep2

    judul("5. VERIFIKASI TERTUNDA")
    print("  menunggu NSM menyatakan layanan UP lagi -- maks 5 menit...")
    ok2, detik2, ts2 = tunggu_resmi(db, "UP", 300)
    print("  -> setelah %ds, vonis resmi @ %s" % (detik2, ts2))
    benar("layanan PULIH dan NSM melihatnya sendiri", ok2,
          "-> masih mati setelah %ds" % detik2)

    segarkan(db)
    pemulih_layanan.verifikasi_tertunda(db)
    segarkan(db)
    t = db.get(models.PagarTindakan, kep.tindakan_id)
    print("  tindakan #%s: status_verifikasi=%r"
          % (kep.tindakan_id, t.status_verifikasi if t else None))
    benar("hasil pemulihan diverifikasi dan dicatat BERHASIL",
          t is not None and t.status_verifikasi is True,
          "-> %r" % (t.status_verifikasi if t else None))

finally:
    judul("PEMBERSIHAN -- kembalikan semuanya seperti semula")
    peta = {"putih": "get_pagar_daftar_putih",
            "jam": "get_pagar_jam_kerja",
            "aktif": "get_pemulih_layanan_aktif"}
    for nama, fn in patch_asli.items():
        if nama == "risiko":
            # The risk classification is restored to `wajib_manusia`. If this line does not
            # run, the service recovery would remain allowed to run automatically after this
            # script ends, exactly the state the whole gate design tries to prevent.
            pagar_otomasi.RISIKO_PEMULIH[pemulih_layanan.KUNCI] = fn
            continue
        setattr(config, peta[nama], fn)
    print("  klasifikasi risiko %s: %r"
          % (pemulih_layanan.KUNCI,
             pagar_otomasi.RISIKO_PEMULIH[pemulih_layanan.KUNCI][0]))
    print("  setelan pagar dikembalikan: daftar_putih=%r jam=%r layanan_aktif=%r"
          % (config.get_pagar_daftar_putih(), config.get_pagar_jam_kerja(),
             config.get_pemulih_layanan_aktif()))

    try:
        _k, aktif_akhir, _e = admin(db.get(models.Device, DEVICE_ID).ip_address,
                                    "systemctl is-active %s" % UNIT)
        if aktif_akhir != "active":
            print("  %s masih %s -- dinyalakan paksa sebagai jaring pengaman"
                  % (UNIT, aktif_akhir))
            admin(db.get(models.Device, DEVICE_ID).ip_address,
                  "systemctl start %s" % UNIT)
            time.sleep(5)
            _k, aktif_akhir, _e = admin(
                db.get(models.Device, DEVICE_ID).ip_address,
                "systemctl is-active %s" % UNIT)
        print("  status akhir %s: %s" % (UNIT, aktif_akhir))
    except Exception as e:
        print("  [PERINGATAN] gagal memeriksa/menyalakan %s: %s" % (UNIT, e))

    print()
    print("=" * 70)
    print("HASIL INJEKSI LAYANAN: %d lolos, %d gagal" % (lolos, gagal))
    print("=" * 70)
    db.close()
    sys.exit(1 if gagal else 0)

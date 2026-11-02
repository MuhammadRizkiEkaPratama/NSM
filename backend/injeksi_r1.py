"""REAL FAULT INJECTION: stop the R1 node in GNS3 and prove the automatic recovery
brings it back.

This is NOT a test: nothing is mocked. Real database, real GNS3 controller, real
router, real poller running on nsm-app.

Why this exists despite hundreds of tests: all recovery tests use a fake `_panggil`
and none ever touch GNS3. Tests prove the LOGIC is right; only a real fault proves
the CHAIN is connected: poller detects -> gate decides -> API called -> router
really comes back -> verification recorded.

How it is stopped, and why not the old way: via `POST /nodes/{id}/stop` on the
controller API, equivalent to pulling the power and fully reversible. No
configuration command is used. The earlier incident that killed R1 permanently
(docs/POSTMORTEM-R1.md) was caused by `reload in N` typed into the router CLI, a
completely different code path not touched here.

Two things are changed temporarily and restored in `finally`:

1. Notification subscriptions of devices 4 and 5 are removed. Stopping R1 cuts R1
   and the LDAP server behind it, and both subscribe to email for real addresses.
   A "Site A router DOWN" alert for an outage the script itself caused is a false
   alarm, and false alarms are what this project tries to eliminate.
2. The gates are loosened by MONKEYPATCH, not by writing `.env`. If this script
   dies midway, `.env` stays clean and automation stays off; there is no way for
   it to leave the system with "automation on and nobody knows".
"""
import sys
import time
from datetime import datetime

from sqlalchemy import text, select, desc

import config
import database
import models
import pagar_otomasi
from connectors import gns3_pemulihan
from pemulih import gns3 as pemulih_gns3

NODE = "R1"
DEVICE_ID = 5
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
    print("=" * 74)
    print(t)
    print("=" * 74)


def status_node(nama=NODE):
    pr = gns3_pemulihan.panggil("GET", "/projects") or []
    p = next((x for x in pr if x.get("status") == "opened"), pr[0] if pr else None)
    if not p:
        return None, None, None
    nodes = gns3_pemulihan.panggil("GET", "/projects/%s/nodes" % p["project_id"]) or []
    n = next((x for x in nodes if x.get("name") == nama), None)
    return p["project_id"], (n or {}).get("node_id"), (n or {}).get("status")


def status_db(db, device_id=DEVICE_ID):
    log = db.execute(
        select(models.StatusLog).where(models.StatusLog.device_id == device_id)
        .order_by(desc(models.StatusLog.timestamp)).limit(1)).scalars().first()
    if not log:
        return None, None
    return bool(log.is_reachable), log.timestamp


def status_resmi(db, device_id=DEVICE_ID):
    """OFFICIAL NSM verdict: the latest `device_events` row.

    Unlike `status_db()`, which reads raw pings. This is what the recovery uses: the
    poller writes DOWN here only after consecutive failures reach the threshold
    (default 5), so a single dropped packet can no longer trigger a reboot.
    """
    ev = db.execute(
        select(models.DeviceEvent).where(models.DeviceEvent.device_id == device_id)
        .order_by(desc(models.DeviceEvent.timestamp),
                  desc(models.DeviceEvent.id)).limit(1)).scalars().first()
    if ev is None:
        return None, None
    return ev.event_type, ev.timestamp


def tunggu_resmi(db, device_id, mau_tipe, batas_detik):
    start = time.time()
    while time.time() - start < batas_detik:
        segarkan(db)
        tipe, ts = status_resmi(db, device_id)
        if tipe == mau_tipe:
            return True, int(time.time() - start), ts
        time.sleep(10)
    segarkan(db)
    tipe, ts = status_resmi(db, device_id)
    return False, int(time.time() - start), ts


def segarkan(db):
    """End the running transaction so the next query sees NEW data.

    This is REQUIRED, not excess caution. MySQL defaults to REPEATABLE READ: once a
    transaction reads, it keeps one snapshot and keeps seeing it even after other
    sessions commit new rows. `expire_all()` does not help; it only drops Python's
    object cache and then asks the same snapshot again.

    Found the first time this injection ran: the topology map already showed R1 red,
    but this script insisted R1 was alive for a full five minutes. Neither the poller
    nor the data was wrong; the script was reading the past.
    """
    db.commit()


def tunggu_db(db, device_id, mau_hidup, batas_detik):
    """Wait for the REAL poller on nsm-app to record the expected state."""
    start = time.time()
    while time.time() - start < batas_detik:
        segarkan(db)
        alive, ts = status_db(db, device_id)
        if alive is mau_hidup:
            return True, int(time.time() - start), ts
        time.sleep(10)
    segarkan(db)
    alive, ts = status_db(db, device_id)
    return False, int(time.time() - start), ts


db = database.SessionLocal()
langganan_dicabut = []
patch_asli = {}

try:
    judul("0. DASAR -- keadaan sebelum apa pun disentuh")
    pid, nid, st = status_node()
    print("  GNS3: proyek=%s node=%s status=%s" % (pid, nid, st))
    benar("node R1 ditemukan di controller GNS3", nid is not None)
    benar("R1 menyala sebelum uji dimulai", st == "started", "-> %s" % st)
    alive, ts = status_db(db)
    print("  NSM : status_logs terbaru R1 = %s @ %s"
          % ("HIDUP" if alive else "MATI", ts))
    benar("NSM melihat R1 HIDUP sebelum uji dimulai", alive is True)
    try:
        db.execute(text("select count(*) from pagar_tindakan")).scalar()
        benar("tabel pagar_tindakan ada di basis data hidup", True)
    except Exception as e:
        benar("tabel pagar_tindakan ada di basis data hidup", False, "-> %s" % e)
        raise SystemExit(1)

    judul("1. REDAM ALARM PALSU -- cabut langganan email sementara")
    baris = db.execute(text(
        "select id, device_id, username from nsm_auth.notif_langganan "
        "where device_id in (4,5)")).fetchall()
    langganan_dicabut = [tuple(x) for x in baris]
    print("  akan dicabut sementara: %r" % (langganan_dicabut,))
    for i, dev, user in langganan_dicabut:
        db.execute(text("delete from nsm_auth.notif_langganan where id=:i"), {"i": i})
    db.commit()
    sisa = db.execute(text(
        "select count(*) from nsm_auth.notif_langganan "
        "where device_id in (4,5)")).scalar()
    benar("langganan device 4 & 5 dicabut (tidak ada email keluar)", sisa == 0)

    judul("2. GERBANG PAGAR HARUS MENOLAK DULU -- bukti remnya bekerja")
    print("  Sekarang %s. Jam kerja %s. Daftar putih %r."
          % (datetime.now().strftime("%H:%M"), config.get_pagar_jam_kerja(),
             config.get_pagar_daftar_putih()))
    k1 = pagar_otomasi.putuskan(db, DEVICE_ID, "pemulih", "gns3_restart",
                                oleh="injeksi_r1")
    print("  ->", k1.alasan[:150])
    benar("daftar putih KOSONG -> ditolak", k1.izin is False)
    benar("alasannya menyebut daftar putih, bukan yang lain",
          "daftar putih" in k1.alasan.lower(), "-> %s" % k1.alasan[:90])

    patch_asli["putih"] = config.get_pagar_daftar_putih
    config.get_pagar_daftar_putih = lambda: {"gns3_restart"}
    k2 = pagar_otomasi.putuskan(db, DEVICE_ID, "pemulih", "gns3_restart",
                                oleh="injeksi_r1")
    print("  ->", k2.alasan[:150])
    benar("sudah di daftar putih TAPI di luar jam kerja -> tetap ditolak",
          k2.izin is False)
    benar("alasannya menyebut jam kerja", "jam" in k2.alasan.lower(),
          "-> %s" % k2.alasan[:90])

    judul("3. SUNTIK GANGGUAN -- matikan R1 lewat API GNS3")
    print("  POST /projects/%s/nodes/%s/stop" % (pid, nid))
    gns3_pemulihan.panggil("POST", "/projects/%s/nodes/%s/stop" % (pid, nid))
    time.sleep(5)
    _, _, st2 = status_node()
    print("  status node sekarang: %s" % st2)
    benar("R1 benar-benar MATI di controller", st2 == "stopped", "-> %s" % st2)

    judul("4. POLLER SUNGGUHAN DI nsm-app HARUS MELIHATNYA SENDIRI")
    print("  (a) ping mentah gagal -- maks 3 menit")
    ok_a, detik_a, ts_a = tunggu_db(db, DEVICE_ID, False, 180)
    print("      -> setelah %ds, status_logs terbaru @ %s" % (detik_a, ts_a))
    benar("ping ke R1 mulai gagal", ok_a)

    print("  (b) NSM RESMI menyatakan DOWN (butuh 5x gagal beruntun) -- maks 5 menit")
    ok, detik, ts = tunggu_resmi(db, DEVICE_ID, "DOWN", 300)
    print("      -> setelah %ds, device_events terbaru @ %s" % (detik, ts))
    benar("NSM mendeteksi R1 MATI tanpa diberi tahu (deteksi nyata)", ok,
          "-> belum ada peristiwa DOWN setelah %ds" % detik)
    benar("vonis resmi datang SETELAH ping pertama gagal, bukan bersamaan "
          "(ambang gagal beruntun benar-benar dipakai)", detik >= detik_a)

    judul("5. KETERGANTUNGAN -- yang di balik R1 tidak boleh dialarmi sendiri")
    try:
        import ketergantungan as K
        import report_service as rs
        segarkan(db)
        g = K.graf(db)
        for dev_id, nama in [(5, "Router Lokasi A (R1)"), (9, "Router Lokasi B"),
                             (10, "Switch Lokasi B"), (4, "Direktori LDAP"),
                             (8, "Switch Lokasi A")]:
            h = K.penyebab_hulu(db, dev_id, g=g)
            print("  #%-3s %-22s %-14s hulu_mati=%s" % (
                dev_id, nama, h["status"],
                [m["nama"] for m in h["hulu_mati"]]))
        benar("R1 dinilai sebagai AKAR (tidak ada hulu yang mati)",
              K.penyebab_hulu(db, 5, g=g)["status"] == K.TIDAK_ADA)
        benar("R2 dinilai AKIBAT dari R1",
              any(m["id"] == 5 for m in K.penyebab_hulu(db, 9, g=g)["hulu_mati"]))
        benar("SW-B dinilai AKIBAT dari R1",
              any(m["id"] == 5 for m in K.penyebab_hulu(db, 10, g=g)["hulu_mati"]))

        # The panel people actually read, not just the function behind it.
        d = rs.diagnosis(db)
        sebab = [x["nama"] for x in d["daftar"] if x.get("vonis") == "sebab"]
        akibat = [x["nama"] for x in d["daftar"] if x.get("vonis") == "akibat"]
        print("  panel diagnosis -> SEBAB=%r" % sebab)
        print("                    AKIBAT=%r" % akibat)
        benar("panel menyebut Router Lokasi A sebagai SEBAB",
              any("Router Lokasi A" in s for s in sebab))
        benar("panel TIDAK lagi menyebut Router Lokasi B sebagai sebab",
              not any("Router Lokasi B" in s for s in sebab),
              "-> %r" % sebab)
        benar("panel TIDAK lagi menyebut Switch Lokasi B sebagai sebab",
              not any("Switch Lokasi B" in s for s in sebab),
              "-> %r" % sebab)
    except Exception as e:
        import traceback
        traceback.print_exc()
        benar("evaluasi ketergantungan berjalan", False, "-> %s" % e)

    judul("6. PEMULIH TAHAP 4 -- gerbang dibuka, pemulihan dijalankan")
    patch_asli["jam"] = config.get_pagar_jam_kerja
    # (0, 24) not (0, 23): the upper bound is EXCLUSIVE, so 23 would EXCLUDE hour 23:xx,
    # and this injection runs at 23:23.
    config.get_pagar_jam_kerja = lambda: (0, 24)
    patch_asli["aktif"] = config.get_pemulih_gns3_aktif
    config.get_pemulih_gns3_aktif = lambda: True

    segarkan(db)  # see the note in segarkan(): without this, `cari_kandidat`
                   # would read the old snapshot and conclude R1 is still alive.
    kandidat = pemulih_gns3.cari_kandidat(db)
    print("  kandidat MENTAH (sebelum saringan hulu): %r"
          % [(d.id, d.name, d.gns3_node) for d in kandidat])
    benar("R1 dikenali sebagai kandidat pemulihan",
          any(d.id == DEVICE_ID for d in kandidat))

    # The raw list above also includes R2 and SW-B, and that is NOT a defect:
    # `cari_kandidat()` only answers "who is down". Deciding who is WORTH acting on is
    # `orkestrasi._saring_hulu()`, one layer above, and that layer is what the poller
    # uses. Calling `cari_kandidat()` directly, as in the line above, bypasses that
    # filter; if this part were not tested too, the injection record would read as if
    # the recovery were about to reboot two healthy routers.
    from pemulih import orkestrasi as _ork
    tersaring = _ork._saring_hulu(db, "gns3", kandidat, lambda d: d)
    print("  kandidat SESUDAH saringan hulu: %r"
          % [(d.id, d.name) for d in tersaring])
    benar("R1 (akar) LOLOS saringan hulu",
          any(d.id == DEVICE_ID for d in tersaring))
    benar("R2 DITAHAN -- matinya akibat R1, bukan masalahnya sendiri",
          all(d.id != 9 for d in tersaring),
          "-> %r" % [(d.id, d.name) for d in tersaring])
    benar("SW-B DITAHAN -- sama, akibat R1",
          all(d.id != 10 for d in tersaring),
          "-> %r" % [(d.id, d.name) for d in tersaring])
    kandidat = tersaring

    dev = db.get(models.Device, DEVICE_ID)
    kep = pemulih_gns3.coba_pulihkan(db, dev, oleh="injeksi_r1")
    print("  keputusan pagar: izin=%s tindakan_id=%s" % (kep.izin, kep.tindakan_id))
    print("  ->", kep.alasan[:180])
    benar("semua enam gerbang dilewati -> DIIZINKAN", kep.izin is True,
          "-> %s" % kep.alasan[:120])
    benar("tindakannya tercatat di pagar_tindakan", kep.tindakan_id is not None)

    time.sleep(8)
    _, _, st3 = status_node()
    print("  status node setelah pemulih dipanggil: %s" % st3)
    benar("pemulih benar-benar menyalakan kembali R1 di controller",
          st3 in ("started", "starting"), "-> %s" % st3)

    judul("7. FASE 2 -- verifikasi tertunda setelah router selesai boot")
    print("  menunggu R1 dinyatakan UP lagi oleh NSM (maks 6 menit)...")
    ok2, detik2, ts2 = tunggu_resmi(db, DEVICE_ID, "UP", 360)
    print("  -> setelah %ds, status terbaru @ %s" % (detik2, ts2))
    benar("R1 PULIH dan NSM melihatnya sendiri", ok2,
          "-> masih mati setelah %ds" % detik2)

    segarkan(db)
    pemulih_gns3.verifikasi_tertunda(db)
    segarkan(db)
    t = db.get(models.PagarTindakan, kep.tindakan_id)
    print("  tindakan #%s: status_verifikasi=%r" % (
        kep.tindakan_id, t.status_verifikasi if t else None))
    benar("hasil pemulihan diverifikasi dan dicatat sebagai BERHASIL",
          t is not None and t.status_verifikasi is True,
          "-> %r" % (t.status_verifikasi if t else None))

finally:
    judul("PEMBERSIHAN -- kembalikan semuanya seperti semula")
    peta = {"putih": "get_pagar_daftar_putih",
            "jam": "get_pagar_jam_kerja",
            "aktif": "get_pemulih_gns3_aktif"}
    for nama, fn in patch_asli.items():
        setattr(config, peta[nama], fn)
    print("  setelan pagar dikembalikan: daftar_putih=%r jam=%r gns3_aktif=%r"
          % (config.get_pagar_daftar_putih(), config.get_pagar_jam_kerja(),
             config.get_pemulih_gns3_aktif()))

    try:
        pid_akhir, nid_akhir, st_akhir = status_node()
        if st_akhir != "started" and nid_akhir:
            print("  R1 masih %s -- dinyalakan paksa sebagai jaring pengaman"
                  % st_akhir)
            gns3_pemulihan.panggil(
                "POST", "/projects/%s/nodes/%s/start" % (pid_akhir, nid_akhir))
            time.sleep(10)
            _, _, st_akhir = status_node()
        print("  status akhir R1 di GNS3: %s" % st_akhir)
    except Exception as e:
        print("  [PERINGATAN] gagal memeriksa/menyalakan R1: %s" % e)

    for i, dev_id, user in langganan_dicabut:
        try:
            db.execute(text(
                "insert into nsm_auth.notif_langganan (id, device_id, username) "
                "values (:i,:d,:u)"), {"i": i, "d": dev_id, "u": user})
        except Exception as e:
            print("  [PERINGATAN] gagal memulihkan langganan %r: %s"
                  % ((i, dev_id, user), e))
    db.commit()
    balik = db.execute(text(
        "select id, device_id, username from nsm_auth.notif_langganan "
        "order by id")).fetchall()
    print("  langganan notifikasi sekarang: %r" % [tuple(x) for x in balik])

    print()
    print("=" * 74)
    print("HASIL INJEKSI: %d lolos, %d gagal" % (lolos, gagal))
    print("=" * 74)
    db.close()
    sys.exit(1 if gagal else 0)

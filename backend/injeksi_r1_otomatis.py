"""Shut down R1, then stay hands-off and let nsm-app recover it on its own.

Unlike `injeksi_r1.py`, which relaxes the safety gate via monkeypatch and calls
`pemulih_gns3.coba_pulihkan()` itself, this script performs a single action
(stopping R1) and then only watches the primary lab instance's database.

Proof of who recovered R1: the poller-driven recovery records itself as
`poller_pemulih_gns3` in `PagarTindakan.diminta_oleh` (see `pemulih/orkestrasi.py`).
That audit row is the evidence, not R1 coming back up, which could have other causes.

Timing: the poller checks recovery every `PEMULIH_INTERVAL` seconds (currently 120),
and R1 must first cross the consecutive-failure threshold to be recorded DOWN in
`device_events` (the GNS3 recovery reads `device_events`, not raw pings). A few
minutes is normal.

Safeguards:
  * Email subscriptions for devices 4 and 5 are suspended and restored in `finally`;
    stopping R1 also cuts LDAP behind it, and alerting on a self-inflicted outage
    is a false alarm.
  * If nsm-app does not recover R1 within the timeout, the script powers it back on
    before exiting.
  * No `.env` changes and no monkeypatching, so an aborted run leaves no settings changed.

Run: venv\\Scripts\\python.exe injeksi_r1_otomatis.py
"""
import sys
import time
from datetime import datetime, timedelta

from sqlalchemy import text, select, desc

import config
import database
import models
from connectors import gns3_pemulihan

NODE = "R1"
DEVICE_ID = 5
# Wait limit. The recovery poller runs every 120 s and R1 must first cross the
# consecutive-failure threshold, so 10 minutes allows several attempts without
# hanging indefinitely.
BATAS_TUNGGU_DETIK = 600
JEDA_PERIKSA = 15

langganan_dicabut = []


def judul(t):
    print()
    print("=" * 74)
    print(t)
    print("=" * 74)


def keadaan_nsmapp():
    """Read the automation settings in effect on nsm-app, over SSH.

    The laptop and nsm-app have separate `.env` files, and only the nsm-app poller
    decides whether R1 gets recovered, so local `config` cannot answer this.
    """
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("192.168.56.156", username="nsmapp",
              password=config.get_nsmapp_sandi(), timeout=20)
    try:
        i, o, e = c.exec_command(
            "cd /home/nsmapp/NSM/backend && ./venv/bin/python -c \""
            "import config as k;"
            "print('gns3=%s' % k.get_pemulih_gns3_aktif());"
            "print('putih=%s' % ','.join(sorted(k.get_pagar_daftar_putih())));"
            "print('jam_kerja=%s' % (k.get_pagar_jam_kerja(),));"
            "print('interval=%s' % k.get_pemulih_interval())\"", timeout=60)
        keluar = o.read().decode(errors="replace")
    finally:
        c.close()
    hasil = {}
    for line in keluar.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            hasil[k.strip()] = v.strip()
    return hasil


def status_node(nama=NODE):
    pr = gns3_pemulihan.panggil("GET", "/projects") or []
    p = next((x for x in pr if x.get("status") == "opened"), pr[0] if pr else None)
    if not p:
        return None, None, None
    nodes = gns3_pemulihan.panggil(
        "GET", "/projects/%s/nodes" % p["project_id"]) or []
    n = next((x for x in nodes if x.get("name") == nama), None)
    return p["project_id"], (n or {}).get("node_id"), (n or {}).get("status")


def segarkan(db):
    """MySQL runs REPEATABLE READ here: without a commit this connection keeps seeing
    a stale snapshot and the nsm-app poller's writes stay invisible.
    """
    db.commit()


def main():
    global langganan_dicabut
    db = database.SessionLocal()
    pid = nid = None
    try:
        judul("0. KEADAAN AWAL")
        pid, nid, st = status_node()
        print("  node R1 di GNS3      : %s" % st)

        # Settings are read from nsm-app, not the laptop: the two `.env` files differ,
        # automation is enabled only on nsm-app, and its poller makes the recovery decision.
        state = keadaan_nsmapp()
        for k in ("gns3", "putih", "jam_kerja", "interval"):
            print("  %-20s : %s" % ({"gns3": "otomasi gns3 (nsm-app)",
                                     "putih": "daftar putih (nsm-app)",
                                     "jam_kerja": "jam kerja (nsm-app)",
                                     "interval": "interval pemulih"}[k],
                                    state.get(k)))
        if st != "started":
            print("\n  R1 tidak sedang hidup -- tidak ada yang bisa dimatikan.")
            return 1
        if state.get("gns3") != "True":
            print("\n  Otomasi GNS3 di nsm-app MATI. Menjalankan ini cuma akan")
            print("  mematikan R1 tanpa ada yang memulihkannya. Dibatalkan.")
            return 1
        if "gns3_restart" not in (state.get("putih") or ""):
            print("\n  `gns3_restart` tidak ada di daftar putih nsm-app --")
            print("  pagar akan menolak, dan R1 tidak akan pulih. Dibatalkan.")
            return 1

        judul("1. REDAM ALARM PALSU -- cabut langganan email sementara")
        line = db.execute(text(
            "select id, device_id, username from nsm_auth.notif_langganan "
            "where device_id in (4,5)")).fetchall()
        langganan_dicabut = [tuple(x) for x in line]
        print("  dicabut sementara: %r" % (langganan_dicabut,))
        for i, dev, user in langganan_dicabut:
            db.execute(text("delete from nsm_auth.notif_langganan where id=:i"),
                       {"i": i})
        db.commit()

        judul("2. SUNTIK GANGGUAN -- matikan R1 lewat API GNS3")
        print("  POST /projects/%s/nodes/%s/stop" % (pid, nid))
        gns3_pemulihan.panggil("POST", "/projects/%s/nodes/%s/stop" % (pid, nid))
        time.sleep(5)
        _, _, st2 = status_node()
        print("  status node sekarang: %s" % st2)
        if st2 != "stopped":
            print("  R1 tidak benar-benar mati; percobaan dihentikan.")
            return 1
        t_down = datetime.now()

        judul("3. SEKARANG SAYA TIDAK MENYENTUH APA PUN")
        print("  Yang ditunggu, berurutan:")
        print("    a. poller nsm-app mencatat R1 DOWN di device_events")
        print("    b. pemulih menulis baris izin di pagar_tindakan")
        print("       dengan diminta_oleh = 'poller_pemulih_gns3'")
        print("    c. R1 hidup lagi di GNS3, dan tercatat UP")
        print("  Batas tunggu %d detik, diperiksa tiap %d detik.\n"
              % (BATAS_TUNGGU_DETIK, JEDA_PERIKSA))

        view_down = view_permission = view_up = None
        start = time.time()
        while time.time() - start < BATAS_TUNGGU_DETIK:
            segarkan(db)
            via = int(time.time() - start)

            if view_down is None:
                ev = db.execute(
                    select(models.DeviceEvent)
                    .where(models.DeviceEvent.device_id == DEVICE_ID,
                           models.DeviceEvent.event_type == "DOWN",
                           models.DeviceEvent.timestamp >= t_down - timedelta(minutes=2))
                    .order_by(desc(models.DeviceEvent.timestamp)).limit(1)
                ).scalars().first()
                if ev:
                    view_down = ev.timestamp
                    print("  [%4ds] (a) DOWN tercatat di device_events: %s"
                          % (via, ev.timestamp))

            if view_permission is None:
                # Only rows written by the poller, and only after R1 was stopped. Otherwise a
                # manual `gns3_restart` row (e.g. `reset_pemutus:...`) written shortly before the
                # test would be mistaken for the recovery and produce a false verdict.
                t = db.execute(
                    select(models.PagarTindakan)
                    .where(models.PagarTindakan.device_id == DEVICE_ID,
                           models.PagarTindakan.kunci == "gns3_restart",
                           models.PagarTindakan.diminta_oleh == "poller_pemulih_gns3",
                           models.PagarTindakan.waktu >= t_down)
                    .order_by(desc(models.PagarTindakan.waktu)).limit(1)
                ).scalars().first()
                if t:
                    view_permission = t
                    print("  [%4ds] (b) pagar memutuskan: %s  oleh=%s"
                          % (via, t.keputusan, t.diminta_oleh))
                    print("           alasan: %s" % str(t.alasan)[:150])

            if view_up is None:
                _, _, stx = status_node()
                if stx == "started":
                    view_up = datetime.now()
                    print("  [%4ds] (c) R1 HIDUP LAGI di GNS3" % via)
                    break

            if via and via % 60 < JEDA_PERIKSA:
                print("  [%4ds] menunggu... (down=%s izin=%s)"
                      % (via, bool(view_down), bool(view_permission)))
            time.sleep(JEDA_PERIKSA)

        judul("4. HASIL")
        actor = getattr(view_permission, "diminta_oleh", None)
        print("  DOWN tercatat sendiri oleh poller : %s" % bool(view_down))
        print("  Pagar mengeluarkan keputusan      : %s"
              % (view_permission.keputusan if view_permission else False))
        print("  Pelakunya                         : %s" % actor)
        print("  R1 hidup lagi                     : %s" % bool(view_up))

        otomatis = bool(view_up) and actor == "poller_pemulih_gns3"
        if otomatis:
            print("\n  TERBUKTI: nsm-app memulihkan R1 SENDIRI.")
            print("  Tidak ada perintah pemulihan yang diketik dari laptop --")
            print("  baris auditnya bernama 'poller_pemulih_gns3', dan nama itu")
            print("  hanya dipakai oleh poller yang berjalan di nsm-app.")
        elif view_up:
            print("\n  R1 hidup lagi TETAPI bukan oleh poller nsm-app (%r)." % actor)
            print("  Itu bukan bukti otomasi lab bekerja.")
        else:
            print("\n  BELUM pulih dalam %d detik." % BATAS_TUNGGU_DETIK)
            if view_permission is not None and view_permission.keputusan != "izin":
                print("  Pagar MENOLAK, dan alasannya ada di atas -- itu")
                print("  jawaban yang sah, bukan kegagalan.")
        return 0 if otomatis else 1

    finally:
        # Never leave R1 down, whatever the outcome.
        try:
            if pid and nid:
                _, _, st_end = status_node()
                if st_end != "started":
                    print("\n  [pemulihan tangan] R1 masih %s -- dinyalakan "
                          "supaya lab tidak ditinggal rusak." % st_end)
                    gns3_pemulihan.panggil(
                        "POST", "/projects/%s/nodes/%s/start" % (pid, nid))
                    time.sleep(6)
                    _, _, st2 = status_node()
                    print("  [pemulihan tangan] status sekarang: %s" % st2)
        except Exception as e:
            print("  [pemulihan tangan] GAGAL: %s -- periksa R1 di GNS3!" % e)

        # Always restore the email subscriptions.
        try:
            for i, dev, user in langganan_dicabut:
                db.execute(text(
                    "insert into nsm_auth.notif_langganan (id, device_id, username) "
                    "values (:i,:d,:u)"), {"i": i, "d": dev, "u": user})
            db.commit()
            if langganan_dicabut:
                print("  langganan email dikembalikan: %d baris"
                      % len(langganan_dicabut))
        except Exception as e:
            print("  [PERINGATAN] langganan email GAGAL dikembalikan: %s" % e)
            print("  Baris yang harus dipulihkan: %r" % (langganan_dicabut,))
        db.close()


if __name__ == "__main__":
    sys.exit(main())

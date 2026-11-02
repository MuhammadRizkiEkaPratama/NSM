"""REAL FAULT INJECTION #3: an interface that is down vs the intent, proving the
automatic recovery path.

Complements `injeksi_r1.py` and `injeksi_layanan.py`. Procedure and fixed rules
are the same; see docs/FAULT-INJECTION.md.

TARGET: `FastEthernet1/1` ON R1, AND THE CHOICE MATTERS MOST. The interface was
chosen because it has ZERO impact, verified before touching it, not assumed:

    R1 snapshot: Fa1/1 exists, `shutdown`, NO IP address, NO description
    GNS3 cabling: R1 has only TWO cables, Fa0/0 to SW-A and Fa1/0 to the ISP.
                  Fa1/1 is not connected to anything.

So enabling it moves no packet. Compare the options that look "more real":
shutting down Fa1/0 would cut ALL of Site B (R2, SW-B, LDAP), and LDAP has
notification subscriptions, so that would also send real email to other people's
addresses. Testing automation must not be paid for with an avoidable outage.

THE SHAPE OF THE FAULT DIFFERS from the two earlier injections. Those start by
turning something OFF. Here nothing needs to be: what makes an interface a
recovery candidate is not "it is down" but "the intent says it should be up BUT
the snapshot says it is down". Fa1/1 has been down for a long time; what is
missing is the STATEMENT that it should be up.

So the fault is injected by stating the intent. That is also the most honest form
for this path, because it is exactly how real drift appears: not the device
changing, but a stated intent that reality does not follow.

Run from the monitoring machine:
    venv\\Scripts\\python.exe -u injeksi_interface.py
"""
import sys
import time
from datetime import datetime

from sqlalchemy import select, delete

import config
import database
import models
import pagar_otomasi
from drift import service as drift_svc
from pemulih import interface as pemulih_iface
from sot import katalog, service as sot_svc

DEVICE_ID = 5
IFACE = "FastEthernet1/1"

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


def baca_iface_langsung(dev, nama=IFACE):
    """Ask R1 ITSELF whether the interface is admin-down.

    Deliberately NOT the `konfig_snapshots` snapshot: snapshots are refreshed
    periodically, so after the recovery acts it still holds the old state. Reading
    the device directly is the only evidence that cannot be confused with "not
    refreshed yet".
    """
    from netmiko import ConnectHandler
    ch = ConnectHandler(device_type="cisco_ios", host=dev.ip_address,
                        username=dev.username, password=dev.password,
                        conn_timeout=20, timeout=30)
    try:
        keluar = ch.send_command("show interfaces %s | include line protocol" % nama)
    finally:
        ch.disconnect()
    return keluar.strip()


def sedang_mati(teks):
    return "administratively down" in (teks or "").lower()


db = database.SessionLocal()
patch_asli = {}
intent_dibuat = False

try:
    judul("0. DASAR -- dibuktikan, bukan diasumsikan")
    dev = db.get(models.Device, DEVICE_ID)
    print("  device: #%s %s (%s)" % (dev.id, dev.name, dev.ip_address))

    teks = baca_iface_langsung(dev)
    print("  R1 menjawab: %s" % teks)
    benar("%s sedang administratively down" % IFACE, sedang_mati(teks),
          "-> %r" % teks)

    lama = db.execute(select(models.IntentInterface).where(
        models.IntentInterface.device_id == DEVICE_ID)).scalars().all()
    print("  baris intent_interface untuk R1 sekarang: %d" % len(lama))
    benar("belum ada intent interface -> pembersihan nanti bersih",
          len(lama) == 0, "-> %d baris" % len(lama))

    judul("1. SUNTIK PENYIMPANGAN -- nyatakan bahwa %s HARUS hidup" % IFACE)
    sot_svc.simpan_interface(db, DEVICE_ID,
                             [{"nama": IFACE, "shutdown": False}],
                             oleh="injeksi_interface")
    db.commit()
    intent_dibuat = True
    baru = db.execute(select(models.IntentInterface).where(
        models.IntentInterface.device_id == DEVICE_ID)).scalars().all()
    print("  intent sekarang: %r" % [(r.nama, r.shutdown) for r in baru])
    benar("intent tersimpan: interface ini dinyatakan harus hidup",
          any(r.nama == IFACE and not r.shutdown for r in baru))

    judul("2. TAHAP 2 HARUS MELIHAT PENYIMPANGANNYA SENDIRI")
    r = drift_svc.bandingkan(db, DEVICE_ID)
    temuan = []
    for i in r.get("interface", []):
        for m in i.get("medan", []):
            if i["kunci"] == IFACE and m["medan"] == "shutdown":
                temuan.append((i["kunci"], m["intended"], m["observed"], m.get("status")))
    print("  temuan drift: %r" % temuan)
    benar("drift melaporkan intent=hidup TAPI kenyataan=mati",
          any(t[1] is False and t[2] is True for t in temuan),
          "-> %r" % temuan)

    judul("3. GERBANG 1 MENOLAK -- walau SEMUA gerbang lain dibuka")
    level, alasan_risiko = pagar_otomasi._risiko(pemulih_iface.KATEGORI,
                                                 pemulih_iface.KUNCI)
    print("  klasifikasi %s = %s" % (pemulih_iface.KUNCI, level))
    benar("`interface_up` diklasifikasikan wajib_manusia",
          level == katalog.RISIKO_MANUSIA, "-> %r" % level)

    patch_asli["putih"] = config.get_pagar_daftar_putih
    config.get_pagar_daftar_putih = lambda: {pemulih_iface.KUNCI}
    patch_asli["jam"] = config.get_pagar_jam_kerja
    config.get_pagar_jam_kerja = lambda: (0, 24)
    patch_asli["aktif"] = config.get_pemulih_interface_aktif
    config.get_pemulih_interface_aktif = lambda: True

    kandidat = pemulih_iface.cari_kandidat(db)
    print("  kandidat: %r" % [(d.name, n) for d, n in kandidat])
    benar("interface ini dikenali sebagai kandidat pemulihan",
          any(d.id == DEVICE_ID and n == IFACE for d, n in kandidat))

    kep = pemulih_iface.coba_nyalakan(db, dev, IFACE, oleh="injeksi_interface")
    print("  keputusan pagar: izin=%s" % kep.izin)
    print("  ->", kep.alasan[:190])
    benar("gerbang 1 TETAP menolak walau daftar putih & jam kerja dibuka",
          kep.izin is False and "wajib_manusia" in kep.alasan,
          "-> %s" % kep.alasan[:110])

    teks = baca_iface_langsung(dev)
    benar("interface TETAP mati -- tidak ada perintah yang terkirim",
          sedang_mati(teks), "-> %r" % teks)

    judul("4. KALAU MANUSIA MEMUTUSKAN LAIN, PERINTAHNYA HARUS BENAR-BENAR SAMPAI")
    # Same as the service injection: gate 1 can only be changed by editing code, so it
    # is patched TEMPORARILY to imitate a deliberate operator decision. Without this
    # round, the file would only prove the recovery does nothing, and a TOTALLY BROKEN
    # recovery would pass such a test too.
    patch_asli["risiko"] = pagar_otomasi.RISIKO_PEMULIH[pemulih_iface.KUNCI]
    pagar_otomasi.RISIKO_PEMULIH[pemulih_iface.KUNCI] = (
        katalog.RISIKO_AMAN, "DITAMBAL SEMENTARA oleh injeksi_interface.py")

    kep2 = pemulih_iface.coba_nyalakan(db, dev, IFACE, oleh="injeksi_interface")
    print("  keputusan pagar: izin=%s tindakan_id=%s" % (kep2.izin, kep2.tindakan_id))
    print("  ->", kep2.alasan[:190])
    benar("sesudah risikonya diturunkan -> DIIZINKAN", kep2.izin is True,
          "-> %s" % kep2.alasan[:120])

    time.sleep(5)
    teks = baca_iface_langsung(dev)
    print("  R1 menjawab: %s" % teks)
    benar("pemulih benar-benar MENYALAKAN interface di perangkat sungguhan",
          not sedang_mati(teks), "-> %r" % teks)

    db.commit()
    t = db.get(models.PagarTindakan, kep2.tindakan_id)
    print("  tindakan #%s: status_verifikasi=%r  state_sebelum=%r"
          % (kep2.tindakan_id, t.status_verifikasi if t else None,
             (t.state_sebelum if t else None)))
    benar("hasilnya diverifikasi dan dicatat BERHASIL",
          t is not None and t.status_verifikasi is True,
          "-> %r" % (t.status_verifikasi if t else None))
    benar("keadaan SEBELUM ikut disimpan (bahan rollback Tahap 8)",
          t is not None and t.state_sebelum, "-> %r" % (t.state_sebelum if t else None))

finally:
    judul("PEMBERSIHAN -- kembalikan semuanya seperti semula")
    # The order is deliberate: device first, then database, then classification. If
    # interrupted midway, what remains is closest to the original state, not an
    # interface that is up with nobody having declared it.
    try:
        dev = db.get(models.Device, DEVICE_ID)
        teks = baca_iface_langsung(dev)
        if not sedang_mati(teks):
            # DIRECTLY via netmiko, NOT via `kirim_perintah.kirim()`.
            #
            # `kirim()` defaults to `sungguhan=False`: it only builds a PREVIEW and never
            # touches the device. An earlier version called `kirim(..., "iface_mati", ...)`
            # assuming the interface had been shut down; the run reported all tests passing
            # while LEAVING Fa1/1 enabled on R1. The test was right; the cleanup lied.
            #
            # Same lesson as in CONTRIBUTING.md: "no error" is not proof of "succeeded". The
            # lines below check the result instead of assuming the command ran.
            #
            # The direct path is used because this is the script's OWN cleanup, not the
            # automation path, and because Fa1/1 is connected to nothing, so shutting it down
            # cannot cut access to R1 (which goes through Fa0/0).
            print("  %s masih hidup -- dimatikan kembali lewat netmiko" % IFACE)
            from netmiko import ConnectHandler
            ch = ConnectHandler(device_type="cisco_ios", host=dev.ip_address,
                                username=dev.username, password=dev.password,
                                conn_timeout=20, timeout=40)
            try:
                ch.send_config_set(["interface %s" % IFACE, "shutdown"])
            finally:
                ch.disconnect()
            time.sleep(4)
            teks = baca_iface_langsung(dev)
            if not sedang_mati(teks):
                print("  [GAGAL PEMBERSIHAN] %s MASIH HIDUP. Matikan manual:"
                      % IFACE)
                print("     ssh %s@%s -> conf t -> interface %s -> shutdown"
                      % (dev.username, dev.ip_address, IFACE))
        print("  keadaan akhir %s: %s" % (IFACE, teks))
    except Exception as e:
        print("  [PERINGATAN] gagal mengembalikan interface: %s: %s"
              % (type(e).__name__, e))

    if intent_dibuat:
        try:
            db.execute(delete(models.IntentInterface).where(
                models.IntentInterface.device_id == DEVICE_ID))
            db.commit()
            sisa = db.execute(select(models.IntentInterface).where(
                models.IntentInterface.device_id == DEVICE_ID)).scalars().all()
            print("  intent_interface R1 dihapus, sisa: %d baris" % len(sisa))
        except Exception as e:
            print("  [PERINGATAN] gagal menghapus intent: %s" % e)

    peta = {"putih": "get_pagar_daftar_putih", "jam": "get_pagar_jam_kerja",
            "aktif": "get_pemulih_interface_aktif"}
    for nama, fn in patch_asli.items():
        if nama == "risiko":
            pagar_otomasi.RISIKO_PEMULIH[pemulih_iface.KUNCI] = fn
            continue
        setattr(config, peta[nama], fn)
    print("  klasifikasi %s: %r" % (pemulih_iface.KUNCI,
          pagar_otomasi.RISIKO_PEMULIH[pemulih_iface.KUNCI][0]))
    print("  pagar: daftar_putih=%r jam=%r interface_aktif=%r"
          % (config.get_pagar_daftar_putih(), config.get_pagar_jam_kerja(),
             config.get_pemulih_interface_aktif()))

    print()
    print("=" * 70)
    print("HASIL INJEKSI INTERFACE: %d lolos, %d gagal" % (lolos, gagal))
    print("=" * 70)
    db.close()
    sys.exit(1 if gagal else 0)

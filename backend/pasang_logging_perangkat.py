r"""Make Cisco devices SEND syslog and traps to NSM.

The receivers on nsm-app (UDP 1514 syslog, 1162 trap) are up; this script
installs the sending side on the devices.

Device changes (additive only; interfaces, routes and ACLs are untouched, no
reload, no dropped sessions):
    logging host <nsm-ip> transport udp port 1514
    logging trap informational
    snmp-server host <nsm-ip> version 2c <community> udp-port 1162
    snmp-server enable traps <selected types>

Undo: `no logging host <nsm-ip>`, `no snmp-server host <nsm-ip>`, or run with
`--cabut`.

Each device is verified twice after sending, because "no error" is not proof of
success:
  1. `show running-config | include logging host`: the line exists
  2. NSM actually RECEIVED messages from that device (row count in
     `syslog_pesan` before and after)
The second is far stronger: a config can be right while a firewall, a wrong
route or a wrong port blocks delivery.

Not saved to startup-config by default, so a reload reverts the change; add
`--simpan` once sure.

Usage:
    python pasang_logging_perangkat.py                   report only
    python pasang_logging_perangkat.py --terapkan --hanya R1   R1 only (test in GNS3 first)
    python pasang_logging_perangkat.py --terapkan        all Cisco devices
"""
import sys
import time

from sqlalchemy import func, select

import config
import database
import dialek_perangkat
import models

NSM_IP = "192.168.56.156"
PORT_SYSLOG = 1514
PORT_TRAP = 1162


def baris_pasang(community, sumber_if=None):
    """Lines installed on the device.

    `sumber_if` sets the address the device sends from, which is required for the
    messages to map to a device at all. The site-B router sent from its WAN
    interface `10.10.20.2` while NSM knows it as `192.168.20.1`, so its messages
    arrived as an unknown sender. (They were not lost, because the receiver stores
    unknown senders instead of dropping them.)
    """
    line = [
        "logging host %s transport udp port %d" % (NSM_IP, PORT_SYSLOG),
        # `informational` (6), not `debugging` (7): debugging floods the network with
        # messages nobody reads and can load a lab router's CPU.
        "logging trap informational",
        "snmp-server host %s version 2c %s udp-port %d"
        % (NSM_IP, community, PORT_TRAP),
        # Trap types are listed one by one, not a bare `snmp-server enable traps`.
        # The bare command enables dozens of types and IOS replies with very long output,
        # so netmiko times out (`ReadTimeout: Pattern not detected`) after earlier lines
        # were already applied, a confusing half-failure. Most trap types are never read
        # in this lab anyway.
        "snmp-server enable traps snmp linkdown linkup coldstart warmstart",
        "snmp-server enable traps config",
    ]
    if sumber_if:
        line += ["logging source-interface %s" % sumber_if,
                  "snmp-server trap-source %s" % sumber_if]
    return line


def baris_cabut():
    return [
        "no logging host %s" % NSM_IP,
        "no snmp-server host %s" % NSM_IP,
    ]


def _perangkat_cisco(db, hanya=None):
    q = select(models.Device).where(
        models.Device.aktif == True,  # noqa: E712
        models.Device.platform.in_(
            dialek_perangkat.platform_dengan("firewall", "acl")))
    daftar = db.execute(q).scalars().all()
    if hanya:
        h = hanya.lower()
        daftar = [d for d in daftar
                  if h in (d.name or "").lower() or h == (d.ip_address or "")]
    return daftar


def _hitung_pesan(db, device_id):
    return db.execute(select(func.count(models.SyslogPesan.id)).where(
        models.SyslogPesan.device_id == device_id)).scalar() or 0


def cari_sumber_if(conn, ip):
    """Name of the interface whose address MATCHES the one NSM knows.
    Without it the device picks the source interface itself and the address may
    differ from the registered one, so messages arrive as an unknown sender (see
    `baris_pasang()`). Returns None if nothing matches; the device then uses its
    default behavior and the second verification checks the mapping.
    """
    if not ip:
        return None
    try:
        keluar = conn.send_command("show ip interface brief", read_timeout=60)
    except Exception:
        return None
    for line in keluar.splitlines():
        section = line.split()
        if len(section) >= 2 and section[1].strip() == ip.strip():
            return section[0]
    return None


def kerjakan(db, d, cabut=False, simpan=False):
    from kirim_perintah import _sambung

    hasil = {"device": d.name, "ip": d.ip_address, "terkirim": False,
             "terverifikasi": False, "pesan_masuk": None, "galat": None}

    before = _hitung_pesan(db, d.id)
    conn = None
    try:
        conn = _sambung(d)
        # Lines are built AFTER connecting, because `sumber_if` needs the device's
        # interface list.
        if cabut:
            line = baris_cabut()
        else:
            source = cari_sumber_if(conn, d.ip_address)
            hasil["sumber_if"] = source
            line = baris_pasang(config.get_snmptrap_community(),
                                 sumber_if=source)
        conn.send_config_set(line)
        if simpan:
            # `write memory` on IOS can be slow, and netmiko may time out waiting for the
            # prompt (`ReadTimeout`) while the save itself SUCCEEDS. So the result is
            # verified from the startup-config instead of being inferred from an exception.
            try:
                conn.save_config(read_timeout=180)
            except Exception as e:
                hasil["simpan_galat"] = str(e)[:80]
            try:
                st = conn.send_command(
                    "show startup-config | include logging host",
                    read_timeout=120)
                hasil["tersimpan"] = NSM_IP in st
            except Exception:
                hasil["tersimpan"] = None
        hasil["terkirim"] = True

        # Verification 1: the line exists in the running-config.
        keluar = conn.send_command("show running-config | include logging host")
        hasil["terverifikasi"] = (NSM_IP in keluar) if not cabut \
            else (NSM_IP not in keluar)
        hasil["baris_konfig"] = keluar.strip()[:120]
    except Exception as e:
        hasil["galat"] = "%s: %s" % (type(e).__name__, str(e)[:140])
        return hasil
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass

    if cabut:
        return hasil

    # Verification 2: NSM actually received messages from this device. A correct
    # config does not guarantee delivery (firewall, routing or a wrong port).
    for _ in range(12):
        time.sleep(5)
        db.commit()  # MySQL REPEATABLE READ: without this, writes
                             # from other sessions are not visible.
        n = _hitung_pesan(db, d.id)
        if n > before:
            hasil["pesan_masuk"] = n - before
            return hasil
    hasil["pesan_masuk"] = 0
    return hasil


def main(terapkan=False, cabut=False, hanya=None, simpan=False):
    db = database.SessionLocal()
    try:
        daftar = _perangkat_cisco(db, hanya)
        print("=" * 72)
        print("PAKET A - %s LOGGING DI PERANGKAT"
              % ("CABUT" if cabut else "PASANG"))
        print("mode: %s%s" % ("TERAPKAN" if terapkan else "LAPORAN SAJA",
                              "  (+simpan ke startup)" if simpan else ""))
        print("sasaran: %d perangkat Cisco%s"
              % (len(daftar), (" (disaring: %s)" % hanya) if hanya else ""))
        print("=" * 72)

        line = (baris_cabut() if cabut
                 else baris_pasang(config.get_snmptrap_community()))
        print("\nBaris yang akan dikirim:")
        for b in line:
            print("    " + b)

        if not terapkan:
            print("\nTambahkan --terapkan untuk benar-benar mengirimnya.")
            return 0

        fail = 0
        for d in daftar:
            print("\n- %s (%s)" % (d.name, d.ip_address))
            h = kerjakan(db, d, cabut=cabut, simpan=simpan)
            if h["galat"]:
                print("    GAGAL: %s" % h["galat"])
                fail += 1
                continue
            print("    terkirim        : %s" % h["terkirim"])
            print("    ada di konfig   : %s   %s"
                  % (h["terverifikasi"], h.get("baris_konfig", "")))
            if simpan:
                ts = h.get("tersimpan")
                print("    tersimpan startup: %s%s"
                      % ({True: "YA", False: "TIDAK",
                          None: "tidak terbaca"}.get(ts, ts),
                         ("   (perintah simpan sempat kehabisan waktu, tetapi "
                          "hasilnya diperiksa langsung)"
                          if h.get("simpan_galat") and ts else "")))
                if ts is False:
                    fail += 1
            if not cabut:
                n = h["pesan_masuk"]
                print("    pesan DITERIMA NSM: %s"
                      % ("%d (jalur terbukti sampai)" % n if n
                         else "0  <-- konfigurasi benar tapi TIDAK ADA yang tiba"))
                if not n:
                    fail += 1
        print("\n" + "=" * 72)
        print("%d perangkat, %d bermasalah" % (len(daftar), fail))
        print("=" * 72)
        return 1 if fail else 0
    finally:
        db.close()


if __name__ == "__main__":
    hanya = None
    if "--hanya" in sys.argv:
        i = sys.argv.index("--hanya")
        if i + 1 < len(sys.argv):
            hanya = sys.argv[i + 1]
    sys.exit(main(terapkan="--terapkan" in sys.argv,
                  cabut="--cabut" in sys.argv,
                  hanya=hanya,
                  simpan="--simpan" in sys.argv))

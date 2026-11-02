from datetime import datetime

from sqlalchemy import desc

import dialek_perangkat
import identitas
import penyangga
from config import (
    get_pemulih_gns3_aktif,
    get_pemulih_interface_aktif,
    get_pemulih_konfig_aktif,
    get_pemulih_layanan_aktif,
)
from connectors import kepatuhan, konfig, konfig_linux
from database import SessionLocal
from models import Device, KonfigSnapshot, KonfigTemuan

from ._inti import status_terakhir


def poll_healer():
    """Run the automatic recovery (stages 4-7): dead GNS3 node, dead service, dead
    interface, drifted config.
    Four separate kill switches, all checked inside
    `pemulih.orkestrasi.jalankan_semua()`; this is only a DB-session wrapper plus a
    safety net for unexpected errors. The switches and `PAGAR_DAFTAR_PUTIH` are
    re-read every round, so a `.env` change applies without a restart.
    """
    if not (get_pemulih_gns3_aktif() or get_pemulih_layanan_aktif()
           or get_pemulih_interface_aktif() or get_pemulih_konfig_aktif()):
        return
    try:
        from pemulih import orkestrasi as _pemulih_orkestrasi
    except Exception:
        return
    db = SessionLocal()
    try:
        _pemulih_orkestrasi.jalankan_semua(db)
    except Exception as e:
        print("[pemulih] lewati putaran: %s" % str(e)[:160])
    finally:
        db.close()


def poll_identity():
    """Collect identity markers for each device and update the verdict.
    Read-only: this machine's ARP table, one SNMP OID (`sysName`), and a few SSH
    read commands listed in `identitas_sumber`. Runs infrequently on purpose, since
    identity rarely changes. The verdict is never a write permission by itself:
    write paths call `identitas.boleh_ditulisi()` again right before sending.
    """
    db, _buffered = penyangga.sesi()
    try:
        catatan = identitas.kumpulkan(db)
        db.commit()
        bentrok = [c for c in catatan if c["bentrok"]]
        baru = [c for c in catatan if c["baru"]]
        if bentrok:
            for c in bentrok:
                for b in c["bentrok"]:
                    print(f"[identitas] PERTENTANGAN {c['device']}: "
                          f"{b['jenis']} tersimpan {b['lama']!r}, "
                          f"terlihat {b['baru']!r}")
        if baru:
            print(f"[identitas] {len(baru)} perangkat mendapat penanda baru")
    except Exception as e:
        db.rollback()
        print(f"[identitas] gagal ({e})")
    finally:
        db.close()


def _potret_linux(db, d):
    """Snapshot of a Linux machine's security configuration, then score compliance.
    Read-only: the commands are listed in `connectors/konfig_linux.PERINTAH` and
    none needs sudo. Stored only when the fingerprint changes, same as Cisco.
    """
    import paramiko
    cl = paramiko.SSHClient()
    cl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    sambung = {"timeout": 25, "allow_agent": False, "look_for_keys": False}
    try:
        if d.ssh_key_path:
            cl.connect(d.ip_address, username=d.username,
                       key_filename=d.ssh_key_path, **sambung)
        else:
            cl.connect(d.ip_address, username=d.username,
                       password=d.password, **sambung)
        try:
            teks = konfig_linux.ambil(cl)
        finally:
            cl.close()

        sidik = konfig.sidik(teks)
        previous = (db.query(KonfigSnapshot)
                      .filter(KonfigSnapshot.device_id == d.id)
                      .order_by(desc(KonfigSnapshot.waktu))
                      .first())
        if previous is not None and previous.sidik == sidik:
            return

        if previous is None:
            tambah = delete = None
            print(f"[cfg] {d.name}: potret keamanan PERTAMA disimpan "
                  f"({len(teks.splitlines())} baris)")
        else:
            # THREE values, not two: (tambah, hapus, potongan_diff). Unpacking the wrong
            # number once made every Linux snapshot fail silently, because the error was
            # swallowed by the windowless poller's stdout buffer.
            tambah, delete, _chunk = konfig.beda_baris(previous.teks, teks)
            print(f"[cfg] {d.name}: KONFIGURASI KEAMANAN BERUBAH "
                  f"(+{tambah} / -{delete})")

        snapshot = KonfigSnapshot(
            device_id=d.id, waktu=datetime.now(), sidik=sidik, teks=teks,
            baris_tambah=tambah, baris_hapus=delete,
            # Linux has no running/startup split, so the column stays empty. Empty means
            # "no such concept", not "all saved"; the page tells them apart via `punya_startup`.
            sidik_startup=None, teks_startup=None, belum_disimpan=None,
        )
        db.add(snapshot)
        db.flush()

        hasil = kepatuhan.nilai(teks, d.platform)
        for h in hasil:
            db.add(KonfigTemuan(
                snapshot_id=snapshot.id, device_id=d.id,
                aturan_id=h["aturan_id"], hasil=h["hasil"],
                keparahan=h["keparahan"], baris_bukti=h["baris_bukti"],
                nomor_baris=h["nomor_baris"], dinilai=datetime.now(),
            ))
        r = kepatuhan.ringkas(hasil)
        if r["temuan"]:
            print(f"[cfg] {d.name}: kepatuhan {r['temuan']} temuan "
                  f"({r['tinggi']} tinggi, {r['sedang']} sedang, "
                  f"{r['rendah']} rendah)")
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[cfg] {d.name}: gagal potret keamanan ({e})")


def poll_config():
    """Fetch the device configuration and store it ONLY when it changed.
    Read-only: no write path to devices belongs in this file.
    Configs rarely change on their own, so storing every round would pile up
    identical copies; with this rule one row means one real change.
    Runs rarely (default 15 min) because each fetch opens a real CLI session.
    """
    db, _buffered = penyangga.sesi()
    try:
        for d in db.query(Device).all():
            # Linux is snapshotted through its own path: `connectors/konfig_linux.py`
            # assembles the snapshot from several sources, after which it is plain text and
            # the fingerprint, diff and compliance scoring work unchanged. Selected by
            # capability (`kemampuan.baca_konfig_layanan`), not by "is Linux".
            if (d.aktif != 0
                    and dialek_perangkat.ambil(d.platform)
                        .kemampuan("baca_konfig_layanan")):
                if d.username and (d.password or d.ssh_key_path):
                    last = status_terakhir(db, d.id)
                    if last is None or last.event_type != "DOWN":
                        _potret_linux(db, d)
                continue

            if d.aktif == 0 or d.platform not in konfig.PERINTAH:
                continue
            if not (d.username and d.password):
                continue
            last = status_terakhir(db, d.id)
            if last is not None and last.event_type == "DOWN":
                continue

            try:
                from netmiko import ConnectHandler
                conn = ConnectHandler(
                    device_type=d.platform, host=d.ip_address,
                    username=d.username, password=d.password, timeout=25,
                )
                try:
                    raw = konfig.ambil(conn, d.platform)
                    raw_startup = konfig.ambil_startup(conn, d.platform)
                finally:
                    conn.disconnect()

                teks, sidik = konfig.olah(raw, d.platform)

                # Config that applies after reboot. None means the platform has no such concept,
                # which differs from empty: a device without a running/startup split must not be
                # reported as safely saved.
                if raw_startup is None:
                    teks_startup = sidik_startup = not_yet = None
                else:
                    teks_startup, sidik_startup = konfig.olah(raw_startup, d.platform)
                    t_b, h_b, _ = konfig.beda_baris(teks_startup, teks)
                    not_yet = t_b + h_b

                # Previous snapshot for comparison, fetched AFTER the network work so the SQLite
                # write lock is not held while waiting on the device.
                previous = (db.query(KonfigSnapshot)
                              .filter(KonfigSnapshot.device_id == d.id)
                              .order_by(desc(KonfigSnapshot.waktu))
                              .first())

                # Check BOTH fingerprints, not just running: `write memory` changes startup
                # without touching running, and otherwise the "unsaved" marker would stay on
                # forever for a device that was saved.
                if (previous is not None
                        and previous.sidik == sidik
                        and previous.sidik_startup == sidik_startup):
                    continue  # nothing changed

                acl_berubah = None
                if previous is None:
                    tambah = delete = None
                    print(f"[cfg] {d.name}: potret konfigurasi PERTAMA disimpan "
                          f"({len(teks.splitlines())} baris)")
                elif previous.sidik != sidik:
                    tambah, delete, _diff = konfig.beda_baris(previous.teks, teks)
                    acl_berubah = 1 if konfig.deteksi_acl_berubah(_diff) else 0
                    print(f"[cfg] {d.name}: KONFIGURASI BERUBAH "
                          f"(+{tambah} / -{delete} baris)")
                    if acl_berubah:
                        # Deliberately prominent: a rogue ACL line added directly via the CLI once went
                        # unnoticed for days; an easily missed log line does not close that gap.
                        print(f"[cfg] {d.name}: *** ACL BERUBAH DI LUAR NSM "
                              f"*** — periksa /admin/konfig/firewall")
                else:
                    # Running is unchanged, so no lines were added or removed; only the status changed.
                    # Three messages, not two: "startup-config changed" would be wrong for a snapshot
                    # that is the first ever read of the startup-config.
                    tambah = delete = 0
                    if previous.sidik_startup is None:
                        kabar = "startup-config mulai ikut dibaca"
                    elif not_yet == 0:
                        kabar = "DISIMPAN permanen (running = startup)"
                    else:
                        kabar = "startup-config berubah"
                    print(f"[cfg] {d.name}: {kabar}")

                if not_yet:
                    print(f"[cfg] {d.name}: PERINGATAN, {not_yet} baris belum "
                          f"disimpan ke startup-config dan akan hilang saat reboot")

                snapshot = KonfigSnapshot(
                    device_id=d.id, waktu=datetime.now(), sidik=sidik,
                    teks=teks, baris_tambah=tambah, baris_hapus=delete,
                    sidik_startup=sidik_startup, teks_startup=teks_startup,
                    belum_disimpan=not_yet, acl_berubah=acl_berubah,
                )
                db.add(snapshot)
                # `flush`, not `commit`, so the snapshot and its compliance score land in ONE
                # transaction; a snapshot without a score would show as "zero findings".
                db.flush()

                # Compliance is scored here, not in a separate job: config changes rarely, and
                # scoring at creation guarantees every snapshot has a score. No device access;
                # it only reads the in-memory `teks`.
                hasil = kepatuhan.nilai(teks, d.platform)
                for h in hasil:
                    db.add(KonfigTemuan(
                        snapshot_id=snapshot.id, device_id=d.id,
                        aturan_id=h["aturan_id"], hasil=h["hasil"],
                        keparahan=h["keparahan"],
                        baris_bukti=h["baris_bukti"],
                        nomor_baris=h["nomor_baris"],
                        dinilai=datetime.now(),
                    ))
                r = kepatuhan.ringkas(hasil)
                if r["temuan"]:
                    print(f"[cfg] {d.name}: kepatuhan {r['temuan']} temuan "
                          f"({r['tinggi']} tinggi, {r['sedang']} sedang, "
                          f"{r['rendah']} rendah)")
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"[cfg] {d.name}: gagal ({e})")
    finally:
        db.close()

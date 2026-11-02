from datetime import datetime

import dialek_perangkat
import penyangga
from connectors.ssh import SshConnector
from models import Device, SumberDaya

from ._inti import kerjakan_bersamaan, sasaran


def poll_sumber_daya():
    """Saturation sample: how full disk, memory and CPU are on each device.
    The one signal that warns BEFORE something breaks. Linux over SSH only: Cisco
    routers have no `df` or `/proc/loadavg`, and skipping them is more honest than
    inventing numbers. One SSH session, one command, three answers, which is also
    why the job runs every 5 minutes rather than every round.
    """
    from connectors import sumberdaya as _sd

    db, _buffered = penyangga.sesi()
    try:
        choice = []
        for d in db.query(Device).all():
            # Selected by "can CPU/RAM/disk be read over SSH", not "is this Linux"
            # (`kemampuan.baca_sumberdaya`).
            if (d.aktif == 0
                    or not dialek_perangkat.ambil(d.platform)
                             .kemampuan("baca_sumberdaya")):
                continue
            choice.append(sasaran(d))
        if not choice:
            return

        # `sasaran()` returns a flat `Sasaran` namedtuple, safe to hand to worker threads
        # without dragging the DB session along. Fields are accessed with dots.
        def baca(t):
            c = SshConnector(t.ip_address, platform=t.platform,
                             username=t.username, password=t.password,
                             key_path=t.ssh_key_path)
            return _sd.urai(c.jalankan_perintah(_sd.PERINTAH_LINUX))

        hasil = kerjakan_bersamaan(choice, baca)
        for t, nilai_ukur, error in hasil:
            if error or not nilai_ukur:
                print(f"   [sumberdaya] {t.name}: gagal dibaca "
                      f"({str(error)[:60] if error else 'kosong'})")
                continue
            db.add(SumberDaya(
                device_id=t.id, waktu=datetime.now(),
                disk_persen=nilai_ukur.get("disk"),
                mem_persen=nilai_ukur.get("mem"),
                load_per_inti=nilai_ukur.get("load"),
                inti=int(nilai_ukur["inti"]) if "inti" in nilai_ukur else None,
                sumber="ssh"))
            v = _sd.vonis(nilai_ukur)
            bad = [k for k, x in v.items() if x != "sehat"]
            catatan = (" [%s]" % ", ".join(
                "%s %s" % (k, v[k]) for k in bad)) if bad else ""
            print("   [sumberdaya] %s: disk %.0f%% mem %.0f%% load %.2f%s"
                  % (t.name, nilai_ukur.get("disk", -1),
                     nilai_ukur.get("mem", -1), nilai_ukur.get("load", -1),
                     catatan))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"   [sumberdaya] job gagal: {e}")
    finally:
        db.close()

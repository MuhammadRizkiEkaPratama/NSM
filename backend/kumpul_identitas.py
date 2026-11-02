"""Collect device identity markers and update their verdicts.

    python kumpul_identitas.py                    show what would be collected
    python kumpul_identitas.py --jalankan         save
    python kumpul_identitas.py `--tanpa-jaringan`   only sources that already exist

SOURCES (all READ-ONLY):
    stored config snapshot   hostname                  zero connections
    ARP table + own cards    mac                       zero new connections
    SSH                      machine-id, hostname, mac (Linux)
                             serial (Cisco), hostname  (Windows)
    SNMP                     sysName

`--tanpa-jaringan` restricts it to the first two sources, for a quick look without
opening any connection to a device.

Safe to run while the poller is up: it writes only `identitas_perangkat` and two
columns of `devices`, once at the end. The poller also runs an `identitas` job every
30 minutes; if the two overlap, one waits (`busy_timeout`) instead of failing.
"""
import sys

from database import SessionLocal
from models import Device
import identitas


def main():
    run = "--jalankan" in sys.argv
    pakai_jaringan = "--tanpa-jaringan" not in sys.argv

    db = SessionLocal()
    try:
        print("=" * 74)
        print("PENGUMPULAN IDENTITAS PERANGKAT"
              + ("" if run else "  (uji coba, tidak menyimpan)"))
        print("=" * 74)
        if pakai_jaringan:
            print("  Sumber: potret tersimpan, tabel ARP, SSH, SNMP.")
            print("  Semua perintahnya MEMBACA. Perangkat yang dijeda dilewati.")
        else:
            print("  Sumber: potret tersimpan + tabel ARP saja. Nol koneksi.")
        print()

        catatan = identitas.kumpulkan(db, pakai_jaringan=pakai_jaringan)

        print("  PENANDA YANG TERLIHAT")
        print("  " + "-" * 70)
        for c in catatan:
            if not c["penanda"]:
                print("  %-22s (tidak ada penanda yang bisa diambil)"
                      % c["device"][:22])
                continue
            content = ", ".join(f"{k}={v}" for k, v in sorted(c["penanda"].items()))
            print("  %-22s %s" % (c["device"][:22], content[:48]))
            for b in c["bentrok"]:
                print("      !! BERTENTANGAN  %s: tersimpan %r, terlihat %r"
                      % (b["jenis"], b["lama"], b["baru"]))
            for b in c["baru"]:
                print("      +  baru: %s = %s" % (b["jenis"], b["nilai"]))

        if run:
            db.commit()

        print()
        print("  VONIS IDENTITAS TIAP PERANGKAT")
        print("  " + "-" * 70)
        for d in db.query(Device).order_by(Device.id).all():
            penanda = identitas.penanda_tersimpan(db, d.id)
            content = ", ".join(f"{p['jenis']}={p['nilai']}" for p in penanda) or "-"
            # The verdict is read from what is STORED, not recomputed here: calling
            # `vonis(db, d.id)` without observations always answers `belum_diketahui` because
            # nothing is compared, so one output row would carry two different answers to the same
            # question.
            v = d.identitas_vonis or identitas.BELUM_DIKETAHUI
            allowed, _v, alasan = identitas.boleh_ditulisi(db, d.id)
            print("  %-22s %-18s %s" % (d.name[:22], v, content[:34]))
            print("      boleh ditulisi: %-5s  %s"
                  % ("YA" if allowed else "tidak", alasan))

        if not run:
            print()
            print("  Tidak ada yang disimpan. Tambahkan --jalankan.")
            print()
            print("  Catatan: pengumpulan PERTAMA selalu berakhir")
            print("  `belum_diketahui` — memang belum ada pembanding. Vonis")
            print("  `sama` baru mungkin pada pengumpulan kedua, dan itu")
            print("  disengaja: bukti yang cocok dengan dirinya sendiri bukan")
            print("  bukti.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

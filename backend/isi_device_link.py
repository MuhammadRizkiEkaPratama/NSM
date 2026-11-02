"""Populate `device_link` with the lab's actual physical paths.

The Dashboard topology map used to draw lines from `flow_koneksi` (who talks to
whom), which looked like a cabling map but was not: LDAP at Site B appeared
directly connected to the web server at Site A, with four devices in between.
This table holds the real cabling.

Links are copied from the `== KABEL ==` section of `gns3/lihat_topologi.py`
output, i.e. the cables actually attached in the `nsm-lab` project:

    LAN-A 0/0  <-->  SW-A 0/0
    SW-A  0/1  <-->  R1   0/0
    R1    1/0  <-->  ISP  0/0
    ISP   0/1  <-->  R2   0/1
    R2    0/0  <-->  SW-B 0/0
    SW-B  0/1  <-->  LAN-B 0/0

Devices are matched by IP address, not `devices.id`, because ids change when a
device is deleted and re-added. Devices that are not found are skipped with a
message instead of failing the whole script.

Idempotent: an existing link for the same pair (in either order) is updated,
not duplicated.

    python isi_device_link.py
"""
import sys

import database
import models
from models import Device, DeviceLink


# (ip_a, ip_b, jenis, keterangan)
#
# `keterangan` names the interface at both ends, as in standard network diagrams,
# so each line can be traced to a physical cable.
JALUR = [
    # ---- Site A: host-only segment (LAN-A in GNS3) -----------------------
    # The laptop, web server, and data server share one Ethernet segment attached to
    # SW-A via the LAN-A cloud. There is no per-machine point-to-point cable, so the
    # type is `segmen` and the map draws it differently from a real cable.
    ("192.168.56.1",   "192.168.56.61", "segmen", "lewat LAN-A (host-only) ke SW-A e0/0"),
    ("192.168.56.103", "192.168.56.61", "segmen", "lewat LAN-A (host-only) ke SW-A e0/0"),
    ("192.168.56.104", "192.168.56.61", "segmen", "lewat LAN-A (host-only) ke SW-A e0/0"),

    # ---- Site A backbone -------------------------------------------------
    ("192.168.56.61",  "192.168.56.60", "kabel",  "SW-A e0/1 <-> R1 f0/0"),

    # ---- WAN: R1 -> ISP -> R2 --------------------------------------------
    # The ISP is not an NSM device (see docs/TOPOLOGY.md): carrier equipment is not
    # monitored, so it appears only as a property of the WAN link, not as a node.
    ("192.168.56.60",  "192.168.20.1",  "wan",    "R1 f1/0 <-> ISP <-> R2 f0/1 (transit ISP)"),

    # ---- Site B backbone -------------------------------------------------
    ("192.168.20.1",   "192.168.20.2",  "kabel",  "R2 f0/0 <-> SW-B e0/0"),
    ("192.168.20.101", "192.168.20.2",  "segmen", "lewat LAN-B ke SW-B e0/1"),

    # ---- Home network -----------------------------------------------------
    # Not part of the lab but still monitored. The laptop's Wi-Fi address changes
    # with each network (`segarkan_ip_lokal` in poller.py), so this row often fails
    # to match and is skipped with a message; that is expected.
    ("192.168.1.43",   "192.168.1.1",   "nirkabel", "Wi-Fi ke gateway rumah"),

    # ---- nsm-files (.105) and nsm-app (.156) -----------------------------
    #
    # Both VMs sit on the same host-only segment as `.103` and `.104`. Without these
    # rows they would be isolated in the `device_link` graph, so `ketergantungan.py`
    # (upstream-down detection) could not trace any path to them.
    #
    # `.156` runs NSM and is the anchor `ketergantungan.py` uses to compute what is
    # upstream of each device; without it every dependency check returns
    # "cannot be determined".
    ("192.168.56.105", "192.168.56.61", "segmen", "lewat LAN-A (host-only) ke SW-A e0/0"),
    ("192.168.56.156", "192.168.56.61", "segmen", "lewat LAN-A (host-only) ke SW-A e0/0"),
]


def main():
    db = database.SessionLocal()
    try:
        # Create the table if missing, so the script works without running the
        # migration first.
        database.Base.metadata.tables["device_link"].create(
            database.engine, checkfirst=True)

        peta = {d.ip_address: d for d in db.query(Device).all() if d.ip_address}

        created = diperbarui = skipped = 0
        for ip_a, ip_b, jenis, note in JALUR:
            a, b = peta.get(ip_a), peta.get(ip_b)
            if not a or not b:
                missing = ip_a if not a else ip_b
                print("  LEWAT  %s <-> %s (tidak ada perangkat beralamat %s)"
                      % (ip_a, ip_b, missing))
                skipped += 1
                continue

            # Links are undirected: look up both A-B and B-A before creating a new row.
            exists = (db.query(DeviceLink)
                   .filter(((DeviceLink.device_a_id == a.id) & (DeviceLink.device_b_id == b.id))
                           | ((DeviceLink.device_a_id == b.id) & (DeviceLink.device_b_id == a.id)))
                   .first())
            if exists:
                exists.jenis = jenis
                exists.keterangan = note
                exists.dibuat_oleh = "isi_device_link.py"
                diperbarui += 1
                print("  UBAH   %-26s <-> %-26s %s" % (a.name, b.name, jenis))
            else:
                db.add(DeviceLink(device_a_id=a.id, device_b_id=b.id,
                                  jenis=jenis, keterangan=note,
                                  dibuat_oleh="isi_device_link.py"))
                created += 1
                print("  BARU   %-26s <-> %-26s %s" % (a.name, b.name, jenis))

        db.commit()
        print("\n%d jalur baru, %d diperbarui, %d dilewati." % (created, diperbarui, skipped))
        if skipped:
            print("Yang dilewati bukan galat: perangkatnya memang belum terdaftar di NSM.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

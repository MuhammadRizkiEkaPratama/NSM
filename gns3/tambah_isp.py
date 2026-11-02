"""Insert an ISP router between R1 and R2 and rename the misleading cloud nodes.

    BEFORE                 R1 ================ R2          1 hop
    AFTER                  R1 === [ ISP ] === R2           2 hops
                        10.10.10.0/30   10.10.20.0/30

A direct cable hides the third-party hop: with an ISP in the middle, traceroute
shows a hop owned by a third party, and shutting down the ISP simulates a carrier
outage (NSM sees site B disappear while site A stays healthy).

Cloud1/Cloud2 are renamed LAN-A/LAN-B: the GNS3 "Cloud" icon means a plug into the
laptop's network card, not a provider network.
"""
import sys
import time

import api

PROYEK = "nsm-lab"
NAMA_BARU_CLOUD = {"Cloud1": "LAN-A", "Cloud2": "LAN-B"}


def peta(pid):
    return dict((n["name"], n) for n in
                api.panggil("GET", "/projects/%s/nodes" % pid))


def main():
    p = api.proyek(PROYEK)
    pid = p["project_id"]
    node = peta(pid)

    print("== 1/4 Mengganti nama yang menyesatkan ==")
    for lama, baru in NAMA_BARU_CLOUD.items():
        if baru in node:
            print("   %s sudah ada" % baru)
        elif lama in node:
            api.panggil("PUT", "/projects/%s/nodes/%s"
                        % (pid, node[lama]["node_id"]), {"name": baru})
            print("   %s -> %s" % (lama, baru))
    node = peta(pid)

    # --- 2. buat ISP ---
    print("\n== 2/4 Membuat router ISP ==")
    if "ISP" in node:
        print("   sudah ada")
    else:
        t = api.template("R2")  # same c2691
        baru = api.panggil(
            "POST", "/projects/%s/templates/%s" % (pid, t["template_id"]),
            {"x": 110, "y": -200, "compute_id": "vm"})
        api.panggil("PUT", "/projects/%s/nodes/%s" % (pid, baru["node_id"]),
                    {"name": "ISP"})
        print("   ISP dibuat (c2691)")
        node = peta(pid)

    # --- 3. potong kabel langsung R1<->R2, sisipkan ISP ---
    print("\n== 3/4 Menyisipkan ISP ke jalur WAN ==")
    id_nama = dict((n["node_id"], nm) for nm, n in node.items())
    for l in api.panggil("GET", "/projects/%s/links" % pid):
        ujung = set(id_nama.get(u["node_id"]) for u in l["nodes"])
        if ujung == {"R1", "R2"}:
            api.panggil("DELETE", "/projects/%s/links/%s" % (pid, l["link_id"]))
            print("   kabel langsung R1<->R2 dilepas")

    terpasang = set()
    for l in api.panggil("GET", "/projects/%s/links" % pid):
        terpasang.add(tuple(sorted((u["node_id"], u["adapter_number"],
                                    u["port_number"]) for u in l["nodes"])))

    # R1 Fa1/0 <-> ISP Fa0/0   and   ISP Fa0/1 <-> R2 Fa0/1
    for a, aa, ap, b, ba, bp, ket in (
            ("R1", 1, 0, "ISP", 0, 0, "R1 Fa1/0 <-> ISP Fa0/0"),
            ("ISP", 0, 1, "R2", 0, 1, "ISP Fa0/1 <-> R2 Fa0/1")):
        kunci = tuple(sorted(((node[a]["node_id"], aa, ap),
                              (node[b]["node_id"], ba, bp))))
        if kunci in terpasang:
            print("   sudah  %s" % ket)
            continue
        api.panggil("POST", "/projects/%s/links" % pid, {"nodes": [
            {"node_id": node[a]["node_id"], "adapter_number": aa,
             "port_number": ap},
            {"node_id": node[b]["node_id"], "adapter_number": ba,
             "port_number": bp}]})
        print("   PASANG %s" % ket)

    # --- 4. nyalakan ISP ---
    print("\n== 4/4 Menyalakan ISP ==")
    isp = peta(pid)["ISP"]
    if isp["status"] == "started":
        print("   sudah jalan")
    else:
        api.panggil("POST", "/projects/%s/nodes/%s/start"
                    % (pid, isp["node_id"]))
        print("   dinyalakan, console telnet %s:%s"
              % (isp["console_host"], isp["console"]))
        time.sleep(3)

    print("\nSelesai. Lanjut: python konfigurasi_isp.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

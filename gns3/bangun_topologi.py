"""Build the two-site GNS3 topology through the API.

    SITE A (main)                                     SITE B (branch)
    Cloud1(eth0) - SW-A - R1 ==== WAN ==== R2 - SW-B - Cloud2(eth2)
    192.168.56.0/24                                192.168.20.0/24

R1 connects to Cloud1 through an access switch (SW-A), like a server and router
plugged into the same switch in a real equipment room.

Safe to re-run: existing nodes are skipped and existing links are not duplicated.
"""
import sys
import time

import api

PROYEK = "nsm-lab"

# (nama, template, x, y)
NODE_BARU = [
    ("SW-A", "SW", -370, -170),
    ("SW-B", "SW", 250, -170),
    ("R2", "R2", 420, -67),
]

# (node_a, adapter_a, port_a, node_b, adapter_b, port_b, description)
#
# Adapter/port numbers:
#   c7200 slot0 C7200-IO-FE  -> adapter 0, port 0       = Fa0/0
#   c7200 slot1 PA-2FE-TX    -> adapter 1, port 0       = Fa1/0
#   c2691 slot0 GT96100-FE   -> adapter 0, port 0 and 1 = Fa0/0, Fa0/1
#   IOU L2                   -> adapter 0, port 0 and 1 = e0/0, e0/1
#   Cloud                    -> port follows ports_mapping order
KABEL = [
    ("Cloud1", 0, 0, "SW-A", 0, 0, "kawat lokasi A (host-only) ke switch A"),
    ("SW-A", 0, 1, "R1", 0, 0, "switch A ke R1 Fa0/0"),
    ("R1", 1, 0, "R2", 0, 1, "WAN: R1 Fa1/0 <-> R2 Fa0/1"),
    ("R2", 0, 0, "SW-B", 0, 0, "R2 Fa0/0 ke switch B"),
    ("SW-B", 0, 1, "Cloud2", 0, 0, "switch B ke kawat lokasi B (eth2)"),
]


def kabar(teks):
    print(teks, flush=True)


def peta_node(pid):
    return dict((n["name"], n) for n in
                api.panggil("GET", "/projects/%s/nodes" % pid))


def hentikan(pid, node):
    if node.get("status") == "started":
        api.panggil("POST", "/projects/%s/nodes/%s/stop" % (pid, node["node_id"]))
        for _ in range(30):
            n = api.panggil("GET", "/projects/%s/nodes/%s"
                            % (pid, node["node_id"]))
            if n["status"] != "started":
                return n
            time.sleep(1)
        raise RuntimeError("%s tidak mau berhenti" % node["name"])
    return node


def main():
    p = api.proyek(PROYEK)
    pid = p["project_id"]
    kabar("Proyek %s (%s)\n" % (p["name"], pid))

    node = peta_node(pid)

    kabar("== 1/5 Menambah port kedua di R1 ==")
    r1 = node["R1"]
    if r1["properties"].get("slot1"):
        kabar("   slot1 sudah terisi (%s), dilewati"
              % r1["properties"]["slot1"])
    else:
        # R1 must be stopped first: Dynamips rejects changing the network cards of a
        # running router, with an error that points elsewhere.
        r1 = hentikan(pid, r1)
        api.panggil("PUT", "/projects/%s/nodes/%s" % (pid, r1["node_id"]),
                    {"properties": {"slot1": "PA-2FE-TX"}})
        kabar("   R1 dihentikan, slot1 diisi PA-2FE-TX (Fa1/0, Fa1/1)")

    kabar("\n== 2/5 Membuat node baru ==")
    for nama, tpl, x, y in NODE_BARU:
        if nama in node:
            kabar("   %s sudah ada, dilewati" % nama)
            continue
        t = api.template(tpl)
        baru = api.panggil(
            "POST", "/projects/%s/templates/%s" % (pid, t["template_id"]),
            {"x": x, "y": y, "compute_id": "vm"})
        # Nodes created from a template get default names (IOU1, R3, ...); rename them.
        if baru["name"] != nama:
            api.panggil("PUT", "/projects/%s/nodes/%s" % (pid, baru["node_id"]),
                        {"name": nama})
        kabar("   %s dibuat dari template %s" % (nama, tpl))

    # --- 3. Cloud lokasi B ---
    kabar("\n== 3/5 Membuat Cloud2 (kawat lokasi B) ==")
    if "Cloud2" in node:
        kabar("   sudah ada, dilewati")
    else:
        api.panggil("POST", "/projects/%s/nodes" % pid, {
            "name": "Cloud2",
            "node_type": "cloud",
            "compute_id": "vm",
            "x": 250, "y": 60,
            "properties": {
                # Map only eth2. Mapping all interfaces would also expose eth0, and cabling to
                # eth0 would silently bridge site B straight to site A, bypassing both routers.
                "ports_mapping": [{
                    "interface": "eth2", "name": "eth2",
                    "port_number": 0, "type": "ethernet"}]
            }})
        kabar("   Cloud2 dibuat, terikat ke eth2 saja")

    node = peta_node(pid)

    kabar("\n== 4/5 Melepas kabel langsung R1 <-> Cloud1 ==")
    dibuang = 0
    for l in api.panggil("GET", "/projects/%s/links" % pid):
        nama_ujung = set()
        for u in l["nodes"]:
            for nm, nd in node.items():
                if nd["node_id"] == u["node_id"]:
                    nama_ujung.add(nm)
        if nama_ujung == {"R1", "Cloud1"}:
            api.panggil("DELETE", "/projects/%s/links/%s" % (pid, l["link_id"]))
            dibuang += 1
    kabar("   %d kabel lama dilepas" % dibuang if dibuang
          else "   tidak ada kabel lama, dilewati")

    kabar("\n== 5/5 Memasang kabel ==")
    terpasang = set()
    for l in api.panggil("GET", "/projects/%s/links" % pid):
        kunci = tuple(sorted((u["node_id"], u["adapter_number"],
                              u["port_number"]) for u in l["nodes"]))
        terpasang.add(kunci)

    for a, aa, ap, b, ba, bp, ket in KABEL:
        if a not in node or b not in node:
            kabar("   LEWAT  %s <-> %s (node belum ada)" % (a, b))
            continue
        kunci = tuple(sorted(((node[a]["node_id"], aa, ap),
                              (node[b]["node_id"], ba, bp))))
        if kunci in terpasang:
            kabar("   sudah  %s" % ket)
            continue
        try:
            api.panggil("POST", "/projects/%s/links" % pid, {"nodes": [
                {"node_id": node[a]["node_id"], "adapter_number": aa,
                 "port_number": ap},
                {"node_id": node[b]["node_id"], "adapter_number": ba,
                 "port_number": bp}]})
            kabar("   PASANG %s" % ket)
        except RuntimeError as e:
            kabar("   GAGAL  %s\n          %s" % (ket, e))

    kabar("\nSelesai. Periksa hasilnya dengan: python lihat_topologi.py")


if __name__ == "__main__":
    sys.exit(main())

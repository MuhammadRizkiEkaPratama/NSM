"""Show the GNS3 topology as-is: nodes, ports, and links.

Used to check the result of `bangun_topologi.py`; a link on the wrong port causes
no error, only unreachable packets.
"""
import api

PROYEK = "nsm-lab"


def main():
    p = api.proyek(PROYEK)
    pid = p["project_id"]
    node = api.panggil("GET", "/projects/%s/nodes" % pid)
    peta = dict((n["node_id"], n) for n in node)

    print("== NODE ==")
    for n in sorted(node, key=lambda x: x["name"]):
        ram = n["properties"].get("ram", "")
        slot = " ".join("slot%d=%s" % (i, n["properties"]["slot%d" % i])
                        for i in range(4)
                        if n["properties"].get("slot%d" % i))
        print("  %-8s %-14s %-9s RAM=%-5s %s"
              % (n["name"], n["node_type"], n["status"], ram, slot))

    print("\n== KABEL ==")
    tautan = api.panggil("GET", "/projects/%s/links" % pid)
    if not tautan:
        print("  (belum ada)")
    for l in tautan:
        bagian = []
        for u in l["nodes"]:
            n = peta.get(u["node_id"], {})
            nama_port = u.get("label", {}).get("text") or "%d/%d" % (
                u["adapter_number"], u["port_number"])
            bagian.append("%s %s" % (n.get("name", "?"), nama_port))
        print("  %s  <-->  %s" % (bagian[0], bagian[1]))

    print("\n== PORT YANG MASIH KOSONG ==")
    dipakai = set()
    for l in tautan:
        for u in l["nodes"]:
            dipakai.add((u["node_id"], u["adapter_number"], u["port_number"]))
    for n in sorted(node, key=lambda x: x["name"]):
        for pt in n.get("ports", []):
            kunci = (n["node_id"], pt["adapter_number"], pt["port_number"])
            if kunci not in dipakai:
                print("  %-8s %s" % (n["name"], pt["short_name"]))


if __name__ == "__main__":
    main()

"""Restart GNS3 nodes whose status is `started` but which are actually dead.

The controller keeps the last known status, which does not change when the
processes inside the GNS3 VM disappear (for example after the VM was stopped and
started again). So the API can report all nodes `started` and the compute
`connected=True` while the console ports refuse connections. The console port is
the cheapest check that only a live process can answer.

`POST /nodes/{id}/start` on a node already marked `started` does nothing, so each
node is stopped first, then started.

Order: switches first, then routers, so routers do not see dead interfaces and
spend extra time recovering neighbors.
"""
import socket
import sys
import time

import api

HOST_KONSOL = "192.168.56.102"

# Switches, then routers, then clouds (a cloud is only a bridge).
URUTAN = ["SW-A", "SW-B", "R1", "R2", "ISP", "LAN-A", "LAN-B"]


def konsol_hidup(port, timeout=2.0):
    """Is anything actually listening on this node's console port?

    The controller's stored status cannot fake this check.
    """
    if not port:
        return None
    try:
        s = socket.create_connection((HOST_KONSOL, port), timeout)
        s.close()
        return True
    except Exception:
        return False


def main():
    paksa = "--paksa" in sys.argv

    pr = api.panggil("GET", "/projects")
    p = ([x for x in pr if x.get("status") == "opened"] or pr)[0]
    pid = p["project_id"]
    print("proyek: %s" % p["name"])

    node = {n["name"]: n for n in api.panggil("GET", "/projects/%s/nodes" % pid)}

    print()
    print("  %-8s %-10s %-8s %s" % ("node", "status API", "konsol", "vonis"))
    print("  " + "-" * 56)
    perlu = []
    for nama in URUTAN:
        n = node.get(nama)
        if not n:
            continue
        hidup = konsol_hidup(n.get("console"))
        if hidup is None:
            vonis = "tidak punya konsol (cloud)"
        elif hidup:
            vonis = "sehat"
        else:
            vonis = "MATI walau statusnya started"
            perlu.append(nama)
        print("  %-8s %-10s %-8s %s"
              # Use `.get`, not `[]`: a freshly reopened node may not have a `status` field yet,
              # and a recovery script must not crash on it.
              % (nama, n.get("status", "?"), "ya" if hidup else
                 ("-" if hidup is None else "TIDAK"), vonis))

    if not perlu and not paksa:
        print()
        print("Semua node yang punya konsol menjawab. Tidak ada yang perlu "
              "dihidupkan ulang.")
        return 0

    sasaran = URUTAN if paksa else perlu
    print()
    print("Menghidupkan ulang: %s" % ", ".join(sasaran))

    for nama in sasaran:
        n = node.get(nama)
        if not n:
            continue
        # Stop first: `start` on an already `started` node does nothing.
        try:
            api.panggil("POST", "/projects/%s/nodes/%s/stop" % (pid, n["node_id"]))
        except Exception as e:
            print("  %-8s stop: %s" % (nama, str(e)[:60]))
        time.sleep(1.0)
        try:
            api.panggil("POST", "/projects/%s/nodes/%s/start" % (pid, n["node_id"]))
            print("  %-8s dinyalakan" % nama)
        except Exception as e:
            print("  %-8s GAGAL start: %s" % (nama, str(e)[:80]))
        # Delay between nodes. Starting five routers at once exhausts the GNS3 VM's CPU and slows
        # everything down.
        time.sleep(2.0)

    print()
    print("Menunggu konsol menjawab (router IOS butuh 1-2 menit untuk boot)...")
    batas = time.time() + 240
    while time.time() < batas:
        belum = [nama for nama in sasaran
                 if node.get(nama) and node[nama].get("console")
                 and not konsol_hidup(node[nama]["console"], 1.5)]
        if not belum:
            print("  semua konsol menjawab")
            break
        time.sleep(10)
    else:
        print("  masih belum menjawab: %s" % ", ".join(belum))
        return 1

    print()
    print("Node hidup. Router IOS masih perlu waktu lagi untuk memuat "
          "konfigurasi dan menemukan tetangganya.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

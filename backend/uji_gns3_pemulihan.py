"""Test `connectors/gns3_pemulihan.py`: recovering GNS3 nodes through the controller
API, replacing Cisco `reload in N` for Dynamips lab devices.

No real GNS3 API calls: `pulihkan()` takes a replaceable `_panggil`, same pattern
as `_exec`/`_notif` in `penjaga_aksi.py`.

Run: py uji_gns3_pemulihan.py
"""
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

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


from connectors import gns3_pemulihan as gp


def _panggil_rekam(rekaman, proyek=None, nodes=None):
    """Fake `_panggil`: records every (method, path) called, answers GET `/projects` with
    `proyek` and GET `.../nodes` with `nodes`.

    Matched with `endswith`, not substring: "/projects/p1/nodes" also contains "/projects".
    """
    def _panggil(metode, jalur, isi=None, timeout=30):
        rekaman.append((metode, jalur))
        if metode != "GET":
            return None
        if jalur == "/projects":
            return proyek if proyek is not None else []
        if jalur.endswith("/nodes"):
            return nodes if nodes is not None else []
        return []
    return _panggil


PROYEK_DIBUKA = [{"project_id": "p1", "name": "Lab", "status": "opened"}]
NODES_R1 = [
    {"node_id": "n-r1", "name": "R1", "console": 5001, "status": "started"},
    {"node_id": "n-swa", "name": "SW-A", "console": 5002, "status": "started"},
]


# ---------------------------------------------------------------------------
print("1. PULIHKAN: STOP DULU, BARU START -- URUTAN DAN NODE YANG BENAR")
print("   (`start` pada node yang statusnya sudah `started` tidak melakukan")
print("    apa pun -- controller GNS3 harus dijatuhkan dulu status-nya)")

rekaman = []
_panggil = _panggil_rekam(rekaman, proyek=PROYEK_DIBUKA, nodes=NODES_R1)
hasil = gp.pulihkan("R1", _panggil=_panggil)

benar("mengembalikan proyek yang benar", hasil.get("proyek") == "Lab")
benar("mengembalikan node yang benar", hasil.get("node") == "R1")
benar("dilaporkan dihentikan", hasil.get("dihentikan") is True)
benar("dilaporkan dinyalakan", hasil.get("dinyalakan") is True)

panggilan = [j for _, j in rekaman]
i_stop = next((i for i, j in enumerate(panggilan) if j.endswith("/n-r1/stop")), None)
i_start = next((i for i, j in enumerate(panggilan) if j.endswith("/n-r1/start")), None)
benar("stop dipanggil", i_stop is not None, "-> %r" % panggilan)
benar("start dipanggil", i_start is not None, "-> %r" % panggilan)
benar("stop MENDAHULUI start",
      i_stop is not None and i_start is not None and i_stop < i_start,
      "-> stop di %s, start di %s" % (i_stop, i_start))
benar("node LAIN (SW-A) TIDAK ikut disentuh",
      not any("n-swa" in j for j in panggilan), "-> %r" % panggilan)

# ---------------------------------------------------------------------------
print("\n2. TIDAK ADA PROYEK YANG TERBUKA -> GagalPulih, BUKAN diam-diam lolos")

try:
    gp.pulihkan("R1", _panggil=_panggil_rekam([], proyek=[]))
    benar("melempar GagalPulih kalau tidak ada proyek terbuka", False,
          "-> tidak melempar apa pun")
except gp.GagalPulih:
    benar("melempar GagalPulih kalau tidak ada proyek terbuka", True)
except Exception as e:
    benar("melempar GagalPulih kalau tidak ada proyek terbuka", False,
          "-> melempar %s, bukan GagalPulih" % type(e).__name__)

# ---------------------------------------------------------------------------
print("\n3. NODE TIDAK DITEMUKAN -> GagalPulih menyebut namanya")

try:
    gp.pulihkan("R99-tidak-ada", _panggil=_panggil_rekam(
        [], proyek=PROYEK_DIBUKA, nodes=NODES_R1))
    benar("melempar GagalPulih untuk node yang tidak ada", False)
except gp.GagalPulih as e:
    benar("melempar GagalPulih untuk node yang tidak ada", True)
    benar("pesannya menyebut nama node yang dicari", "R99-tidak-ada" in str(e),
          "-> %r" % str(e))
except Exception as e:
    benar("melempar GagalPulih untuk node yang tidak ada", False,
          "-> melempar %s" % type(e).__name__)

# ---------------------------------------------------------------------------
print("\n4. GALAT DARI PANGGILAN API SENDIRI TIDAK DITELAN")
print("   (kalau GNS3 server tidak jalan di mesin ini, pemanggilnya harus")
print("    tahu pemulihannya GAGAL, bukan mengira berhasil)")


def _panggil_meledak(metode, jalur, isi=None, timeout=30):
    if jalur == "/projects":
        return PROYEK_DIBUKA
    if jalur.endswith("/nodes"):
        return NODES_R1
    raise gp.GagalPulih("POST %s -> 500 server tidak menjawab" % jalur)


try:
    gp.pulihkan("R1", _panggil=_panggil_meledak)
    benar("galat dari panggilan stop/start diteruskan, bukan ditelan", False)
except gp.GagalPulih as e:
    benar("galat dari panggilan stop/start diteruskan, bukan ditelan", True)
    benar("pesan aslinya ikut terbawa", "500" in str(e), "-> %r" % str(e))

# ---------------------------------------------------------------------------
print("\n5. KREDENSIAL API TIDAK ADA -> GagalPulih yang jelas, bukan galat mentah")

isi = open(os.path.join(DIR, "connectors", "gns3_pemulihan.py"),
           encoding="utf-8").read()
benar("_kredensial melempar GagalPulih kalau user tidak ditemukan",
      "raise GagalPulih" in isi and "Kredensial API GNS3 tidak ditemukan" in isi)

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

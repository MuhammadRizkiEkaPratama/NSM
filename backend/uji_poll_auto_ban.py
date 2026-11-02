"""Test of click-free auto-ban: `poller.poll_auto_ban()`.

The most dangerous poller job: the only one that changes a firewall with no human
click. Guarded safeguards (listed in the `poll_auto_ban()` docstring):

  1. The kill switch (`AUTO_BAN_AKTIF`) is OFF by default and does nothing until
     enabled deliberately.
  2. A rate limit per round is REQUIRED: candidates beyond it are deferred, not
     all blocked at once.
  3. ufw ONLY: candidates with `acl_router_id` do not trigger automatic ACL blocks.
  4. One failed/rejected candidate does not stop the others in the same round.

Runs on a TEMPORARY database with no real SSH: `penjaga_aksi.blokir` is replaced
by a spy via module monkeypatch, and `report_service` functions return canned
data so the test does not depend on other tables.
"""
import os
import sys
import tempfile

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


def sama(nama, dapat, harap):
    benar(nama, dapat == harap, "-> dapat %r, harusnya %r" % (dapat, harap))


def siapkan():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    file = os.path.join(tempfile.mkdtemp(prefix="uji_autoban_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    server1 = models.Device(id=1, name="Server A", ip_address="192.168.56.201",
                            device_type="server", platform="linux", aktif=1,
                            username="nsmro", ssh_key_path="/x/kunci")
    server2 = models.Device(id=2, name="Server B", ip_address="192.168.56.202",
                            device_type="server", platform="linux", aktif=1,
                            username="nsmro", ssh_key_path="/x/kunci")
    db.add_all([server1, server2])
    db.commit()
    return db


print("=" * 74)
print("UJI AUTO-BAN TANPA KLIK (poller.poll_auto_ban, §E3)")
print("=" * 74)

db = siapkan()
import poller
import penjaga_aksi as pa
import report_service as rs

# `poller` and `report_service` now only forward; the logic lives in
# `nsm/pemantau/*` and `report_service/*`. Setting `poller.nama = fake` has no
# effect, so `tambal()` patches the module that actually owns the name. See
# `bantu_tambal.py`.
from bantu_tambal import patch

# poller.SessionLocal() must return the TEST session, not the real database;
# `poll_auto_ban()` creates its own session via SessionLocal().
patch("SessionLocal", lambda: db)
db.close_orig = db.close
db.close = lambda: None


def _kandidat(asal, target_ids, acl_router_id=None, aksi_saran="blokir-otomatis"):
    return {"asal": asal, "pola": "memindai", "keparahan": "tinggi",
           "alasan": "uji", "aksi_saran": aksi_saran, "target": ["x"],
           "target_ids": target_ids, "perintah": "sudo ufw ...",
           "mac": None, "acl_router_id": acl_router_id}


patch("penolakan_acl", lambda db: {})
patch("deteksi_pembobolan", lambda db: {})


def _pasang_rencana(kandidat):
    patch("rencana_penjagaan", lambda db, p, b: {"kandidat": kandidat})


def _spy_blokir(hasil=None, galat=None, ditolak=None):
    """Create a replacement for `penjaga_aksi.blokir` that records every call."""
    panggilan = []

    def _fn(db, ip, device_id=None, alasan="", pola="manual", oleh="auto"):
        panggilan.append({"ip": ip, "device_id": device_id, "oleh": oleh})
        if ditolak and ip in ditolak:
            raise pa.DitolakPengaman("uji: %s ada di allowlist" % ip)
        if galat and ip in galat:
            raise RuntimeError("uji: galat SSH transien untuk %s" % ip)
        return dict(hasil or {"ok": True, "ban_id": 1})
    _fn.panggilan = panggilan
    return _fn


ASLI_BLOKIR = pa.blokir
ASLI_BLOKIR_ACL = pa.block_acl
ASLI_ENABLED = poller.get_auto_ban_enabled
ASLI_MAKS = poller.get_auto_ban_maks_per_putaran


def _reset():
    pa.blokir = ASLI_BLOKIR
    pa.block_acl = ASLI_BLOKIR_ACL
    patch("get_auto_ban_enabled", ASLI_ENABLED)
    patch("get_auto_ban_maks_per_putaran", ASLI_MAKS)


# ---------------------------------------------------------------------------
print("\n1. Kill-switch MATI (bawaan) — tidak menyentuh apa pun")

patch("get_auto_ban_enabled", lambda: False)
_pasang_rencana([_kandidat("10.90.0.1", [1])])
spy = _spy_blokir()
pa.blokir = spy
poller.poll_auto_ban()
sama("blokir() tidak pernah dipanggil", len(spy.panggilan), 0)

# ---------------------------------------------------------------------------
print("\n2. Kill-switch NYALA, tidak ada kandidat — tidak menyentuh apa pun")

patch("get_auto_ban_enabled", lambda: True)
patch("get_auto_ban_maks_per_putaran", lambda: 5)
_pasang_rencana([])
spy = _spy_blokir()
pa.blokir = spy
poller.poll_auto_ban()
sama("blokir() tidak pernah dipanggil (kosong)", len(spy.panggilan), 0)

# ---------------------------------------------------------------------------
print("\n3. Kill-switch NYALA, 2 kandidat blokir-otomatis -> keduanya diblokir")

_pasang_rencana([_kandidat("10.90.0.1", [1]), _kandidat("10.90.0.2", [2])])
spy = _spy_blokir()
pa.blokir = spy
poller.poll_auto_ban()
sama("dua kandidat diproses", len(spy.panggilan), 2)
sama("device_id kandidat 1 = target_ids[0]", spy.panggilan[0]["device_id"], 1)
sama("device_id kandidat 2 = target_ids[0]", spy.panggilan[1]["device_id"], 2)
sama("oleh='auto' untuk keduanya",
    all(p["oleh"] == "auto" for p in spy.panggilan), True)

# ---------------------------------------------------------------------------
print("\n4. Kandidat 'tinjau' (bukan blokir-otomatis) TIDAK ikut diproses")

_pasang_rencana([_kandidat("10.90.0.1", [1], aksi_saran="tinjau")])
spy = _spy_blokir()
pa.blokir = spy
poller.poll_auto_ban()
sama("kandidat 'tinjau' dilewati", len(spy.panggilan), 0)

# ---------------------------------------------------------------------------
print("\n5. Batas laju WAJIB — 3 kandidat, batas 2 -> hanya 2 diproses")

patch("get_auto_ban_maks_per_putaran", lambda: 2)
_pasang_rencana([_kandidat("10.90.0.1", [1]), _kandidat("10.90.0.2", [2]),
                 _kandidat("10.90.0.3", [1])])
spy = _spy_blokir()
pa.blokir = spy
poller.poll_auto_ban()
sama("hanya 2 dari 3 diproses (batas laju)", len(spy.panggilan), 2)
patch("get_auto_ban_maks_per_putaran", lambda: 5)

# ---------------------------------------------------------------------------
print("\n6. Satu kandidat GALAT TEKNIS tidak menghentikan yang lain (§D2.3/§E3)")

_pasang_rencana([_kandidat("10.90.0.1", [1]), _kandidat("10.90.0.2", [2])])
spy = _spy_blokir(galat={"10.90.0.1"})
pa.blokir = spy
poller.poll_auto_ban()
sama("kandidat kedua TETAP diproses walau kandidat pertama galat",
    len(spy.panggilan), 2)

# ---------------------------------------------------------------------------
print("\n7. Satu kandidat DITOLAK PENGAMAN tidak menghentikan yang lain")

_pasang_rencana([_kandidat("10.90.0.1", [1]), _kandidat("10.90.0.2", [2])])
spy = _spy_blokir(ditolak={"10.90.0.1"})
pa.blokir = spy
poller.poll_auto_ban()
sama("kandidat kedua TETAP diproses walau kandidat pertama ditolak pengaman",
    len(spy.panggilan), 2)

# ---------------------------------------------------------------------------
print("\n8. Kandidat dengan acl_router_id TIDAK memicu blokir_acl() otomatis"
     " (§E2 tetap wajib klik manual, sama seperti D2.10)")

_pasang_rencana([_kandidat("10.90.0.1", [1], acl_router_id=9)])
spy_ufw = _spy_blokir()
spy_acl_panggilan = []
pa.blokir = spy_ufw
pa.block_acl = lambda *a, **k: (spy_acl_panggilan.append((a, k))
                                 or {"ok": True})
poller.poll_auto_ban()
sama("blokir() ufw TETAP dipanggil", len(spy_ufw.panggilan), 1)
sama("blokir_acl() TIDAK PERNAH dipanggil otomatis",
    len(spy_acl_panggilan), 0)

# ---------------------------------------------------------------------------
print("\n9. Kandidat tanpa target_ids (kosong) dilewati, tidak KeyError")

_pasang_rencana([_kandidat("10.90.0.1", [])])
spy = _spy_blokir()
pa.blokir = spy
poller.poll_auto_ban()
sama("kandidat tanpa target_ids dilewati", len(spy.panggilan), 0)

_reset()
db.close = db.close_orig
db.close()

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

"""Test of the route layer: the 13 WRITING endpoints and their guards.

`main.py` is the only entry point to NSM's logic. Behind it are 13 endpoints
that write: monitoring settings, intents, firewall IP blocks, and commands to
real network devices.

Tested: the endpoint-layer CONTRACT. Invalid input is rejected with a
page-readable answer instead of a 500; safety rejections reach the caller
unchanged; read endpoints never write.
Not tested: the guard logic itself (`penjaga_aksi`, `sot/katalog`, and
`kirim_perintah` have their own test files).

A correct guard is useless if the endpoint above it swallows the rejection and
replies "ok".

Touches no network and no primary database: `main.SessionLocal` is replaced
with a temporary SQLite, and for firewall endpoints only the REJECTION path is
tested (it happens before any packet is sent).

Run: py uji_main.py
"""
import os
import sys
import tempfile

lolos = 0
gagal = 0


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print(f"  LOLOS  {nama}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama} {ket}")


def cek(nama, dapat, harap):
    global lolos, gagal
    if dapat == harap:
        lolos += 1
        print(f"  LOLOS  {nama}: {dapat!r}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama}: dapat {dapat!r}, harusnya {harap!r}")


import notifikasi_berjenjang as _nb  # noqa: E402

_nb.eskalasi_segera = lambda *a, **k: None

import models  # noqa: E402
import importlib

import main  # noqa: E402
from nsm.antarmuka.http.rute import device as _rute_device
from nsm.antarmuka.http.rute import firewall as _rute_firewall
from nsm.antarmuka.http.rute import sot as _rute_sot

_asli_sessionlocal = main.SessionLocal


def siapkan_db():
    """Temporary SQLite; all session paths are pointed to it.

    All routes take their session as a parameter (`db=Depends(wiring.beri_sesi)`).
    This test calls the route functions directly, so `Depends` is never resolved
    and the session is passed by hand (`rute.f(..., db=db)`).

    The patching below stays as a safety net for paths that may not use the
    parameter (non-route modules, future routes). If it is missed, the test does
    not fail: it PASSES while writing to the primary lab database.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    file = os.path.join(tempfile.mkdtemp(prefix="uji_main_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    main.SessionLocal = factory

    # Also patch every router module that creates its own session. Routes live in
    # `nsm/antarmuka/http/rute/*`, and those modules do `from database import
    # SessionLocal`, so patching `main.SessionLocal` alone is not enough. The patch
    # sweeps all router modules so future routers are covered automatically.
    import pkgutil

    import nsm.antarmuka.http.rute as _paket_rute
    for _info in pkgutil.iter_modules(_paket_rute.__path__):
        _m = importlib.import_module("nsm.antarmuka.http.rute." + _info.name)
        if hasattr(_m, "SessionLocal"):
            _m.SessionLocal = factory
    import nsm.infrastruktur.db.sesi as _sesi
    _sesi.SessionLocal = factory

    return factory()


def buat_device(db, nama="R-uji", ip="10.9.9.9", platform="cisco_ios"):
    d = models.Device(name=nama, ip_address=ip, device_type="router",
                      platform=platform, aktif=1)
    db.add(d)
    db.commit()
    return d


def jumlah_baris(db):
    """Snapshot of row counts per table, to prove something does NOT write."""
    hasil = {}
    for table in models.Base.metadata.sorted_tables:
        try:
            hasil[table.name] = db.execute(table.select()).rowcount
        except Exception:
            from sqlalchemy import func, select
            hasil[table.name] = db.execute(
                select(func.count()).select_from(table)).scalar()
    return hasil


# =============================================================================
print("=" * 74)
print("1. ENDPOINT TULIS ADA, DAN JUMLAHNYA TIDAK BERTAMBAH DIAM-DIAM")
print("   Endpoint tulis adalah permukaan serang NSM. Bertambahnya satu")
print("   tanpa ada yang sadar adalah persis cara permukaan itu melebar.")
print("=" * 74)

# Routes are read flattened, not from `main.app.routes` directly: with
# `APIRouter` that list holds one wrapper node per router, which would yield
# "0 write endpoints". The flattener is borrowed from `uji_daftar_rute.py`.
from uji_daftar_rute import _penyelesai

_semua_rute = {}
for _r in main.app.routes:
    for _jalur, _metode, _nama in _penyelesai(_r):
        _semua_rute.setdefault(_jalur, set()).add(_metode.upper())

rute_tulis = sorted(
    (jalur, tuple(sorted(m for m in metode if m != "HEAD")))
    for jalur, metode in _semua_rute.items()
    if {"POST", "PUT", "PATCH", "DELETE"} & metode)

for jalur, metode in rute_tulis:
    print("   %-42s %s" % (jalur, ",".join(metode)))

# The list, not just the count. A count catches "added" but not "swapped": removing
# one write endpoint and adding another leaves the number unchanged while the
# attack surface changes. A named list makes each addition visible in the diff.
TULIS_DIHARAPKAN = {
    "/devices/{device_id}/aktif",
    "/devices/{device_id}/penting",

    # Command sending to devices: the most dangerous path here, with the most guards
    # (see `penjaga_aksi.py`).
    "/devices/{device_id}/perintah/kirim",
    "/devices/{device_id}/perintah/pratinjau",
    "/devices/{device_id}/perintah/putuskan",
    "/devices/{device_id}/perintah/simpan",

    # Address block: ufw on the host, ACL on the router.
    "/firewall/blokir",
    "/firewall/blokir-acl",
    "/firewall/buka-blokir",

    # Sumber kebenaran konfigurasi.
    "/sot/{device_id}/interface",
    "/sot/{device_id}/nilai",
    "/sot/{device_id}/rute",
    "/sot/{device_id}/vlan",

    # Device discovery (docs/design/DEVICE-AGNOSTIC.md). All three are POST on purpose:
    #
    #   pindai   changes no device, but it is an ACTION: it sends packets to every
    #            address in a subnet, and a GET could be repeated by a reload button.
    #   setujui  the ONLY path from scan results into the `devices` table; the device
    #            it creates has `aktif=0`.
    #   abaikan  stores the decision "not our device" so it survives later scans.
    #
    # None of the three sends commands to a device.
    "/penemuan/pindai",
    "/penemuan/{temuan_id}/setujui",
    "/penemuan/{temuan_id}/abaikan",
}

_jalur_tulis = {jalur for jalur, _ in rute_tulis}
cek("tidak ada endpoint tulis yang tidak terdaftar",
    sorted(_jalur_tulis - TULIS_DIHARAPKAN), [])
cek("tidak ada endpoint tulis yang hilang diam-diam",
    sorted(TULIS_DIHARAPKAN - _jalur_tulis), [])
cek("jumlah endpoint yang bisa MENULIS", len(rute_tulis), len(TULIS_DIHARAPKAN))
benar("semuanya POST -- tidak ada PUT/PATCH/DELETE yang terlewat ditinjau",
      all(m == ("POST",) for _j, m in rute_tulis),
      "-> %r" % [(j, m) for j, m in rute_tulis if m != ("POST",)])

jalur_tulis = {j for j, _m in rute_tulis}
for wajib in ("/firewall/blokir", "/firewall/blokir-acl", "/firewall/buka-blokir",
              "/devices/{device_id}/perintah/kirim",
              "/devices/{device_id}/aktif"):
    benar("endpoint berisiko masih terdaftar: %s" % wajib, wajib in jalur_tulis)


# =============================================================================
print()
print("=" * 74)
print("2. PENOLAKAN PENGAMAN HARUS SAMPAI KE PEMANGGIL, BUKAN JADI GALAT 500")
print("   Pengaman yang benar tidak ada gunanya kalau endpoint di atasnya")
print("   menelan penolakannya. Halaman perlu MENAMPILKAN alasannya.")
print("=" * 74)

db = siapkan_db()
buat_device(db, "Laptop Sendiri", "192.168.56.1", platform="lokal")

hasil = _rute_firewall.firewall_blokir({}, db=db)
print("   -> %r" % hasil)
benar("IP kosong -> ditolak, bukan galat", isinstance(hasil, dict))
cek("  ok=False", hasil.get("ok"), False)
cek("  ditolak=True", hasil.get("ditolak"), True)
benar("  pesannya menjelaskan apa yang salah",
      isinstance(hasil.get("pesan"), str) and len(hasil["pesan"]) > 5,
      "-> %r" % hasil.get("pesan"))

hasil = _rute_firewall.firewall_blokir({"ip": "bukan-alamat-ip", "oleh": "uji"}, db=db)
print("   -> %r" % hasil)
cek("alamat ngawur -> ditolak", hasil.get("ditolak"), True)

# An address REGISTERED as a device must not be blockable. This is the key
# safeguard: blocking NSM's own address would cut NSM off from the network it
# monitors with nothing left to reopen it.
hasil = _rute_firewall.firewall_blokir({"ip": "192.168.56.1", "oleh": "uji"}, db=db)
print("   -> %r" % hasil)
cek("alamat yang dilindungi (allowlist) -> ditolak", hasil.get("ditolak"), True)
benar("  alasannya menyebut allowlist, bukan alasan lain",
      "allowlist" in (hasil.get("pesan") or "").lower(),
      "-> %r" % hasil.get("pesan"))

hasil = _rute_firewall.firewall_blokir_acl({"ip": "192.168.56.1", "oleh": "uji"}, db=db)
cek("jalur ACL memakai pengaman yang SAMA -> juga ditolak",
    hasil.get("ditolak"), True)


# =============================================================================
print()
print("=" * 74)
print("3. VALIDASI KATALOG SoT SAMPAI KE LAPISAN ENDPOINT")
print("   Nilai intent kelak jadi baris CLI sungguhan di router. Kalau")
print("   validasinya berhenti di lapisan bawah dan endpoint menerima apa")
print("   saja, penyuntikan baris perintah cuma soal waktu.")
print("=" * 74)

def baca_jawaban(h):
    """Normalize an endpoint answer into (http_code, dict).

    Two answer shapes coexist in this API, recorded here so they do not change unnoticed:

      firewall : HTTP 200 + {"ok": False, "ditolak": True,   "pesan": "..."}
      SoT      : HTTP 409 + {"ok": False, "ditolak": "message..."}

    Note `ditolak` holds a boolean in one path and text in the other. This is a
    KNOWN inconsistency, not silently fixed.
    """
    import json as _json
    from starlette.responses import Response as _Resp
    if isinstance(h, _Resp):
        return h.status_code, _json.loads(h.body.decode())
    return 200, h


db = siapkan_db()
d = buat_device(db, "Router Lokasi A", "192.168.56.60")

kode, hasil = baca_jawaban(
    _rute_sot.sot_simpan_nilai(d.id, {"nilai": {"kunci_yang_tidak_ada": "x"},
                                 "oleh": "uji"}, db=db))
print("   -> HTTP %s %r" % (kode, hasil))
benar("kunci di luar katalog -> ditolak", hasil.get("ok") is not True,
      "-> %r" % hasil)
cek("  dan dijawab dengan kode galat, bukan 200", kode, 409)

kode, hasil = baca_jawaban(
    _rute_sot.sot_simpan_nilai(d.id, {"nilai": {"hostname": "sah\nno shutdown"},
                                 "oleh": "uji"}, db=db))
print("   -> HTTP %s %r" % (kode, hasil))
benar("aksara baris-baru (suntikan perintah) -> ditolak",
      hasil.get("ok") is not True, "-> %r" % hasil)
benar("  alasannya disebutkan, bukan penolakan diam",
      bool(hasil.get("ditolak")), "-> %r" % hasil)

kode, hasil = baca_jawaban(
    _rute_sot.sot_simpan_nilai(d.id, {"nilai": {"hostname": "R1-sah"},
                                 "oleh": "uji"}, db=db))
print("   -> HTTP %s %r" % (kode, hasil))
benar("nilai yang SAH tetap diterima (pengaman tidak menolak segalanya)",
      hasil.get("ok") is True, "-> %r" % hasil)
cek("  dan dijawab 200", kode, 200)


# =============================================================================
print()
print("=" * 74)
print("4. /devices/{id}/aktif -- menjeda BERARTI BERHENTI MELIHAT,")
print("   bukan mengubah perangkat")
print("=" * 74)

db = siapkan_db()
d = buat_device(db, "Gateway WiFi", "192.168.1.1")

sebelum = jumlah_baris(db)
_rute_device.set_aktif(d.id, aktif=False, alasan="diluar lokasi", oleh="uji", db=db)
db.expire_all()
d2 = db.get(models.Device, d.id)
cek("device benar-benar dijeda", bool(d2.aktif), False)
benar("alasannya ikut tersimpan (jeda yang sah harus bisa dibedakan "
      "dari jeda yang terlupakan)",
      (d2.jeda_alasan or "") == "diluar lokasi", "-> %r" % d2.jeda_alasan)

sesudah = jumlah_baris(db)
benar("menjeda TIDAK menghapus satu baris riwayat pun",
      all(sesudah.get(t, 0) >= sebelum.get(t, 0) for t in sebelum),
      "-> sebelum=%r sesudah=%r" % (sebelum, sesudah))

_rute_device.set_aktif(d.id, aktif=True, alasan=None, oleh="uji", db=db)
db.expire_all()
cek("bisa dilanjutkan lagi", bool(db.get(models.Device, d.id).aktif), True)


# =============================================================================
print()
print("=" * 74)
print("5. ENDPOINT BACA TIDAK BOLEH MENULIS")
print("   Invarian, bukan sekadar kebiasaan: halaman NSM memanggil endpoint")
print("   baca terus-menerus. Satu saja yang diam-diam menulis akan")
print("   menggandakan data sebanyak jumlah orang yang membuka halamannya.")
print("=" * 74)

db = siapkan_db()
d = buat_device(db, "R-baca", "10.1.1.1")

sebelum = jumlah_baris(db)
dibaca = 0
# `/devices` is served by `nsm.antarmuka.http.rute.device` and takes the session as
# an argument. Unlike `device_info` just below, it cannot touch anything but the
# session it is given.

for fungsi, args in [(_rute_device.daftar_device, (db,)),
                     (_rute_device.device_info, (d.id,))]:
    try:
        fungsi(*args)
        dibaca += 1
    except Exception as e:
        print("   (dilewati %s: %s)" % (getattr(fungsi, "__name__", "?"),
                                        str(e)[:60]))
db.expire_all()
sesudah = jumlah_baris(db)
benar("%d endpoint baca dipanggil -> nol baris bertambah" % dibaca,
      sesudah == sebelum,
      "-> sebelum=%r sesudah=%r" % (sebelum, sesudah))


main.SessionLocal = _asli_sessionlocal

if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

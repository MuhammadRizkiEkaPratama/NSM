"""Tests for gate 1b: the evidence that lets a `wajib_manusia` action run automatically.

Three of four recoverers (`layanan_restart`, `interface_up`, `konfig_kembalikan`)
were `wajib_manusia`, a dead end no state could open. Flipping them to
`aman_otomatis` would delete the reasons in `RISIKO_PEMULIH` (each names a real
way automation can hurt) instead of answering them. Instead each reason gets a
CONDITION provable from data NSM already has.

A gate that can always be opened is not a gate, so each condition is tested BOTH
ways: it can open AND it can refuse (same pattern as `uji_pagar_otomasi.py`).

Pure test: temporary SQLite, `config` monkeypatched. No network, no devices, no real `.env`.

Run: py uji_gerbang_bukti.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

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


def siapkan_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    file = os.path.join(tempfile.mkdtemp(prefix="uji_bukti_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    r1 = models.Device(name="Router Uji", ip_address="192.168.56.60",
                       device_type="router", platform="cisco_ios")
    db.add(r1)
    db.commit()
    return db, r1


import config  # noqa: E402
import models  # noqa: E402
import pagar_otomasi as pagar  # noqa: E402

_asli = {
    "layanan": config.get_otomasi_penuh_layanan,
    "interface": config.get_otomasi_penuh_interface,
    "konfig": config.get_otomasi_penuh_konfig,
    "batas": config.get_batas_restart_layanan_harian,
}


def saklar(layanan=False, interface=False, konfig=False, batas=3):
    config.get_otomasi_penuh_layanan = lambda: layanan
    config.get_otomasi_penuh_interface = lambda: interface
    config.get_otomasi_penuh_konfig = lambda: konfig
    config.get_batas_restart_layanan_harian = lambda: batas
    pagar.config = config


def pulihkan():
    config.get_otomasi_penuh_layanan = _asli["layanan"]
    config.get_otomasi_penuh_interface = _asli["interface"]
    config.get_otomasi_penuh_konfig = _asli["konfig"]
    config.get_batas_restart_layanan_harian = _asli["batas"]


SEKARANG = datetime(2026, 8, 22, 10, 0, 0)


try:
    # =========================================================================
    print("=" * 74)
    print("1. SAKLAR MATI = TETAP MILIK MANUSIA")
    print("   Ini keadaan bawaan. Memasang versi baru TIDAK BOLEH diam-diam")
    print("   menyalakan apa pun -- kalau bisa, satu deploy rutin berubah")
    print("   menjadi perubahan kebijakan yang tak seorang pun putuskan.")
    print("=" * 74)

    db, r1 = siapkan_db()
    saklar()  # all down
    for kunci in ("layanan_restart", "interface_up", "konfig_kembalikan"):
        boleh, ket = pagar._bukti_cukup(db, r1.id, kunci, {}, SEKARANG)
        benar("%-18s ditolak saat saklarnya mati" % kunci,
              boleh is False, "-> %r" % ket)
        benar("%-18s alasannya menyebut saklarnya" % kunci,
              "saklar" in ket, "-> %r" % ket)

    # =========================================================================
    print()
    print("=" * 74)
    print("2. INTERFACE: `shutdown` di konfigurasi = keputusan ORANG")
    print("   Kekhawatiran aslinya 'mungkin ada yang sengaja mematikannya'.")
    print("   Di perangkat Cisco, mematikan dengan sengaja MENINGGALKAN JEJAK")
    print("   `shutdown` di running-config -- jadi ini bisa dijawab, bukan")
    print("   dikira-kira.")
    print("=" * 74)

    db, r1 = siapkan_db()
    saklar(interface=True)

    # (a) no snapshot at all -> NOT allowed.
    boleh, ket = pagar._bukti_cukup(db, r1.id, "interface_up",
                                    {"interface": "Fa1/1"}, SEKARANG)
    benar("tanpa potret konfigurasi -> ditolak", boleh is False, "-> %r" % ket)
    benar("alasannya bilang tidak bisa dibedakan, bukan 'aman'",
          "dibedakan" in ket, "-> %r" % ket)

    # (b) snapshot EXISTS and Fa1/1 is shut down -> NOT allowed.
    db.add(models.KonfigSnapshot(
        device_id=r1.id, waktu=SEKARANG - timedelta(minutes=5), sidik="x1",
        teks="interface FastEthernet1/0\n no shutdown\n"
             "interface FastEthernet1/1\n shutdown\n"))
    db.commit()
    boleh, ket = pagar._bukti_cukup(db, r1.id, "interface_up",
                                    {"interface": "Fa1/1"}, SEKARANG)
    benar("Fa1/1 ber-`shutdown` -> DITOLAK (keputusan orang)",
          boleh is False, "-> %r" % ket)
    benar("alasannya menyebut keputusan seseorang",
          "keputusan seseorang" in ket, "-> %r" % ket)

    # (c) Fa1/0 in the SAME snapshot is not shut down -> allowed.
    boleh, ket = pagar._bukti_cukup(db, r1.id, "interface_up",
                                    {"interface": "Fa1/0"}, SEKARANG)
    benar("Fa1/0 tanpa `shutdown` -> BOLEH (gangguan, bukan keputusan)",
          boleh is True, "-> %r" % ket)

    # (d) interface name not sent -> must NOT guess.
    boleh, ket = pagar._bukti_cukup(db, r1.id, "interface_up", {}, SEKARANG)
    benar("tanpa nama interface -> ditolak, bukan menebak",
          boleh is False, "-> %r" % ket)

    # (e) different spellings of the name point to the same thing.
    boleh, _ = pagar._bukti_cukup(db, r1.id, "interface_up",
                                  {"interface": "FastEthernet1/1"}, SEKARANG)
    benar("`FastEthernet1/1` dikenali sama dengan `Fa1/1` -> tetap ditolak",
          boleh is False)

    # =========================================================================
    print()
    print("=" * 74)
    print("3. LAYANAN: restart yang tidak menyembuhkan tidak boleh diulang")
    print("   Bentuk paling umum dari otomasi yang berubah menjadi gangguan")
    print("   yang dibuat sendiri.")
    print("=" * 74)

    db, r1 = siapkan_db()
    saklar(layanan=True, batas=3)

    boleh, ket = pagar._bukti_cukup(db, r1.id, "layanan_restart", {}, SEKARANG)
    benar("belum pernah restart -> BOLEH", boleh is True, "-> %r" % ket)

    # Two ALLOWED restarts in 24 hours -> still allowed (limit 3).
    for i in range(2):
        db.add(models.PagarTindakan(
            device_id=r1.id, kategori="pemulih", kunci="layanan_restart",
            keputusan=pagar.IZIN, alasan="uji", diminta_oleh="uji",
            waktu=SEKARANG - timedelta(hours=i + 1)))
    db.commit()
    boleh, ket = pagar._bukti_cukup(db, r1.id, "layanan_restart", {}, SEKARANG)
    benar("2 dari 3 restart -> masih BOLEH", boleh is True, "-> %r" % ket)

    # The third closes the door.
    db.add(models.PagarTindakan(
        device_id=r1.id, kategori="pemulih", kunci="layanan_restart",
        keputusan=pagar.IZIN, alasan="uji", diminta_oleh="uji",
        waktu=SEKARANG - timedelta(hours=3)))
    db.commit()
    boleh, ket = pagar._bukti_cukup(db, r1.id, "layanan_restart", {}, SEKARANG)
    benar("3 dari 3 restart -> DITOLAK", boleh is False, "-> %r" % ket)
    benar("alasannya menyebut 'butuh orang', bukan cuma angka",
          "butuh orang" in ket, "-> %r" % ket)

    # REFUSED actions must not count: what loads the device is restarts that really happened, not ones prevented.
    db2, r2 = siapkan_db()
    for i in range(5):
        db2.add(models.PagarTindakan(
            device_id=r2.id, kategori="pemulih", kunci="layanan_restart",
            keputusan=pagar.TOLAK, alasan="uji", diminta_oleh="uji",
            waktu=SEKARANG - timedelta(hours=i + 1)))
    db2.commit()
    boleh, ket = pagar._bukti_cukup(db2, r2.id, "layanan_restart", {}, SEKARANG)
    benar("5 penolakan TIDAK ikut terhitung -> tetap BOLEH",
          boleh is True, "-> %r" % ket)

    # A restart 30 hours ago is outside the window.
    db3, r3 = siapkan_db()
    for i in range(4):
        db3.add(models.PagarTindakan(
            device_id=r3.id, kategori="pemulih", kunci="layanan_restart",
            keputusan=pagar.IZIN, alasan="uji", diminta_oleh="uji",
            waktu=SEKARANG - timedelta(hours=30 + i)))
    db3.commit()
    boleh, _ = pagar._bukti_cukup(db3, r3.id, "layanan_restart", {}, SEKARANG)
    benar("restart 30 jam lalu di luar jendela 24 jam -> BOLEH", boleh is True)

    # =========================================================================
    print()
    print("=" * 74)
    print("4. KONFIG: nol korban hilir, dan angkanya harus PASTI")
    print("   Risiko tertinggi dari keempatnya, jadi syaratnya paling ketat.")
    print("=" * 74)

    db, r1 = siapkan_db()
    saklar(konfig=True)

    boleh, ket = pagar._bukti_cukup(
        db, r1.id, "konfig_kembalikan",
        {"dampak_hilir_jumlah": 0, "dampak_hilir_pasti": True}, SEKARANG)
    benar("nol hilir + pasti -> BOLEH", boleh is True, "-> %r" % ket)

    boleh, ket = pagar._bukti_cukup(
        db, r1.id, "konfig_kembalikan",
        {"dampak_hilir_jumlah": 3, "dampak_hilir_pasti": True}, SEKARANG)
    benar("3 perangkat hilir -> DITOLAK", boleh is False, "-> %r" % ket)

    # The deciding case: NOT KNOWING does not mean safe.
    boleh, ket = pagar._bukti_cukup(
        db, r1.id, "konfig_kembalikan",
        {"dampak_hilir_jumlah": 0, "dampak_hilir_pasti": False}, SEKARANG)
    benar("nol TAPI tidak pasti -> DITOLAK", boleh is False, "-> %r" % ket)
    benar("alasannya menyebut ketidakpastiannya",
          "tidak pasti" in ket, "-> %r" % ket)

    # =========================================================================
    print()
    print("=" * 74)
    print("5. KUNCI ASING TIDAK PERNAH LOLOS")
    print("   Bawaan sebuah pengaman harus MENOLAK. Kunci baru yang belum")
    print("   punya syarat tidak boleh ikut terbuka hanya karena ia baru.")
    print("=" * 74)

    db, r1 = siapkan_db()
    saklar(layanan=True, interface=True, konfig=True)
    for kunci in ("hapus_semua", "reboot_device", ""):
        boleh, ket = pagar._bukti_cukup(db, r1.id, kunci, {}, SEKARANG)
        benar("kunci %-14r ditolak" % kunci, boleh is False, "-> %r" % ket)

    # =========================================================================
    print()
    print("=" * 74)
    print("6. GERBANG 1b BUKAN IZIN -- gerbang berikutnya tetap berlaku")
    print("   Lolos bukti hanya memindahkan tindakan dari 'tidak akan pernah'")
    print("   ke 'diperiksa seperti yang lain'. Kalau lolos bukti langsung")
    print("   berarti jalan, seluruh pagar lain jadi hiasan.")
    print("=" * 74)

    db, r1 = siapkan_db()
    saklar(layanan=True)
    _putih_asli = config.get_pagar_daftar_putih
    try:
        config.get_pagar_daftar_putih = lambda: set()  # allowlist EMPTY
        pagar.config = config
        kep = pagar.putuskan(db, r1.id, "pemulih", "layanan_restart",
                             oleh="uji", sekarang=SEKARANG, bukti={})
        benar("lolos bukti TAPI tidak di daftar putih -> tetap ditolak",
              kep.izin is False, "-> %r" % kep.alasan[:90])
        benar("penolakannya dari gerbang daftar putih, bukan gerbang 1b",
              "daftar putih" in kep.alasan, "-> %r" % kep.alasan[:90])
    finally:
        config.get_pagar_daftar_putih = _putih_asli
        pagar.config = config

finally:
    pulihkan()
    pagar.config = config


if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

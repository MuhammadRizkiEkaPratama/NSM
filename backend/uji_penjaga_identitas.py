"""Test of the identity guard on the write path (docs/design/TRAFFIC-IDENTITY-FW.md).

The `reload in 5` safety net protects against a wrong COMMAND, not a wrong
DEVICE: a perfect command sent to someone else's device runs smoothly and
raises no alarm. Four of six lab devices have default addresses that would
match on any network (`192.168.1.1`, `192.168.56.101`, `192.168.56.103`, `192.168.56.1`).

So this tests not whether the verdict is right (that is `uji_identitas.py`) but
whether it actually BLOCKS, and only what it should. A guard that rejects
everything is as useless as one that passes everything; people would disable it.

Runs on a TEMPORARY database. Touches no device.
"""
import os
import re
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


def siapkan():
    """Temporary database holding one router and its snapshot."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    file = os.path.join(tempfile.mkdtemp(prefix="uji_penjaga_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    d = models.Device(name="Router Uji", ip_address="192.168.56.60",
                      device_type="router", platform="cisco_ios", aktif=True)
    db.add(d)
    db.commit()

    db.add(models.KonfigSnapshot(
        device_id=d.id, teks="hostname R1\n!\ninterface FastEthernet0/0\n"
                             " ip address 192.168.56.60 255.255.255.0\n",
        sidik="x" * 8))
    db.commit()
    return db, d


# ---------------------------------------------------------------------------
print("\n1. PENJAGA IKUT DI SETIAP PRATINJAU")
print("   (dijawab saat orang MEMBACA perintahnya, bukan sebagai penolakan")
print("    mendadak sesudah ia menekan kirim)")

import identitas as idn
import report_service

db, d = siapkan()

hasil = report_service.perintah_pratinjau(
    db, d.id, "iface_keterangan",
    {"interface": "FastEthernet0/0", "teks": "catatan uji"})

benar("pratinjau berhasil disusun", hasil.get("ok") is True,
      "-> %r" % hasil.get("galat"))
benar("pratinjau memuat bagian identitas", "identitas" in hasil,
      "-> penjaga tidak terlihat sampai detik terakhir")

ident = hasil.get("identitas") or {}
benar("vonis ikut disebut", "vonis" in ident)
benar("alasan ikut disebut", bool(ident.get("alasan")),
      "-> 'tidak boleh' tanpa sebab memancing orang mematikan penjaganya")

benar("perangkat yang belum pernah dikenali TIDAK boleh ditulisi",
      ident.get("boleh_ditulisi") is False,
      "-> %r" % ident.get("vonis"))

# ---------------------------------------------------------------------------
print("\n2. PRATINJAU TETAP TIDAK MENGIRIM APA PUN")
print("   (penjaga ditambahkan ke jalur ini justru karena ia tidak mengirim)")

benar("pratinjau menyatakan belum terkirim", hasil.get("terkirim") is False,
      "-> %r" % hasil.get("terkirim"))
teks_semua = str(hasil)
benar("tidak ada tanda perintah dieksekusi",
      "terkirim': True" not in teks_semua)

# ---------------------------------------------------------------------------
print("\n3. TIAP VONIS MENGHASILKAN KEPUTUSAN YANG BENAR")

for v, harap in ((idn.SAMA, True),
                 (idn.KEMUNGKINAN_SAMA, False),
                 (idn.BERTENTANGAN, False),
                 (idn.BELUM_DIKETAHUI, False),
                 (None, False)):
    d.identitas_vonis = v
    db.commit()
    h = report_service.perintah_pratinjau(
        db, d.id, "iface_keterangan",
        {"interface": "FastEthernet0/0", "teks": "x"})
    dapat = (h.get("identitas") or {}).get("boleh_ditulisi")
    benar("vonis %-17r -> boleh_ditulisi %s" % (v, harap), dapat is harap,
          "-> dapat %r" % dapat)

# ---------------------------------------------------------------------------
print("\n4. PERANGKAT YANG BENAR TIDAK IKUT TERHALANG")
print("   (penjaga yang menolak semuanya akan dimatikan orang, bukan dipatuhi)")

d.identitas_vonis = idn.SAMA
db.commit()
h = report_service.perintah_pratinjau(
    db, d.id, "iface_keterangan",
    {"interface": "FastEthernet0/0", "teks": "x"})
benar("perangkat dengan identitas terbukti diloloskan",
      (h.get("identitas") or {}).get("boleh_ditulisi") is True)
benar("perintahnya tetap tersusun lengkap", h.get("ok") is True)

# ---------------------------------------------------------------------------
print("\n5. PENANDA IKUT DITAMPILKAN, BUKAN CUMA VONISNYA")
print("   (vonis tanpa buktinya menuntut kepercayaan buta, dan alat keamanan")
print("    adalah tempat terakhir yang pantas menuntut itu)")

idn.catat(db, d.id, "hostname", "R1", "uji")
idn.catat(db, d.id, "serial", "FTX1234ABCD", "uji")
db.commit()
h = report_service.perintah_pratinjau(
    db, d.id, "iface_keterangan",
    {"interface": "FastEthernet0/0", "teks": "x"})
penanda = (h.get("identitas") or {}).get("penanda") or []
jenis = {p["jenis"] for p in penanda}
benar("penanda tersimpan ikut dikirim", {"hostname", "serial"} <= jenis,
      "-> %r" % jenis)

# ---------------------------------------------------------------------------
print("\n6. PEMERIKSAAN DIULANG TIAP PANGGILAN, BUKAN DISIMPAN")
print("   (vonis yang benar sepuluh menit lalu tidak membuktikan apa pun")
print("    tentang perangkat yang menjawab sekarang)")

d.identitas_vonis = idn.SAMA
db.commit()
h1 = report_service.perintah_pratinjau(
    db, d.id, "iface_keterangan", {"interface": "FastEthernet0/0", "teks": "x"})

idn.perbarui_vonis(db, d.id, {"hostname": "SwitchOrangLain",
                              "serial": "ZZZ9999"})
db.commit()
h2 = report_service.perintah_pratinjau(
    db, d.id, "iface_keterangan", {"interface": "FastEthernet0/0", "teks": "x"})

benar("panggilan pertama meloloskan",
      (h1.get("identitas") or {}).get("boleh_ditulisi") is True)
benar("panggilan kedua MEMBLOKIR setelah perangkatnya berganti",
      (h2.get("identitas") or {}).get("boleh_ditulisi") is False,
      "-> jawabannya di-cache; perangkat asing akan lolos")
benar("vonisnya berbunyi bertentangan",
      (h2.get("identitas") or {}).get("vonis") == idn.BERTENTANGAN,
      "-> %r" % (h2.get("identitas") or {}).get("vonis"))

# ---------------------------------------------------------------------------
print("\n7. JALUR PENGUMPULAN TIDAK MENGIRIM PERINTAH APA PUN")
print("   (fungsi inilah yang memutuskan boleh tidaknya menulis; kalau ia")
print("    sendiri menulis, penjaganya justru jadi jalan masuk)")

isi = open(os.path.join(DIR, "identitas_sumber.py"), encoding="utf-8").read()
tanpa_komentar = re.sub(r"#[^\n]*", " ", re.sub(r'""".*?"""', " ", isi, flags=re.S))
for terlarang in ("configure terminal", "conf t", "write memory",
                  "copy run", "reload", "shutdown", "rm -", "sudo "):
    benar("tidak memuat %r" % terlarang, terlarang not in tanpa_komentar,
          "-> jalur pengumpulan identitas menyentuh keadaan perangkat")

db.close()

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

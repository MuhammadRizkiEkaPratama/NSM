"""Test the blast radius: `ketergantungan.hilir()` and its link to the `kirim_perintah` preview.

The existing guard in `kirim_perintah` rejects commands targeting the interface NSM
uses to reach THAT device, but only one hop. Shutting down `Fa1/0` on R1 does not
cut R1 (NSM still enters via `Fa0/0`) yet cuts R2, SW-B and LDAP. "Safe for the
target device" is not "safe for the network".

Invariants:
  1. The numbers are CORRECT for a known topology.
  2. If the graph is INCOMPLETE, the answer is "cannot be determined", NOT "nothing
     depends on it". Doubt must not read as safe.

Uses temporary SQLite + an embedded topology. The preview is called with
`sungguhan=False` (default), so no packet is sent to any device.

Run: py uji_dampak_hilir.py
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
import ketergantungan as K  # noqa: E402


def siapkan_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    file = os.path.join(tempfile.mkdtemp(prefix="uji_hilir_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def dev(db, nama, ip, platform="cisco_ios"):
    d = models.Device(name=nama, ip_address=ip, device_type="router",
                      platform=platform, aktif=1)
    db.add(d)
    db.commit()
    return d


def kabel(db, a, b, jenis="kabel"):
    db.add(models.DeviceLink(device_a_id=a.id, device_b_id=b.id, jenis=jenis,
                             keterangan="uji", dibuat_oleh="uji"))
    db.commit()


def nama_hilir(h):
    return sorted(x["nama"] for x in h)


# =============================================================================
print("=" * 74)
print("1. TOPOLOGI LURUS -- NSM > SW > R1 > R2 > LDAP")
print("   Bentuk yang sama dengan lab sungguhan: satu rantai transit.")
print("=" * 74)

db = siapkan_db()
nsm = dev(db, "NSM sendiri", "10.0.0.1", platform="lokal")
sw = dev(db, "SW-A", "10.0.0.2")
r1 = dev(db, "R1", "10.0.0.3")
r2 = dev(db, "R2", "10.0.0.4")
ldap = dev(db, "LDAP", "10.0.0.5", platform="linux")
for a, b in [(nsm, sw), (sw, r1), (r1, r2), (r2, ldap)]:
    kabel(db, a, b)

g = K.graf(db)
cek("SW-A memikul semua yang di belakangnya",
    nama_hilir(K.hilir(db, sw.id, g=g)), ["LDAP", "R1", "R2"])
cek("R1 memikul dua", nama_hilir(K.hilir(db, r1.id, g=g)), ["LDAP", "R2"])
cek("R2 memikul satu", nama_hilir(K.hilir(db, r2.id, g=g)), ["LDAP"])
cek("LDAP di ujung -> tidak memikul siapa pun",
    nama_hilir(K.hilir(db, ldap.id, g=g)), [])

benar("titik pandang (NSM sendiri) TIDAK menghitung dirinya sendiri",
      K.hilir(db, nsm.id, g=g) == [],
      "-> %r" % nama_hilir(K.hilir(db, nsm.id, g=g)))
benar("perangkat sasaran tidak pernah masuk daftar hilirnya sendiri",
      all(x["id"] != r1.id for x in K.hilir(db, r1.id, g=g)))


# =============================================================================
print()
print("=" * 74)
print("2. PERCABANGAN -- yang di cabang LAIN tidak boleh ikut terhitung")
print("   Kesalahan yang mudah terjadi kalau dihitung dari 'siapa yang jauh'")
print("   alih-alih dari JALUR sesungguhnya.")
print("=" * 74)

db = siapkan_db()
nsm = dev(db, "NSM sendiri", "10.0.0.1", platform="lokal")
sw = dev(db, "SW-A", "10.0.0.2")
r1 = dev(db, "R1", "10.0.0.3")
web = dev(db, "Server Web", "10.0.0.9", platform="linux")
r2 = dev(db, "R2", "10.0.0.4")
for a, b in [(nsm, sw), (sw, r1), (r1, r2), (sw, web)]:
    kabel(db, a, b)

g = K.graf(db)
cek("R1 memikul R2 saja -- Server Web ada di cabang lain",
    nama_hilir(K.hilir(db, r1.id, g=g)), ["R2"])
cek("SW-A memikul KEDUA cabang",
    nama_hilir(K.hilir(db, sw.id, g=g)), ["R1", "R2", "Server Web"])
cek("Server Web tidak memikul siapa pun",
    nama_hilir(K.hilir(db, web.id, g=g)), [])


# =============================================================================
print()
print("=" * 74)
print("3. RAGU BUKAN AMAN -- graf tak lengkap harus KETAHUAN")
print("   Invarian terpenting berkas ini. Perangkat tanpa jalur tercatat")
print("   akan menghasilkan radius dampak 0, dan angka 0 itu MENIPU kalau")
print("   tidak disertai keterangan bahwa grafnya memang tidak tahu.")
print("=" * 74)

db = siapkan_db()
nsm = dev(db, "NSM sendiri", "10.0.0.1", platform="lokal")
sw = dev(db, "SW-A", "10.0.0.2")
r1 = dev(db, "R1", "10.0.0.3")
yatim = dev(db, "Perangkat tanpa jalur", "10.0.0.77", platform="linux")
for a, b in [(nsm, sw), (sw, r1)]:
    kabel(db, a, b)

g = K.graf(db)
lengkap, putus = K.graf_lengkap(db, g)
print("   lengkap=%r  tak terjangkau=%r" % (lengkap, [p["nama"] for p in putus]))
benar("graf dinyatakan TIDAK lengkap", lengkap is False)
cek("dan perangkat yang putus disebut namanya",
    [p["nama"] for p in putus], ["Perangkat tanpa jalur"])

benar("perangkat yatim menghasilkan radius 0 -- itu sebabnya `lengkap` WAJIB "
      "diperiksa bersamanya",
      K.hilir(db, yatim.id, g=g) == [])

# Conversely: once the path is recorded, it counts.
kabel(db, r1, yatim)
g = K.graf(db)
lengkap2, putus2 = K.graf_lengkap(db, g)
benar("sesudah jalurnya dicatat -> graf lengkap lagi", lengkap2 is True,
      "-> putus=%r" % [p["nama"] for p in putus2])
cek("dan R1 sekarang memikulnya",
    nama_hilir(K.hilir(db, r1.id, g=g)), ["Perangkat tanpa jalur"])


# =============================================================================
print()
print("=" * 74)
print("4. TANPA TITIK PANDANG -- tidak ada 'hilir' yang punya arti")
print("   `hilir` diukur DARI NSM. Tanpa device ber-platform 'lokal',")
print("   arah tidak terdefinisi, dan menjawab 0 lebih jujur daripada")
print("   menebak dari bentuk grafnya.")
print("=" * 74)

db = siapkan_db()
a = dev(db, "A", "10.0.0.1")
b = dev(db, "B", "10.0.0.2")
kabel(db, a, b)
benar("tanpa titik pandang -> daftar kosong, bukan galat",
      K.hilir(db, a.id) == [])
lengkap, _p = K.graf_lengkap(db)
benar("dan graf dinyatakan TIDAK lengkap", lengkap is False)


# =============================================================================
print()
print("=" * 74)
print("5. TERSAMBUNG KE PRATINJAU PERINTAH")
print("   Angkanya tidak ada gunanya kalau tidak sampai ke orang yang")
print("   menekan tombol. `sungguhan=False` -> nol paket terkirim.")
print("=" * 74)

import kirim_perintah  # noqa: E402

# The IDENTITY guard is patched here and only here.
#
# `periksa_izin()` refuses to write to a device whose identity was never collected
# (tested in `uji_identitas.py` and `uji_penjaga_identitas.py`). This section tests
# how the blast radius is wired into the preview, not that guard; faking identity data
# would copy another module's rules into this file.
kirim_perintah.identitas.boleh_ditulisi = lambda db, did: (
    True, "sama", "ditambal oleh uji_dampak_hilir.py")

db = siapkan_db()
nsm = dev(db, "NSM sendiri", "10.0.0.1", platform="lokal")
sw = dev(db, "SW-A", "10.0.0.2")
r1 = dev(db, "R1", "10.0.0.3")
r2 = dev(db, "R2", "10.0.0.4")
for x, y in [(nsm, sw), (sw, r1), (r1, r2)]:
    kabel(db, x, y)

# Credentials are needed for `periksa_izin` to pass. Not used to connect; the preview never opens a connection.
for d in (r1, r2):
    d.username = "nsm"
    d.password = "x"
db.commit()

db.add(models.KonfigSnapshot(
    device_id=r1.id, teks=("interface FastEthernet0/0\n"
                           " ip address 10.0.0.3 255.255.255.0\n"
                           "!\n"
                           "interface FastEthernet1/1\n"
                           " shutdown\n!\n"),
    sidik="uji", baris_tambah=0, baris_hapus=0))
db.commit()

r = kirim_perintah.kirim(db, r1.id, "iface_mati",
                         {"interface": "FastEthernet1/1"}, oleh="uji")
print("   dampak_hilir_jumlah=%r pasti=%r" % (r.get("dampak_hilir_jumlah"),
                                              r.get("dampak_hilir_pasti")))
print("   %s" % (r.get("dampak_hilir_kalimat") or "")[:150])
cek("pratinjau TIDAK mengirim apa pun", r.get("terkirim"), False)
cek("radius dampak ikut di rencana", r.get("dampak_hilir_jumlah"), 1)
benar("isinya menyebut perangkat yang benar",
      [x["nama"] for x in (r.get("dampak_hilir") or [])] == ["R2"],
      "-> %r" % r.get("dampak_hilir"))
benar("dinyatakan PASTI karena grafnya lengkap",
      r.get("dampak_hilir_pasti") is True)
benar("kalimatnya bisa dibaca manusia, bukan cuma angka",
      "R2" in (r.get("dampak_hilir_kalimat") or ""),
      "-> %r" % r.get("dampak_hilir_kalimat"))

# Leaf device: zero downstream, and the sentence MUST differ from the "cannot be determined" case (opposite meanings).
db.add(models.KonfigSnapshot(
    device_id=r2.id, teks=("interface FastEthernet0/0\n"
                           " ip address 10.0.0.4 255.255.255.0\n"
                           "!\n"
                           "interface FastEthernet1/1\n shutdown\n!\n"),
    sidik="uji", baris_tambah=0, baris_hapus=0))
db.commit()
r2p = kirim_perintah.kirim(db, r2.id, "iface_mati",
                           {"interface": "FastEthernet1/1"}, oleh="uji")
cek("perangkat ujung -> radius 0", r2p.get("dampak_hilir_jumlah"), 0)
benar("dan kalimatnya menyatakan TIDAK ADA yang bergantung, "
      "bukan 'tidak bisa dipastikan'",
      "Tidak ada perangkat lain" in (r2p.get("dampak_hilir_kalimat") or ""),
      "-> %r" % r2p.get("dampak_hilir_kalimat"))


if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

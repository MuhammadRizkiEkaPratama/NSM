"""Test the "who fetched which file" page: do the numbers answer the right question?

The log reader is tested separately (`uji_sftplog.py`). Guards here:
  1. DELETE and RENAME must not add to any volume number
  2. "fetched by how many" counts PEOPLE, not events
  3. transfers without an owner still appear, flagged, not dropped
  4. no data is stated plainly, not shown as zero
  5. the period really filters

Runs on a TEMPORARY database. Does not touch nsm.db.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

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

    berkas = os.path.join(tempfile.mkdtemp(prefix="uji_berkas_"), "coba.db")
    engine = create_engine("sqlite:///" + berkas)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    d = models.Device(name="Server Berkas", ip_address="192.168.56.103",
                      device_type="server", platform="linux", aktif=True)
    db.add(d)
    db.commit()
    return db, d, models


def tambah(db, models, dev, menit_lalu, pengguna, aksi, jalur,
           baca=0, tulis=0, jalur_baru=None):
    db.add(models.TransferBerkas(
        device_id=dev.id,
        waktu=datetime.now() - timedelta(minutes=menit_lalu),
        pid=1000, pengguna=pengguna, ip_klien="192.168.56.1",
        aksi=aksi, jalur=jalur, jalur_baru=jalur_baru,
        byte_baca=float(baca), byte_tulis=float(tulis)))


print("=" * 74)
print("UJI TAMPILAN PERPINDAHAN BERKAS")
print("=" * 74)

db, dev, models = siapkan()
import report_service

# ---------------------------------------------------------------------------
print("\n1. Tidak ada data dikatakan terus terang")
print("   (nol yang ditampilkan sebagai angka tidak bisa dibedakan dari")
print("    'belum pernah dibaca sama sekali'.)")

kosong = report_service.berkas_transfer(db, "24h")
sama("ada_data False", kosong["ada_data"], False)
benar("alasannya disebut, bukan tabel kosong tanpa keterangan",
      len(kosong.get("alasan") or "") > 30, "-> %r" % kosong.get("alasan"))
sama("dan tabelnya kosong, bukan berisi angka nol", kosong["orang"], [])

# ---------------------------------------------------------------------------
print("\n2. HAPUS dan GANTI_NAMA tidak menambah volume apa pun")
print("   (menghapus berkas 40 MB akan menambah 40 MB ke 'volume yang")
print("    diambil' kalau kolomnya ikut dijumlahkan tanpa syarat — dan angka")
print("    itu tidak akan pernah terlihat salah.)")

tambah(db, models, dev, 10, "dewi", "AMBIL", "/publik/laporan.pdf",
       baca=2097152)
tambah(db, models, dev, 9, "dewi", "HAPUS", "/unggah/lama.txt")
tambah(db, models, dev, 8, "dewi", "GANTI_NAMA", "/unggah/gaji.xlsx",
       jalur_baru="/unggah/catatan.txt")
db.commit()

h = report_service.berkas_transfer(db, "24h")
sama("tiga kejadian terhitung", h["total_kejadian"], 3)
sama("tetapi volumenya hanya dari yang AMBIL", h["total_ambil_teks"], "2.00 MB")
dewi = [o for o in h["orang"] if o["pengguna"] == "dewi"][0]
sama("kejadian dewi tetap tiga", dewi["kejadian"], 3)
sama("volumenya tetap 2 MB", dewi["ambil_byte"], 2097152.0)

sama("tabel per-berkas hanya memuat yang benar-benar berpindah",
     [b["jalur"] for b in h["berkas"]], ["/publik/laporan.pdf"])

# ---------------------------------------------------------------------------
print("\n3. 'Diambil oleh berapa orang' menghitung ORANG, bukan kejadian")
print("   (satu orang mengambil empat kali = kebiasaan kerja;")
print("    empat orang mengambil sekali = sesuatu sedang beredar.")
print("    Totalnya sama persis, artinya berlawanan.)")

for _ in range(3):
    tambah(db, models, dev, 7, "bagas", "AMBIL", "/publik/panduan.pdf",
           baca=1000)
tambah(db, models, dev, 6, "intan", "AMBIL", "/publik/panduan.pdf", baca=1000)
db.commit()

h = report_service.berkas_transfer(db, "24h")
pand = [b for b in h["berkas"] if b["jalur"] == "/publik/panduan.pdf"][0]
sama("diambil empat kali", pand["kali"], 4)
sama("tetapi oleh DUA orang", pand["orang"], 2)

# ---------------------------------------------------------------------------
print("\n4. Transfer tanpa pemilik tetap muncul, ditandai, tidak dibuang")
print("   (membuangnya menyembunyikan perpindahan berkas yang sungguh")
print("    terjadi, hanya karena sesinya sudah berjalan sebelum NSM mulai")
print("    membaca lognya.)")

tambah(db, models, dev, 5, None, "AMBIL", "/publik/rahasia.zip",
       baca=41943040)
db.commit()

h = report_service.berkas_transfer(db, "24h")
tanpa = [o for o in h["orang"] if not o["dikenali"]]
sama("satu baris tanpa pemilik", len(tanpa), 1)
sama("ditulis apa adanya, bukan dikosongkan",
     tanpa[0]["pengguna"], "(tidak diketahui)")
sama("dan volumenya tetap terhitung", tanpa[0]["ambil_teks"], "40.00 MB")

# Sorted by NUMBER OF EVENTS, fair to both sources: SMB (`full_audit`) never reports
# byte sizes, so sorting by bytes made someone active only over SMB lose to a single
# large SFTP download.
benar("satu unduhan besar TIDAK mengalahkan orang dengan lebih banyak kejadian",
      h["orang"][0]["pengguna"] != "(tidak diketahui)",
      "-> urutan: %r" % [o["pengguna"] for o in h["orang"]])
benar("yang tanpa pemilik tenggelam ke bawah, bukan hilang -- tetap ada di daftar",
      any(o["pengguna"] == "(tidak diketahui)" for o in h["orang"]),
      "-> urutan: %r" % [o["pengguna"] for o in h["orang"]])

# ---------------------------------------------------------------------------
print("\n5. Periode benar-benar menyaring")

tambah(db, models, dev, 60 * 24 * 3, "joko", "AMBIL", "/publik/kuno.pdf",
       baca=999)
db.commit()

h24 = report_service.berkas_transfer(db, "24h")
h7d = report_service.berkas_transfer(db, "7d")
benar("baris tiga hari lalu TIDAK muncul di periode 24 jam",
      all(o["pengguna"] != "joko" for o in h24["orang"]),
      "-> %r" % [o["pengguna"] for o in h24["orang"]])
benar("tetapi muncul di periode 7 hari",
      any(o["pengguna"] == "joko" for o in h7d["orang"]),
      "-> %r" % [o["pengguna"] for o in h7d["orang"]])

# ---------------------------------------------------------------------------
print("\n6. Penggantian nama membawa KEDUA namanya sampai ke layar")
print("   ('berkas rahasia diganti namanya jadi sesuatu yang tidak")
print("    mencurigakan' tercatat setengah kalau cuma satu yang terlihat.)")

h = report_service.berkas_transfer(db, "24h")
ganti = [r for r in h["terbaru"] if r["aksi"] == "GANTI_NAMA"]
sama("kejadiannya ada di daftar terbaru", len(ganti), 1)
sama("nama lamanya", ganti[0]["jalur"], "/unggah/gaji.xlsx")
sama("dan nama barunya", ganti[0]["jalur_baru"], "/unggah/catatan.txt")
sama("ukurannya '-' karena tidak ada byte berpindah",
     ganti[0]["ukuran_teks"], "-")

# ---------------------------------------------------------------------------
print("\n7. Catatan tentang scp administrator disebut, bukan didiamkan")
print("   (pembaca yang tidak tahu scp ikut terhitung akan salah")
print("    menyimpulkan siapa yang paling sibuk.)")

benar("catatannya menyebut scp",
      "scp" in (h.get("catatan") or ""), "-> %r" % h.get("catatan"))
benar("dan menyebut bahwa yang ditampilkan ORANG, bukan alamat",
      "ORANG" in (h.get("catatan") or ""), "-> %r" % h.get("catatan"))

# ---------------------------------------------------------------------------
print("\n8. NAMA & JABATAN dari direktori ikut sampai ke layar")
print("   ('arif mengambil 40 MB' adalah baris data; 'Arif Rahman, Auditor,")
print("    mengambil rekaman CCTV' memancing pertanyaan yang benar.)")

db.add(models.OrangLdap(uid="dewi", nama="Dewi Anggraini",
                        jabatan="Staf Keuangan", email="dewi@bsp.id",
                        grup="berkas, ecanteen"))
db.commit()

h = report_service.berkas_transfer(db, "24h")
d_row = [o for o in h["orang"] if o["pengguna"] == "dewi"][0]
sama("nama lengkapnya terbawa", d_row["nama_lengkap"], "Dewi Anggraini")
sama("jabatannya juga", d_row["jabatan"], "Staf Keuangan")
sama("dan uid-nya TIDAK diganti nama", d_row["pengguna"], "dewi")

t_row = [r for r in h["terbaru"] if r["pengguna"] == "dewi"][0]
sama("baris terbaru ikut membawanya", t_row["jabatan"], "Staf Keuangan")

# ---------------------------------------------------------------------------
print("\n9. Yang TIDAK ada di direktori tetap tampil, tanpa nama karangan")
print("   (akun mesin seperti `nsmro` memang bukan orang. Mengarang nama dari")
print("    uid akan membuat akun sistem terbaca seperti manusia.)")

b_row = [o for o in h["orang"] if o["pengguna"] == "bagas"][0]
sama("bagas tidak ada di salinan direktori", b_row["nama_lengkap"], None)
sama("jabatannya juga kosong", b_row["jabatan"], None)
sama("tetapi barisnya tetap ada dengan uid apa adanya",
     b_row["pengguna"], "bagas")

tanpa = [o for o in h["orang"] if not o["dikenali"]][0]
sama("baris tanpa pemilik tidak dicarikan nama", tanpa["nama_lengkap"], None)

# ---------------------------------------------------------------------------
print("\n10. DIREKTORI MATI TIDAK MENGHAPUS NAMA DI RIWAYAT")
print("    (riwayat yang berubah isinya karena server lain sedang mati adalah")
print("     riwayat yang tidak bisa dipercaya. Nama dibaca dari SALINAN di")
print("     basis data, bukan ditanyakan ke direktori saat halaman dibuka —")
print("     jadi tidak ada satu pun kueri LDAP di jalur ini.)")

# Proven by closing off the directory entirely: if report_service quietly contacted LDAP, this line would raise.
import connectors.ldapdir as _ld
_asli = _ld.baca
_ld.baca = lambda *a, **k: (_ for _ in ()).throw(
    RuntimeError("direktori tidak boleh dihubungi saat halaman dibuka"))
try:
    h2 = report_service.berkas_transfer(db, "24h")
    d2 = [o for o in h2["orang"] if o["pengguna"] == "dewi"][0]
    sama("nama tetap muncul walau direktori tak terjangkau",
         d2["nama_lengkap"], "Dewi Anggraini")
finally:
    _ld.baca = _asli

# ---------------------------------------------------------------------------
print("\n11. SMB (byte_baca=0 apa adanya): 'tidak dicatat', BUKAN '0 B'")
print("    (ketahuan nyata 19 Agustus 2026: dewi 87 kejadian SMB terlihat")
print("     seolah tidak pernah mengunduh apa pun, padahal cuma UKURANNYA")
print("     yang tidak pernah dilaporkan `full_audit` Samba. '0 B' dan")
print("     'tidak diketahui' artinya sangat berbeda, dan menyamakan")
print("     keduanya persis bug yang barusan ditemukan.)")
print("    (basis data BARU dan TERPISAH, supaya tidak mengganggu urutan")
print("     atau isi yang sudah diuji di atas.)")

db3, dev3, models3 = siapkan()

for _ in range(5):
    tambah(db3, models3, dev3, 3, "siti", "AMBIL", "/publik/absen_smb.xlsx")
db3.commit()

h3 = report_service.berkas_transfer(db3, "24h")
siti = [o for o in h3["orang"] if o["pengguna"] == "siti"][0]
sama("lima kejadian tetap terhitung", siti["kejadian"], 5)
sama("BUKAN '0 B' -- ditulis terus terang tidak dicatat",
     siti["ambil_teks"], "ukuran tak diketahui (SMB)")

absen = [b for b in h3["berkas"] if b["jalur"] == "/publik/absen_smb.xlsx"][0]
sama("berkas SMB tetap muncul di Per Berkas (dulu tersaring habis)",
     absen["kali"], 5)
sama("total byte-nya juga jujur 'tidak dicatat', bukan 0 B",
     absen["total_teks"], "ukuran tak diketahui (SMB)")

# Control: someone who NEVER fetched anything (only DELETE/RENAME) must show a plain
# "-", NOT "size unknown (SMB)": two different states.
tambah(db3, models3, dev3, 2, "joko", "GANTI_NAMA", "/publik/x.txt",
       jalur_baru="/publik/y.txt")
db3.commit()
h3 = report_service.berkas_transfer(db3, "24h")
joko = [o for o in h3["orang"] if o["pengguna"] == "joko"][0]
sama("joko (cuma GANTI_NAMA, tidak pernah AMBIL) -> '-' polos",
     joko["ambil_teks"], "-")

print("\n12. PER BERKAS MENJUMLAH byte_baca APA `byte_tulis`, WALAU SELURUH")
print("    KEJADIANNYA CUMA KIRIM (byte_tulis), TIDAK PERNAH AMBIL")
print("    (bug diperbaiki 19 Agustus 2026: query lama SUM byte_baca saja --")
print("     berkas yang cuma pernah di-KIRIM/SALIN [mis. upload SFTP] akan")
print("     terlihat '0 byte' walau ukurannya sebenarnya sudah diketahui)")

tambah(db3, models3, dev3, 4, "arif", "KIRIM", "/publik/laporan_kirim.pdf",
       tulis=204800)
tambah(db3, models3, dev3, 3, "arif", "KIRIM", "/publik/laporan_kirim.pdf",
       tulis=204800)
db3.commit()
h3 = report_service.berkas_transfer(db3, "24h")
lapor = [b for b in h3["berkas"] if b["jalur"] == "/publik/laporan_kirim.pdf"][0]
sama("dua kejadian KIRIM terhitung", lapor["kali"], 2)
benar("total_byte BUKAN nol -- byte_tulis ikut terjumlah",
      lapor["total_byte"] == 409600.0, "-> %r" % lapor["total_byte"])
benar("total_teks angka sungguhan, BUKAN 'ukuran tak diketahui (SMB)'",
      "tak diketahui" not in lapor["total_teks"], "-> %r" % lapor["total_teks"])

print("\n13. PERINTAH (auditd/SSH) TERPISAH dari BERKAS (SMB/SFTP)")
print("    (sempat digabung jadi satu 'Log Kejadian' kronologis, dipisah")
print("     lagi 19 Agustus 2026: 'berkas apa disentuh' dan 'perintah apa")
print("     diketik' dua pertanyaan berbeda, jangan disamakan)")

db4, dev4, models4 = siapkan()
tambah(db4, models4, dev4, 5, "dewi", "AMBIL", "/publik/laporan.pdf")
db4.add(models4.PerintahPengguna(
    device_id=dev4.id, waktu=datetime.now() - timedelta(minutes=3),
    pengguna="arif", perintah="ls", argumen="ls -la /srv/sharing",
    berhasil=1, ip_klien="192.168.56.1", sesi="2610"))
db4.add(models4.PerintahPengguna(
    device_id=dev4.id, waktu=datetime.now() - timedelta(minutes=2),
    pengguna="arif", perintah="rm", argumen="rm rahasia.txt",
    berhasil=0, ip_klien="192.168.56.1", sesi="2610"))
db4.commit()

h4 = report_service.berkas_transfer(db4, "24h")
benar("terbaru CUMA berisi aktivitas berkas (1 baris AMBIL, bukan 3)",
      len(h4["terbaru"]) == 1, "-> %r" % h4["terbaru"])
benar("tidak ada baris beraksi 'PERINTAH' yang menyelip ke terbaru",
      not any(t.get("aksi") == "PERINTAH" for t in h4["terbaru"]))

benar("riwayat_perintah berisi TEPAT 2 baris (ls + rm)",
      len(h4["riwayat_perintah"]) == 2, "-> %r" % h4["riwayat_perintah"])
rp = sorted(h4["riwayat_perintah"], key=lambda r: r["waktu"])
sama("perintah pertama teksnya utuh", rp[0]["perintah"], "ls -la /srv/sharing")
sama("perintah kedua tercatat GAGAL (rm ditolak)", rp[1]["hasil"], "gagal")
sama("pengguna terbawa", rp[0]["pengguna"], "arif")
benar("dikenali=True (pengguna bukan None)", rp[0]["dikenali"] is True)

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

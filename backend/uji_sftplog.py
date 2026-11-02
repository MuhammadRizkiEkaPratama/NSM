"""Tests for the SFTP log reader: is "who fetched which file" really answered.
A parsing defect shows up as plausible numbers (an unrecognized line looks like "nobody fetched anything"), so this checks:
  1. user names carry across poller rounds via the pid map
  2. transfers from an unknown pid are still recorded, with an empty owner
  3. a pid reused by the system does not inherit the old owner
  4. direction (fetch/send) comes from the byte counts, not the flags
  5. server UTC timestamps are shifted to local time
Sample lines are copied from a real auth.log.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from connectors import sftplog

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
    benar(nama, dapat == harap, "-> dapat %r, harap %r" % (dapat, harap))


NYATA = """\
2026-08-08T23:15:40.390913+00:00 testUbuntu internal-sftp[607516]: session opened for local user dewi from [192.168.56.1]
2026-08-08T23:15:40.393654+00:00 testUbuntu internal-sftp[607516]: opendir "/"
2026-08-08T23:15:40.399457+00:00 testUbuntu internal-sftp[607516]: closedir "/"
2026-08-08T23:15:40.410180+00:00 testUbuntu internal-sftp[607516]: open "/publik/laporan-keuangan-q2.pdf" flags READ mode 0666
2026-08-08T23:15:40.618256+00:00 testUbuntu internal-sftp[607516]: close "/publik/laporan-keuangan-q2.pdf" bytes read 2097152 written 0
2026-08-08T23:15:40.620473+00:00 testUbuntu internal-sftp[607516]: open "/unggah/dari-dewi.txt" flags WRITE,CREATE,TRUNCATE mode 0666
2026-08-08T23:15:40.627479+00:00 testUbuntu internal-sftp[607516]: close "/unggah/dari-dewi.txt" bytes read 0 written 1500
2026-08-08T23:15:40.630686+00:00 testUbuntu internal-sftp[607516]: session closed for local user dewi from [192.168.56.1]
""".splitlines()

print("=" * 74)
print("UJI PEMBACA LOG SFTP")
print("=" * 74)

# ---------------------------------------------------------------------------
print("\n1. Satu sesi utuh: siapa, berkas apa, berapa byte, arah mana")

transfer, sesi, selesai = sftplog.gabung(NYATA, {})

sama("dua transfer tercatat", len(transfer), 2)
sama("opendir/closedir TIDAK ikut tercatat",
     [t["jalur"] for t in transfer],
     ["/publik/laporan-keuangan-q2.pdf", "/unggah/dari-dewi.txt"])

unduh, unggah = transfer
sama("unduhan bernama pemiliknya", unduh["pengguna"], "dewi")
sama("dan membawa alamat asalnya", unduh["ip_klien"], "192.168.56.1")
sama("dikenali sebagai AMBIL", unduh["aksi"], "AMBIL")
sama("besarnya utuh, bukan dibulatkan", unduh["byte_baca"], 2097152.0)

sama("unggahan dikenali sebagai KIRIM", unggah["aksi"], "KIRIM")
sama("dan byte-nya di kolom tulis", unggah["byte_tulis"], 1500.0)

sama("sesi yang ditutup tidak lagi terbuka", sesi, {})
sama("dan pid-nya dilaporkan selesai", selesai, [607516])

# ---------------------------------------------------------------------------
print("\n2. Zona waktu VM (UTC) digeser ke waktu lokal, TIDAK dibuang")
print("   (VM berjalan di UTC, NSM di WIB. Membuang offsetnya menggeser")
print("    seluruh riwayat tujuh jam dan membuatnya tak bisa disandingkan")
print("    dengan event lain di basis data.)")

t = sftplog.urai_waktu("2026-08-08T23:15:40.390913+00:00")
asal = datetime(2026, 8, 8, 23, 15, 40, 390913, tzinfo=timezone.utc)
harusnya = asal.astimezone().replace(tzinfo=None)
sama("waktunya digeser ke zona mesin ini", t, harusnya)

# Independent oracle: the difference between raw log time and parsed time must equal this machine's timezone offset exactly.
geser = t - asal.replace(tzinfo=None)
sama("selisihnya persis sebesar offset zona mesin ini",
     geser, asal.astimezone().utcoffset())

# ---------------------------------------------------------------------------
print("\n3. NAMA ORANG MENYEBERANG ANTAR PUTARAN POLLER")
print("   (nama hanya muncul di baris 'session opened'. Sesi yang dibuka")
print("    pukul 10.00 bisa masih mengirim berkas pukul 10.30, sementara")
print("    poller sudah berputar puluhan kali di antaranya.)")

putaran1 = [NYATA[0]]
putaran2 = NYATA[3:5]

t1, sesi1, _ = sftplog.gabung(putaran1, {})
sama("putaran pertama belum menghasilkan transfer", len(t1), 0)
benar("tetapi sudah mengingat siapa pemilik pid itu",
      sesi1.get(607516, {}).get("pengguna") == "dewi", "-> %r" % (sesi1,))

t2, _sesi2, _ = sftplog.gabung(putaran2, sesi1)
sama("putaran kedua mencatat transfernya", len(t2), 1)
sama("dan tahu itu milik dewi, walau barisnya tidak menyebut nama",
     t2[0]["pengguna"], "dewi")

# ---------------------------------------------------------------------------
print("\n4. Transfer dari pid TAK DIKENAL tetap dicatat, pemiliknya kosong")
print("   (membuangnya menyembunyikan perpindahan berkas yang sungguh")
print("    terjadi, hanya karena NSM kebetulan mulai membaca di tengah sesi —")
print("    dan yang hilang justru sesi panjang, yang biasanya berkas besar.)")

t3, _s, _sel = sftplog.gabung(putaran2, {})
sama("tetap satu baris, tidak dibuang", len(t3), 1)
sama("pemiliknya kosong, bukan ditebak", t3[0]["pengguna"], None)
sama("tetapi berkas dan besarnya tetap terbaca",
     (t3[0]["jalur"], t3[0]["byte_baca"]),
     ("/publik/laporan-keuangan-q2.pdf", 2097152.0))

# ---------------------------------------------------------------------------
print("\n5. PID YANG DIPAKAI ULANG tidak mewarisi nama pemilik lama")
print("   (sistem operasi memakai ulang nomor proses. Tanpa penjagaan ini,")
print("    berkas yang diambil orang lain tercatat atas nama orang sebelumnya")
print("    — kesalahan yang justru terlihat sangat meyakinkan di laporan.)")

daur_ulang = [
    NYATA[0],                                    # dewi buka sesi pid 607516
    NYATA[7],                                    # dewi tutup sesi
    '2026-08-08T23:20:00.000000+00:00 testUbuntu internal-sftp[607516]: '
    'session opened for local user arif from [192.168.56.9]',
    '2026-08-08T23:20:01.000000+00:00 testUbuntu internal-sftp[607516]: '
    'close "/publik/rekaman-cctv-lobi.zip" bytes read 41943040 written 0',
]
t4, _s, _sel = sftplog.gabung(daur_ulang, {})
sama("satu transfer", len(t4), 1)
sama("atas nama ARIF, bukan dewi", t4[0]["pengguna"], "arif")
sama("dan alamatnya ikut yang baru", t4[0]["ip_klien"], "192.168.56.9")

# ---------------------------------------------------------------------------
print("\n6. Arah diambil dari BYTE, bukan dari flags")
print("   (berkas yang dibuka untuk ditulis lalu batal tetap berbunyi WRITE")
print("    di flags, padahal tidak ada satu byte pun berpindah.)")

sama("baca > 0 -> AMBIL", sftplog.arah(500, 0, "WRITE,CREATE"), "AMBIL")
sama("tulis > 0 -> KIRIM", sftplog.arah(0, 500, "READ"), "KIRIM")
sama("dua-duanya nol, flags READ -> AMBIL", sftplog.arah(0, 0, "READ"), "AMBIL")
sama("dua-duanya nol, flags WRITE -> KIRIM (berkas kosong yang diunggah)",
     sftplog.arah(0, 0, "WRITE,CREATE"), "KIRIM")
sama("nol dan tanpa flags -> BUKA, bukan menebak arah",
     sftplog.arah(0, 0, ""), "BUKA")

# ---------------------------------------------------------------------------
print("\n7. Aksi selain transfer ikut terbaca")
print("   ('berkas rahasia diganti namanya jadi sesuatu yang tidak")
print("    mencurigakan' adalah kejadian yang pantas terlihat.)")

lain = [
    NYATA[0],
    '2026-08-08T23:16:00.000000+00:00 testUbuntu internal-sftp[607516]: '
    'remove name "/unggah/dari-dewi.txt"',
    '2026-08-08T23:16:01.000000+00:00 testUbuntu internal-sftp[607516]: '
    'rename old "/unggah/gaji.xlsx" new "/unggah/catatan.txt"',
    '2026-08-08T23:16:02.000000+00:00 testUbuntu internal-sftp[607516]: '
    'mkdir name "/unggah/arsip" mode 0777',
]
t5, _s, _sel = sftplog.gabung(lain, {})
sama("tiga aksi terbaca", [t["aksi"] for t in t5],
     ["HAPUS", "GANTI_NAMA", "BUAT_FOLDER"])
sama("penggantian nama menyimpan KEDUA namanya",
     (t5[1]["jalur"], t5[1]["jalur_baru"]),
     ("/unggah/gaji.xlsx", "/unggah/catatan.txt"))
sama("aksi biasa tidak menyimpan jalur_baru", t5[0]["jalur_baru"], None)

# ---------------------------------------------------------------------------
print("\n8. Baris yang bukan milik sftp diabaikan, bukan bikin kacau")

bukan = [
    "2026-08-08T23:00:00.000000+00:00 testUbuntu sshd-session[1]: "
    "Accepted password for doni from 192.168.56.1 port 5000 ssh2",
    "",
    "sampah tanpa bentuk",
    "2026-08-08T23:00:01.000000+00:00 testUbuntu sudo: doni : TTY=pts/0",
]
t6, s6, _sel = sftplog.gabung(bukan, {})
sama("tidak ada transfer dari baris asing", len(t6), 0)
sama("dan tidak ada sesi yang terbentuk", s6, {})
sama("urai_baris menolak baris asing", sftplog.urai_baris(bukan[0]), None)

# ---------------------------------------------------------------------------
print("\n9. SCP ikut tertangkap, dan itu memang benar")
print("   (OpenSSH modern menjalankan scp di atas protokol SFTP. Pemantau")
print("    yang menyembunyikan lalu lintas administratornya sendiri membuat")
print("    angkanya tidak bisa dipertanggungjawabkan.)")

scp = [
    "2026-08-08T23:14:28.876693+00:00 testUbuntu internal-sftp[606966]: "
    "session opened for local user doni from [192.168.56.1]",
    "2026-08-08T23:14:28.973725+00:00 testUbuntu internal-sftp[606966]: "
    'open "/tmp/pasang-sftp.sh" flags WRITE,CREATE mode 0666',
    "2026-08-08T23:14:28.974264+00:00 testUbuntu internal-sftp[606966]: "
    'close "/tmp/pasang-sftp.sh" bytes read 0 written 9343',
]
t7, _s, _sel = sftplog.gabung(scp, {})
sama("transfer scp administrator tercatat juga", len(t7), 1)
sama("sebagai KIRIM oleh doni",
     (t7[0]["aksi"], t7[0]["pengguna"]), ("KIRIM", "doni"))

# ---------------------------------------------------------------------------
print("\n10. REGRESI 18 Agustus 2026: byte NUL di dalam kurung siku ip klien")
print("    (audit menyeluruh setelah cacat sejenis TERBUKTI nyata di")
print("    akseslog.py -- ip_klien ber-byte-NUL yang membatalkan seluruh")
print("    transaksi penyimpanan. Belum pernah kejadian di baris SFTP,")
print("    tapi pola regex-nya identik, jadi diperketat sekarang juga.)")

baris_rusak = [
    "2026-08-15T19:19:58.000000+00:00 testUbuntu internal-sftp[999999]: "
    "session opened for local user rina from [" + ("\x00" * 300) + "192.168.56.1]",
]
t8, sesi8, _sel8 = sftplog.gabung(baris_rusak, {})
benar("baris session-opened ber-NUL TIDAK tercatat sebagai sesi",
     999999 not in sesi8,
     "-> sesi8 = %r" % sesi8)

# Directly tests the second-line-of-defense trimming (`_potong`), independent of the regex.
ip_panjang = "9" * 500
sama("_potong() ip_klien dipotong ke <=45 walau nilainya sepanjang 500",
    len(sftplog._potong(ip_panjang, 45)), 45)
sama("_potong() pengguna dipotong ke <=100 walau nilainya sepanjang 500",
    len(sftplog._potong("x" * 500, 100)), 100)
sama("_potong() nilai None tetap None (tidak meledak)",
    sftplog._potong(None, 45), None)

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

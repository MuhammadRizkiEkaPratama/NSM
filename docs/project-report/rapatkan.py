"""Pemangkasan terakhir naskah versi kedua supaya isinya muat di bawah 35 halaman.

Tiga jenis pemangkasan dikerjakan di sini, dan ketiganya dipilih karena
menghemat halaman tanpa membuang keterangan:

1. Daftar bernomor yang isinya bukan benar-benar daftar diubah jadi paragraf.
   Tiap butir memakai indentasi gantung dan jarak antarbutir, sehingga satu
   butir dua baris memakan ruang lebih besar daripada dua baris paragraf biasa.
2. Dua tabel kecil dilebur ke dalam kalimat, karena isinya cukup disebut.
3. Kalimat yang mengulang keterangan di tempat lain dihapus.

Dijalankan sekali. Berkas aslinya sudah tersimpan di Git, jadi hasil
pemangkasan ini bisa dibandingkan atau dikembalikan.
"""
import io
import os

AKAR = os.path.dirname(os.path.abspath(__file__))


def ganti(nama, pasangan):
    jalur = os.path.join(AKAR, nama)
    s = io.open(jalur, encoding="utf-8").read()
    for lama, baru in pasangan:
        if lama not in s:
            print("  LEWAT (tidak cocok):", lama[:60].replace("\n", " "))
            continue
        s = s.replace(lama, baru)
    io.open(jalur, "w", encoding="utf-8").write(s)
    print("  selesai:", nama, "->", len(s.split()), "kata")


print("Bab I")
ganti("v2-01-bab1.md", [
    # Rumusan masalah tetap daftar (memang daftar), tetapi batasan masalah
    # dijadikan paragraf karena butirnya panjang-panjang.
    ("""1. Seluruh implementasi dilakukan pada laboratorium tervirtualisasi milik pribadi penulis yang dibangun menggunakan emulator GNS3 dengan dukungan QEMU dan KVM, ditambah mesin virtual Oracle VirtualBox.
2. Proyek ini tidak menyentuh, tidak memodifikasi, dan tidak mengambil data dari jaringan produksi PT Bumi Siak Pusako. Seluruh alamat yang muncul adalah alamat privat sesuai RFC 1918 (Rekhter dkk., 1996) yang hanya berlaku di dalam laboratorium.
3. Citra sistem operasi Cisco IOS yang digunakan dipakai semata-mata untuk pembelajaran pribadi dan tidak mewakili kepentingan perusahaan.
4. Sistem SCADA dan perangkat kendali proses tidak menjadi objek implementasi, dan jaringan *Operational Technology* dibahas hanya sebagai latar belakang.
5. Laboratorium tidak memiliki jalur cadangan antarlokasi, sehingga pengujian pemulihan jalur melalui protokol perutean dinamis tidak dapat dilakukan.
6. Seluruh kata sandi, nilai *hash*, dan kunci yang muncul dalam laporan telah disamarkan, sedangkan nama akun tetap ditampilkan karena diperlukan untuk menjelaskan rancangan pembagian hak akses.""",
     """Seluruh implementasi dilakukan pada laboratorium tervirtualisasi milik pribadi penulis yang dibangun menggunakan emulator GNS3 dengan dukungan QEMU dan KVM, ditambah mesin virtual Oracle VirtualBox. Proyek ini tidak menyentuh, tidak memodifikasi, dan tidak mengambil data dari jaringan produksi PT Bumi Siak Pusako, dan seluruh alamat yang muncul adalah alamat privat sesuai RFC 1918 (Rekhter dkk., 1996) yang hanya berlaku di dalam laboratorium. Citra sistem operasi Cisco IOS yang digunakan dipakai semata-mata untuk pembelajaran pribadi dan tidak mewakili kepentingan perusahaan.

Sistem SCADA dan perangkat kendali proses tidak menjadi objek implementasi, dan jaringan *Operational Technology* dibahas hanya sebagai latar belakang. Laboratorium tidak memiliki jalur cadangan antarlokasi, sehingga pengujian pemulihan jalur melalui protokol perutean dinamis tidak dapat dilakukan. Seluruh kata sandi, nilai *hash*, dan kunci yang muncul dalam laporan telah disamarkan, sedangkan nama akun tetap ditampilkan karena diperlukan untuk menjelaskan rancangan pembagian hak akses."""),
])

print("Bab III")
ganti("v2-03-bab3.md", [
    # Subbab otomasi tertutup dilebur ke subbab otomasi jaringan.
    ("""## 3.5 Otomasi Tertutup dan Pagar Pengamannya

Otomasi tertutup adalah rangkaian deteksi, pengambilan keputusan, tindakan perbaikan, dan verifikasi hasil yang berjalan tanpa campur tangan manusia. Rangkaian semacam ini menuntut pembatas, karena tindakan otomatis yang salah dapat memperluas gangguan alih-alih memperbaikinya.

Pola *circuit breaker* menghentikan pemanggilan yang berulang kali gagal, lalu memulihkan diri setelah ada satu keberhasilan (Nygard, 2018). Pola ini berbeda dari pembatasan laju, karena pembatasan laju hanya mengurangi seberapa sering sebuah tindakan dicoba sedangkan *circuit breaker* menghentikan tindakan yang tidak pernah berhasil. Praktik rekayasa keandalan situs melengkapinya dengan sasaran tingkat layanan beserta anggaran galat, yaitu jumlah gangguan yang masih dapat diterima dalam satu periode, sehingga pertanyaan apakah sebuah angka ketersediaan sudah memadai dapat dijawab (Beyer dkk., 2016).

## 3.6 Administrasi Sistem""",
     """## 3.5 Otomasi Tertutup dan Administrasi Sistem

Otomasi tertutup adalah rangkaian deteksi, pengambilan keputusan, tindakan perbaikan, dan verifikasi hasil yang berjalan tanpa campur tangan manusia. Rangkaian semacam ini menuntut pembatas, karena tindakan otomatis yang salah dapat memperluas gangguan alih-alih memperbaikinya. Pola *circuit breaker* menghentikan pemanggilan yang berulang kali gagal lalu memulihkan diri setelah ada satu keberhasilan (Nygard, 2018), dan pola ini berbeda dari pembatasan laju yang hanya mengurangi seberapa sering sebuah tindakan dicoba. Praktik rekayasa keandalan situs melengkapinya dengan sasaran tingkat layanan beserta anggaran galat, yaitu jumlah gangguan yang masih dapat diterima dalam satu periode (Beyer dkk., 2016)."""),
])

print("Bab IV")
ganti("v2-04-bab4.md", [
    # Tabel blok alamat dilebur ke kalimat.
    ("""Pengalamatan memisahkan segmen jaringan lokal dari segmen transit antarperangkat perutean, sebagaimana disajikan pada Tabel 4.3. Kedua jaringan lokal memakai prefiks /24, sedangkan kedua segmen transit memakai prefiks /30 karena hanya perlu menampung dua alamat pada masing-masing ujung tautan.

!TABEL[Tabel 4.3 Pembagian blok alamat]

| Segmen | Blok | Prefiks | Penghuni |
|---|---|---|---|
| Jaringan lokal Lokasi A | 192.168.56.0 | /24 | R1, SW-A, nsm-app, testUbuntu, nsm-data, file-server, laptop |
| Jaringan lokal Lokasi B | 192.168.20.0 | /24 | R2, SW-B, nsm-ubuntu |
| Transit R1 menuju ISP | 10.10.10.0 | /30 | dua ujung tautan |
| Transit ISP menuju R2 | 10.10.20.0 | /30 | dua ujung tautan |

Perutean""",
     """Pengalamatan memisahkan segmen jaringan lokal dari segmen transit antarperangkat perutean. Jaringan lokal Lokasi A memakai blok 192.168.56.0/24 dan Lokasi B memakai 192.168.20.0/24, sedangkan kedua segmen transit memakai 10.10.10.0/30 antara R1 dan penyedia jasa serta 10.10.20.0/30 antara penyedia jasa dan R2. Prefiks /30 dipilih untuk segmen transit karena hanya perlu menampung dua alamat pada masing-masing ujung tautan.

Perutean"""),
    # Tabel pekerjaan berkala dilebur ke kalimat.
    ("""Program pemantau menjalankan sekitar dua puluh pekerjaan berkala yang saling bebas, dengan pekerjaan utamanya disajikan pada Tabel 4.7.

!TABEL[Tabel 4.7 Pekerjaan berkala pada program pemantau]

| Pekerjaan | Selang | Fungsi |
|---|---|---|
| Ping seluruh perangkat | 5 detik | Mendeteksi perangkat hidup atau mati |
| Pembacaan pemakaian antarmuka | 30 detik | Membaca pencacah melalui SSH atau SNMP |
| Pemeriksaan layanan | 30 detik | Memeriksa layanan TCP, HTTP, dan MySQL |
| Pembacaan lalu lintas dan pemblokiran otomatis | 60 detik | Membaca catatan akses dan menjalankan pemblokiran |
| Pembacaan sumber daya dan penolakan penyaringan | 300 detik | Membaca cakram, memori, beban, dan catatan penolakan |
| Penambangan pola pesan log | 300 detik | Melipat pesan syslog menjadi templat |
| Peringkasan data per jam | 600 detik | Meringkas catatan status mentah |
| Potret konfigurasi dan kepatuhan | 900 detik | Mengambil konfigurasi dan menilainya |

Pola optimasi""",
     """Program pemantau menjalankan sekitar dua puluh pekerjaan berkala yang saling bebas. Ping ke seluruh perangkat berjalan tiap 5 detik, pembacaan pemakaian antarmuka dan pemeriksaan layanan tiap 30 detik, pembacaan lalu lintas beserta pelaksanaan pemblokiran otomatis tiap 60 detik, pembacaan pemakaian sumber daya dan catatan penolakan penyaringan tiap 300 detik, peringkasan data per jam tiap 600 detik, serta pengambilan potret konfigurasi beserta penilaian kepatuhannya tiap 900 detik.

Pola optimasi"""),
])

print("Bab VI")
ganti("v2-06-bab6.md", [
    ("""1. Menempatkan replika direktori identitas di setiap lokasi, karena direktori tunggal menghilangkan kemampuan seluruh aplikasi mengautentikasi pengguna ketika lokasinya tidak terjangkau, termasuk sistem pemantauan yang justru dibutuhkan saat gangguan berlangsung.
2. Memantau replika basis data, bukan sekadar membuatnya, karena replikasi dapat berhenti tanpa pesan galat dan keadaan itu baru ditemukan ketika replika benar-benar dibutuhkan.
3. Menyediakan jalur cadangan antarlokasi melalui penyedia jasa berbeda disertai protokol perutean dinamis seperti Open Shortest Path First, sehingga perpindahan jalur berlangsung tanpa campur tangan manusia.
4. Menerapkan segmentasi berbasis VLAN dan *port security* pada switch akses, untuk memisahkan lalu lintas pengelolaan perangkat dari lalu lintas pengguna sekaligus membatasi jumlah alamat MAC yang dipelajari tiap porta.
5. Menerapkan kerangka kerja AAA dengan server autentikasi terpusat seperti RADIUS atau TACACS, sehingga pencabutan akses cukup dilakukan sekali dan setiap perintah yang dijalankan tercatat.
6. Menghapus hak istimewa yang melebihi kebutuhan pada akun pemantauan, memakai pembatasan perintah berdasarkan tingkat hak istimewa yang tersedia pada perangkat Cisco.
7. Menjadikan verifikasi pemulihan cadangan sebagai kegiatan terjadwal yang benar-benar memulihkan berkas cadangan ke lingkungan terpisah, karena pencadangan yang tidak pernah diuji hanya membuktikan prosesnya berjalan.
8. Menerapkan infrastruktur sebagai kode secara bertahap, dimulai dari pengambilan potret konfigurasi terjadwal beserta riwayatnya, sehingga penyimpangan terhadap standar sudah dapat dideteksi tanpa mengubah satu pun konfigurasi perangkat.
9. Menerapkan pengumpulan syslog terpusat pada seluruh perangkat, agar catatan kejadian tetap tersimpan meskipun perangkat asalnya mati atau catatannya dihapus.""",
     """Pada aspek ketahanan, perusahaan disarankan menempatkan replika direktori identitas di setiap lokasi, karena direktori tunggal menghilangkan kemampuan seluruh aplikasi mengautentikasi pengguna ketika lokasinya tidak terjangkau, termasuk sistem pemantauan yang justru dibutuhkan saat gangguan berlangsung. Replika basis data perlu dipantau, bukan sekadar dibuat, karena replikasi dapat berhenti tanpa pesan galat dan keadaan itu baru ditemukan ketika replika benar-benar dibutuhkan. Jalur cadangan antarlokasi melalui penyedia jasa berbeda disertai protokol perutean dinamis seperti Open Shortest Path First perlu disediakan agar perpindahan jalur berlangsung tanpa campur tangan manusia.

Pada aspek keamanan, segmentasi berbasis VLAN dan *port security* pada switch akses perlu diterapkan untuk memisahkan lalu lintas pengelolaan perangkat dari lalu lintas pengguna sekaligus membatasi jumlah alamat MAC yang dipelajari tiap porta. Kerangka kerja AAA dengan server autentikasi terpusat seperti RADIUS atau TACACS membuat pencabutan akses cukup dilakukan sekali dan setiap perintah yang dijalankan tercatat. Hak istimewa yang melebihi kebutuhan pada akun pemantauan perlu dihapus memakai pembatasan perintah berdasarkan tingkat hak istimewa yang tersedia pada perangkat Cisco.

Pada aspek pengelolaan, verifikasi pemulihan cadangan perlu dijadikan kegiatan terjadwal yang benar-benar memulihkan berkas cadangan ke lingkungan terpisah, karena pencadangan yang tidak pernah diuji hanya membuktikan prosesnya berjalan. Penerapan infrastruktur sebagai kode dapat dimulai bertahap dari pengambilan potret konfigurasi terjadwal beserta riwayatnya, sehingga penyimpangan terhadap standar sudah dapat dideteksi tanpa mengubah satu pun konfigurasi perangkat. Pengumpulan syslog terpusat pada seluruh perangkat juga perlu diterapkan agar catatan kejadian tetap tersimpan meskipun perangkat asalnya mati."""),
])

print("selesai")

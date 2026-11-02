!SAMPUL

!LOGO(gambar/logo-nanjing-xiaozhuang.png)

IMPLEMENTASI SISTEM NSM (NETWORK STATUS MONITOR) BERBASIS EMULASI GNS3 UNTUK PEMANTAUAN DAN OTOMASI JARINGAN

LAPORAN PRAKTIK KERJA LAPANGAN

Diajukan sebagai salah satu syarat untuk menyelesaikan
program Praktik Kerja Lapangan

Disusun oleh:

Nama : Muhammad Rizki Eka Pratama
NIM : L25020010
Program Studi : Software Engineering

NANJING XIAOZHUANG UNIVERSITY
NANJING, REPUBLIK RAKYAT TIONGKOK
2026

\pagebreak

# LEMBAR PENGESAHAN

LAPORAN PRAKTIK KERJA LAPANGAN

IMPLEMENTASI SISTEM NSM (NETWORK STATUS MONITOR) BERBASIS EMULASI GNS3 UNTUK PEMANTAUAN DAN OTOMASI JARINGAN

Disusun oleh:

Nama : Muhammad Rizki Eka Pratama
NIM : L25020010

Telah dilaksanakan pada tanggal 1 Juli 2026 sampai dengan 30 Agustus 2026 di PT Bumi Siak Pusako, Pekanbaru, Provinsi Riau, Republik Indonesia, dan laporan ini telah diperiksa serta disetujui pada tanggal 24 Agustus 2026.

!TANDATANGAN

\pagebreak

# LEMBAR PERNYATAAN KEASLIAN

Yang bertanda tangan di bawah ini:

Nama : Muhammad Rizki Eka Pratama
NIM : L25020010
Program Studi : Software Engineering

menyatakan bahwa laporan Praktik Kerja Lapangan berjudul "Implementasi Sistem NSM (Network Status Monitor) Berbasis Emulasi GNS3 untuk Pemantauan dan Otomasi Jaringan" adalah hasil karya sendiri.

Seluruh sistem yang diuraikan dalam laporan ini dirancang, dibangun, dan diuji sendiri oleh penulis pada laboratorium tervirtualisasi milik pribadi, sebagai proyek belajar mandiri atas arahan Pembimbing Lapangan. Seluruh angka, tabel, dan gambar yang disajikan diambil langsung dari sistem tersebut pada saat laporan disusun. Kutipan dan pendapat orang lain telah disebutkan sumbernya sesuai kaidah penulisan ilmiah.

Apabila di kemudian hari terbukti terdapat penjiplakan di dalam laporan ini, penulis bersedia menerima sanksi sesuai ketentuan yang berlaku.

Pekanbaru, 24 Agustus 2026
Yang menyatakan,


( Muhammad Rizki Eka Pratama )

\pagebreak

# ABSTRAK

Pengelolaan jaringan komputer secara manual menghadirkan persoalan yang berulang, yaitu kesalahan manusia, konfigurasi yang tidak seragam antarperangkat, dan lambatnya deteksi kegagalan. Persoalan tersebut menjadi dasar penugasan yang diberikan Pembimbing Lapangan kepada penulis untuk mempelajari dan membangun sistem pemantauan serta otomasi jaringan sebagai proyek belajar mandiri, dikerjakan pada laboratorium tervirtualisasi milik pribadi tanpa menyentuh jaringan produksi perusahaan mana pun.

Laporan ini bertujuan merancang dan membangun sistem NSM (Network Status Monitor) pada laboratorium emulasi GNS3 sebagai *proof of concept*. Metode yang digunakan meliputi observasi, wawancara dengan pembimbing, studi pustaka, serta implementasi dan pengujian langsung pada laboratorium. Laboratorium dibangun menyerupai jaringan kantor pusat dan lokasi cabang yang lazim pada organisasi dengan lokasi tersebar, terdiri atas lima perangkat Cisco dan lima mesin virtual Linux yang dihubungkan melalui sebuah router penyedia jasa.

Sistem yang dihasilkan memantau sebelas perangkat beserta sepuluh layanan secara terus-menerus dan telah mengumpulkan 1.328.380 catatan status sejak 22 Juli 2026. Keamanan diterapkan dalam tiga lapisan penyaringan yang mencatat 82.709 penolakan. Otomasi mempersingkat pemeriksaan status sebelas perangkat dari sekitar 15 menit secara manual menjadi 1,01 detik, dan pada pengujian pemulihan gangguan sistem mengembalikan router yang mati dalam waktu 78,86 detik tanpa perintah manusia. Pemeriksa kepatuhan konfigurasi menghasilkan 509 temuan, termasuk temuan berkeparahan tinggi pada sistem yang dibangun sendiri.

Hasil tersebut menunjukkan bahwa penggabungan keamanan jaringan, otomasi, pemantauan, dan administrasi sistem meningkatkan kemampuan pengamatan serta mempersingkat waktu penanganan gangguan, dan dapat dijadikan bahan pembelajaran maupun rujukan awal bagi penerapan pada jaringan yang sesungguhnya.

Kata kunci: otomasi jaringan, pemantauan jaringan, keamanan jaringan, GNS3, SNMP

\pagebreak

# KATA PENGANTAR

Puji syukur penulis panjatkan ke hadirat Tuhan Yang Maha Esa atas rahmat dan karunia-Nya sehingga kegiatan Praktik Kerja Lapangan beserta laporannya dapat diselesaikan.

Laporan ini disusun berdasarkan pelaksanaan Praktik Kerja Lapangan selama dua bulan di PT Bumi Siak Pusako. Selama masa penempatan, penulis memperoleh arahan dan bimbingan dari Pembimbing Lapangan untuk mempelajari serta membangun sebuah sistem pemantauan dan otomasi jaringan sebagai proyek belajar mandiri, yang kemudian dikerjakan pada laboratorium tervirtualisasi milik pribadi.

Penulis menyampaikan terima kasih kepada:

1. Jajaran manajemen PT Bumi Siak Pusako atas kesempatan melaksanakan Praktik Kerja Lapangan di lingkungan perusahaan.
2. Bapak Jarizal selaku Pembimbing Lapangan atas penugasan, arahan, dan bimbingan teknis yang diberikan sepanjang proyek ini dikerjakan.
3. Rekan-rekan di lingkungan tempat magang atas pengetahuan yang dibagikan mengenai praktik pengelolaan jaringan.
4. Jajaran pimpinan Nanjing Xiaozhuang University atas dukungan terhadap keikutsertaan penulis dalam program magang internasional ini.
5. Kedua orang tua dan keluarga penulis atas dukungan selama masa studi.

Penulis menyadari laporan ini masih memiliki kekurangan. Kritik dan saran yang membangun sangat diharapkan.

Pekanbaru, 24 Agustus 2026

Penulis

\pagebreak

# DAFTAR ISI

!DAFTARISI

\pagebreak

# DAFTAR TABEL

!DAFTARTABEL

\pagebreak

# DAFTAR GAMBAR

!DAFTARGAMBAR

\pagebreak

# DAFTAR LAMPIRAN

Lampiran laporan ini disusun sebagai dokumen tersendiri dengan judul "Lampiran Laporan Praktik Kerja Lapangan". Isinya sebagai berikut.

| Lampiran | Isi |
|---|---|
| A | Konfigurasi lengkap perangkat jaringan (R1, SW-A, R2, SW-B) |
| B | Daftar kendali akses R2 beserta pencacah kecocokan |
| C | Daftar program otomasi beserta fungsinya |
| D | Potongan kode program yang tidak dimuat di dalam laporan |
| E | Tangkapan layar antarmuka sistem NSM |
| F | Catatan kegiatan harian |
| G | Surat keterangan pelaksanaan Praktik Kerja Lapangan |

\pagebreak

# DAFTAR SINGKATAN DAN ISTILAH

| Singkatan | Kepanjangan dan keterangan |
|---|---|
| AAA | Authentication, Authorization, Accounting. Kerangka kerja pengelolaan hak akses perangkat jaringan |
| ACL | Access Control List. Daftar aturan penyaringan lalu lintas pada router |
| AES | Advanced Encryption Standard. Algoritma enkripsi simetris |
| CIA | Confidentiality, Integrity, Availability. Tiga sasaran keamanan informasi |
| GNS3 | Graphical Network Simulator 3. Emulator jaringan yang menjalankan sistem operasi perangkat sesungguhnya |
| ICMP | Internet Control Message Protocol. Protokol yang dipakai perintah ping |
| IOS | Internetwork Operating System. Sistem operasi perangkat jaringan Cisco |
| IT | Information Technology. Jaringan perkantoran |
| KVM | Kernel-based Virtual Machine. Mesin virtualisasi berbantuan perangkat keras pada Linux |
| LDAP | Lightweight Directory Access Protocol. Protokol akses direktori identitas terpusat |
| MTTR | Mean Time To Recovery. Waktu pemulihan rata-rata sebuah gangguan |
| NSM | Network Status Monitor. Nama sistem yang dibangun pada laporan ini |
| OT | Operational Technology. Jaringan perangkat kendali proses produksi |
| QEMU | Quick Emulator. Mesin emulasi dan virtualisasi sumber terbuka |
| RFC | Request for Comments. Dokumen standar yang diterbitkan Internet Engineering Task Force |
| SCADA | Supervisory Control and Data Acquisition. Sistem pengawasan dan pengendalian proses industri |
| SFTP | SSH File Transfer Protocol. Protokol pemindahan berkas di atas SSH |
| SHA | Secure Hash Algorithm. Fungsi hash kriptografis |
| SMB | Server Message Block. Protokol berbagi berkas jaringan |
| SNMP | Simple Network Management Protocol. Protokol pembacaan data pengelolaan perangkat jaringan |
| SSH | Secure Shell. Protokol akses jarak jauh terenkripsi |
| TLS | Transport Layer Security. Protokol pengamanan lalu lintas jaringan |
| VLAN | Virtual Local Area Network. Pemisahan jaringan lokal secara logis |
| WAN | Wide Area Network. Jaringan yang menghubungkan lokasi yang berjauhan |

\pagebreak

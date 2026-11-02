!SAMPUL

IMPLEMENTASI PROYEK NSM (NETWORK STATUS MONITOR) BERBASIS EMULASI GNS3 SEBAGAI PROOF OF CONCEPT PADA PT BUMI SIAK PUSAKO

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

IMPLEMENTASI PROYEK NSM (NETWORK STATUS MONITOR) BERBASIS EMULASI GNS3 SEBAGAI PROOF OF CONCEPT PADA PT BUMI SIAK PUSAKO

Disusun oleh:

Nama : Muhammad Rizki Eka Pratama
NIM : L25020010

Telah dilaksanakan pada tanggal 1 Juli 2026 sampai dengan 30 Agustus 2026 di PT Bumi Siak Pusako, Pekanbaru, Provinsi Riau, Republik Indonesia, dan laporan ini telah diperiksa serta disetujui pada tanggal 24 Agustus 2026.

!TANDATANGAN

\pagebreak

# KATA PENGANTAR

Puji syukur penulis panjatkan ke hadirat Tuhan Yang Maha Esa atas rahmat dan karunia-Nya sehingga penulis dapat menyelesaikan kegiatan Praktik Kerja Lapangan beserta laporannya yang berjudul "Implementasi Proyek NSM (Network Status Monitor) Berbasis Emulasi GNS3 sebagai Proof of Concept pada PT Bumi Siak Pusako".

Laporan ini disusun berdasarkan pelaksanaan Praktik Kerja Lapangan selama dua bulan di PT Bumi Siak Pusako, sebuah Badan Usaha Milik Daerah Provinsi Riau yang bergerak di sektor minyak dan gas bumi. Selama periode tersebut penulis ditempatkan pada unit Teknologi Informasi dan memperoleh penugasan untuk merancang serta membangun sebuah sistem pemantauan dan otomasi jaringan di dalam lingkungan laboratorium tervirtualisasi.

Penulis menyadari bahwa pelaksanaan Praktik Kerja Lapangan dan penyusunan laporan ini tidak akan terlaksana tanpa bantuan banyak pihak. Oleh karena itu, penulis menyampaikan terima kasih kepada:

1. Jajaran manajemen PT Bumi Siak Pusako yang telah memberikan kesempatan kepada penulis untuk melaksanakan Praktik Kerja Lapangan di lingkungan perusahaan.
2. Bapak Jarizal selaku Pembimbing Lapangan, yang memberikan penugasan awal, mengoreksi ruang lingkup pekerjaan agar sesuai dengan kemampuan seorang peserta magang, serta menyediakan arahan teknis selama proyek berlangsung.
3. Rekan-rekan pada unit Teknologi Informasi PT Bumi Siak Pusako atas kesediaannya berbagi pengetahuan mengenai praktik pengelolaan jaringan di lingkungan industri.
4. Jajaran pimpinan Nanjing Xiaozhuang University yang telah mendukung keikutsertaan penulis dalam program magang internasional ini.
5. Kedua orang tua dan keluarga penulis atas dukungan yang diberikan selama masa studi dan selama pelaksanaan Praktik Kerja Lapangan.

Penulis menyadari laporan ini masih memiliki kekurangan. Sejumlah keterbatasan sistem yang dibangun sengaja penulis cantumkan secara terbuka pada bab-bab yang bersangkutan, karena sebuah sistem pemantauan yang menyembunyikan kelemahannya sendiri justru lebih berbahaya daripada sistem yang tidak ada sama sekali. Kritik dan saran yang membangun sangat penulis harapkan.

Pekanbaru, 24 Agustus 2026

Penulis

\pagebreak

# DAFTAR ISI

!DAFTARISI

\pagebreak

# DAFTAR GAMBAR

!DAFTARGAMBAR

\pagebreak

# DAFTAR TABEL

!DAFTARTABEL

\pagebreak

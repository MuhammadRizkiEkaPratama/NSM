"""Pemangkasan lanjutan Bab I dan Bab V.

Sasarannya dua halaman terakhir supaya isi laporan berhenti di bawah 35
halaman. Yang dipangkas hanya kalimat yang mengulang keterangan di tempat
lain, bukan angka maupun bukti.
"""
import io
import os

AKAR = os.path.dirname(os.path.abspath(__file__))


def ganti(nama, pasangan):
    jalur = os.path.join(AKAR, nama)
    s = io.open(jalur, encoding="utf-8").read()
    for i, (lama, baru) in enumerate(pasangan, 1):
        if lama not in s:
            print("  butir", i, "TIDAK COCOK")
            continue
        s = s.replace(lama, baru)
        print("  butir", i, "diterapkan")
    io.open(jalur, "w", encoding="utf-8").write(s)
    print("  ", nama, "->", len(s.split()), "kata")


print("Bab I")
ganti("v2-01-bab1.md", [
    ("""Kegiatan produksi minyak dan gas bumi bergantung pada aliran data yang tidak boleh terputus. Tekanan sumur dipantau, pompa dikendalikan, dan volume produksi dilaporkan kepada regulator melalui jaringan komputer perusahaan. Terputusnya jaringan pada jalur menuju stasiun pengumpul menghilangkan visibilitas operator terhadap keadaan lapangan.

Jaringan di perusahaan migas terbagi menjadi dua wilayah dengan sifat berlawanan. Wilayah *Information Technology* melayani surat elektronik dan aplikasi perkantoran, sedangkan wilayah *Operational Technology* melayani perangkat kendali proses seperti SCADA yang tersebar di lapangan. Pada wilayah pertama urutan prioritas keamanan adalah kerahasiaan, keutuhan, lalu ketersediaan, sementara pada wilayah kedua urutan itu terbalik karena berhentinya sistem kendali berarti berhentinya produksi dan berpotensi menimbulkan risiko keselamatan (Stouffer dkk., 2015).""",
     """Kegiatan produksi minyak dan gas bumi bergantung pada aliran data yang tidak boleh terputus, karena tekanan sumur dipantau, pompa dikendalikan, dan volume produksi dilaporkan kepada regulator melalui jaringan komputer perusahaan. Jaringan tersebut terbagi menjadi dua wilayah dengan sifat berlawanan. Wilayah *Information Technology* melayani aplikasi perkantoran dengan urutan prioritas kerahasiaan, keutuhan, lalu ketersediaan, sedangkan wilayah *Operational Technology* melayani perangkat kendali proses seperti SCADA dengan urutan yang terbalik, karena berhentinya sistem kendali berarti berhentinya produksi dan berpotensi menimbulkan risiko keselamatan (Stouffer dkk., 2015)."""),

    ("""Bagi PT Bumi Siak Pusako, laporan ini menyediakan cetak biru jaringan aman yang telah diuji pada lingkungan terpisah beserta daftar temuan konfigurasi yang dapat dijadikan bahan pertimbangan. Bagi penulis, kegiatan ini memberikan pengalaman membangun sistem yang berjalan terus-menerus dan menanggung akibat dari kesalahannya sendiri. Bagi Nanjing Xiaozhuang University, laporan ini menjadi masukan bagi pengembangan pembelajaran jaringan komputer berbasis praktik industri.""",
     """Bagi PT Bumi Siak Pusako, laporan ini menyediakan cetak biru jaringan aman yang telah diuji pada lingkungan terpisah beserta daftar temuan konfigurasi. Bagi penulis, kegiatan ini memberikan pengalaman membangun sistem yang berjalan terus-menerus dan menanggung akibat dari kesalahannya sendiri. Bagi Nanjing Xiaozhuang University, laporan ini menjadi masukan bagi pengembangan pembelajaran jaringan berbasis praktik industri."""),

    ("""Data dan bahan laporan dikumpulkan melalui empat cara. Observasi dilakukan terhadap praktik pengelolaan jaringan pada unit Teknologi Informasi PT Bumi Siak Pusako selama masa penempatan. Wawancara dengan Pembimbing Lapangan menghasilkan rumusan penugasan, batasan kewenangan, dan penyesuaian ruang lingkup pekerjaan. Studi pustaka dilakukan terhadap dokumen standar Internet Engineering Task Force, panduan konfigurasi Cisco, serta pustaka keamanan jaringan dan rekayasa keandalan.

Implementasi dan pengujian dilakukan langsung pada laboratorium, mencakup pengujian fungsional melalui berkas uji otomatis dan pengujian dengan cara mematikan perangkat sungguhan untuk mengamati perilaku sistem.""",
     """Data dan bahan laporan dikumpulkan melalui empat cara, yaitu observasi terhadap praktik pengelolaan jaringan pada unit Teknologi Informasi selama masa penempatan, wawancara dengan Pembimbing Lapangan yang menghasilkan rumusan penugasan beserta batasan kewenangan, studi pustaka terhadap dokumen standar Internet Engineering Task Force dan panduan konfigurasi Cisco, serta implementasi dan pengujian langsung pada laboratorium. Pengujian mencakup berkas uji otomatis dan pengujian dengan cara mematikan perangkat sungguhan untuk mengamati perilaku sistem."""),

    ("""Bab I memuat latar belakang, rumusan masalah, tujuan, manfaat, batasan masalah, metode pelaksanaan, serta waktu dan tempat pelaksanaan. Bab II memuat profil kedua instansi dan kedudukan penulis di dalam organisasi. Bab III memuat landasan teori keamanan jaringan, emulasi, otomasi, pemantauan, dan administrasi sistem. Bab IV memuat perancangan dan implementasi sistem. Bab V memuat hasil pengujian dan pembahasannya. Bab VI memuat kesimpulan dan saran.""",
     """Bab I memuat latar belakang, rumusan masalah, tujuan, manfaat, batasan masalah, metode, serta waktu dan tempat pelaksanaan. Bab II memuat profil kedua instansi dan kedudukan penulis. Bab III memuat landasan teori. Bab IV memuat perancangan dan implementasi sistem. Bab V memuat hasil pengujian beserta pembahasannya, dan Bab VI memuat kesimpulan serta saran."""),
])

print("Bab V")
ganti("v2-05-bab5.md", [
    ("""Sebuah router yang mati tidak menghasilkan satu gejala, melainkan sejumlah gejala pada perangkat di belakangnya. Sistem mengaitkannya memakai graf ketergantungan antarperangkat, dengan waktu hanya sebagai penyaring tambahan. Pada kejadian 25 Agustus 2026 pukul 00.11, enam gejala pada enam perangkat berbeda dikaitkan menjadi satu kejadian dengan Switch Lokasi A sebagai akarnya. Tanpa pengaitan tersebut, keadaan itu tercatat sebagai enam gangguan terpisah dan menghasilkan enam peringatan, lima di antaranya menunjuk perangkat yang tidak rusak.""",
     """Sebuah router yang mati tidak menghasilkan satu gejala, melainkan sejumlah gejala pada perangkat di belakangnya, dan sistem mengaitkannya memakai graf ketergantungan antarperangkat. Pada kejadian 25 Agustus 2026 pukul 00.11, enam gejala pada enam perangkat berbeda dikaitkan menjadi satu kejadian dengan Switch Lokasi A sebagai akarnya. Tanpa pengaitan tersebut, keadaan itu akan tercatat sebagai enam gangguan terpisah dan menghasilkan enam peringatan, lima di antaranya menunjuk perangkat yang tidak rusak."""),

    ("""Temuan tersebut mengubah ambang deteksi. Ambang semula dua kali kegagalan berturut-turut dan menghasilkan catatan 267 sampai 277 gangguan per hari pada perangkat emulasi, padahal pemeriksaan terhadap sebaran durasi menunjukkan 99 persen episode berakhir kurang dari empat puluh detik. Ambang dinaikkan menjadi lima kali kegagalan, setara sekitar lima puluh detik, dan jumlah gangguan turun menjadi 5 sampai 16 per hari. Perangkat dengan ketersediaan terendah adalah direktori LDAP di Lokasi B, karena kedudukannya di balik dua router membuatnya terdampak oleh gangguan pada perangkat mana pun di sepanjang jalur.""",
     """Temuan tersebut mengubah ambang deteksi. Ambang semula dua kali kegagalan berturut-turut dan menghasilkan catatan 267 sampai 277 gangguan per hari, padahal 99 persen episode berakhir kurang dari empat puluh detik. Setelah ambang dinaikkan menjadi lima kali kegagalan, jumlah gangguan turun menjadi 5 sampai 16 per hari. Ketersediaan terendah dimiliki direktori LDAP di Lokasi B, karena kedudukannya di balik dua router membuatnya terdampak oleh gangguan pada perangkat mana pun di sepanjang jalur."""),

    ("""Laboratorium tidak memiliki jalur cadangan antarlokasi, sehingga pengujian konvergensi protokol perutean dinamis tidak dapat dilakukan. Segmentasi berbasis VLAN, *port security* pada switch, dan kerangka kerja AAA terpusat belum diterapkan. Pemantauan masih berdasarkan alamat IP tanpa penemuan perangkat otomatis, sehingga alamat yang sama dapat menunjuk perangkat berbeda pada jaringan berbeda.

Kelemahan rancangan yang paling berdampak adalah direktori identitas yang hanya ada satu dan berada di Lokasi B. Ketika Router Lokasi A mati, seluruh Lokasi B menjadi tidak terjangkau dan tidak seorang pun dapat masuk ke sistem NSM selama gangguan berlangsung. Sistem menyediakan jalur masuk darurat yang tidak bergantung pada direktori, tetapi jalur itu menangani gejala, bukan akar masalahnya.""",
     """Laboratorium tidak memiliki jalur cadangan antarlokasi sehingga pengujian konvergensi protokol perutean dinamis tidak dapat dilakukan, sedangkan segmentasi berbasis VLAN, *port security*, dan kerangka kerja AAA terpusat belum diterapkan. Pemantauan juga masih berdasarkan alamat IP tanpa penemuan perangkat otomatis, sehingga alamat yang sama dapat menunjuk perangkat berbeda pada jaringan berbeda.

Kelemahan rancangan yang paling berdampak adalah direktori identitas yang hanya ada satu dan berada di Lokasi B. Ketika Router Lokasi A mati, seluruh Lokasi B menjadi tidak terjangkau dan tidak seorang pun dapat masuk ke sistem NSM selama gangguan berlangsung. Jalur masuk darurat yang tersedia menangani gejala, bukan akar masalahnya."""),
])

print("selesai")

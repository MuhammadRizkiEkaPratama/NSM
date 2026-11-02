/*
 * NSM glossary. Terms appear on many pages, so each has a single explanation here. Each entry says what it means, where the number comes from, and what the reader should do.
 *
 * HTML:       <span data-istilah="mttr">MTTR</span>
 * JavaScript: jelaskan(elemen, "mttr");
 * Both fill `data-petunjuk`, which `petunjuk.js` reads.
 */

var KAMUS_ISTILAH = {

  // ---------- Pengukuran dasar ----------
  ping:
    "Pemeriksaan hidup atau tidaknya sebuah device dengan mengirim paket ICMP "
    + "lalu menunggu balasannya. NSM melakukannya tiap 10 detik. Ping yang "
    + "berhasil hanya membuktikan device menjawab di jaringan, bukan bahwa "
    + "layanan di dalamnya sehat.",

  latency:
    "Waktu yang dibutuhkan satu paket ping untuk pergi dan kembali, dalam "
    + "milidetik. Angka besar berarti jalurnya jauh, padat, atau perangkatnya "
    + "sibuk, TETAPI device tetap hidup. Latency yang tiba-tiba naik berkali "
    + "lipat sering menjadi tanda awal sebelum device benar-benar putus.",

  availability:
    "Persentase pemeriksaan yang berhasil selama periode yang dipilih. "
    + "Dihitung dari catatan transisi UP dan DOWN, bukan dari perasaan. "
    + "Perlu dibaca bersama jumlah insiden: 99% dari satu gangguan panjang "
    + "berarti hal yang sangat berbeda dari 99% yang tersebar jadi dua puluh "
    + "gangguan pendek.",

  "kualitas-sambungan":
    "Persentase paket ping yang HILANG pada periode ini, dihitung dari "
    + "SETIAP percobaan ping (bukan cuma yang sampai dianggap gangguan). "
    + "BEDA dari Availability: availability menjawab device hidup atau mati "
    + "(sudah disaring supaya paket hilang sesekali tidak dihitung mati), "
    + "kolom ini menjawab bagus-tidaknya jalurnya lepas dari saringan itu. "
    + "Device bisa Availability 100% tapi Kualitas-nya buruk -- itu tandanya "
    + "jalurnya goyah tapi belum sampai membuatnya dianggap mati. Bagus di "
    + "bawah 1%, Cukup di bawah 5%, Buruk di bawah 15%, sisanya Sangat buruk.",

  insiden:
    "Satu insiden dihitung sejak device berhenti merespons sampai ia "
    + "merespons lagi. Berhenti sepuluh menit sekali dihitung satu insiden, "
    + "sama seperti berhenti sepuluh detik. Karena itu jumlah insiden selalu "
    + "perlu dibaca bersama total waktu down.",

  mttr:
    "Mean Time To Recovery, rata-rata lama device kembali normal setelah "
    + "mengalami gangguan. Dihitung dari total waktu down dibagi jumlah "
    + "insiden. Makin kecil makin baik. Angka kecil dengan insiden banyak "
    + "menunjukkan sambungan yang putus-nyambung, bukan kerusakan berat.",

  "total-down":
    "Jumlah seluruh waktu device tidak merespons selama periode ini, "
    + "digabung dari semua insiden. Inilah angka yang biasanya ditanyakan "
    + "atasan, karena ia menggambarkan dampak, bukan sekadar frekuensi.",

  uptime_streak:
    "Berapa lama sejak gangguan terakhir di seluruh jaringan yang dipantau. "
    + "Dihitung ulang dari nol begitu ada satu device saja yang bermasalah.",

  // ---------- Kategori penyebab ----------
  "tidak-ada-respons":
    "Ping gagal DAN tidak ada satu pun port TCP yang biasa terbuka (22, 80, "
    + "443) yang menjawab. Device kemungkinan besar mati, kabelnya lepas, "
    + "atau terputus dari jaringan. Ini kesimpulan dari jaringan, jadi sebab "
    + "fisik seperti listrik padam tidak bisa dibedakan dari sini.",

  "ping-diblokir":
    "Ping gagal, TETAPI port TCP masih menjawab. Artinya device kemungkinan "
    + "besar HIDUP dan yang ditolak hanyalah paket ICMP, biasanya karena "
    + "aturan firewall. Ini bukan gangguan layanan; yang perlu diperiksa "
    + "adalah aturan firewallnya, bukan devicenya.",

  flapping:
    "Pola putus-nyambung berulang dalam waktu singkat, bukan satu kerusakan "
    + "tunggal. NSM menandainya bila ada banyak gangguan pendek berturut-turut. "
    + "Penyebab lazimnya sinyal lemah, perpindahan antar titik akses, atau "
    + "penghematan daya pada kartu jaringan. Menggantinya dengan perangkat "
    + "baru jarang menyelesaikan masalah ini.",

  interface:
    "Kartu jaringan di dalam device. Penamaan Linux modern bersifat "
    + "deskriptif: en berarti Ethernet, p menunjuk slot PCI, dan s posisi "
    + "perangkat di slot itu. Jadi enp0s3 dibaca sebagai Ethernet pada slot "
    + "PCI 0 posisi 3. Satu device bisa punya beberapa interface untuk "
    + "jaringan yang berbeda.",

  "lalu-lintas":
    "Berapa banyak data yang benar-benar mengalir lewat tiap interface. "
    + "Masuk berarti data yang DITERIMA device, Keluar berarti yang DIKIRIM. "
    + "Diambil dengan menanyai device langsung lewat SSH atau SNMP, bukan "
    + "dari ping, jadi hanya tersedia untuk device yang punya kredensial.",

  bps:
    "Mbps berarti juta bit per detik. Perhatikan bit, bukan byte: 8 bit sama "
    + "dengan 1 byte, jadi 8 Mbps kira-kira 1 MB per detik. NSM sengaja "
    + "memakai Mbps di SEMUA tempat, tidak pernah berganti-ganti satuan, "
    + "supaya kolom angka bisa dibandingkan sekilas tanpa dihitung dulu. "
    + "Akibatnya lalu lintas kecil terbaca 0,000; arahkan kursor ke angkanya "
    + "untuk melihat nilai aslinya dalam bps.",

  ssh:
    "Secure Shell, cara masuk ke device dari jarak jauh lewat sambungan "
    + "terenkripsi. NSM memakainya hanya untuk MEMBACA keadaan device; tidak "
    + "ada satu pun perintah yang mengubah konfigurasi. Tiap pengambilan "
    + "tercatat di Audit Log lengkap dengan siapa dan kapan.",

  snmp:
    "Simple Network Management Protocol, cara baku menanyai perangkat "
    + "jaringan tentang keadaannya. NSM memakai versi 3 yang sudah memiliki "
    + "autentikasi dan enkripsi, berbeda dari versi 1 dan 2c yang mengirim "
    + "kata kunci dalam bentuk terbaca.",

  platform:
    "Jenis sistem di dalam device, misalnya linux atau cisco_ios. Menentukan "
    + "perintah mana yang dipakai NSM saat membaca keadaannya. Device yang "
    + "belum diisi platformnya hanya bisa dipantau lewat ping, dan tombol "
    + "Data SSH untuknya dimatikan.",

  "beban-cpu":
    "Load average, yaitu rata-rata jumlah proses yang menunggu giliran CPU, "
    + "BUKAN persentase. Nilai 1,00 kira-kira berarti satu inti CPU terpakai "
    + "penuh. Pada mesin berinti empat, nilai 4,00 baru berarti penuh. "
    + "Ketiga angkanya menunjukkan rata-rata 1, 5, dan 15 menit terakhir.",

  "grafik-langsung":
    "Menggambar data yang BARU MASUK ke database NSM, bukan menanyai device "
    + "saat itu juga. Sumbernya tabel status_logs untuk ping dan "
    + "bandwidth_samples untuk lalu lintas. Karena kedua data itu dicatat "
    + "dengan irama berbeda, kedua grafik mencakup rentang waktu yang "
    + "berbeda pula; rentang masing-masing tertulis di sudut kanan bawahnya.",

  "pola-sparkline":
    "Bentuk naik-turun sepanjang periode, satu batang mewakili satu potongan "
    + "waktu. Gunanya menjawab hal yang tidak bisa dijawab satu angka: "
    + "apakah 97% itu satu gangguan panjang atau dua puluh gangguan pendek. "
    + "Batang samar di dasar berarti tidak ada data pada potongan itu, "
    + "biasanya karena pemantauan sedang dijeda atau poller mati.",

  "riwayat-gangguan":
    "Daftar tiap kali device berhenti lalu kembali merespons, diambil dari "
    + "tabel device_events. Berbeda dari status_logs yang mencatat SETIAP "
    + "pemeriksaan, tabel ini hanya mencatat saat statusnya BERUBAH, jadi "
    + "isinya sedikit dan cepat dibaca.",

  "audit-log":
    "Rekam jejak aktivitas AKUN dan sistem: siapa masuk, siapa menyetujui "
    + "user, siapa menjeda device, dan kapan peringatan email terkirim. "
    + "Berbeda dari halaman Report yang mencatat keadaan DEVICE. Tersimpan di "
    + "MySQL, terpisah dari data pemantauan.",

  "dijeda":
    "Pemantauan device ini dihentikan sementara, jadi NSM berhenti mem-ping "
    + "dan statusnya sekarang tidak diketahui. Riwayat lama tidak dihapus, "
    + "dan angka pada barisnya berhenti bertambah. Berguna saat sebuah device "
    + "memang sedang dimatikan dan tidak perlu dihitung sebagai gangguan.",

  "lapis-layanan":
    "Pemeriksaan layanan dilakukan berlapis, dan LAPIS MANA YANG JATUH itulah "
    + "diagnosisnya. ICMP menjawab apakah mesinnya menyala. TCP menjawab "
    + "apakah ada program yang mendengarkan di port itu. HTTP menjawab apakah "
    + "jawabannya benar, bukan sekadar ada. MySQL menjawab apakah yang "
    + "menjawab di port itu benar-benar MySQL, bukan program lain yang "
    + "kebetulan memakainya. Kalau ping berhasil tetapi TCP ditolak, yang mati "
    + "layanannya, bukan servernya.",

  "layanan-vs-device":
    "Device hidup tidak berarti layanannya melayani. Ping hanya membuktikan "
    + "mesin menjawab di jaringan; Apache di atasnya bisa berhenti tanpa "
    + "mengubah hasil ping sama sekali. Karena itu kartu device bisa tetap "
    + "hijau sementara layanannya merah, dan keduanya benar. Selisih antara "
    + "availability device dan availability layanan justru yang paling layak "
    + "diperhatikan.",

  "sumber-bacaan":
    "Dari mana angka lalu lintas ini dibaca. SNMP adalah jalur utama karena "
    + "paling murah bagi device. SSH adalah cadangan yang dipakai otomatis "
    + "saat SNMP tidak menjawab, dan lokal berarti dibaca langsung dari mesin "
    + "yang menjalankan NSM tanpa membuka koneksi apa pun. Kalau sebuah device "
    + "tiba-tiba terbaca lewat SSH padahal biasanya SNMP, snmpd di device itu "
    + "kemungkinan mati; angkanya tetap benar, tetapi penyebabnya perlu "
    + "diperiksa.",

  "akses-web":
    "Catatan permintaan yang benar-benar dilayani web server, dibaca dari "
    + "access log Apache lewat SSH. Inilah satu-satunya sumber yang tahu SIAPA "
    + "mengambil APA; counter interface hanya tahu berapa byte lewat, dan "
    + "memang tidak menyimpan lawan bicara. Besar unggahan tidak tercatat "
    + "kecuali mod_logio dinyalakan, jadi kolom yang kosong berarti tidak "
    + "diketahui, bukan nol.",

  "flow-koneksi":
    "Potret berkala koneksi TCP yang sedang terbuka di device: siapa bicara "
    + "dengan siapa, di port berapa. Berbeda dari access log yang hanya "
    + "melihat HTTP, ini melihat seluruh TCP. Karena berupa potret berkala, "
    + "koneksi yang hidup sebentar lalu tutup di antara dua potret bisa "
    + "terlewat, dan itu batas yang melekat pada caranya, bukan kesalahan.",

  poller:
    "Program Python yang berjalan terus di latar belakang, mem-ping semua "
    + "device tiap 10 detik lalu menyimpan hasilnya. Kalau poller mati, "
    + "seluruh halaman berhenti mendapat data baru walau tampilannya tetap "
    + "terbuka, dan lubang itu akan terlihat sebagai celah pada grafik pola.",

  lockout:
    "Penguncian bertingkat setelah beberapa kali gagal masuk. Tingkat 1 "
    + "membekukan akun sementara, tingkat 2 mengirim tautan reset ke email "
    + "pemiliknya, tingkat 3 memblokir alamat asalnya. Alamat localhost tidak "
    + "pernah diblokir supaya admin tidak bisa mengunci dirinya sendiri.",

  "notifikasi-langganan":
    "Tiap user memilih sendiri device mana yang peringatannya ingin ia terima "
    + "lewat email. Bawaannya mati. Ini satu-satunya saklar: tidak ada "
    + "pengaturan lain yang perlu dinyalakan, dan pilihan satu user tidak "
    + "memengaruhi user lain.",


  "access-log":
    "Catatan yang ditulis SENDIRI oleh web server tiap kali ada yang meminta "
    + "sebuah halaman atau berkas: siapa alamatnya, apa yang diminta, berapa "
    + "byte terkirim. Karena ditulis oleh server yang melayani, ia tahu NAMA "
    + "BERKASNYA — sesuatu yang tidak bisa diketahui dengan mengintip paket di "
    + "jaringan. Batasnya: hanya HTTP, dan hanya dari device yang layanan "
    + "web-nya sudah didaftarkan di NSM. Yang lewat HTTPS, SSH, atau protokol "
    + "lain tidak pernah muncul di sini.",

  "garis-dasar":
    "Angka 'berapa yang BIASA' yang dipakai sebagai pembanding, dihitung dari "
    + "median lalu lintas per jam pada jam-jam sebelumnya. Tanpa ini, "
    + "'203 MB' tidak bisa dinilai sama sekali — banyak atau sedikit "
    + "sepenuhnya bergantung pada kebiasaannya. NSM menolak menghitungnya "
    + "sebelum ada cukup jam berisi data, dan saat itu ia mengatakannya terus "
    + "terang alih-alih memakai rata-rata dari sampel sedikit yang hasilnya "
    + "kebetulan, bukan kebiasaan.",

  "pintu-port":
    "Nomor pintu pada sebuah alamat. Satu mesin punya satu alamat IP tetapi "
    + "ribuan pintu, dan tiap layanan menunggu di pintunya sendiri: 22 untuk "
    + "SSH, 80 untuk web biasa, 3306 untuk MySQL. Mengetahui pintunya berarti "
    + "mengetahui LAYANAN APA yang dipakai, walau isi percakapannya sendiri "
    + "tidak pernah dilihat NSM.",

  "arah-masuk-keluar":
    "Dibaca dari sudut pandang perangkat yang DIPANTAU, bukan lawan bicaranya. "
    + "Masuk berarti perangkat kita yang melayani, jadi ada pihak lain yang "
    + "mengaksesnya. Keluar berarti perangkat kita yang menghubungi pihak "
    + "lain. Sekali tertukar, kesimpulan tentang arah kebocoran data akan "
    + "berlawanan dengan kenyataan — itulah sebabnya kolomnya tidak pernah "
    + "diberi nama 'masuk' dan 'keluar' telanjang.",

  "dari-nsm":
    "Permintaan yang dibuat NSM SENDIRI saat memeriksa apakah layanan itu "
    + "masih hidup, bukan oleh manusia. Jumlahnya bisa ribuan karena "
    + "pemeriksaan berjalan tiap beberapa detik. Ditandai, BUKAN dibuang: alat "
    + "pemantau yang diam-diam membuang lalu lintasnya sendiri membuat "
    + "angkanya tidak bisa dipertanggungjawabkan oleh siapa pun.",

  "rata-rata-berkas":
    "Total dibagi berapa kali berkas itu diambil. Kolom ini memisahkan dua "
    + "hal yang totalnya bisa sama persis tetapi artinya berlawanan: satu "
    + "berkas besar yang ditarik sekali, dan berkas kecil yang ditarik ribuan "
    + "kali. Yang pertama biasanya pemindahan data, yang kedua biasanya "
    + "denyut sebuah program.",

  "luar-jaringan-lab":
    "Alamat yang tidak termasuk rentang jaringan lab. Ditandai, bukan diberi "
    + "warna peringatan: perangkat yang mengambil pembaruan paket dari "
    + "internet bukan sedang bermasalah. Yang perlu disampaikan cuma bahwa "
    + "percakapan itu MENINGGALKAN lab, supaya baris itu yang dilihat lebih "
    + "dulu kalau ada yang perlu dicurigai.",

  "nama-dns":
    "Nama yang didapat dengan menanyakan balik sebuah alamat IP. Ditaruh di "
    + "BAWAH alamatnya, tidak pernah menggantikannya: nama itu dikendalikan "
    + "oleh pemilik alamat dan bisa saja berbohong, sedangkan yang "
    + "benar-benar tercatat tetap alamatnya.",

  "sftp":
    "Perpindahan berkas yang berjalan di atas SSH. NSM membacanya dari log "
    + "SSH server berkas, jadi inilah satu-satunya bagian halaman Lalu Lintas "
    + "yang menyebut ORANG, bukan alamat — dan orang adalah penunjuk yang "
    + "jauh lebih berguna, sebab alamat berpindah tangan sedangkan nama tidak. "
    + "`scp` ikut terhitung karena OpenSSH menjalankannya di atas protokol "
    + "yang sama."
};

/* Attach the explanation to an element. Safe for unknown keys: the element is left without a hint instead of an empty tooltip. */
function jelaskan(elemen, kunci, tambahan) {
  if (!elemen) return elemen;
  var teks = KAMUS_ISTILAH[kunci];
  if (!teks) return elemen;
  elemen.setAttribute("data-petunjuk", tambahan ? tambahan + " " + teks : teks);
  elemen.classList.add("beristilah");
  return elemen;
}

/* Apply to every element with `data-istilah`. Runs once on page ready and can be called again after JavaScript redraws part of the page. */
function pasangIstilah(akar) {
  var wadah = akar || document;
  var daftar = wadah.querySelectorAll("[data-istilah]");
  Array.prototype.forEach.call(daftar, function (el) {
    if (!el.getAttribute("data-petunjuk")) {
      jelaskan(el, el.getAttribute("data-istilah"));
    }
  });
}

document.addEventListener("DOMContentLoaded", function () { pasangIstilah(); });

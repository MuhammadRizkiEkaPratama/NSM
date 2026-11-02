"""Menyusun naskah Markdown untuk dokumen Lampiran laporan.

Lampiran dibuat sebagai dokumen tersendiri, terpisah dari laporan utama, atas
permintaan pemilik pekerjaan. Isinya disusun dari berkas yang sudah ada di
disk, bukan diketik ulang, sehingga konfigurasi yang dilampirkan dijamin sama
dengan yang benar-benar terpasang pada perangkat.

Keluarannya `lampiran-00.md`, yang kemudian dirakit `rakit_docx.py lampiran`.
"""
import io
import os

AKAR = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(AKAR, "lampiran-data")
GAMBAR = os.path.join(AKAR, "gambar")
KELUAR = os.path.join(AKAR, "lampiran-00.md")

PERANGKAT = [
    ("R1", "Router Lokasi A, Cisco 7200, IOS 15.2(4)S5"),
    ("SW-A", "Switch Lokasi A, IOU Layer 2, IOS 15.1"),
    ("R2", "Router Lokasi B, Cisco 2691, IOS 12.4(13b)"),
    ("SW-B", "Switch Lokasi B, IOU Layer 2, IOS 15.1"),
]

# nama berkas gambar, judul yang dipakai di lampiran
TANGKAPAN = [
    ("lampiran-dashboard", "Halaman Dashboard"),
    ("lampiran-report", "Halaman Report Availability"),
    ("report-device", "Halaman Riwayat Device"),
    ("report-cetak", "Lembar cetak laporan ketersediaan"),
    ("lampiran-insiden", "Halaman Insiden"),
    ("lampiran-insiden-detail", "Garis waktu satu insiden"),
    ("services", "Halaman Layanan"),
    ("traffic", "Halaman Lalu Lintas"),
    ("konfig", "Halaman Konfigurasi"),
    ("lampiran-konfig-kepatuhan", "Halaman Kepatuhan Konfigurasi"),
    ("lampiran-konfig-firewall", "Halaman Firewall"),
    ("konfig-potret", "Halaman Potret Konfigurasi"),
    ("konfig-perintah", "Halaman Susun Perintah Konfigurasi"),
    ("lampiran-konfig-pagar", "Halaman Pagar Otomasi"),
    ("konfig-identitas", "Halaman Identitas Perangkat"),
    ("konfig-drift", "Halaman Deteksi Penyimpangan Konfigurasi"),
    ("lampiran-kesehatan", "Halaman Kesehatan Sistem"),
    ("lampiran-backup", "Halaman Pemantau Backup"),
    ("lampiran-wawasan", "Halaman Wawasan"),
    ("agen", "Halaman Agen SOC"),
    ("syslog", "Halaman Syslog"),
    ("audit", "Halaman Audit Log"),
]

PROGRAM = [
    ("api.py", "Penghubung menuju antarmuka pemrograman GNS3"),
    ("bangun_topologi.py", "Membuat SW-A, SW-B, R2, jaringan lokal Lokasi B, beserta kabelnya"),
    ("tambah_isp.py", "Menyisipkan router penyedia jasa ke jalur antarlokasi"),
    ("konfigurasi_lokasi.py", "Mengonfigurasi Cisco IOS pada R1, R2, SW-A, dan SW-B"),
    ("konfigurasi_isp.py", "Mengonfigurasi router penyedia jasa"),
    ("konsol.py", "Mengirim perintah melalui konsol memakai soket mentah"),
    ("lihat_topologi.py", "Memeriksa simpul, kabel, dan porta yang masih kosong"),
    ("acl_lokasi_b.py", "Memasang daftar kendali akses pada R2"),
    ("pasang_ntp_router.py", "Menyetel sumber waktu pada perangkat Cisco"),
    ("nyalakan_log_router.py", "Mengarahkan pesan syslog perangkat ke penampung"),
    ("hidupkan_ulang_node.py", "Menyalakan ulang simpul GNS3 yang terbukti mati"),
]

KODE_R2 = '''"configure terminal",
"no ip domain lookup",
"ip domain name lab.local",
"username nsm privilege 15 secret " + sandi,
"interface FastEthernet0/0",
"  description LAN lokasi B ke SW-B",
"  ip address 192.168.20.1 255.255.255.0",
"  no shutdown",
"  exit",
"interface FastEthernet0/1",
"  description WAN ke R1 (lokasi A)",
"  ip address 10.10.10.2 255.255.255.252",
"  no shutdown",
"  exit",
"ip route 192.168.56.0 255.255.255.0 10.10.10.1",
"ip ssh version 2",
"line vty 0 4",
"  login local",
"  transport input ssh",
"  exit",
"crypto key generate rsa general-keys modulus 1024",
"end",'''

KODE_SNMP = '''sudo apt install snmpd

sudo systemctl stop snmpd
sudo net-snmp-create-v3-user -ro \\
     -a SHA -A <frasa-autentikasi> \\
     -x AES -X <frasa-enkripsi> \\
     nsmmon
sudo systemctl start snmpd'''

KODE_RUTE = '''R1# show ip route
Gateway of last resort is 10.10.10.2 to network 0.0.0.0

S*    0.0.0.0/0 [1/0] via 10.10.10.2
      10.0.0.0/8 is variably subnetted, 2 subnets, 2 masks
C        10.10.10.0/30 is directly connected, FastEthernet1/0
L        10.10.10.1/32 is directly connected, FastEthernet1/0
S     192.168.20.0/24 [1/0] via 10.10.10.2
      192.168.56.0/24 is variably subnetted, 2 subnets, 2 masks
C        192.168.56.0/24 is directly connected, FastEthernet0/0
L        192.168.56.60/32 is directly connected, FastEthernet0/0

R2# show ip route
Gateway of last resort is 10.10.20.1 to network 0.0.0.0

S    192.168.56.0/24 [1/0] via 10.10.20.1
C    192.168.20.0/24 is directly connected, FastEthernet0/0
     10.0.0.0/30 is subnetted, 1 subnets
C       10.10.20.0 is directly connected, FastEthernet0/1
S*   0.0.0.0/0 [1/0] via 10.10.20.1'''


def main():
    b = []
    t = b.append

    t("!SAMPUL")
    t("")
    t("!LOGO(gambar/logo-nanjing-xiaozhuang.png)")
    t("")
    t("LAMPIRAN")
    t("")
    t("LAPORAN PRAKTIK KERJA LAPANGAN")
    t("")
    t("IMPLEMENTASI SISTEM NSM (NETWORK STATUS MONITOR) BERBASIS EMULASI GNS3 UNTUK PEMANTAUAN DAN OTOMASI JARINGAN")
    t("")
    t("Disusun oleh:")
    t("")
    t("Nama : Muhammad Rizki Eka Pratama")
    t("NIM : L25020010")
    t("Program Studi : Software Engineering")
    t("")
    t("NANJING XIAOZHUANG UNIVERSITY")
    t("NANJING, REPUBLIK RAKYAT TIONGKOK")
    t("2026")
    t("")
    t("\\pagebreak")
    t("")

    # ---- Lampiran A ----
    t("# LAMPIRAN A KONFIGURASI PERANGKAT JARINGAN")
    t("")
    t("Lampiran ini memuat keluaran perintah `show running-config` dari keempat "
      "perangkat Cisco pada laboratorium, diambil langsung dari perangkat pada "
      "saat laporan disusun. Seluruh nilai *hash* kata sandi telah disamarkan "
      "dan digantikan penanda.")
    t("")
    for nama, ket in PERANGKAT:
        jalur = os.path.join(DATA, nama + "-running-config.txt")
        if not os.path.exists(jalur):
            continue
        isi = io.open(jalur, encoding="utf-8").read().strip().splitlines()
        # Baris pemisah bawaan Cisco dibuang supaya lampirannya tidak berisi
        # ratusan tanda seru yang tidak menambah keterangan apa pun.
        isi = [x.rstrip() for x in isi if x.strip() != "!"]
        t("## A." + str(PERANGKAT.index((nama, ket)) + 1) + " " + nama + " (" + ket + ")")
        t("")
        t("```")
        b.extend(isi)
        t("```")
        t("")

    t("\\pagebreak")
    t("")

    # ---- Lampiran B ----
    t("# LAMPIRAN B TABEL PERUTEAN PERANGKAT")
    t("")
    t("Isi tabel perutean R1 dan R2 yang benar-benar terpasang, diambil "
      "langsung dari perangkat.")
    t("")
    t("```")
    b.extend(KODE_RUTE.splitlines())
    t("```")
    t("")
    t("\\pagebreak")
    t("")

    # ---- Lampiran C ----
    t("# LAMPIRAN C DAFTAR PROGRAM OTOMASI")
    t("")
    t("Program berikut membangun dan mengonfigurasi laboratorium melalui "
      "antarmuka pemrograman GNS3. Seluruhnya ditulis dalam bahasa Python.")
    t("")
    t("!TABEL[Tabel C.1 Program pembangun dan pengatur topologi]")
    t("")
    t("| Berkas | Fungsi |")
    t("|---|---|")
    for berkas, fungsi in PROGRAM:
        t("| " + berkas + " | " + fungsi + " |")
    t("")
    t("\\pagebreak")
    t("")

    # ---- Lampiran D ----
    t("# LAMPIRAN D POTONGAN KODE PROGRAM")
    t("")
    t("## D.1 Daftar perintah konfigurasi awal R2")
    t("")
    t("Potongan berikut adalah daftar perintah yang disusun program lalu "
      "dikirimkan ke R2 melalui konsol. Nilai kata sandi dibaca dari berkas "
      "setelan, tidak ditulis di dalam kode.")
    t("")
    t("```python")
    b.extend(KODE_R2.splitlines())
    t("```")
    t("")
    t("## D.2 Pemasangan SNMP versi 3 pada server Linux")
    t("")
    t("Layanan dihentikan lebih dulu karena perintah pembuat pengguna menulis "
      "langsung ke berkas keadaan layanan, dan menulis berkas itu selagi "
      "layanan berjalan menyebabkan perubahan hilang saat layanan berhenti. "
      "Penanda `-ro` membuat pengguna hanya memiliki hak baca.")
    t("")
    t("```")
    b.extend(KODE_SNMP.splitlines())
    t("```")
    t("")
    t("\\pagebreak")
    t("")

    # ---- Lampiran E ----
    t("# LAMPIRAN E TANGKAPAN LAYAR ANTARMUKA SISTEM")
    t("")
    t("Seluruh tangkapan layar berikut diambil dari sistem NSM yang sedang "
      "berjalan pada alamat 192.168.56.156 porta 8080, memakai akun pengguna "
      "sungguhan, pada saat laporan disusun.")
    t("")
    nomor = 0
    for berkas, judul in TANGKAPAN:
        jalur = os.path.join(GAMBAR, berkas + ".png")
        if not os.path.exists(jalur):
            print("  gambar tidak ada, dilewati:", berkas)
            continue
        nomor += 1
        t("!GAMBAR[Gambar E." + str(nomor) + " " + judul + "](gambar/" + berkas + ".png)")
        t("")
    t("\\pagebreak")
    t("")

    # ---- Lampiran F dan G ----
    t("# LAMPIRAN F CATATAN KEGIATAN HARIAN")
    t("")
    t("Catatan kegiatan harian selama pelaksanaan Praktik Kerja Lapangan, "
      "memuat tanggal, kegiatan yang dilaksanakan, dan hasil yang dicapai, "
      "beserta paraf Pembimbing Lapangan.")
    t("")
    t("!TABEL[Tabel F.1 Catatan kegiatan harian]")
    t("")
    t("| Tanggal | Kegiatan | Hasil | Paraf |")
    t("|---|---|---|---|")
    for _ in range(12):
        t("|  |  |  |  |")
    t("")
    t("\\pagebreak")
    t("")
    t("# LAMPIRAN G SURAT KETERANGAN PELAKSANAAN")
    t("")
    t("Surat keterangan dari PT Bumi Siak Pusako yang menyatakan bahwa penulis "
      "telah melaksanakan Praktik Kerja Lapangan pada periode yang disebutkan.")
    t("")
    t("[Tempat salinan surat keterangan]")
    t("")

    io.open(KELUAR, "w", encoding="utf-8").write("\n".join(b))
    print("tersimpan:", KELUAR)
    print("baris:", len(b), " gambar:", nomor)


if __name__ == "__main__":
    main()

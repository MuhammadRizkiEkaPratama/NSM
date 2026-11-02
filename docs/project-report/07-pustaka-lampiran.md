# DAFTAR PUSTAKA

Beyer, B., Jones, C., Petoff, J., & Murphy, N. R. (2016). *Site reliability engineering: How Google runs production systems*. O'Reilly Media.

Blumenthal, U., & Wijnen, B. (2002). *User-based Security Model (USM) for version 3 of the Simple Network Management Protocol (SNMPv3)* (RFC 3414). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc3414

Cisco Systems. (2024). *Cisco IOS security configuration guide: Securing user services*. Cisco Systems, Inc.

Gerhards, R. (2009). *The Syslog protocol* (RFC 5424). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc5424

GNS3 Technologies. (2024). *GNS3 documentation*. https://docs.gns3.com

Harrington, D., Presuhn, R., & Wijnen, B. (2002). *An architecture for describing Simple Network Management Protocol (SNMP) management frameworks* (RFC 3411). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc3411

He, P., Zhu, J., Zheng, Z., & Lyu, M. R. (2017). Drain: An online log parsing approach with fixed depth tree. Dalam *2017 IEEE International Conference on Web Services (ICWS)* (hlm. 33-40). IEEE. https://doi.org/10.1109/ICWS.2017.13

Kurose, J. F., & Ross, K. W. (2021). *Computer networking: A top-down approach* (Edisi ke-8). Pearson.

Lonvick, C. (2001). *The BSD Syslog protocol* (RFC 3164). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc3164

Morris, K. (2020). *Infrastructure as code: Dynamic systems for the cloud age* (Edisi ke-2). O'Reilly Media.

Netmiko. (2024). *Netmiko documentation: Multi-vendor library to simplify SSH connections to network devices*. https://github.com/ktbyers/netmiko

Nygard, M. T. (2018). *Release it! Design and deploy production-ready software* (Edisi ke-2). Pragmatic Bookshelf.

Red Hat. (2024). *Ansible documentation: Network automation*. https://docs.ansible.com

Rekhter, Y., Moskowitz, B., Karrenberg, D., de Groot, G. J., & Lear, E. (1996). *Address allocation for private internets* (RFC 1918). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc1918

Sermersheim, J. (2006). *Lightweight Directory Access Protocol (LDAP): The protocol* (RFC 4511). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc4511

Stallings, W. (2017). *Network security essentials: Applications and standards* (Edisi ke-6). Pearson.

Stouffer, K., Pillitteri, V., Lightman, S., Abrams, M., & Hahn, A. (2015). *Guide to industrial control systems (ICS) security* (NIST Special Publication 800-82 Revisi 2). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-82r2

Ylonen, T., & Lonvick, C. (2006). *The Secure Shell (SSH) protocol architecture* (RFC 4251). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc4251

\pagebreak

# LAMPIRAN

## Lampiran A. Diagram Arsitektur Laboratorium GNS3

Lampiran ini memuat gambar susunan laboratorium sebagaimana tampak pada antarmuka GNS3, meliputi seluruh simpul, kabel penghubung, dan penamaan porta. Gambar tersebut melengkapi Gambar 4.1 pada Bab IV yang menyajikan topologi dalam bentuk skema.

[Tempat gambar tangkapan layar antarmuka GNS3]

## Lampiran B. Konfigurasi Lengkap Perangkat Jaringan

Lampiran ini memuat keluaran perintah `show running-config` dari keempat perangkat Cisco pada laboratorium, yaitu R1, SW-A, R2, dan SW-B. Seluruh nilai hash kata sandi, kunci, dan frasa autentikasi pada keluaran tersebut telah disamarkan.

[Tempat keluaran show running-config R1]

[Tempat keluaran show running-config SW-A]

[Tempat keluaran show running-config R2]

[Tempat keluaran show running-config SW-B]

## Lampiran C. Daftar Kendali Akses Beserta Pencacah Kecocokan

Lampiran ini memuat keluaran perintah `show ip access-lists` pada R2 beserta pencacah kecocokan setiap barisnya, diambil pada tanggal penyusunan laporan. Isi ringkasnya telah disajikan pada Kode 4.5.

[Tempat keluaran show ip access-lists R2]

## Lampiran D. Daftar Program Otomasi

Lampiran ini memuat daftar berkas program beserta fungsinya, meliputi program pembangun topologi, program pengonfigurasi perangkat, program pemantau berkala, dan program pemulih otomatis.

[Tempat daftar berkas program]

## Lampiran E. Keluaran Program Otomasi

Lampiran ini memuat keluaran menjalankan program pembangun topologi dan program pengonfigurasi perangkat, termasuk pesan konfirmasi dari perangkat atas setiap perintah yang diterima.

[Tempat keluaran program]

## Lampiran F. Tangkapan Layar Antarmuka Sistem NSM

Lampiran ini memuat tangkapan layar seluruh halaman sistem NSM yang tidak dicantumkan pada bab utama, yaitu halaman Report, Report per perangkat, Lembar Cetak, Insiden, Layanan, Lalu Lintas, Konfigurasi, Firewall, Potret Konfigurasi, Susun Perintah, Identitas Perangkat, Deteksi Penyimpangan, Backup, Wawasan, Agen SOC, Syslog, dan Audit Log.

!GAMBAR[Gambar F.1 Halaman Report Availability](gambar/report.png)

!GAMBAR[Gambar F.2 Halaman Riwayat Device](gambar/report-device.png)

!GAMBAR[Gambar F.3 Lembar cetak laporan ketersediaan](gambar/report-cetak.png)

!GAMBAR[Gambar F.4 Halaman Insiden](gambar/insiden.png)

!GAMBAR[Gambar F.5 Halaman Layanan](gambar/services.png)

!GAMBAR[Gambar F.6 Halaman Lalu Lintas](gambar/traffic.png)

!GAMBAR[Gambar F.7 Halaman Konfigurasi](gambar/konfig.png)

!GAMBAR[Gambar F.8 Halaman Firewall](gambar/konfig-firewall.png)

!GAMBAR[Gambar F.9 Halaman Potret Konfigurasi](gambar/konfig-potret.png)

!GAMBAR[Gambar F.10 Halaman Susun Perintah Konfigurasi](gambar/konfig-perintah.png)

!GAMBAR[Gambar F.11 Halaman Identitas Perangkat](gambar/konfig-identitas.png)

!GAMBAR[Gambar F.12 Halaman Deteksi Penyimpangan Konfigurasi](gambar/konfig-drift.png)

!GAMBAR[Gambar F.13 Halaman Pemantau Backup](gambar/backup.png)

!GAMBAR[Gambar F.14 Halaman Wawasan](gambar/wawasan.png)

!GAMBAR[Gambar F.15 Halaman Agen SOC](gambar/agen.png)

!GAMBAR[Gambar F.16 Halaman Syslog](gambar/syslog.png)

!GAMBAR[Gambar F.17 Halaman Audit Log](gambar/audit.png)

## Lampiran G. Catatan Kegiatan Harian

Lampiran ini memuat catatan kegiatan harian selama pelaksanaan Praktik Kerja Lapangan, meliputi tanggal, kegiatan yang dilaksanakan, dan hasil yang dicapai, beserta tanda tangan Pembimbing Lapangan.

[Tempat tabel catatan kegiatan harian]

## Lampiran H. Surat Keterangan Pelaksanaan Praktik Kerja Lapangan

Lampiran ini memuat surat keterangan dari PT Bumi Siak Pusako yang menyatakan bahwa penulis telah melaksanakan Praktik Kerja Lapangan pada periode yang disebutkan.

[Tempat salinan surat keterangan]

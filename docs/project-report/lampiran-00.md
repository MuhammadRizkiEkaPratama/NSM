!SAMPUL

!LOGO(gambar/logo-nanjing-xiaozhuang.png)

LAMPIRAN

LAPORAN PRAKTIK KERJA LAPANGAN

IMPLEMENTASI SISTEM NSM (NETWORK STATUS MONITOR) BERBASIS EMULASI GNS3 UNTUK PEMANTAUAN DAN OTOMASI JARINGAN

Disusun oleh:

Nama : Muhammad Rizki Eka Pratama
NIM : L25020010
Program Studi : Software Engineering

NANJING XIAOZHUANG UNIVERSITY
NANJING, REPUBLIK RAKYAT TIONGKOK
2026

\pagebreak

# LAMPIRAN A KONFIGURASI PERANGKAT JARINGAN

Lampiran ini memuat keluaran perintah `show running-config` dari keempat perangkat Cisco pada laboratorium, diambil langsung dari perangkat pada saat laporan disusun. Seluruh nilai *hash* kata sandi telah disamarkan dan digantikan penanda.

## A.1 R1 (Router Lokasi A, Cisco 7200, IOS 15.2(4)S5)

```
Building configuration...

Current configuration : 1681 bytes
version 15.2
service timestamps debug datetime msec
service timestamps log datetime msec localtime show-timezone
hostname R1
boot-start-marker
boot-end-marker
logging buffered 16384 informational
logging rate-limit 20 except errors
no aaa new-model
no ip icmp rate-limit unreachable
ip cef
no ip domain lookup
ip domain name lab.local
no ipv6 cef
multilink bundle-name authenticated
username nsm privilege 15 secret 5 <disamarkan>
ip tcp synwait-time 5
ip ssh version 2
interface FastEthernet0/0
 description lewat tombol NSM
 ip address 192.168.56.60 255.255.255.0
 duplex full
interface FastEthernet1/0
 description WAN ke R2 (lokasi B)
 ip address 10.10.10.1 255.255.255.252
 speed auto
 duplex auto
interface FastEthernet1/1
 no ip address
 shutdown
 speed auto
 duplex auto
ip forward-protocol nd
no ip http server
no ip http secure-server
ip route 0.0.0.0 0.0.0.0 10.10.10.2
ip route 192.168.20.0 255.255.255.0 10.10.10.2
logging source-interface FastEthernet0/0
logging host 192.168.56.156 transport udp port 1514
snmp-server group NSMGRUP v3 priv read NSMVIEW
snmp-server view NSMVIEW iso included
snmp-server trap-source FastEthernet0/0
snmp-server enable traps snmp linkdown linkup coldstart warmstart
snmp-server enable traps config
snmp-server host 192.168.56.156 version 2c public udp-port 1162
control-plane
line con 0
 exec-timeout 0 0
 privilege level 15
 logging synchronous
 stopbits 1
line aux 0
 exec-timeout 0 0
 privilege level 15
 logging synchronous
 stopbits 1
line vty 0 4
 login local
 transport input ssh
ntp server 192.168.56.104
end
```

## A.2 SW-A (Switch Lokasi A, IOU Layer 2, IOS 15.1)

```
Building configuration...

Current configuration : 1938 bytes
version 15.1
service timestamps debug datetime msec
service timestamps log datetime msec
no service password-encryption
service compress-config
hostname SW-A
boot-start-marker
boot-end-marker
logging discriminator EXCESS severity drops 6 msg-body drops EXCESSCOLL
logging buffered 50000
logging console discriminator EXCESS
username nsm privilege 15 secret 4 <disamarkan>
no aaa new-model
no ipv6 cef
ipv6 multicast rpf use-bgp
no ip routing
no ip icmp rate-limit unreachable
no ip domain-lookup
ip domain-name lab.local
no ip cef
spanning-tree mode pvst
spanning-tree extend system-id
vlan internal allocation policy ascending
ip tcp synwait-time 5
ip ssh version 2
interface Ethernet0/0
 duplex auto
interface Ethernet0/1
 duplex auto
interface Ethernet0/2
 duplex auto
interface Ethernet0/3
 duplex auto
interface Ethernet1/0
 duplex auto
interface Ethernet1/1
 duplex auto
interface Ethernet1/2
 duplex auto
interface Ethernet1/3
 duplex auto
interface Ethernet2/0
 duplex auto
interface Ethernet2/1
 duplex auto
interface Ethernet2/2
 duplex auto
interface Ethernet2/3
 duplex auto
interface Ethernet3/0
 duplex auto
interface Ethernet3/1
 duplex auto
interface Ethernet3/2
 duplex auto
interface Ethernet3/3
 duplex auto
interface Vlan1
 ip address 192.168.56.61 255.255.255.0
 no ip route-cache
ip default-gateway 192.168.56.60
no ip http server
logging source-interface Vlan1
logging host 192.168.56.156 transport udp port 1514
snmp-server trap-source Vlan1
snmp-server enable traps snmp linkdown linkup coldstart warmstart
snmp-server host 192.168.56.156 version 2c public udp-port 1162
control-plane
line con 0
 exec-timeout 0 0
 privilege level 15
 logging synchronous
line aux 0
 exec-timeout 0 0
 privilege level 15
 logging synchronous
line vty 0 4
 login local
 transport input ssh
end
```

## A.3 R2 (Router Lokasi B, Cisco 2691, IOS 12.4(13b))

```
Building configuration...

Current configuration : 2812 bytes
! No configuration change since last restart
version 12.4
service timestamps debug datetime msec
service timestamps log datetime msec localtime show-timezone
no service password-encryption
hostname R2
boot-start-marker
boot-end-marker
logging buffered 16384 informational
logging rate-limit 20 except errors
no aaa new-model
memory-size iomem 5
no ip icmp rate-limit unreachable
ip cef
no ip domain lookup
ip domain name lab.local
username nsm privilege 15 secret 5 <disamarkan>
ip tcp synwait-time 5
ip ssh version 2
interface FastEthernet0/0
 description LAN lokasi B ke SW-B
 ip address 192.168.20.1 255.255.255.0
 duplex auto
 speed auto
interface FastEthernet0/1
 description WAN ke ISP - disaring ACL DARI-LOKASI-A
 ip address 10.10.20.2 255.255.255.252
 ip access-group DARI-LOKASI-A in
 duplex auto
 speed auto
ip route 0.0.0.0 0.0.0.0 10.10.20.1
ip route 192.168.56.0 255.255.255.0 10.10.20.1
no ip http server
no ip http secure-server
ip access-list extended DARI-LOKASI-A
 remark dibuat NSM - memisahkan Lokasi A dari Lokasi B
 remark balasan untuk koneksi yang dimulai dari Lokasi B
 permit tcp any any established
 remark pemantauan NSM: ping ke seluruh Lokasi B
 permit icmp 192.168.56.0 0.0.0.255 192.168.20.0 0.0.0.255
 remark NSM: SSH ke .101, R2, dan SW-B (ambil konfigurasi)
 permit tcp host 192.168.56.1 192.168.20.0 0.0.0.255 eq 22
 remark NSM: login lewat LDAP (satu-satunya yang masih perlu 389)
 permit tcp host 192.168.56.1 host 192.168.20.101 eq 389
 remark NSM: SNMP untuk sampel bandwidth (ditemukan lewat deny log)
 permit udp host 192.168.56.1 host 192.168.20.101 eq snmp
 remark server web .103: sssd dan E-Canteen ke direktori LDAP
 permit tcp host 192.168.56.103 host 192.168.20.101 eq 389
 remark data server .104: sssd ke direktori LDAP (login admin terpusat)
 permit tcp host 192.168.56.104 host 192.168.20.101 eq 389
 permit tcp host 192.168.56.105 host 192.168.20.101 eq 389
 remark NTP: JAWABAN dari sumber waktu lab (UDP tidak tertutup established)
 permit udp host 192.168.56.104 eq ntp 192.168.20.0 0.0.0.255
 remark sisanya ditolak DAN DICATAT
 deny   ip any any log
logging source-interface FastEthernet0/0
logging host 192.168.56.156 transport udp port 1514
snmp-server trap-source FastEthernet0/0
snmp-server enable traps snmp linkdown linkup coldstart warmstart
snmp-server enable traps config
snmp-server host 192.168.56.156 version 2c public udp-port 1162
no cdp log mismatch duplex
control-plane
line con 0
 exec-timeout 0 0
 privilege level 15
 logging synchronous
line aux 0
 exec-timeout 0 0
 privilege level 15
 logging synchronous
line vty 0 4
 login local
 transport input ssh
ntp source FastEthernet0/0
ntp server 192.168.56.104
end
```

## A.4 SW-B (Switch Lokasi B, IOU Layer 2, IOS 15.1)

```
Building configuration...

Current configuration : 1936 bytes
version 15.1
service timestamps debug datetime msec
service timestamps log datetime msec
no service password-encryption
service compress-config
hostname SW-B
boot-start-marker
boot-end-marker
logging discriminator EXCESS severity drops 6 msg-body drops EXCESSCOLL
logging buffered 50000
logging console discriminator EXCESS
username nsm privilege 15 secret 4 <disamarkan>
no aaa new-model
no ipv6 cef
ipv6 multicast rpf use-bgp
no ip routing
no ip icmp rate-limit unreachable
no ip domain-lookup
ip domain-name lab.local
no ip cef
spanning-tree mode pvst
spanning-tree extend system-id
vlan internal allocation policy ascending
ip tcp synwait-time 5
ip ssh version 2
interface Ethernet0/0
 duplex auto
interface Ethernet0/1
 duplex auto
interface Ethernet0/2
 duplex auto
interface Ethernet0/3
 duplex auto
interface Ethernet1/0
 duplex auto
interface Ethernet1/1
 duplex auto
interface Ethernet1/2
 duplex auto
interface Ethernet1/3
 duplex auto
interface Ethernet2/0
 duplex auto
interface Ethernet2/1
 duplex auto
interface Ethernet2/2
 duplex auto
interface Ethernet2/3
 duplex auto
interface Ethernet3/0
 duplex auto
interface Ethernet3/1
 duplex auto
interface Ethernet3/2
 duplex auto
interface Ethernet3/3
 duplex auto
interface Vlan1
 ip address 192.168.20.2 255.255.255.0
 no ip route-cache
ip default-gateway 192.168.20.1
no ip http server
logging source-interface Vlan1
logging host 192.168.56.156 transport udp port 1514
snmp-server trap-source Vlan1
snmp-server enable traps snmp linkdown linkup coldstart warmstart
snmp-server host 192.168.56.156 version 2c public udp-port 1162
control-plane
line con 0
 exec-timeout 0 0
 privilege level 15
 logging synchronous
line aux 0
 exec-timeout 0 0
 privilege level 15
 logging synchronous
line vty 0 4
 login local
 transport input ssh
end
```

\pagebreak

# LAMPIRAN B TABEL PERUTEAN PERANGKAT

Isi tabel perutean R1 dan R2 yang benar-benar terpasang, diambil langsung dari perangkat.

```
R1# show ip route
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
S*   0.0.0.0/0 [1/0] via 10.10.20.1
```

\pagebreak

# LAMPIRAN C DAFTAR PROGRAM OTOMASI

Program berikut membangun dan mengonfigurasi laboratorium melalui antarmuka pemrograman GNS3. Seluruhnya ditulis dalam bahasa Python.

!TABEL[Tabel C.1 Program pembangun dan pengatur topologi]

| Berkas | Fungsi |
|---|---|
| api.py | Penghubung menuju antarmuka pemrograman GNS3 |
| bangun_topologi.py | Membuat SW-A, SW-B, R2, jaringan lokal Lokasi B, beserta kabelnya |
| tambah_isp.py | Menyisipkan router penyedia jasa ke jalur antarlokasi |
| konfigurasi_lokasi.py | Mengonfigurasi Cisco IOS pada R1, R2, SW-A, dan SW-B |
| konfigurasi_isp.py | Mengonfigurasi router penyedia jasa |
| konsol.py | Mengirim perintah melalui konsol memakai soket mentah |
| lihat_topologi.py | Memeriksa simpul, kabel, dan porta yang masih kosong |
| acl_lokasi_b.py | Memasang daftar kendali akses pada R2 |
| pasang_ntp_router.py | Menyetel sumber waktu pada perangkat Cisco |
| nyalakan_log_router.py | Mengarahkan pesan syslog perangkat ke penampung |
| hidupkan_ulang_node.py | Menyalakan ulang simpul GNS3 yang terbukti mati |

\pagebreak

# LAMPIRAN D POTONGAN KODE PROGRAM

## D.1 Daftar perintah konfigurasi awal R2

Potongan berikut adalah daftar perintah yang disusun program lalu dikirimkan ke R2 melalui konsol. Nilai kata sandi dibaca dari berkas setelan, tidak ditulis di dalam kode.

```python
"configure terminal",
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
"end",
```

## D.2 Pemasangan SNMP versi 3 pada server Linux

Layanan dihentikan lebih dulu karena perintah pembuat pengguna menulis langsung ke berkas keadaan layanan, dan menulis berkas itu selagi layanan berjalan menyebabkan perubahan hilang saat layanan berhenti. Penanda `-ro` membuat pengguna hanya memiliki hak baca.

```
sudo apt install snmpd

sudo systemctl stop snmpd
sudo net-snmp-create-v3-user -ro \
     -a SHA -A <frasa-autentikasi> \
     -x AES -X <frasa-enkripsi> \
     nsmmon
sudo systemctl start snmpd
```

\pagebreak

# LAMPIRAN E TANGKAPAN LAYAR ANTARMUKA SISTEM

Seluruh tangkapan layar berikut diambil dari sistem NSM yang sedang berjalan pada alamat 192.168.56.156 porta 8080, memakai akun pengguna sungguhan, pada saat laporan disusun.

!GAMBAR[Gambar E.1 Halaman Dashboard](gambar/lampiran-dashboard.png)

!GAMBAR[Gambar E.2 Halaman Report Availability](gambar/lampiran-report.png)

!GAMBAR[Gambar E.3 Halaman Riwayat Device](gambar/report-device.png)

!GAMBAR[Gambar E.4 Lembar cetak laporan ketersediaan](gambar/report-cetak.png)

!GAMBAR[Gambar E.5 Halaman Insiden](gambar/lampiran-insiden.png)

!GAMBAR[Gambar E.6 Garis waktu satu insiden](gambar/lampiran-insiden-detail.png)

!GAMBAR[Gambar E.7 Halaman Layanan](gambar/services.png)

!GAMBAR[Gambar E.8 Halaman Lalu Lintas](gambar/traffic.png)

!GAMBAR[Gambar E.9 Halaman Konfigurasi](gambar/konfig.png)

!GAMBAR[Gambar E.10 Halaman Kepatuhan Konfigurasi](gambar/lampiran-konfig-kepatuhan.png)

!GAMBAR[Gambar E.11 Halaman Firewall](gambar/lampiran-konfig-firewall.png)

!GAMBAR[Gambar E.12 Halaman Potret Konfigurasi](gambar/konfig-potret.png)

!GAMBAR[Gambar E.13 Halaman Susun Perintah Konfigurasi](gambar/konfig-perintah.png)

!GAMBAR[Gambar E.14 Halaman Pagar Otomasi](gambar/lampiran-konfig-pagar.png)

!GAMBAR[Gambar E.15 Halaman Identitas Perangkat](gambar/konfig-identitas.png)

!GAMBAR[Gambar E.16 Halaman Deteksi Penyimpangan Konfigurasi](gambar/konfig-drift.png)

!GAMBAR[Gambar E.17 Halaman Kesehatan Sistem](gambar/lampiran-kesehatan.png)

!GAMBAR[Gambar E.18 Halaman Pemantau Backup](gambar/lampiran-backup.png)

!GAMBAR[Gambar E.19 Halaman Wawasan](gambar/lampiran-wawasan.png)

!GAMBAR[Gambar E.20 Halaman Agen SOC](gambar/agen.png)

!GAMBAR[Gambar E.21 Halaman Syslog](gambar/syslog.png)

!GAMBAR[Gambar E.22 Halaman Audit Log](gambar/audit.png)

\pagebreak

# LAMPIRAN F CATATAN KEGIATAN HARIAN

Catatan kegiatan harian selama pelaksanaan Praktik Kerja Lapangan, memuat tanggal, kegiatan yang dilaksanakan, dan hasil yang dicapai, beserta paraf Pembimbing Lapangan.

!TABEL[Tabel F.1 Catatan kegiatan harian]

| Tanggal | Kegiatan | Hasil | Paraf |
|---|---|---|---|
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |

\pagebreak

# LAMPIRAN G SURAT KETERANGAN PELAKSANAAN

Surat keterangan dari PT Bumi Siak Pusako yang menyatakan bahwa penulis telah melaksanakan Praktik Kerja Lapangan pada periode yang disebutkan.

[Tempat salinan surat keterangan]

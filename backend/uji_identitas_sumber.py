"""Tests for the identity marker sources: ARP, SNMP, SSH.

Companion of `uji_identitas.py` (which tests the weighing); this tests collection.
Two cases come from real defects:
  1. MAC from the wrong NIC on a multi-homed machine: the VMs have a NAT NIC (default
     route) and a host-only NIC (used by NSM); ARP sees the host-only one.
  2. Different MAC notations: Windows uses hyphens, Linux colons, Cisco dots.

Both end in `bertentangan`, which BLOCKS the write path; a guard that accuses the
right device is worse than none.

No device is contacted; all parsing is tested with recorded output.
"""
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

import identitas_sumber as s

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


# ---------------------------------------------------------------------------
print("\n1. PENULISAN MAC DISERAGAMKAN SEBELUM DIBANDINGKAN")
print("   (kalau tidak, MAC yang sama dari dua sumber terbaca bertentangan)")

for bentuk in ("02-00-5e-10-00-01",      # Windows
               "02:00:5E:10:00:01",      # Linux, huruf besar
               "02:00:5e:10:00:01",      # Linux, huruf kecil
               "0200.5e10.0001",         # Cisco
               "2458-6ED0-190E"):
    sama("bentuk %-20s" % bentuk, s.normalkan_mac(bentuk), "02:00:5e:10:00:01")

bentuk_beda = {s.normalkan_mac(x) for x in
               ("02-00-5e-10-00-01", "02:00:5E:10:00:01", "0200.5e10.0001")}
benar("tiga penulisan berbeda menghasilkan SATU nilai", len(bentuk_beda) == 1,
      "-> %r; MAC yang sama akan dinilai bertentangan" % bentuk_beda)

for buruk in ("", None, "bukan mac", "02-00-5e-10-00", "02-00-5e-10-00-01-ff"):
    sama("ditolak: %r" % buruk, s.normalkan_mac(buruk), None)

# ---------------------------------------------------------------------------
print("\n2. MAC SEMU TIDAK BOLEH JADI PENANDA")
print("   (semuanya cocok dengan banyak perangkat sekaligus, yaitu kebalikan")
print("    dari identitas)")

for semu in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00",
             "01:00:5e:00:00:fb", "33:33:00:00:00:01"):
    benar("dibuang: %s" % semu, s._mac_semu(semu))
benar("MAC sungguhan tidak ikut dibuang", not s._mac_semu("02:00:5e:10:00:01"))

# ---------------------------------------------------------------------------
print("\n3. URAIAN TABEL ARP")

ARP_WINDOWS = """
Interface: 192.168.56.1 --- 0x3
  Internet Address      Physical Address      Type
  192.168.56.60         ca-01-0a-6f-00-00     dynamic
  192.168.56.101        08-00-27-35-8d-d0     dynamic
  192.168.56.255        ff-ff-ff-ff-ff-ff     static
  224.0.0.22            01-00-5e-00-00-16     static

Interface: 192.168.1.3 --- 0x9
  192.168.1.1           02-00-5e-10-00-01     dynamic
  192.168.1.255         ff-ff-ff-ff-ff-ff     static
"""
peta = s.baca_arp(ARP_WINDOWS)
sama("router GNS3 terbaca", peta.get("192.168.56.60"), "ca:01:0a:6f:00:00")
sama("VM terbaca", peta.get("192.168.56.101"), "08:00:27:35:8d:d0")
sama("gateway rumah terbaca", peta.get("192.168.1.1"), "02:00:5e:10:00:01")
benar("alamat siaran .255 tidak ikut", "192.168.56.255" not in peta)
benar("alamat multicast tidak ikut", "224.0.0.22" not in peta)
sama("jumlah yang terbaca", len(peta), 3)
sama("tabel kosong tidak meledak", s.baca_arp(""), {})
sama("teks None tidak meledak", s.baca_arp(None), {})

# ---------------------------------------------------------------------------
print("\n4. PERINTAH MAC LINUX BERTANYA SOAL ALAMAT YANG BENAR")
print("   (cacat nyata 8 Agu 2026: MAC kartu NAT terambil, bukan kartu")
print("    host-only yang dipakai NSM; dua-duanya sah, pertanyaannya yang salah)")

perintah = dict(s.perintah_linux("192.168.56.101"))["mac"]
benar("alamat perangkat ikut ke dalam perintah",
      "192.168.56.101" in perintah,
      "-> perintahnya tidak menyebut alamat, jadi ia menebak kartu")
benar("TIDAK lagi memakai rute bawaan",
      "route show default" not in perintah and "route get" not in perintah,
      "-> pada mesin bermuka banyak ini mengambil kartu yang salah")
benar("membaca alamat kartu dari /sys/class/net",
      "/sys/class/net/" in perintah)

# The address is sanitized before entering the shell command line.
jahat = dict(s.perintah_linux("192.168.1.1; rm -rf /"))["mac"]
benar("alamat dibersihkan sebelum masuk perintah shell",
      "rm -rf" not in jahat and ";" not in jahat.split("awk")[0],
      "-> %r" % jahat)

# ---------------------------------------------------------------------------
print("\n5. WINDOWS SENGAJA TIDAK DITANYAI MAC")
print("   (laptop ini punya belasan kartu; jawaban yang salah menghasilkan")
print("    'bertentangan' pada perangkat yang benar)")

label = [x[0] for x in s.PERINTAH_WINDOWS]
benar("nama mesin ditanyakan", "hostname" in label)
benar("MAC tidak ditanyakan lewat SSH", "mac" not in label,
      "-> MAC-nya sudah pasti dari psutil, dipetakan menurut alamatnya")

# ---------------------------------------------------------------------------
print("\n6. URAIAN show version CISCO")

SHOW_VERSION = """Cisco IOS Software, 7200 Software (C7200-ADVENTERPRISEK9-M), Version 15.2(4)S7, RELEASE SOFTWARE (fc4)
Technical Support: http://www.cisco.com/techsupport
Copyright (c) 1986-2016 by Cisco Systems, Inc.

ROM: ROMMON EMULATION MICROCODE

R1 uptime is 2 hours, 11 minutes
System returned to ROM by unknown reload cause

Cisco 7206VXR (NPE400) processor (revision A) with 491520K/32768K bytes of memory.
Processor board ID 4279256517
"""
rinci = s.urai_show_version(SHOW_VERSION)
sama("serial terbaca", rinci.get("serial"), "4279256517")
sama("model terbaca", rinci.get("model"), "7206VXR")
benar("versi IOS terbaca", (rinci.get("versi_ios") or "").startswith("15.2"),
      "-> %r" % rinci.get("versi_ios"))
sama("teks kosong tidak meledak", s.urai_show_version(""), {})

# ---------------------------------------------------------------------------
print("\n7. URAIAN KELUARAN LINUX")

bersih = s.parse_linux({
    "machine_id": "af7c5983589e46ceba12cdefb762662f\n",
    "hostname": "nsm-ubuntu\n",
    "mac": "08:00:27:35:8d:d0\n",
})
sama("machine-id terbaca", bersih.get("machine_id"),
     "af7c5983589e46ceba12cdefb762662f")
sama("hostname terbaca", bersih.get("hostname"), "nsm-ubuntu")
sama("mac terbaca sudah seragam", bersih.get("mac"), "08:00:27:35:8d:d0")

# A machine-id containing an error message must NOT be stored, or it would be compared as if it were an identity.
for buruk in ("cat: /etc/machine-id: No such file or directory", "", "   ",
              "bukan-heks-sama-sekali"):
    hasil = s.parse_linux({"machine_id": buruk})
    benar("machine-id ditolak: %r" % buruk[:34], "machine_id" not in hasil,
          "-> tersimpan %r" % hasil.get("machine_id"))

benar("keluaran kosong menghasilkan penanda kosong, bukan galat",
      s.parse_linux({}) == {})

# MAC 00:00:00:00:00:00 (e.g. the `lo` interface) must not pass.
benar("MAC nol tidak jadi penanda",
      "mac" not in s.parse_linux({"mac": "00:00:00:00:00:00"}))

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

"""Tests for the Samba audit log parser (`connectors/sambaaudit.py`), which answers who deleted a file, when, and from which machine.
Checks:
  1. the %u|%I|%S|%m fields parse to user / address / share / client machine
  2. `openat` distinguishes read (r) from write (w)
  3. Explorer noise (repeated folder opens) is filtered
  4. deletions and failures are never filtered
  5. file names containing "|" do not break parsing
  6. server UTC timestamps are shifted to local time
Sample lines are real entries from the file server's samba-audit.log.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from connectors import sambaaudit

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


P = "2026-08-19T01:49:57.351920+00:00 file-server smbd_audit: "

NYATA = [
    P + "dewi|192.168.56.1|sharing|lab-pc|openat|ok|r|/srv/sharing",
    P + "dewi|192.168.56.1|sharing|lab-pc|openat|ok|r|/srv/sharing/file penting",
    P + "dewi|192.168.56.1|sharing|lab-pc|openat|ok|r|/srv/sharing/file penting/.",
    P + "dewi|192.168.56.1|sharing|lab-pc|openat|ok|r|/srv/sharing/file penting/..",
    P + "dewi|192.168.56.1|sharing|lab-pc|openat|ok|r|/srv/sharing/file penting/usernamePenting.txt",
    P + "dewi|192.168.56.1|sharing|lab-pc|unlinkat|ok|/srv/sharing/file penting/usernamePenting.txt",
    P + "dewi|192.168.56.1|sharing|lab-pc|openat|fail (No such file or directory)|r|/srv/sharing/file penting/usernamePenting.txt",
]

print("=" * 74)
print("UJI PENGURAI AUDIT SAMBA (connectors/sambaaudit.py)")
print("=" * 74)

# ---------------------------------------------------------------------------
print("\n1. Bidang %u|%I|%S|%m terurai -- termasuk NAMA MESIN KLIEN")
print("   (inilah 'device Z' pada pertanyaan 'si X hapus berkas Y di device Z')")

d = sambaaudit.urai_baris(
    P + "dewi|192.168.56.1|sharing|lab-pc|unlinkat|ok|/srv/sharing/rahasia.xlsx")
benar("baris terurai (bukan None)", d is not None)
if d:
    sama("pengguna dari LDAP", d["pengguna"], "dewi")
    sama("alamat klien", d["ip_klien"], "192.168.56.1")
    sama("nama share", d["berbagi"], "sharing")
    sama("NAMA MESIN klien", d["mesin_klien"], "lab-pc")
    sama("operasi", d["operasi"], "unlinkat")
    sama("hasil", d["hasil"], "ok")
    sama("berkas", d["jalur"], "/srv/sharing/rahasia.xlsx")

# ---------------------------------------------------------------------------
print("\n2. `openat` membedakan DIBACA (r) dari DITULIS (w)")
print("   (temuan dari uji nyata -- man page tidak menyebut bidang ini)")

dr = sambaaudit.urai_baris(P + "arif|10.0.0.5|sharing|pc-arif|openat|ok|r|/srv/sharing/a.xlsx")
dw = sambaaudit.urai_baris(P + "arif|10.0.0.5|sharing|pc-arif|openat|ok|w|/srv/sharing/a.xlsx")
sama("dibaca -> arah r", dr and dr["arah"], "r")
sama("ditulis -> arah w", dw and dw["arah"], "w")
sama("dibaca jadi aksi AMBIL",
     sambaaudit._siap_simpan(dr, "/srv/sharing")["aksi"], "AMBIL")
sama("ditulis jadi aksi KIRIM",
     sambaaudit._siap_simpan(dw, "/srv/sharing")["aksi"], "KIRIM")

# ---------------------------------------------------------------------------
print("\n3. DERAU Explorer disaring, PERBUATAN tetap utuh")
print("   (7 baris nyata di atas: 3 derau + 4 yang bermakna)")

kejadian, disaring = sambaaudit.gabung(NYATA, "/srv/sharing")
aksi = [(k["aksi"], k["jalur"]) for k in kejadian]
benar("ada yang disaring", disaring > 0, "-> disaring %d" % disaring)
benar("membuka AKAR share disaring",
      not any(k["jalur"] in ("", "/srv/sharing") for k in kejadian),
      "-> %r" % aksi)
benar("entri '.' dan '..' disaring",
      not any((k["jalur"] or "").endswith((".", "..")) for k in kejadian),
      "-> %r" % aksi)

# ---------------------------------------------------------------------------
print("\n4. PENGHAPUSAN dan KEGAGALAN tidak pernah hilang")

benar("penghapusan tercatat",
      ("HAPUS", "file penting/usernamePenting.txt") in aksi, "-> %r" % aksi)
benar("percobaan yang GAGAL tetap tercatat",
      any(k["hasil"] == "gagal" for k in kejadian),
      "-> %r" % [(k["aksi"], k["hasil"]) for k in kejadian])
benar("membuka berkas sungguhan tercatat",
      ("AMBIL", "file penting/usernamePenting.txt") in aksi, "-> %r" % aksi)

# ---------------------------------------------------------------------------
print("\n5. Dua penghapusan berkas SAMA dalam 3 detik = DUA kejadian")
print("   (kembar hanya disaring untuk operasi yang tidak mengubah apa pun)")

dua_hapus = [
    "2026-08-19T01:49:57.100000+00:00 file-server smbd_audit: "
    "dewi|192.168.56.1|sharing|lab-pc|unlinkat|ok|/srv/sharing/x.txt",
    "2026-08-19T01:49:57.900000+00:00 file-server smbd_audit: "
    "dewi|192.168.56.1|sharing|lab-pc|unlinkat|ok|/srv/sharing/x.txt",
]
k2, _ = sambaaudit.gabung(dua_hapus, "/srv/sharing")
sama("dua penghapusan tetap dua baris", len(k2), 2)

print("\n5b. Tapi dua kali MEMBUKA berkas sama dalam 3 detik = SATU")
dua_buka = [
    "2026-08-19T01:49:57.100000+00:00 file-server smbd_audit: "
    "dewi|192.168.56.1|sharing|lab-pc|openat|ok|r|/srv/sharing/x.txt",
    "2026-08-19T01:49:57.900000+00:00 file-server smbd_audit: "
    "dewi|192.168.56.1|sharing|lab-pc|openat|ok|r|/srv/sharing/x.txt",
]
k3, d3 = sambaaudit.gabung(dua_buka, "/srv/sharing")
sama("dua pembukaan kembar jadi satu", len(k3), 1)

# ---------------------------------------------------------------------------
print("\n6. Nama berkas yang MENGANDUNG '|' tidak memotong penguraian")
print("   (bidang dipisah '|', jadi nama berkas ber-'|' adalah jebakan nyata)")

dp = sambaaudit.urai_baris(
    P + "dewi|192.168.56.1|sharing|lab-pc|unlinkat|ok|/srv/sharing/laporan|final.xlsx")
sama("nama berkas utuh", dp and dp["jalur"], "/srv/sharing/laporan|final.xlsx")

# ---------------------------------------------------------------------------
print("\n7. Zona waktu server (UTC) digeser ke waktu lokal, bukan dibuang")

t = sambaaudit.urai_waktu("2026-08-19T01:49:57.351920+00:00")
benar("waktu terurai", isinstance(t, datetime))
benar("tidak menyimpan tzinfo (sudah jadi waktu lokal)",
      t is not None and t.tzinfo is None)

# ---------------------------------------------------------------------------
print("\n8. Baris asing / rusak dilewati, tidak bikin kacau")

benar("baris bukan smbd_audit -> None",
      sambaaudit.urai_baris("2026-08-19T01:00:00+00:00 file-server sshd: hello") is None)
benar("baris kurang bidang -> None",
      sambaaudit.urai_baris(P + "dewi|192.168.56.1") is None)
benar("baris kosong -> None", sambaaudit.urai_baris("") is None)

# ---------------------------------------------------------------------------
print("\n9. Baris kompresi rsyslog ('message repeated N times') DITOLAK")
print("   (ketahuan nyata di basis data 19 Agustus 2026: pengguna jadi rusak)")

rusak = sambaaudit.urai_baris(
    "2026-08-19T01:23:08.015734+00:00 file-server smbd_audit: "
    "message repeated 4 times: [ dewi|192.168.56.1|sharing|lab-pc|"
    "openat|ok|r|/srv/sharing]")
sama("baris kompresi -> None (ditolak, bukan diterima rusak)", rusak, None)

# ---------------------------------------------------------------------------
print("\n10. MEMBUKA FOLDER (dibuktikan dari data) disaring; ISINYA tidak")
print("    (inilah akar 'kebanyakan DOWNLOAD' yang dilaporkan pengguna)")

P2 = "2026-08-19T08:48:00.000000+00:00 file-server smbd_audit: "
JELAJAH = [
    # The same file is opened repeatedly while Explorer browses; timestamps differ by more than 3 seconds so the twin filter does not catch them, but they must not be logged as DOWNLOAD.
    P2.replace("08:48:00", "08:48:28") +
        "dewi|192.168.56.1|sharing|lab-pc|openat|ok|r|/srv/sharing/file penting",
    P2.replace("08:48:00", "08:48:44") +
        "dewi|192.168.56.1|sharing|lab-pc|openat|ok|r|/srv/sharing/file penting",
    P2.replace("08:48:00", "08:49:24") +
        "dewi|192.168.56.1|sharing|lab-pc|openat|ok|r|/srv/sharing/file penting",
    P2.replace("08:48:00", "08:49:51") +
        "dewi|192.168.56.1|sharing|lab-pc|openat|ok|r|/srv/sharing/file penting",
    # Really opened: must still be recorded as a download (AMBIL).
    P2.replace("08:48:00", "08:48:44") +
        "dewi|192.168.56.1|sharing|lab-pc|openat|ok|r|"
        "/srv/sharing/file penting/usernamePenting.txt",
]
k9, d9 = sambaaudit.gabung(JELAJAH, "/srv/sharing")
aksi9 = [(k["aksi"], k["jalur"]) for k in k9]
benar("EMPAT kali buka FOLDER 'file penting' semuanya disaring",
      not any(k["jalur"] == "file penting" for k in k9), "-> %r" % aksi9)
benar("berkas SUNGGUHAN di dalamnya tetap tercatat",
      ("AMBIL", "file penting/usernamePenting.txt") in aksi9, "-> %r" % aksi9)

print("\n10b. mkdirat SENDIRIAN (tanpa isi disebut) juga cukup membuktikan folder")
BUAT_KOSONG = [
    P2.replace("08:48:00", "08:48:22") +
        "dewi|192.168.56.1|sharing|lab-pc|mkdirat|ok|/srv/sharing/New folder",
    P2.replace("08:48:00", "08:48:25") +
        "dewi|192.168.56.1|sharing|lab-pc|openat|ok|r|/srv/sharing/New folder",
]
k10, _ = sambaaudit.gabung(BUAT_KOSONG, "/srv/sharing")
aksi10 = [(k["aksi"], k["jalur"]) for k in k10]
benar("folder baru tercatat DIBUAT",
      ("BUAT_FOLDER", "New folder") in aksi10, "-> %r" % aksi10)
benar("membukanya sesudah itu disaring (sudah terbukti folder)",
      ("AMBIL", "New folder") not in aksi10, "-> %r" % aksi10)

# ---------------------------------------------------------------------------
print("\n11. Intaian ikon Explorer (folder.jpg dkk) yang GAGAL disaring;")
print("    yang benar-benar ADA di server (berhasil dibuka) TETAP tercatat")

P3 = "2026-08-19T08:48:29.000000+00:00 file-server smbd_audit: "
k11, _ = sambaaudit.gabung([
    P3 + "dewi|192.168.56.1|sharing|lab-pc|openat|fail (No such file or directory)|r|/srv/sharing/folder.jpg",
    P3 + "dewi|192.168.56.1|sharing|lab-pc|openat|fail (No such file or directory)|r|/srv/sharing/desktop.ini",
], "/srv/sharing")
benar("intaian ikon yang gagal disaring semua", len(k11) == 0, "-> %r" % k11)

k11b, _ = sambaaudit.gabung([
    P3 + "dewi|192.168.56.1|sharing|lab-pc|openat|ok|r|/srv/sharing/folder.jpg",
], "/srv/sharing")
benar("folder.jpg yang SUNGGUHAN ada (berhasil) tetap tercatat",
      len(k11b) == 1 and k11b[0]["jalur"] == "folder.jpg", "-> %r" % k11b)

k11c, _ = sambaaudit.gabung([
    P3 + "dewi|192.168.56.1|sharing|lab-pc|openat|fail (Permission denied)|r|/srv/sharing/rahasia.xlsx",
], "/srv/sharing")
benar("kegagalan pada berkas BUKAN-intaian tetap tercatat (bukan disembunyikan)",
      len(k11c) == 1, "-> %r" % k11c)

# ---------------------------------------------------------------------------
print("\n12. Copy sisi-server (offload_read_send/write_send) jadi SATU baris SALIN")
print("    (disalin APA ADANYA dari 2 kejadian nyata, 19 Agustus 2026)")

P4 = "2026-08-19T03:21:17."
NYATA_SALIN = [
    P4 + "525366+00:00 file-server smbd_audit: dewi|192.168.56.1|sharing|lab-pc|openat|ok|w|/srv/sharing/10mb-examplefile-com.txt",
    P4 + "526346+00:00 file-server smbd_audit: dewi|192.168.56.1|sharing|lab-pc|openat|ok|r|/srv/sharing",
    P4 + "529478+00:00 file-server smbd_audit: dewi|192.168.56.1|sharing|lab-pc|offload_read_send|ok|",
    P4 + "533509+00:00 file-server smbd_audit: dewi|192.168.56.1|sharing|lab-pc|offload_write_send|ok|",
    P4 + "536144+00:00 file-server smbd_audit: dewi|192.168.56.1|sharing|lab-pc|offload_write_send|ok|",
    P4 + "549342+00:00 file-server smbd_audit: dewi|192.168.56.1|sharing|lab-pc|offload_write_send|ok|",
]
k12, d12 = sambaaudit.gabung(NYATA_SALIN, "/srv/sharing")
benar("tepat SATU kejadian tersimpan (bukan 6 baris terpisah)", len(k12) == 1,
      "-> %r" % k12)
if k12:
    sama("kejadiannya berlabel SALIN", k12[0]["aksi"], "SALIN")
    sama("nama berkas diambil dari openat...w", k12[0]["jalur"],
         "10mb-examplefile-com.txt")
    sama("berhasil", k12[0]["hasil"], "ok")

print("\n12b. TANPA openat...w yang bisa dikaitkan -> DIBUANG, bukan ditebak")
YATIM = [
    P4 + "600000+00:00 file-server smbd_audit: dewi|192.168.56.1|sharing|lab-pc|offload_read_send|ok|",
    P4 + "605000+00:00 file-server smbd_audit: dewi|192.168.56.1|sharing|lab-pc|offload_write_send|ok|",
]
k12b, d12b = sambaaudit.gabung(YATIM, "/srv/sharing")
benar("tidak ada baris SALIN tanpa dasar nama berkas", len(k12b) == 0,
      "-> %r" % k12b)

print("\n12c. openat...w yang JAUH sebelumnya (>2 detik) TIDAK dikaitkan")
JAUH = [
    "2026-08-19T03:21:10.000000+00:00 file-server smbd_audit: "
    "dewi|192.168.56.1|sharing|lab-pc|openat|ok|w|/srv/sharing/lain.txt",
    "2026-08-19T03:21:20.000000+00:00 file-server smbd_audit: "
    "dewi|192.168.56.1|sharing|lab-pc|offload_read_send|ok|",
]
k12c, _ = sambaaudit.gabung(JAUH, "/srv/sharing")
aksi12c = [(k["aksi"], k["jalur"]) for k in k12c]
benar("openat...w lama tetap tercatat sebagai KIRIM biasa (tidak diklaim)",
      ("KIRIM", "lain.txt") in aksi12c, "-> %r" % aksi12c)
benar("tidak ada SALIN yang salah kaitan ke berkas 10 detik sebelumnya",
      not any(k[0] == "SALIN" for k in aksi12c), "-> %r" % aksi12c)

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

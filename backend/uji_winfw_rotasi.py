"""Tests for reading `pfirewall.log` (Windows Firewall), `connectors/winfw.py`.
Windows rotates the log when full (4 MB): the old file becomes `.old` and a new empty one starts, so the tail of the old file exists only in `.old`. Tested: rotation detection via a shrinking file size, reading the `.old` tail and merging with the new file, plus two known traps:
  - column order comes from the real `#Fields:` header, not an assumed order (it differs between Windows versions)
  - the first line after rotation may start with NUL bytes, which must be stripped before `.split()`
Runs entirely on temp files; `winfw.JALUR_LOG` is swapped temporarily so `baca_log_potongan()` reads the test file.
"""
import os
import sys
import tempfile

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

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


print("=" * 74)
print("UJI ROTASI LOG WINDOWS FIREWALL (connectors/winfw.py)")
print("=" * 74)

import connectors.winfw as winfw

TMPDIR = tempfile.mkdtemp(prefix="uji_winfw_")
JALUR = os.path.join(TMPDIR, "pfirewall.log")

HEADER = ("#Fields: date time action protocol src-ip dst-ip src-port "
          "dst-port size tcpflags tcpsyn tcpack tcpwin icmptype icmpcode "
          "info path pid\n")


def baris_drop(waktu, src, dst, dport, sport=51000):
    return ("2026-08-17 %s DROP TCP %s %s %d %d 40 - - - - - - - - -\n"
            % (waktu, src, dst, sport, dport))


def baris_allow(waktu, src, dst, dport, sport=51000):
    return ("2026-08-17 %s ALLOW TCP %s %s %d %d 40 - - - - - - - - -\n"
            % (waktu, src, dst, sport, dport))


def tulis(jalur, isi):
    with open(jalur, "w", encoding="utf-8", newline="") as fh:
        fh.write(isi)


# ---------------------------------------------------------------------------
print("\n1. BERKAS BELUM ADA SAMA SEKALI -> ada=False, BUKAN GALAT")
print("   (beda dari 'berkas ada tapi kosong': logging Windows mungkin")
print("    memang belum dinyalakan.)")

winfw.JALUR_LOG = os.path.join(TMPDIR, "tidak-ada.log")
entri, posisi, diputar, ada = winfw.baca_log_potongan(0)
sama("entri kosong", entri, [])
sama("posisi tetap 0", posisi, 0)
sama("diputar False", diputar, False)
sama("ada False", ada, False)

# ---------------------------------------------------------------------------
print("\n2. PEMBACAAN PERTAMA (posisi 0) — HANYA DROP, ALLOW DIABAIKAN")

winfw.JALUR_LOG = JALUR
tulis(JALUR, HEADER
     + baris_allow("10:00:00", "10.66.66.60", "192.168.56.103", 80)
     + baris_drop("10:00:01", "10.66.66.66", "192.168.56.103", 22)
     + baris_drop("10:00:02", "10.66.66.67", "192.168.56.103", 3389))

entri, posisi1, diputar, ada = winfw.baca_log_potongan(0)
sama("ada True", ada, True)
sama("diputar False (pembacaan pertama)", diputar, False)
sama("hanya 2 DROP, ALLOW disaring", len(entri), 2)
sama("alamat asal baris pertama benar", entri[0]["dari"], "10.66.66.66")
sama("port tujuan terbaca benar", entri[0]["port_ke"], 22)
sama("acl ditandai winfw", entri[0]["acl"], "winfw")
benar("posisi baca maju", posisi1 > 0)

# ---------------------------------------------------------------------------
print("\n3. UTUH TERHADAP UKURAN KOLOM YANG BEDA DARI HEADER — DIAMBIL DARI")
print("   BERKAS, BUKAN DITEBAK DARI FIELD_BAWAAN")
print("   (src-ip/dst-ip dan src-port/dst-port SENGAJA ditukar posisinya")
print("    di header, membuktikan pemetaan ikut urutan header sungguhan.)")

HEADER_TUKAR = ("#Fields: date time action protocol dst-ip src-ip "
                "dst-port src-port size tcpflags tcpsyn tcpack tcpwin "
                "icmptype icmpcode info path pid\n")
baris_tukar = ("2026-08-17 11:00:00 DROP TCP 192.168.56.103 10.66.66.99 "
              "445 55000 40 - - - - - - - - -\n")
tulis(JALUR, HEADER_TUKAR + baris_tukar)

entri, _p, _d, _a = winfw.baca_log_potongan(0)
sama("satu entri terbaca", len(entri), 1)
sama("'dari' diambil dari kolom src-ip SUNGGUHAN (posisi ke-6)",
     entri[0]["dari"], "10.66.66.99")
sama("'ke' diambil dari kolom dst-ip SUNGGUHAN (posisi ke-5)",
     entri[0]["ke"], "192.168.56.103")
sama("port juga dipetakan dari posisi kolom SUNGGUHAN (dst-port di posisi ke-7)",
     entri[0]["port_ke"], 445)

# ---------------------------------------------------------------------------
print("\n4. PEMBACAAN LANJUTAN (posisi > 0, TANPA header di posisi itu)")
print("   memakai FIELD_BAWAAN sebagai asumsi urutan standar")

tulis(JALUR, HEADER
     + baris_drop("10:00:00", "10.66.66.66", "192.168.56.103", 22))
with open(JALUR, encoding="utf-8") as fh:
    fh.seek(0, os.SEEK_END)
    posisi_tengah = fh.tell()
with open(JALUR, "a", encoding="utf-8", newline="") as fh:
    fh.write(baris_drop("10:05:00", "10.66.66.68", "192.168.56.103", 3306))

entri, posisi2, diputar, ada = winfw.baca_log_potongan(posisi_tengah)
sama("diputar False (berkas masih tumbuh, bukan diputar)", diputar, False)
sama("hanya entri BARU yang terbaca (bukan dari awal lagi)", len(entri), 1)
sama("entri baru itu benar", entri[0]["dari"], "10.66.66.68")

# ---------------------------------------------------------------------------
print("\n5. NUL BYTE DI AWAL BARIS TIDAK MENGGESER PEMETAAN KOLOM")
print("   (artefak Windows: berkas dialokasikan sebelum diisi.)")

baris_nul = "\x00\x00\x00" + baris_drop("12:00:00", "10.66.66.70", "192.168.56.103", 22)
tulis(JALUR, HEADER + baris_nul)
entri, _p, _d, _a = winfw.baca_log_potongan(0)
sama("baris ber-NUL tetap terurai benar", len(entri), 1)
sama("field tidak bergeser", entri[0]["dari"], "10.66.66.70")

# ---------------------------------------------------------------------------
print("\n6. ROTASI TERDETEKSI DARI UKURAN YANG MENGECIL, EKOR .old TERBACA")
print("   (Windows: berkas lama -> .old, berkas baru dibuat kosong.)")

# The "before rotation" file is large enough and read to position P, so the new post-rotation file is smaller than P, as on Windows.
tulis(JALUR, HEADER
     + baris_drop("13:00:00", "10.66.66.80", "192.168.56.103", 22)
     + baris_drop("13:00:01", "10.66.66.80", "192.168.56.103", 23)
     + baris_drop("13:00:02", "10.66.66.80", "192.168.56.103", 24))
entri_awal, posisi_p, _d, _a = winfw.baca_log_potongan(0)
sama("bacaan awal 3 entri", len(entri_awal), 3)

# Rotation: everything read (up to P) plus the unread tail moves to .old; a new, smaller file replaces it.
isi_sebelum_rotasi = open(JALUR, encoding="utf-8").read()
tulis(JALUR + ".old", isi_sebelum_rotasi
     + baris_drop("13:00:05", "10.66.66.81", "192.168.56.103", 3389))
tulis(JALUR, HEADER
     + baris_drop("13:01:00", "10.66.66.82", "192.168.56.103", 445))
benar("berkas baru pasca-rotasi memang lebih kecil dari posisi P (prasyarat uji)",
      os.path.getsize(JALUR) < posisi_p,
      "-> %d vs %d" % (os.path.getsize(JALUR), posisi_p))

entri, posisi3, diputar, ada = winfw.baca_log_potongan(posisi_p)
sama("diputar TERDETEKSI", diputar, True)
asal = sorted(e["dari"] for e in entri)
sama("ekor .old (yang belum sempat dibaca) + isi berkas baru, KEDUANYA ada",
     asal, ["10.66.66.81", "10.66.66.82"])
benar("entri sebelum rotasi (.80) TIDAK diulang (sudah pernah dibaca)",
      "10.66.66.80" not in asal)

# ---------------------------------------------------------------------------
print("\n7. ROTASI TAPI .old TIDAK ADA/HILANG -> TETAP BACA BERKAS BARU,")
print("   TIDAK CRASH (lubang kecil lebih baik daripada berhenti total)")

os.remove(JALUR + ".old")
tulis(JALUR, HEADER
     + baris_drop("14:00:00", "10.66.66.90", "192.168.56.103", 22))
try:
    entri, posisi4, diputar, ada = winfw.baca_log_potongan(posisi_p)
    lolos += 1
    print("  LOLOS  tidak melempar exception walau .old hilang")
except Exception as e:
    gagal += 1
    print("  GAGAL  melempar %r, harusnya tetap membaca berkas baru" % e)
    entri, diputar, ada = [], False, False
sama("diputar tetap terdeteksi", diputar, True)
sama("berkas baru tetap terbaca", [e["dari"] for e in entri], ["10.66.66.90"])

# ---------------------------------------------------------------------------
print("\n8. SIDIK (dedup) — deterministik dan berbeda untuk entri berbeda")

tulis(JALUR, HEADER
     + baris_drop("15:00:00", "10.66.66.91", "192.168.56.103", 22)
     + baris_drop("15:00:00", "10.66.66.92", "192.168.56.103", 22))
entri, _p, _d, _a = winfw.baca_log_potongan(0)
sama("dua entri berbeda asal", len(entri), 2)
benar("sidik keduanya BERBEDA", entri[0]["sidik"] != entri[1]["sidik"])

entri_ulang, _p, _d, _a = winfw.baca_log_potongan(0)
sama("sidik untuk baris yang SAMA persis stabil (dibaca ulang dari awal)",
     entri_ulang[0]["sidik"], entri[0]["sidik"])

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

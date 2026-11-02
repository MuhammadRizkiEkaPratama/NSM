"""Tests for backup encryption: it really locks, and the result really opens.
Checks:
 1. Lock then unlock gives identical content.
 2. The locked file contains no fragment of the original.
 3. A wrong passphrase is rejected, not turned into garbage.
 4. A file changed by one byte is rejected even with the right passphrase.
 5. The header (salt and nonce) is protected: changing it is rejected.
 6. Encrypting the same content twice gives different files.
 7. Error messages do not distinguish wrong passphrase from tampered file.
 8. A half-written file never appears as a valid file.
 9. `terenkripsi()` recognizes locked files and rejects plain zips.
Run: py uji_sandi_backup.py
"""
import os
import sys
import tempfile

lolos = 0
gagal = 0


def cek(nama, dapat, harap):
    global lolos, gagal
    if dapat == harap:
        lolos += 1
        print(f"  LOLOS  {nama}: {dapat}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama}: dapat {dapat!r}, harusnya {harap!r}")


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print(f"  LOLOS  {nama}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama} {ket}")


SANDI = "frasa-sandi-uji-yang-cukup-panjang"
# Distinctive canary content so leaks can be searched for. It only needs to be unique, not a real secret.
RAHASIA = b"KENARI-UJI-NSM-7f3a91-JANGAN-PAKAI-NILAI-ASLI"


def uji():
    print("=" * 74)
    print("Enkripsi backup: mengunci, dan bisa dibuka lagi")
    print("=" * 74)

    import sandi_backup as sb

    work = tempfile.mkdtemp(prefix="nsm-ujienc-")
    original = os.path.join(work, "asli.zip")
    locked = os.path.join(work, "asli.zip.enc")
    dibuka = os.path.join(work, "dibuka.zip")

    content = b"PK\x03\x04" + os.urandom(4096) + RAHASIA + os.urandom(4096)
    with open(original, "wb") as f:
        f.write(content)

    # --- 1. bolak-balik utuh -------------------------------------------
    print("\n1. Dikunci lalu dibuka menghasilkan isi yang sama persis")
    n = sb.enkripsi(original, locked, SANDI)
    print(f"       {len(content)} byte -> {n} byte terkunci")
    sb.dekripsi(locked, dibuka, SANDI)
    with open(dibuka, "rb") as f:
        back = f.read()
    cek("panjang isi sama", len(back), len(content))
    benar("isinya sama persis, bita per bita", back == content)

    print("\n2. Berkas terkunci tidak memuat potongan isi aslinya")
    with open(locked, "rb") as f:
        data = f.read()
    benar("nilai rahasia tidak ada di berkas terkunci",
          RAHASIA not in data, "-> isinya bocor apa adanya")
    benar("penanda zip `PK` di kepala isi asli juga tidak terlihat",
          b"PK\x03\x04" not in data)

    print("\n3. Frasa sandi salah ditolak")
    wrong = os.path.join(work, "salah.zip")
    try:
        sb.dekripsi(locked, wrong, SANDI + "x")
        benar("sandi salah ditolak", False, "-> justru berhasil membuka")
        message_wrong = ""
    except ValueError as e:
        benar("sandi salah ditolak", True)
        message_wrong = str(e)
    benar("tidak meninggalkan berkas separuh jadi",
          not os.path.exists(wrong),
          "-> berkas hasil gagal tetap tertulis, dan itu akan disangka sah")

    print("\n4. Berkas yang diubah satu bita ditolak, walau sandinya benar")
    rusak = os.path.join(work, "rusak.enc")
    ubah = bytearray(data)
    # Changed in the middle of the ciphertext, not in the header.
    ubah[len(data) // 2] ^= 0x01
    with open(rusak, "wb") as f:
        f.write(bytes(ubah))
    try:
        sb.dekripsi(rusak, os.path.join(work, "x.zip"), SANDI)
        benar("berkas berubah ditolak", False, "-> justru berhasil membuka")
        message_broken = ""
    except ValueError as e:
        benar("berkas berubah ditolak", True)
        message_broken = str(e)
    print("       (AES-GCM menyertakan tanda keaslian; AES-CBC tidak, dan")
    print("        akan menghasilkan sampah tanpa satu pun peringatan)")

    print("\n5. Kepala berkas (garam & nonce) ikut terlindungi")
    ubah2 = bytearray(data)
    ubah2[len(sb.AJAIB) + 2] ^= 0x01
    rusak2 = os.path.join(work, "rusak2.enc")
    with open(rusak2, "wb") as f:
        f.write(bytes(ubah2))
    try:
        sb.dekripsi(rusak2, os.path.join(work, "y.zip"), SANDI)
        benar("garam yang diubah ditolak", False)
    except ValueError:
        benar("garam yang diubah ditolak", True)

    print("\n6. Mengunci isi yang sama dua kali menghasilkan berkas berbeda")
    secondary = os.path.join(work, "kedua.enc")
    sb.enkripsi(original, secondary, SANDI)
    with open(secondary, "rb") as f:
        data2 = f.read()
    benar("hasilnya tidak identik", data != data2,
          "-> garam/nonce dipakai ulang; pola antar backup jadi terbaca")
    benar("keduanya tetap bisa dibuka",
          sb.dekripsi(secondary, os.path.join(work, "z.zip"), SANDI) == len(content))
    print("       (nonce yang dipakai ulang menghancurkan keamanan GCM")
    print("        seluruhnya, bukan sebagian)")

    print("\n7. Pesan galat tidak membedakan sandi salah dari berkas berubah")
    cek("kedua pesannya sama persis", message_wrong, message_broken)
    print("       (memberi tahu penebak bahwa sandinya BENAR tetapi berkasnya")
    print("        rusak sama saja dengan memberi tahu bahwa sandinya benar)")

    print("\n8. Berkas separuh tertulis tidak muncul sebagai berkas sah")
    remaining = [f for f in os.listdir(work) if f.endswith(".sedang-ditulis")]
    cek("tidak ada sisa berkas sementara", remaining, [])
    print("       (ditulis ke nama sementara lalu diganti nama; berkas yang")
    print("        separuh tertulis karena listrik padam akan terlihat sah)")

    print("\n9. Berkas terkunci dikenali, zip biasa ditolak")
    cek("berkas terkunci dikenali", sb.terenkripsi(locked), True)
    cek("zip biasa tidak dianggap terkunci", sb.terenkripsi(original), False)
    cek("berkas yang tidak ada tidak membuat galat",
        sb.terenkripsi(os.path.join(work, "tidak-ada")), False)

    import shutil
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    uji()
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

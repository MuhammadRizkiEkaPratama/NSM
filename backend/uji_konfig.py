"""Test of configuration backup (Stage 6, read-only part).

Two things can go wrong in `konfig_snapshots`, which stores `show running-config`:

1. SECRETS GET STORED. The config contains enable password hashes, SNMP
   communities, and pre-shared keys. If masking leaks, they end up in `nsm.db`.
2. FALSE CHANGES. `ntp clock-period` and timestamps change on their own;
   comparing them would report "config changed" every hour.

The opposite direction is guarded too: real changes must still be detected, so
masking and cleaning must not swallow them along with the noise.

Run: py uji_konfig.py
"""
import sys

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


def cek_benar(nama, syarat, keterangan=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print(f"  LOLOS  {nama}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama} {keterangan}")


CONTOH = """Building configuration...

Current configuration : 1837 bytes
!
! Last configuration change at 10:22:31 UTC Wed Jul 29 2026
!
version 15.2
hostname R1
!
enable secret 5 $1$mERr$hx5rVt7rPNoS4wqbXKX7m0
enable password 7 08701E1D0A5B
username admin privilege 15 secret 5 $1$abcd$efghijklmnop
!
snmp-server community rahasiaBanget RO
snmp-server community tulisJuga RW
crypto isakmp key kunciVPNrahasia address 10.0.0.1
!
interface FastEthernet0/0
 ip address 192.168.56.60 255.255.255.0
 no shutdown
!
line vty 0 4
 password 7 08701E1D0A5B
 transport input ssh
!
ntp clock-period 17179869
!
end"""

RAHASIA = ["mERr", "hx5rVt7rPNoS4wqbXKX7m0", "08701E1D0A5B", "abcd",
           "efghijklmnop", "rahasiaBanget", "tulisJuga", "kunciVPNrahasia"]


def uji():
    print("=" * 74)
    print("Backup konfigurasi: penyamaran, pembersihan, dan deteksi perubahan")
    print("=" * 74)

    from connectors import konfig

    teks, sidik = konfig.olah(CONTOH)

    # ------------------------------------------------------------------
    print("\n-- 1. tidak ada rahasia yang lolos ke teks tersimpan --")
    leak = [r for r in RAHASIA if r in teks]
    cek_benar("seluruh nilai rahasia tersamarkan",
              not leak, f"(masih bocor: {leak})")
    cek("jumlah baris yang disamarkan",
        sum(1 for b in teks.split("\n") if "<DISAMARKAN>" in b), 7)

    # ------------------------------------------------------------------
    print("\n-- 2. STRUKTUR dipertahankan, bukan barisnya dibuang --")
    cek_benar("baris snmp-server masih ada", "snmp-server community" in teks)
    cek_benar("hak akses RO/RW masih terbaca",
              "RO" in teks and "RW" in teks,
              "(tanpa ini, community read-write tidak bisa dibedakan dari read-only)")
    cek_benar("baris enable secret masih ada", "enable secret" in teks)

    # ------------------------------------------------------------------
    print("\n-- 3. baris yang berubah sendiri dibuang --")
    for pattern in ("clock-period", "Last configuration change",
                 "Current configuration", "Building configuration"):
        cek_benar(f"'{pattern}' tidak ikut tersimpan", pattern not in teks)

    # ------------------------------------------------------------------
    print("\n-- 4. konfigurasi yang tidak berubah menghasilkan sidik yang sama --")
    lagi = (CONTOH
            .replace("10:22:31 UTC Wed Jul 29 2026", "11:47:02 UTC Wed Jul 29 2026")
            .replace("ntp clock-period 17179869", "ntp clock-period 17179999")
            .replace("Current configuration : 1837 bytes", "Current configuration : 1840 bytes"))
    teks2, sidik2 = konfig.olah(lagi)
    cek("sidik tidak berubah walau cap waktu & clock-period bergeser",
        sidik2, sidik)
    tambah, hapus, _ = konfig.beda_baris(teks, teks2)
    cek("tidak ada baris yang terbaca berubah", (tambah, hapus), (0, 0))

    # ------------------------------------------------------------------
    print("\n-- 5. PENJAGA ARAH SEBALIKNYA: perubahan NYATA tetap terdeteksi --")
    actual = CONTOH.replace(" no shutdown", " shutdown")
    teks3, sidik3 = konfig.olah(actual)
    cek_benar("sidik berubah", sidik3 != sidik)
    tambah, hapus, potongan = konfig.beda_baris(teks, teks3)
    cek("satu baris ditambah", tambah, 1)
    cek("satu baris dihapus", hapus, 1)
    cek_benar("diff menyebut baris shutdown",
              "shutdown" in potongan, f"(diff: {potongan[:120]})")

    dihapus = CONTOH.replace("snmp-server community tulisJuga RW\n", "")
    teks4, sidik4 = konfig.olah(dihapus)
    cek_benar("hilangnya community RW terdeteksi", sidik4 != sidik)
    _, h4, _ = konfig.beda_baris(teks, teks4)
    cek("satu baris hilang", h4, 1)

    # ------------------------------------------------------------------
    print("\n-- 6. sidik dihitung dari teks yang SUDAH disamarkan --")
    # The fingerprint must be computed from normalized text; with raw text, a device
    # rewriting its password hash would read as a changed config.
    hash_new = CONTOH.replace("$1$mERr$hx5rVt7rPNoS4wqbXKX7m0",
                               "$1$zzzz$berbedaTotalTapiSamaSaja")
    _, sidik5 = konfig.olah(hash_new)
    cek("hash password digenerasi ulang tidak dianggap perubahan", sidik5, sidik)

    # ------------------------------------------------------------------
    print("\n-- 7. platform yang belum didukung ditolak dengan jelas --")
    try:
        konfig.ambil(None, "linux")
        cek_benar("platform tak dikenal ditolak", False, "(malah lolos)")
    except ValueError as e:
        cek_benar("platform tak dikenal ditolak dengan pesan jelas",
                  "linux" in str(e), f"(pesan: {e})")
    except Exception as e:
        cek_benar("platform tak dikenal ditolak dengan ValueError",
                  False, f"(malah {type(e).__name__})")




# Part 2: running vs startup (changes that would be lost on reboot)
STARTUP = CONTOH          # simpanan = keadaan awal
RUNNING = CONTOH.replace(
    "line vty 0 4",
    "banner motd ^CUji deteksi perubahan NSM^C\n!\nline vty 0 4")


def test_startup():
    print()
    print("=" * 74)
    print("Running vs startup: apa yang hilang kalau perangkat di-reboot")
    print("=" * 74)

    from connectors import konfig

    t_run, s_run = konfig.olah(RUNNING)
    t_start, s_start = konfig.olah(STARTUP)

    print("\n-- 1. selisihnya terdeteksi --")
    cek_benar("sidik running berbeda dari sidik startup", s_run != s_start)
    tambah, hapus, potongan = konfig.beda_baris(t_start, t_run)
    cek("baris yang akan HILANG saat reboot", tambah, 2)
    cek("baris yang akan KEMBALI saat reboot", hapus, 0)
    cek_benar("banner disebut di diff", "banner motd" in potongan)

    print("\n-- 2. arah perbandingan benar (startup dulu, running kemudian) --")
    baris_tambah = [b for b in potongan.split("\n")
                    if b.startswith("+") and not b.startswith("+++")]
    cek_benar("baris bertanda '+' adalah yang ada SEKARANG",
              any("banner motd" in b for b in baris_tambah),
              f"(baris +: {baris_tambah})")

    print("\n-- 3. konfigurasi yang SUDAH disimpan tidak dilaporkan bermasalah --")
    t2, s2 = konfig.olah(STARTUP)
    tambah2, hapus2, _ = konfig.beda_baris(t2, t_start)
    cek("tidak ada selisih sama sekali", (tambah2, hapus2), (0, 0))
    cek("sidik keduanya sama", s2, s_start)

    print("\n-- 4. platform tanpa startup-config dibedakan dari 'kosong' --")
    # None means "no concept of startup config", not "zero lines"; mixing them would
    # report such devices as safely saved without ever checking.
    cek("mikrotik tidak punya perintah startup",
        konfig.PERINTAH_STARTUP.get("mikrotik_routeros"), None)
    cek("cisco punya", konfig.PERINTAH_STARTUP.get("cisco_ios"),
        "show startup-config")




# Part 3: noise specific to `show startup-config` (the NVRAM usage header and
# differing `!` separators), which must not inflate the unsaved-lines count.
def uji_derau_startup():
    print()
    print("=" * 74)
    print("Derau khas `show startup-config` tidak boleh terbaca sebagai selisih")
    print("=" * 74)

    from connectors import konfig

    running = """!
hostname R1
!
banner motd ^CUji^C
!
end"""

    startup = """Using 1019 out of 522232 bytes
!
!
!
!
!
hostname R1
!
!
end"""

    t_run, _ = konfig.olah(running)
    t_start, _ = konfig.olah(startup)

    print("\n-- 1. laporan pemakaian NVRAM dibuang --")
    cek_benar("'Using ... out of ... bytes' tidak ikut tersimpan",
              "Using" not in t_start, f"(hasil: {t_start.split(chr(10))[:3]})")

    print("\n-- 2. deretan pemisah '!' dirapatkan --")
    consecutive = 0
    maksimum = 0
    for b in t_start.split("\n"):
        consecutive = consecutive + 1 if b.strip() == "!" else 0
        maksimum = max(maksimum, consecutive)
    cek("pemisah '!' beruntun paling banyak", maksimum, 1)
    cek_benar("pemisah tidak dihapus seluruhnya", "!" in t_start,
              "(struktur konfigurasi harus tetap terbaca)")

    print("\n-- 3. selisihnya kini SATU baris, bukan tujuh --")
    tambah, hapus, potongan = konfig.beda_baris(t_start, t_run)
    # Two, not one: adding a banner also adds a `!` separator that exists in running
    # but not in startup.
    cek("baris yang benar-benar belum disimpan", tambah, 2)
    cek("tidak ada baris yang akan kembali", hapus, 0)
    cek_benar("yang disebut memang banner-nya",
              "banner motd" in potongan, f"(diff: {potongan})")

    print("\n-- 4. PENJAGA: perubahan nyata pada baris '!' berdampingan tetap terlihat --")
    # Tightening the separator must not swallow the command between them.
    a, _ = konfig.olah("!\nhostname R1\n!\n!\nip domain-name lab\n!\nend")
    b, _ = konfig.olah("!\nhostname R1\n!\n!\nend")
    t2, h2, potongan2 = konfig.beda_baris(b, a)
    cek("baris perintah di antara pemisah tetap terdeteksi", t2, 2)
    cek_benar("yang terdeteksi memang perintahnya",
              "ip domain-name" in potongan2, f"(diff: {potongan2})")


def uji_interface_untuk_ip():
    print("\n" + "=" * 74)
    print("interface_untuk_ip: interface mana yang membawa IP manajemen")
    print("(dipakai kirim_perintah.py mencegah kirim perintah `memutus` ke")
    print(" interface yang dipakai NSM sendiri -- docs/POSTMORTEM-R1.md §5a)")
    print("=" * 74)

    from connectors import konfig

    two_iface = """interface FastEthernet0/0
 ip address 192.168.56.60 255.255.255.0
 no shutdown
!
interface FastEthernet0/1
 ip address 10.0.0.1 255.255.255.0
 shutdown
!
end"""

    cek("interface yang benar ditemukan",
        konfig.interface_untuk_ip(two_iface, "192.168.56.60"), "FastEthernet0/0")
    cek("bukan interface pertama yang selalu dikembalikan",
        konfig.interface_untuk_ip(two_iface, "10.0.0.1"), "FastEthernet0/1")
    cek("IP yang tidak ada di perangkat manapun -> None",
        konfig.interface_untuk_ip(two_iface, "8.8.8.8"), None)
    cek("teks kosong -> None, bukan galat",
        konfig.interface_untuk_ip("", "192.168.56.60"), None)
    cek("None sebagai teks -> None, bukan galat",
        konfig.interface_untuk_ip(None, "192.168.56.60"), None)

    without_iface_earlier = "ip address 192.168.56.60 255.255.255.0\nend"
    cek("`ip address` sebelum ada `interface` apa pun -> None",
        konfig.interface_untuk_ip(without_iface_earlier, "192.168.56.60"), None)


if __name__ == "__main__":
    uji()
    test_startup()
    uji_derau_startup()
    uji_interface_untuk_ip()
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

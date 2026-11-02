"""Test of the command catalog and parameter validation (Stage 6, parts 1-3).

Unvalidated parameters are command injection into the device CLI. If an
interface description is filled with extra lines such as `no shutdown` and
`ip address ...`, those lines run as router commands: the same vulnerability
class as SQL injection, and worse, since a wrong command can cut access to the
router itself.

Two equally important kinds of checks:

  A. MALICIOUS INPUT IS REJECTED. A dozen injection forms are tried one by one.
  B. VALID INPUT IS ACCEPTED. Over-strict validation is as useless as leaky
     validation: people would return to typing in the console, losing the audit trail.

Plus a guard that the PREVIEW is identical to what will be sent.

Run: py uji_perintah.py
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


IFACE = ["FastEthernet0/0", "Loopback0"]


def test_injection():
    from connectors import perintah as pr

    print("=" * 74)
    print("BAGIAN A: masukan jahat harus DITOLAK")
    print("=" * 74)

    malicious = [
        ("baris baru \\n", "Uplink\n no shutdown"),
        ("baris baru \\r\\n", "Uplink\r\n shutdown"),
        ("carriage return sendirian", "Uplink\rshutdown"),
        ("null byte", "Uplink\x00shutdown"),
        ("tab kendali", "Uplink\x0bshutdown"),
        ("escape ANSI", "Uplink\x1b[2J"),
        ("tanda seru pemisah config", "Uplink!\nhostname JAHAT"),
        ("titik dua perintah", "Uplink; shutdown"),
        ("pipa", "Uplink | shutdown"),
        ("backtick", "Uplink `shutdown`"),
        ("dollar", "Uplink $(shutdown)"),
        ("tanda kutip", 'Uplink "shutdown"'),
        ("kurung kurawal templat", "Uplink {teks}"),
        ("kosong", ""),
        ("spasi saja", "   "),
    ]

    print("\n-- keterangan interface --")
    for note, value in malicious:
        g = pr.validasi("iface_keterangan",
                        {"interface": "FastEthernet0/0", "teks": value}, IFACE)
        cek_benar(f"ditolak: {note}", "teks" in g,
                  f"(malah lolos, nilai={value!r})")

    print("\n-- nama perangkat --")
    for note, value in [("baris baru", "R1\nhostname JAHAT"),
                       ("spasi", "R1 JAHAT"),
                       ("diawali tanda hubung", "-R1"),
                       ("terlalu panjang", "R" * 64),
                       ("karakter aneh", "R1$")]:
        g = pr.validasi("hostname", {"nama": value})
        cek_benar(f"ditolak: {note}", "nama" in g, f"(malah lolos, {value!r})")

    print("\n-- alamat IP --")
    for note, value in [("baris baru", "10.0.0.1\nshutdown"),
                       ("oktet > 255", "10.0.0.300"),
                       ("kurang oktet", "10.0.0"),
                       ("huruf", "10.0.0.a"),
                       ("diawali nol", "10.0.0.010"),
                       ("kosong", "")]:
        g = pr.validasi("ntp_tambah", {"alamat": value})
        cek_benar(f"ditolak: {note}", "alamat" in g, f"(malah lolos, {value!r})")

    print("\n-- interface --")
    for note, value in [("baris baru", "FastEthernet0/0\nshutdown"),
                       ("tidak ada di perangkat", "FastEthernet9/9"),
                       ("bentuk asal", "bukan-interface"),
                       ("kosong", "")]:
        g = pr.validasi("iface_mati", {"interface": value}, IFACE)
        cek_benar(f"ditolak: {note}", "interface" in g, f"(malah lolos, {value!r})")

    print("\n-- perintah & parameter di luar katalog --")
    g = pr.validasi("perintah_karangan", {"apa": "saja"})
    cek_benar("perintah yang tidak ada di katalog ditolak", bool(g))
    g = pr.validasi("hostname", {"nama": "R1", "sisipan": "shutdown"})
    cek_benar("parameter asing ditolak, bukan diabaikan diam-diam",
              "sisipan" in g, f"(galat: {g})")


def test_valid():
    from connectors import perintah as pr

    print()
    print("=" * 74)
    print("BAGIAN B: masukan SAH harus diterima")
    print("=" * 74)

    print("\n-- keterangan yang wajar dipakai orang --")
    for value in ["Uplink ke switch lantai 2",
                  "Link ke ISP (cadangan)",
                  "server-farm / VLAN 30",
                  "Port 1-8, trunk",
                  "cadangan_2026"]:
        g = pr.validasi("iface_keterangan",
                        {"interface": "FastEthernet0/0", "teks": value}, IFACE)
        cek_benar(f"diterima: {value!r}", not g, f"(malah ditolak: {g})")

    print("\n-- nilai sah lainnya --")
    cek_benar("hostname R1-lab", not pr.validasi("hostname", {"nama": "R1-lab"}))
    cek_benar("NTP 192.168.56.1",
              not pr.validasi("ntp_tambah", {"alamat": "192.168.56.1"}))
    cek_benar("interface Loopback0",
              not pr.validasi("iface_hidup", {"interface": "Loopback0"}, IFACE))
    cek_benar("interface tanpa daftar pembanding tetap lolos pola",
              not pr.validasi("iface_hidup", {"interface": "GigabitEthernet0/1"}, None),
              "(daftar interface belum tentu ada kalau perangkat belum pernah dipotret)")


def uji_pratinjau():
    from connectors import perintah as pr

    print()
    print("=" * 74)
    print("BAGIAN C: pratinjau = persis yang akan dikirim")
    print("=" * 74)

    p = pr.pratinjau("iface_keterangan",
                     {"interface": "FastEthernet0/0", "teks": "Uplink ke switch"},
                     IFACE)
    cek("pratinjau berhasil", p["ok"], True)
    cek("baris yang akan dikirim", p["baris"],
        ["configure terminal", "interface FastEthernet0/0",
         " description Uplink ke switch", "end"])
    cek_benar("pratinjau menyatakan BELUM terkirim", p["terkirim"] is False)
    cek_benar("pratinjau memperingatkan soal belum disimpan permanen",
              any("disimpan permanen" in x for x in p["peringatan"]),
              f"(peringatan: {p['peringatan']})")

    print("\n-- perintah berbahaya diberi peringatan tambahan --")
    p2 = pr.pratinjau("iface_mati", {"interface": "FastEthernet0/0"}, IFACE)
    cek("ditandai bisa memutus", p2["memutus"], True)
    cek_benar("peringatannya menyebut reload sebagai jaring pengaman",
              any("reload in 5" in x for x in p2["peringatan"]),
              f"(peringatan: {p2['peringatan']})")

    print("\n-- perintah tidak berbahaya TIDAK diberi peringatan palsu --")
    cek("ubah hostname tidak ditandai memutus",
        pr.pratinjau("hostname", {"nama": "R1"})["memutus"], False)

    print("\n-- pratinjau atas masukan jahat tidak menghasilkan baris --")
    p3 = pr.pratinjau("iface_keterangan",
                      {"interface": "FastEthernet0/0", "teks": "x\n shutdown"},
                      IFACE)
    cek("pratinjau ditolak", p3["ok"], False)
    cek_benar("tidak ada baris perintah yang tersusun", "baris" not in p3,
              f"(malah ada: {p3.get('baris')})")

    print("\n-- susun() menolak nilai yang belum lolos --")
    try:
        pr.susun("iface_keterangan",
                 {"interface": "FastEthernet0/0", "teks": "x\n shutdown"}, IFACE)
        cek_benar("susun() menolak masukan jahat", False, "(malah menyusun)")
    except ValueError:
        cek_benar("susun() menolak masukan jahat dengan ValueError", True)

    print("\n-- parameter tidak bisa jadi NAMA perintah --")
    # Even if it looks like a command, it lands as a value inside the template, not as a separate line.
    p4 = pr.pratinjau("iface_keterangan",
                      {"interface": "FastEthernet0/0", "teks": "shutdown"}, IFACE)
    cek("tetap jadi keterangan, bukan perintah", p4["baris"][2],
        " description shutdown")
    cek("jumlah baris tidak bertambah", len(p4["baris"]), 4)


def test_catalog():
    from connectors import perintah as pr

    print()
    print("=" * 74)
    print("BAGIAN D: katalog itu sendiri")
    print("=" * 74)

    # The count is deliberately pinned even though it is brittle: the structural
    # invariants below guard each entry's quality, but only this number catches a
    # command silently disappearing. It was raised so Stage 7 (config remediator) can
    # fix ALL SoT keys classified `aman_otomatis`.
    cek("jumlah perintah di katalog", len(pr.KATALOG), 15)
    cek("semuanya cisco_ios",
        {p["platform"] for p in pr.KATALOG}, {"cisco_ios"})
    cek_benar("id-nya unik",
              len({p["id"] for p in pr.KATALOG}) == len(pr.KATALOG))

    print("\n-- tiap entri katalog utuh --")
    for p in pr.KATALOG:
        ok = all(k in p for k in
                 ("id", "nama", "penjelasan", "platform", "memutus",
                  "parameter", "perintah"))
        cek_benar(f"{p['id']} punya semua bidang", ok, f"({sorted(p)})")
        import re as _re
        needed = set()
        for baris in p["perintah"]:
            needed |= set(_re.findall(r"\{(\w+)\}", baris))
        available = {q["nama"] for q in p["parameter"]}
        cek_benar(f"{p['id']}: semua {{kurung}} punya parameter",
                  needed <= available,
                  f"(kurang: {needed - available})")
        cek_benar(f"{p['id']}: semua parameter jenisnya dikenal",
                  all(q["jenis"] in pr.JENIS for q in p["parameter"]))

    print("\n-- tidak ada entri yang menulis 'configure terminal' sendiri --")
    for p in pr.KATALOG:
        cek_benar(f"{p['id']} tidak memuat pembungkus",
                  not any(b.strip() in ("configure terminal", "end", "exit")
                          for b in p["perintah"]))

    print("\n-- tidak ada perintah berbahaya yang lolos ke katalog --")
    TERLARANG = ("line vty", "aaa ", "username", "enable secret",
                 "access-list", "ip route", "boot system", "reload",
                 "erase", "write ")
    for p in pr.KATALOG:
        content = " ".join(p["perintah"]).lower()
        bad = [t for t in TERLARANG if t in content]
        cek_benar(f"{p['id']} tidak menyentuh hal terlarang", not bad,
                  f"(memuat: {bad})")


def uji_lapis_pertama():
    """The newline guard is tested ALONE, not through the allowlist.

    Disabling the `_BARIS_BARU` guard left all ninety-one checks green, because
    newline input is also rejected by the allowlist in the second layer, so a test
    through `validasi()` cannot tell "the guard works" from "the allowlist happens
    to reject it too". If the allowlist is ever widened, the newline guard becomes
    the only defense. Hence the first layer is called directly.
    """
    from connectors import perintah as pr

    print()
    print("=" * 74)
    print("BAGIAN E: penjaga baris baru diuji SENDIRIAN (lapis pertama)")
    print("=" * 74)

    KENDALI = [
        ("newline", "aman" + chr(10) + "shutdown"),
        ("carriage return", "aman" + chr(13) + "shutdown"),
        ("CRLF", "aman" + chr(13) + chr(10) + "shutdown"),
        ("null byte", "aman" + chr(0) + "shutdown"),
        ("escape ANSI", "aman" + chr(27) + "[2J"),
        ("vertical tab", "aman" + chr(11) + "shutdown"),
        ("DEL", "aman" + chr(127) + "shutdown"),
    ]
    for note, value in KENDALI:
        message = pr._cek_umum(value)
        cek_benar("_cek_umum menolak " + note, message is not None,
                  "(malah lolos)")
        if message:
            cek_benar("alasannya menyebut baris baru (" + note + ")",
                      "baris baru" in message, "(pesan: " + message + ")")

    print()
    print("-- teks wajar tetap lolos lapis pertama --")
    for value in ["Uplink ke switch", "R1-lab", "192.168.56.1", "Loopback0"]:
        message = pr._cek_umum(value)
        cek_benar("_cek_umum meloloskan " + repr(value), message is None,
                  "(malah ditolak: " + str(message) + ")")


if __name__ == "__main__":
    test_injection()
    test_valid()
    uji_pratinjau()
    test_catalog()
    uji_lapis_pertama()
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

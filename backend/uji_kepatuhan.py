"""Tests for the configuration compliance scorer.

A security scorer must be tested both ways: a rule tested only with violating
configs passes even if it always says "finding"; one tested only with compliant
configs passes even if it always says "compliant". So EACH catalog rule is tested
with a config that violates it and one that satisfies it.

 1. The block splitter understands Cisco IOS indentation.
 2. Each rule answers TEMUAN on a violating config.
 3. Each rule answers PATUH on a compliant config.
 4. A platform that is not its target answers TIDAK_BERLAKU, not PATUH.
 5. A block that does not exist (e.g. `line aux` never defined) answers TIDAK_BERLAKU.
 6. `pola_alternatif`: two valid ways to meet one rule are both accepted.
 7. Evidence lines point to the CORRECT line number in the original file.
 8. Already-masked secrets never leak through evidence lines.
 9. The summary does not publish a single percentage.
10. Tested on the REAL R1 snapshot from nsm.db, not just synthetic data.

Run: py uji_kepatuhan.py
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


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print(f"  LOLOS  {nama}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama} {ket}")


# Two complete configs: one violating ALL rules, one satisfying ALL. Written whole, not assembled per rule, so interactions between rules are tested (e.g. `hash_lemah` shares a line with `akun_privilege15`).
MELANGGAR = """version 15.2
hostname RUSAK
!
username admin privilege 15 secret 5 abc
!
snmp-server community public RO
!
ip http server
!
line con 0
 exec-timeout 0 0
!
line aux 0
 exec-timeout 0 0
!
line vty 0 4
 login local
 transport input telnet ssh
!
end
"""

PATUH_SEMUA = """version 15.2
service password-encryption
hostname AMAN
!
enable secret 9 xyz
username nsm privilege 5 secret 9 abc
!
no ip http server
no ip http secure-server
ip ssh version 2
!
logging buffered 16384
ntp server 192.168.56.1
banner login ^C Akses hanya untuk yang berwenang ^C
!
snmp-server group NSMGRUP v3 priv read NSMVIEW
!
line con 0
 exec-timeout 10 0
!
line aux 0
 no exec
!
line vty 0 4
 login local
 access-class 10 in
 transport input ssh
!
end
"""


# The same pair for Linux. The snapshot is assembled by `connectors/konfig_linux.py` from several sources, each headed `### name`.
LINUX_MELANGGAR = """### sshd
PasswordAuthentication yes
PermitEmptyPasswords yes
PermitRootLogin yes
X11Forwarding yes

### port-mendengarkan
0.0.0.0:22

### firewall
inactive

### akun-uid0
root
toor

### akun-bershell
root:/bin/bash

### grup-istimewa
lxd:nsm
sudo:nsm

### akun-pemantau-grup
lxd
sudo

### pembaruan-keamanan-tertunda
7
"""

LINUX_PATUH = """### sshd
PasswordAuthentication no
PermitEmptyPasswords no
PermitRootLogin prohibit-password
X11Forwarding no

### port-mendengarkan
0.0.0.0:22

### firewall
active

### akun-uid0
root

### akun-bershell
root:/bin/bash

### grup-istimewa
adm:syslog

### akun-pemantau-grup
!! kosong

### pembaruan-keamanan-tertunda
0
"""

# Which config is used to test which platform's rules.
CONTOH = {
    "cisco_ios": (MELANGGAR, PATUH_SEMUA),
    "linux": (LINUX_MELANGGAR, LINUX_PATUH),
}


def uji():
    print("=" * 74)
    print("Penilai kepatuhan konfigurasi")
    print("=" * 74)

    from connectors import kepatuhan as k

    # --- 1. pemecah blok -----------------------------------------------
    print("\n1. Pemecah blok memahami indentasi Cisco IOS")
    block = dict(k.pecah_blok(MELANGGAR))
    benar("blok `line vty 0 4` ditemukan", "line vty 0 4" in block,
          f"-> yang ada: {list(block)[:6]}")
    cek("isi blok vty terkumpul benar",
        block.get("line vty 0 4"),
        ["login local", "transport input telnet ssh"])
    benar("baris global tidak tertelan ke blok sebelumnya",
          "snmp-server community public RO" in block)
    cek("pemisah `!` dan baris kosong dibuang",
        [j for j in block if j.strip() == "!"], [])

    # 2 & 3. each rule tested BOTH ways
    print("\n2 & 3. Tiap aturan diuji dua arah")
    # EACH RULE IS TESTED AGAINST ITS OWN PLATFORM. An earlier version tested all rules with the Cisco config, so the nine Linux rules answered TIDAK_BERLAKU and counted as wrong.
    print("       %-26s %-8s %-14s %-14s"
          % ("aturan", "platform", "pada MELANGGAR", "pada PATUH"))
    wrong_direction = []
    for a in k.KATALOG:
        example = CONTOH.get(a["platform"])
        if example is None:
            print("       %-26s %-8s (belum ada contoh konfigurasinya)"
                  % (a["id"], a["platform"]))
            wrong_direction.append(a["id"])
            continue
        violate, patuh = example
        h_violate = k.nilai_satu(violate, a, a["platform"])["hasil"]
        h_patuh = k.nilai_satu(patuh, a, a["platform"])["hasil"]
        mark = ""
        if h_violate != k.TEMUAN or h_patuh != k.PATUH:
            mark = "   <-- SALAH"
            wrong_direction.append(a["id"])
        print("       %-26s %-8s %-14s %-14s%s"
              % (a["id"], a["platform"], h_violate, h_patuh, mark))
    cek("tidak ada aturan yang salah arah", wrong_direction, [])
    print(f"       ({len(k.KATALOG)} aturan x 2 arah = "
          f"{len(k.KATALOG) * 2} pemeriksaan)")

    # Every platform in the catalog MUST have a sample config pair; otherwise a rule for a new platform would silently go untested.
    platform_catalog = sorted({a["platform"] for a in k.KATALOG})
    cek("tiap platform di katalog punya contoh konfigurasi",
        [p for p in platform_catalog if p not in CONTOH], [])

    # --- 4. platform lain -----------------------------------------------
    print("\n4. Platform yang bukan sasarannya: TIDAK BERLAKU, bukan PATUH")
    linux = k.nilai(MELANGGAR, "linux")
    cek("semua aturan tidak berlaku untuk linux",
        sorted({h["hasil"] for h in linux}), [k.TIDAK_BERLAKU])
    r = k.ringkas(linux)
    cek("nol temuan, nol patuh, semua tidak berlaku",
        (r["temuan"], r["patuh"], r["tidak_berlaku"]),
        (0, 0, len(k.KATALOG)))
    print("       (kalau ini PATUH, perangkat Linux akan terlihat aman 100%")
    print("        terhadap aturan Cisco yang tidak pernah diperiksa padanya)")

    # 5. nonexistent block
    print("\n5. Blok yang tidak ada: TIDAK BERLAKU, bukan TEMUAN")
    tanpa_aux = PATUH_SEMUA.replace("line aux 0\n no exec\n!\n", "")
    h = k.nilai_satu(tanpa_aux, k.PETA_KATALOG["aux_aktif"], "cisco_ios")
    cek("perangkat tanpa `line aux` sama sekali", h["hasil"], k.TIDAK_BERLAKU)
    print("       (perangkat yang tidak punya port AUX tidak bisa lalai")
    print("        mematikannya; melaporkannya sebagai temuan adalah tuduhan)")

    # --- 6. pola alternatif ---------------------------------------------
    print("\n6. Dua cara sah memenuhi satu aturan, keduanya diterima")
    with_acl = PATUH_SEMUA
    with_block = (PATUH_SEMUA
                    .replace(" access-class 10 in\n", "")
                    .replace("hostname AMAN",
                             "hostname AMAN\nlogin block-for 120 attempts 3 within 60"))
    a = k.PETA_KATALOG["vty_dibatasi"]
    cek("cara pertama: access-class di vty",
        k.nilai_satu(with_acl, a, "cisco_ios")["hasil"], k.PATUH)
    cek("cara kedua: login block-for global",
        k.nilai_satu(with_block, a, "cisco_ios")["hasil"], k.PATUH)
    tanpa_keduanya = PATUH_SEMUA.replace(" access-class 10 in\n", "")
    cek("tanpa keduanya: tetap temuan",
        k.nilai_satu(tanpa_keduanya, a, "cisco_ios")["hasil"], k.TEMUAN)

    # 7. line numbers point at the ORIGINAL file
    print("\n7. Nomor baris menunjuk baris yang benar di berkas aslinya")
    h = k.nilai_satu(MELANGGAR, k.PETA_KATALOG["akun_privilege15"], "cisco_ios")
    line_original = MELANGGAR.splitlines()
    n = h["nomor_baris"]
    benar("nomor baris terisi", n is not None)
    if n:
        print(f"       baris {n}: {line_original[n - 1]!r}")
        benar("baris di nomor itu memang yang memicu temuannya",
              "privilege 15" in line_original[n - 1],
              f"-> yang ada di baris {n}: {line_original[n - 1]!r}")
    print("       (nomor yang dihitung dari teks TERSARING akan menunjuk")
    print("        baris lain saat pembacanya membuka potret aslinya)")

    # 8. secrets do not leak
    print("\n8. Rahasia yang sudah tersamar tidak bocor lewat baris bukti")
    tersamar = MELANGGAR.replace("secret 5 abc", "secret 5 <DISAMARKAN>")
    semua = k.nilai(tersamar, "cisco_ios")
    bukti = " ".join(h["baris_bukti"] or "" for h in semua)
    benar("tidak ada nilai rahasia di baris bukti",
          "abc" not in bukti, f"-> {bukti!r}")
    benar("penandanya justru ikut terbawa apa adanya",
          "<DISAMARKAN>" in bukti)

    # 9. no single percentage
    print("\n9. Ringkasan tidak menerbitkan satu persen tunggal")
    r = k.ringkas(k.nilai(MELANGGAR, "cisco_ios"))
    benar("tidak ada kunci 'persen' di ringkasan",
          not any("persen" in x for x in r),
          f"-> kunci yang ada: {sorted(r)}")
    benar("keparahan dilaporkan terpisah, tidak dijumlahkan",
          all(x in r for x in (k.TINGGI, k.SEDANG, k.RENDAH)))
    print("       (\"patuh 78%\" menjumlahkan telnet terbuka dengan banner")
    print("        yang hilang, seolah keduanya seperdua belas masalah sama)")

    # 10. REAL snapshot from nsm.db
    print("\n10. Diuji pada potret R1 sungguhan, bukan cuma data buatan")
    import os
    import sqlite3
    # Anchored to this test file's folder. With a relative "nsm.db", running from another folder would print "skipped" and stay green, though this is the only section using REAL data.
    db_actual = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nsm.db")
    if not os.path.exists(db_actual):
        print("       (nsm.db tidak ada, dilewati)")
    else:
        # The snapshot BELONGING TO A CISCO DEVICE, not just the latest one. After the Linux
        # VM was also snapshotted, the latest belonged to Linux and every rule answered
        # TIDAK_BERLAKU. "The latest is surely the device I mean" holds only until a second device appears.
        c = sqlite3.connect(f"file:{db_actual.replace(os.sep, '/')}?mode=ro",
                            uri=True)
        try:
            baris = c.execute(
                "select s.teks from konfig_snapshots s "
                "join devices d on d.id = s.device_id "
                "where d.platform = 'cisco_ios' "
                "order by s.id desc limit 1"
            ).fetchone()
        finally:
            c.close()
        if not baris:
            print("       (belum ada potret konfigurasi, dilewati)")
        else:
            hasil = k.nilai(baris[0], "cisco_ios")
            r = k.ringkas(hasil)
            print("       %d temuan (%d tinggi, %d sedang, %d rendah), "
                  "%d patuh" % (r["temuan"], r[k.TINGGI], r[k.SEDANG],
                                r[k.RENDAH], r["patuh"]))
            benar("penilaian menghasilkan sesuatu, bukan diam",
                  r["temuan"] + r["patuh"] > 0)
            # Most important about this real snapshot: NSM's own monitoring account has full rights on a router claimed to be read-only. See docs/design/CONFIG-COMPLIANCE.md.
            priv = [h for h in hasil if h["aturan_id"] == "akun_privilege15"]
            cek("akun privilege 15 di R1 terdeteksi",
                priv[0]["hasil"] if priv else None, k.TEMUAN)
            benar("dan buktinya menunjuk baris `username nsm`",
                  priv and priv[0]["baris_bukti"]
                  and "username nsm" in priv[0]["baris_bukti"],
                  f"-> {priv[0]['baris_bukti'] if priv else None}")


if __name__ == "__main__":
    uji()
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

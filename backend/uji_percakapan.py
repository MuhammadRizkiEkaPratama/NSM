"""Test of `percakapan_jaringan()`: the second source of the Traffic page.

The page used to read only `akses_web` (Apache access log) and reported one
distinct address while `flow_koneksi` already held six peers, three of them
internet addresses, including a 114.63 MB HTTPS download that never showed. A
number that is too low is the most dangerous kind on a security page: it
reassures without basis.

Guarded, the first being the most important:

1. CUMULATIVE COUNTERS ARE NOT SUMMED. `bytes_sent` in `ss` counts since the
   connection opened and the poller snapshots the same connection every minute;
   summing all rows inflated 60.05 MB to 343.06 MB. Take the MAXIMUM per 5-tuple,
   then sum across connections.
2. One machine must not appear twice: Linux writes dual-stack sockets as
   `::ffff:192.168.56.101`; without normalization one party looks like two.
3. Ports on the PEER side are named with the peer device's services, not the
   device being read.
4. Direction is distinguished: someone reaching our port 8080 differs from us
   contacting port 443 outside.
5. Addresses outside RFC1918 are flagged; lab addresses are not.

Closed with a cross-check against the real database, as in other tests here:
synthetic cases prove the formula, real data proves it still holds on real data shapes.

Run: py uji_percakapan.py
"""
import os
import sys
from datetime import datetime, timedelta

lolos = 0
gagal = 0


def cek(nama, dapat, harap):
    global lolos, gagal
    ok = dapat == harap
    if ok:
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


def uji_buatan():
    print("=" * 74)
    print("BAGIAN 1: kasus buatan (jawaban benarnya dihitung tangan)")
    print("=" * 74)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import database

    mesin = create_engine("sqlite://")
    original_engine, original_session = database.engine, database.SessionLocal
    database.engine = mesin
    database.SessionLocal = sessionmaker(bind=mesin)

    import models
    models.Base.metadata.create_all(mesin)
    db = database.SessionLocal()

    import report_service as rs

    try:
        db.add(models.Device(id=1, name="Server Web", ip_address="192.168.56.103",
                             device_type="server", platform="linux", aktif=1))
        db.add(models.Device(id=2, name="Server DB", ip_address="192.168.56.101",
                             device_type="server", platform="linux", aktif=1))
        db.add(models.Service(id=1, device_id=1, nama="E-Canteen v2",
                              jenis="http", port=8080, aktif=1))
        db.add(models.Service(id=2, device_id=2, nama="MySQL labweb",
                              jenis="mysql", port=3306, aktif=1))
        db.flush()

        t = datetime.now() - timedelta(minutes=30)

        def potret(dev, lokal, p_lokal, lawan, p_lawan, masuk, keluar, menit):
            db.add(models.Flow(device_id=dev, waktu=t + timedelta(minutes=menit),
                               ip_lokal=lokal, port_lokal=p_lokal,
                               ip_lawan=lawan, port_lawan=p_lawan,
                               byte_masuk=masuk, byte_keluar=keluar,
                               keadaan="ESTAB"))

        # CASE A: one connection to E-Canteen, sampled 3 times with a rising counter. The
        # correct value is the last sample (1000 in, 5000 out); summing gives 1800 / 9000.
        potret(1, "192.168.56.103", 8080, "192.168.56.50", 44001, 300, 1500, 0)
        potret(1, "192.168.56.103", 8080, "192.168.56.50", 44001, 500, 2500, 1)
        potret(1, "192.168.56.103", 8080, "192.168.56.50", 44001, 1000, 5000, 2)

        potret(1, "192.168.56.103", 22, "192.168.56.101", 51000, 100, 200, 0)
        potret(1, "::ffff:192.168.56.103", 22, "::ffff:192.168.56.101", 51002,
               100, 200, 1)

        # CASE C: the web server connects OUT to the DB server's MySQL. Port 3306 on the
        # peer side must be named "MySQL labweb" (device 2's service), not device 1's.
        potret(1, "192.168.56.103", 55000, "192.168.56.101", 3306, 7000, 900, 2)

        # CASE D: outbound connection to the internet.
        potret(1, "10.0.2.15", 40000, "91.189.91.99", 443, 120000, 800, 3)

        db.commit()

        h = rs.percakapan_jaringan(db, "24h")
        per_ip = {p["ip"]: p for p in h["percakapan"]}

        print("\n-- 1. counter kumulatif diambil nilai terbesar, bukan dijumlah --")
        a = per_ip["192.168.56.50"]
        cek("kasus A: diambil dari kita (benar 5000, kalau dijumlah 9000)",
            a["keluar_byte"], 5000.0)
        cek("kasus A: dikirim ke kita (benar 1000, kalau dijumlah 1800)",
            a["masuk_byte"], 1000.0)
        cek("kasus A: dihitung 1 koneksi, bukan 3 potret", a["koneksi"], 1)

        print("\n-- 2. dua bentuk alamat yang sama jadi satu baris --")
        cek_benar("::ffff:192.168.56.101 tidak muncul sebagai baris sendiri",
                  "::ffff:192.168.56.101" not in per_ip,
                  f"(baris yang ada: {sorted(per_ip)})")
        cek_benar("192.168.56.101 ada sebagai satu baris",
                  "192.168.56.101" in per_ip)

        print("\n-- 3. port di sisi lawan dinamai memakai layanan milik lawan --")
        db_ip = per_ip["192.168.56.101"]
        cek_benar("koneksi keluar ke 3306 dinamai 'MySQL labweb'",
                  any("MySQL labweb (3306)" in x for x in db_ip["pintu"]),
                  f"(pintu terbaca: {db_ip['pintu']})")
        cek_benar("nama layanan milik device sendiri TIDAK ikut tertempel",
                  not any("E-Canteen" in x for x in db_ip["pintu"]),
                  f"(pintu terbaca: {db_ip['pintu']})")

        print("\n-- 4. arah dibedakan: kita dilayani vs kita menghubungi --")
        pintu = {(q["port"], q["arah"]): q for q in h["pintu"]}
        cek_benar("port 8080 tercatat sebagai MASUK (ada yang mengakses kita)",
                  (8080, "masuk") in pintu, f"(pintu: {sorted(pintu)})")
        cek_benar("port 3306 tercatat sebagai KELUAR (kita yang menghubungi)",
                  (3306, "keluar") in pintu, f"(pintu: {sorted(pintu)})")
        cek_benar("port 443 tercatat sebagai KELUAR",
                  (443, "keluar") in pintu, f"(pintu: {sorted(pintu)})")
        cek("nama layanan port 8080 diambil dari pendaftaran NSM",
            pintu[(8080, "masuk")]["nama"], "E-Canteen v2")

        print("\n-- 5. alamat di luar jaringan lab ditandai --")
        cek("91.189.91.99 ditandai di luar",
            per_ip["91.189.91.99"]["luar_jaringan"], True)
        cek("192.168.56.50 TIDAK ditandai di luar",
            per_ip["192.168.56.50"]["luar_jaringan"], False)
        cek("jumlah alamat luar", h["lawan_luar"], 1)

        print("\n-- 6. nama perangkat dibaca dari id, bukan dari alamat lokal --")
        # Case D comes through the NAT card 10.0.2.15, which is not registered as any
        # device; an address-based lookup would fail here and show "device 1".
        outer = [q for q in h["pintu"] if q["port"] == 443][0]
        cek("perangkat pada koneksi lewat kartu NAT tetap bernama",
            outer["device"], "Server Web")

        print("\n-- 7. ringkasan --")
        # Three, not four: cases B and C share the peer `192.168.56.101`, so they merge into one row.
        cek("jumlah lawan bicara berbeda", h["lawan_jumlah"], 3)
        cek("jumlah koneksi (5-tuple, bukan potret)", h["koneksi"], 5)

        print("\n-- 8. periode dihormati --")
        h1 = rs.percakapan_jaringan(db, "1h")
        cek("periode 1 jam masih memuat semuanya (data berumur 30 menit)",
            h1["koneksi"], 5)

        # 9. "First seen" may only be used when the history is deep enough; a first attempt
        #    flagged 5 of 6 rows as new only because the table was 31 hours old.
        print("\n-- 9. penanda alamat baru menahan diri saat riwayat dangkal --")
        cek_benar("riwayat 30 menit tidak cukup untuk menilai jendela 1 jam",
                  h1["bisa_nilai_baru"] is False,
                  f"(awal pengamatan {h1['awal_pengamatan']})")
        cek("tidak ada baris yang ditandai baru", h1["lawan_baru"], 0)

        # Plant much older history for ONE old address, then add one truly new address;
        # the 1-hour window now has days of history behind it, so "new" is legitimate.
        old = datetime.now() - timedelta(days=3)
        db.add(models.Flow(device_id=1, waktu=old, ip_lokal="192.168.56.103",
                           port_lokal=8080, ip_lawan="192.168.56.50",
                           port_lawan=44001, byte_masuk=10, byte_keluar=10,
                           keadaan="ESTAB"))
        potret(1, "192.168.56.103", 8080, "192.168.56.77", 45000, 50, 60, 5)
        db.commit()

        h2 = rs.percakapan_jaringan(db, "1h")
        per2 = {p["ip"]: p for p in h2["percakapan"]}
        cek_benar("riwayat 3 hari cukup untuk menilai jendela 1 jam",
                  h2["bisa_nilai_baru"] is True,
                  f"(awal pengamatan {h2['awal_pengamatan']})")
        cek("alamat yang baru muncul ditandai",
            per2["192.168.56.77"]["baru_terlihat"], True)
        cek("alamat yang sudah ada sejak 3 hari lalu TIDAK ditandai",
            per2["192.168.56.50"]["baru_terlihat"], False)

        # 10. DNS names are read from the cache, not looked up when the page opens.
        print("\n-- 10. nama DNS dibaca dari singgahan --")
        db.add(models.NamaAlamat(ip="192.168.56.77",
                                 nama="mesin-uji.lab.local", ditemukan=1,
                                 diperiksa=datetime.now()))
        db.add(models.NamaAlamat(ip="192.168.56.50", nama=None, ditemukan=0,
                                 diperiksa=datetime.now()))
        db.commit()

        h3 = rs.percakapan_jaringan(db, "1h")
        per3 = {p["ip"]: p for p in h3["percakapan"]}
        cek("nama DNS ikut ke halaman",
            per3["192.168.56.77"]["nama_dns"], "mesin-uji.lab.local")
        cek("alamat yang pencariannya gagal tidak dapat nama palsu",
            per3["192.168.56.50"]["nama_dns"], None)
        cek("halaman tahu singgahan namanya siap", h3["nama_dns_siap"], True)

        # 11. The `nama_alamat` table comes from a migration, so new code may run before the
        #     table exists; the page must not die because of an extra annotation.
        print("\n-- 11. halaman tetap hidup walau migrasi belum dijalankan --")
        models.NamaAlamat.__table__.drop(mesin)
        try:
            h4 = rs.percakapan_jaringan(db, "1h")
            cek_benar("halaman tetap menjawab tanpa tabel nama_alamat",
                      h4["ada_data"] is True)
            cek("halaman mengaku singgahan namanya belum ada",
                h4["nama_dns_siap"], False)
            cek_benar("catatan menyebut migrasinya belum dijalankan",
                      "migrasi" in h4["catatan"],
                      f"(catatan: {h4['catatan'][-90:]})")
            cek_benar("angka lalu lintasnya tetap utuh",
                      h4["koneksi"] == h3["koneksi"],
                      f"({h4['koneksi']} vs {h3['koneksi']})")
        except Exception as e:
            cek_benar("halaman tetap menjawab tanpa tabel nama_alamat",
                      False, f"(malah melempar {type(e).__name__}: {e})")
        finally:
            models.NamaAlamat.__table__.create(mesin)

    finally:
        db.close()
        database.engine, database.SessionLocal = original_engine, original_session


# Part 2: pure helpers, tested separately because they are cheap and widely used
def uji_pembantu():
    print()
    print("=" * 74)
    print("BAGIAN 2: penyeragaman alamat & penggolongan dalam/luar")
    print("=" * 74)
    import report_service as rs

    cek("::ffff: dibuang", rs._ip_bersih("::ffff:192.168.56.101"), "192.168.56.101")
    cek("kurung siku dibuang", rs._ip_bersih("[fe80::1]"), "fe80::1")
    cek("alamat biasa tidak berubah", rs._ip_bersih("10.1.2.3"), "10.1.2.3")

    for ip, harap in (("10.0.0.5", False), ("192.168.1.1", False),
                      ("172.16.0.1", False), ("172.31.255.254", False),
                      ("172.32.0.1", True), ("127.0.0.1", False),
                      ("169.254.1.1", False), ("8.8.8.8", True),
                      ("91.189.91.99", True), ("fe80::1", False),
                      ("::ffff:192.168.56.1", False)):
        cek(f"{ip} di luar jaringan", rs._di_luar_jaringan(ip), harap)


# Part 2b: the DNS-name lookup job in the poller
#
# Runs on an in-memory database, never `nsm.db`: running poller functions against
# the primary database while the poller runs makes two concurrent writers.
#
# The resolver is replaced by a fake. Tested are three decisions of our own:
# failures are stored so they are not looked up forever, addresses that already
# have a name are not looked up again, and the `::ffff:` form is not stored twice.
def uji_job_dns():
    print()
    print("=" * 74)
    print("BAGIAN 2b: job pencari nama DNS (basis data memori, resolver tiruan)")
    print("=" * 74)

    import socket
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import database

    mesin = create_engine("sqlite://")
    original_engine, original_session = database.engine, database.SessionLocal
    database.engine = mesin
    database.SessionLocal = sessionmaker(bind=mesin)

    import models
    models.Base.metadata.create_all(mesin)

    import poller
    asli_resolver = socket.gethostbyaddr
    dicari = []

    JAWABAN = {"91.189.91.99": "snapstore.canonical.com"}

    def resolver_tiruan(ip):
        dicari.append(ip)
        if ip in JAWABAN:
            return (JAWABAN[ip], [], [ip])
        raise socket.herror(1, "tidak ada PTR")

    socket.gethostbyaddr = resolver_tiruan
    db = database.SessionLocal()
    try:
        t = datetime.now() - timedelta(minutes=5)
        for ip in ("91.189.91.99", "192.168.56.101", "::ffff:192.168.56.101"):
            db.add(models.Flow(device_id=1, waktu=t, ip_lokal="192.168.56.103",
                               port_lokal=22, ip_lawan=ip, port_lawan=50000,
                               byte_masuk=1, byte_keluar=1, keadaan="ESTAB"))
        db.commit()
        db.close()

        poller.poll_nama_alamat()

        db = database.SessionLocal()
        simpan = {n.ip: n for n in db.query(models.NamaAlamat).all()}

        cek("alamat yang punya PTR dapat namanya",
            simpan["91.189.91.99"].nama, "snapstore.canonical.com")
        cek("alamat yang gagal tetap disimpan sebagai baris",
            "192.168.56.101" in simpan, True)
        cek("alamat yang gagal ditandai tidak ditemukan",
            simpan["192.168.56.101"].ditemukan, 0)
        cek_benar("bentuk ::ffff: tidak disimpan sebagai baris kedua",
                  "::ffff:192.168.56.101" not in simpan,
                  f"(baris: {sorted(simpan)})")
        cek("dua alamat berbeda dicari, bukan tiga", len(dicari), 2)

        # Second round: no lookups at all. Without storing failures, addresses with no PTR
        # would be looked up every round, and those are the most expensive (9.0 s timeout).
        db.close()
        dicari.clear()
        poller.poll_nama_alamat()
        cek("putaran kedua tidak mencari ulang apa pun", len(dicari), 0)

    finally:
        socket.gethostbyaddr = asli_resolver
        try:
            db.close()
        except Exception:
            pass
        database.engine, database.SessionLocal = original_engine, original_session


def uji_data_nyata():
    print()
    print("=" * 74)
    print("BAGIAN 3: pemeriksaan silang ke nsm.db yang sebenarnya")
    print("=" * 74)

    # The comparison SQL runs through the SAME session, not by opening the database
    # file directly. After the data moved to MySQL, a separate `sqlite3` connection
    # would read a frozen file while the session reads the live database, so the two
    # sides would compare different datasets.
    from sqlalchemy import text

    from database import SessionLocal

    import report_service as rs

    db = SessionLocal()
    try:
        h = rs.percakapan_jaringan(db, "30d")
        if not h["ada_data"]:
            print("  DILEWATI  flow_koneksi masih kosong")
            return

        # The reference figure is computed by plain SQL, separate from the code under test,
        # so the formula is not validating itself.
        naif = db.execute(
            text("SELECT SUM(byte_keluar) FROM flow_koneksi")).scalar() or 0
        # The subquery is aliased `T`: MySQL rejects a derived table without a name.
        correct = db.execute(text("""
            SELECT SUM(m) FROM (
                SELECT MAX(byte_keluar) m FROM flow_koneksi
                GROUP BY device_id, ip_lokal, port_lokal, ip_lawan, port_lawan
            ) AS T
        """)).scalar() or 0

        print(f"  jumlah naif seluruh baris : {naif / 1048576:,.2f} MB")
        print(f"  maksimum per 5-tuple      : {correct / 1048576:,.2f} MB")
        if correct:
            print(f"  selisihnya                : {naif / correct:.2f} kali lipat")

        cek_benar("hasil fungsi tidak sebesar penjumlahan naif",
                  correct <= naif,
                  "(kalau ini gagal, ada baris yang hilang, bukan yang melar)")

        total_exit = sum(p["keluar_byte"] for p in h["percakapan"])
        cek_benar(
            "total di halaman cocok dengan maksimum-per-5-tuple (selisih < 1%)",
            correct == 0 or abs(total_exit - correct) / correct < 0.01,
            f"(halaman {total_exit:,.0f} B, SQL {correct:,.0f} B)")

        n_ffff = db.execute(text(
            "SELECT COUNT(*) FROM flow_koneksi WHERE ip_lawan LIKE '::ffff:%'"
        )).scalar()
        print(f"  baris beralamat ::ffff:   : {n_ffff}")
        cek_benar("tidak ada alamat ::ffff: yang lolos ke halaman",
                  not any(p["ip"].startswith("::ffff:") for p in h["percakapan"]),
                  f"(alamat: {[p['ip'] for p in h['percakapan']]})")

        print(f"\n  {h['lawan_jumlah']} lawan bicara, {h['lawan_luar']} di luar lab, "
              f"{h['koneksi']} koneksi")
        for p in h["percakapan"][:6]:
            mark = " [luar]" if p["luar_jaringan"] else ""
            print(f"    {p['ip']:<18} diambil {p['keluar_teks']:>10}  "
                  f"dikirim {p['masuk_teks']:>10}{mark}")
    finally:
        db.close()


if __name__ == "__main__":
    uji_buatan()
    uji_pembantu()
    uji_job_dns()
    uji_data_nyata()
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

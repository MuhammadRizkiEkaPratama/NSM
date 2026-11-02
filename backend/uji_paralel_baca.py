"""Test of batched port checks and traffic reads: faster AND still correct.

Continues `uji_ping_paralel.py`. Three remaining sequential steps are batched:

    port check when ping is silent   poll_all() stage 1b
    counter reads                    poll_bandwidth() stage 2
    access log + flow reads          poll_traffic() stage 2

Speed is easy; the point is speed without changing the meaning of the data:

 1. `cek_port_banyak()` returns one key per address; an empty list differs from a missing key.
 2. Port order follows the requested list, not who answers first.
 3. `perlu_probe_tcp()` rejects every state that needs no check.
 4. A device whose ports are silent is STILL recorded DOWN (the dangerous direction).
 5. Ports are not checked twice in one round (batch then single).
 6. A wholly failed batch falls back to single checks instead of killing the round.
 7. `kerjakan_bersamaan()` returns errors rather than raising, so one bad device
    does not stop others.
 8. The bandwidth sample timestamp is taken AFTER the network read; before it,
    the rate denominator shrinks and all Mbps figures inflate.
 9. The access-log read position advances only if the rows were really stored.
10. `Sasaran` carries all fields the connector needs, so worker threads never
    touch the session's Device object.

Run: py uji_paralel_baca.py
"""
import sys
import time
from datetime import datetime, timedelta

# `poller` and `report_service` now only forward; the logic lives in
# `nsm/pemantau/*` and `report_service/*`. Setting `poller.nama = fake` has no
# effect, so `tambal()` patches the module that actually owns the name. See
# `bantu_tambal.py`.
from bantu_tambal import patch

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


# Simulated wait for one connection attempt: much smaller than the real timeout
# (1 s) so the test is fast, but large enough to make sequential vs concurrent obvious.
TUNGGU = 0.3


def uji():
    print("=" * 74)
    print("Pemborongan cek port & pembacaan lalu lintas")
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

    import poller
    import connectors.tcp as tcp

    # =====================================================================
    print("\n1. cek_port_banyak: bentuk hasilnya")
    # =====================================================================
    alamat = ["192.168.56.210", "192.168.56.211", "192.168.56.212"]
    peta = tcp.cek_port_banyak(alamat, [22, 80, 443])
    cek("satu kunci untuk tiap alamat", sorted(peta), sorted(alamat))
    benar("alamat mati dijawab daftar KOSONG, bukan kunci yang hilang",
          all(peta[ip] == [] for ip in alamat), f"-> {peta}")

    cek("daftar alamat kosong dijawab peta kosong",
        tcp.cek_port_banyak([], [22]), {})
    cek("daftar port kosong tetap memberi kunci untuk tiap alamat",
        tcp.cek_port_banyak(["10.0.0.9"], []), {"10.0.0.9": []})

    kembar = tcp.cek_port_banyak(["10.0.0.9", "10.0.0.9", "10.0.0.8"], [])
    cek("alamat kembar tidak digandakan", len(kembar), 2)

    # =====================================================================
    print("\n2. urutan port mengikuti yang diminta, bukan siapa tercepat")
    # =====================================================================
    original_tcp = tcp.TcpConnector

    class TcpPalsu:
        """Always answers, but port 443 is deliberately slowest."""

        def __init__(self, ip_address, port=22, timeout=1.0):
            self.port = port

        def check_reachable(self):
            time.sleep(0.05 if self.port == 443 else 0.01)
            return True, 1.0

    tcp.TcpConnector = TcpPalsu
    try:
        hasil = tcp.cek_port_banyak(["10.0.0.1", "10.0.0.2"], [443, 22, 80])
    finally:
        tcp.TcpConnector = original_tcp
    cek("alamat pertama: urutan seperti diminta", hasil["10.0.0.1"], [443, 22, 80])
    cek("alamat kedua: urutan seperti diminta", hasil["10.0.0.2"], [443, 22, 80])

    # =====================================================================
    print("\n3. borongan menghapus antrean antar-device")
    # =====================================================================

    class TcpLambat:
        """Imitate a closed port that only gives up after its timeout."""

        def __init__(self, ip_address, port=22, timeout=1.0):
            pass

        def check_reachable(self):
            time.sleep(TUNGGU)
            return False, None

    enam = [f"192.168.56.2{n}" for n in range(20, 26)]
    port = [22, 80, 443]
    tcp.TcpConnector = TcpLambat
    try:
        t0 = time.time()
        for ip in enam:
            tcp.cek_port_terbuka(ip, port)
        berurutan = time.time() - t0

        t0 = time.time()
        tcp.cek_port_banyak(enam, port)
        bersamaan = time.time() - t0
    finally:
        tcp.TcpConnector = original_tcp

    print(f"       {len(enam)} device x {len(port)} port, tiap percobaan {TUNGGU} dtk")
    print(f"       berurutan {berurutan:.2f} dtk   bersamaan {bersamaan:.2f} dtk")
    benar("bersamaan lebih cepat dari sepertiga waktu berurutan",
          bersamaan < berurutan / 3,
          f"-> {bersamaan:.2f} dtk vs {berurutan:.2f} dtk")

    # =====================================================================
    print("\n4. perlu_probe_tcp menolak keadaan yang memang tidak perlu")
    # =====================================================================
    d = models.Device(id=1, name="Uji probe", ip_address="192.168.56.230",
                      device_type="server", platform="linux", aktif=1)
    db.add(d)
    db.commit()
    sekarang = datetime.now()
    limit = poller.get_down_threshold()

    poller.tcp_terjangkau_sampai.clear()
    poller.tcp_periksa_lagi_pada.clear()

    cek("device HIDUP tidak perlu diperiksa portnya",
        poller.perlu_probe_tcp(d, True, 99, sekarang), False)
    cek("device mati DI BAWAH ambang gagal beruntun belum diperiksa",
        poller.perlu_probe_tcp(d, False, limit - 1, sekarang), False)
    cek("device mati yang MENCAPAI ambang diperiksa",
        poller.perlu_probe_tcp(d, False, limit, sekarang), True)

    lokal = models.Device(id=2, name="Mesin ini", ip_address="127.0.0.1",
                          device_type="pc", platform="lokal", aktif=1)
    cek("device lokal tidak pernah diperiksa lewat port",
        poller.perlu_probe_tcp(lokal, False, 99, sekarang), False)

    poller.tcp_terjangkau_sampai[1] = sekarang.timestamp() + 30
    cek("hasil sebelumnya masih berlaku -> tidak diperiksa ulang",
        poller.perlu_probe_tcp(d, False, limit, sekarang), False)
    poller.tcp_terjangkau_sampai.clear()

    poller.tcp_periksa_lagi_pada[1] = sekarang.timestamp() + 30
    cek("belum waktunya diperiksa lagi -> tidak diperiksa",
        poller.perlu_probe_tcp(d, False, limit, sekarang), False)
    poller.tcp_periksa_lagi_pada.clear()

    print("\n   beruntun_berikutnya menghitung, bukan memakai angka lama")
    poller.gagal_beruntun.clear()
    poller.gagal_beruntun[1] = limit - 1
    cek("device yang BARU mencapai ambang tidak terlewat dari borongan",
        poller.beruntun_berikutnya(1, False), limit)
    cek("device yang hidup kembali dihitung nol",
        poller.beruntun_berikutnya(1, True), 0)
    poller.gagal_beruntun.clear()

    # =====================================================================
    print("\n5. hasil borongan dipakai, dan port tidak dicoba dua kali")
    # Two devices down: one whose port answers (ICMP blocked), one truly silent.
    # Both go through the same batch path.
    db.query(models.Device).delete()
    db.query(models.StatusLog).delete()
    db.query(models.DeviceEvent).delete()
    db.commit()
    db.add_all([
        models.Device(id=10, name="ICMP diblokir", ip_address="192.168.56.240",
                      device_type="server", platform="linux", aktif=1),
        models.Device(id=11, name="Benar-benar mati", ip_address="192.168.56.241",
                      device_type="server", platform="linux", aktif=1),
        # The third device deliberately does NOT appear in the batch ping results (an
        # address that failed to parse). It must fall back to the single ping inside
        # `periksa_device()`, not be guessed dead and port-checked.
        models.Device(id=12, name="Tak ada di hasil", ip_address="192.168.56.242",
                      device_type="server", platform="linux", aktif=1),
    ])
    db.commit()

    poller.gagal_beruntun.clear()
    poller.tcp_terjangkau_sampai.clear()
    poller.tcp_periksa_lagi_pada.clear()

    compute = {"borongan": 0, "satuan": 0, "alamat": [], "satuan_ip": []}
    original_many = poller.cek_port_banyak
    original_unit = poller.cek_port_terbuka

    def borongan_palsu(daftar, ports, timeout=1.0):
        compute["borongan"] += 1
        compute["alamat"] = sorted(daftar)
        return {ip: ([22] if ip == "192.168.56.240" else []) for ip in daftar}

    def satuan_palsu(ip, ports, timeout=1.0):
        compute["satuan"] += 1
        compute["satuan_ip"].append(ip)
        return []

    def ping_semua_mati(daftar):
        # The third device's address is deliberately omitted from the result.
        return {ip: (False, None) for ip in daftar if ip != "192.168.56.242"}

    original_ping = poller.ping_banyak
    patch("cek_port_banyak", borongan_palsu)
    patch("cek_port_terbuka", satuan_palsu)
    patch("ping_banyak", ping_semua_mati)
    try:
        # (threshold - 1) rounds: consecutive failures still below the threshold.
        for _ in range(limit - 1):
            poller.poll_all()
        cek("di bawah ambang, belum ada pemeriksaan port sama sekali",
            (compute["borongan"], compute["satuan"]), (0, 0))
        poller.poll_all()
    finally:
        patch("cek_port_banyak", original_many)
        patch("cek_port_terbuka", original_unit)
        patch("ping_banyak", original_ping)

    cek("borongan dipanggil SEKALI untuk seluruh putaran",
        compute["borongan"], 1)
    cek("kedua device mati ikut satu borongan yang sama",
        compute["alamat"], ["192.168.56.240", "192.168.56.241"])
    benar("alamat yang tidak ada di hasil ping TIDAK ditebak mati",
          "192.168.56.242" not in compute["alamat"],
          f"-> yang diborongkan {compute['alamat']}")
    benar("device yang sudah diborong tidak diperiksa satuan lagi",
          not ({"192.168.56.240", "192.168.56.241"} & set(compute["satuan_ip"])),
          f"-> yang diperiksa satuan {compute['satuan_ip']}")
    cek("hanya device di luar borongan yang jatuh ke jalur satuan",
        compute["satuan_ip"], ["192.168.56.242"])

    b10 = (db.query(models.StatusLog)
           .filter(models.StatusLog.device_id == 10)
           .order_by(models.StatusLog.id.desc()).first())
    b11 = (db.query(models.StatusLog)
           .filter(models.StatusLog.device_id == 11)
           .order_by(models.StatusLog.id.desc()).first())
    cek("device yang portnya menjawab dicatat HIDUP", b10.is_reachable, True)
    cek("dan cara membuktikannya ikut disimpan", b10.sumber, "tcp")

    print("\n   PENJAGA ARAH SEBALIKNYA")
    cek("device yang portnya DIAM tetap dicatat MATI", b11.is_reachable, False)
    cek("dan sumbernya tetap icmp, bukan tcp", b11.sumber, "icmp")

    # =====================================================================
    print("\n6. borongan gagal seluruhnya -> jatuh ke satuan, putaran hidup")
    # =====================================================================
    poller.gagal_beruntun.clear()
    poller.tcp_terjangkau_sampai.clear()
    poller.tcp_periksa_lagi_pada.clear()
    compute["satuan"] = 0
    compute["satuan_ip"] = []

    def borongan_meledak(daftar, ports, timeout=1.0):
        raise OSError("soket ditolak sistem (disengaja, ini uji)")

    patch("cek_port_banyak", borongan_meledak)
    patch("cek_port_terbuka", satuan_palsu)
    patch("ping_banyak", ping_semua_mati)
    try:
        for _ in range(limit - 1):
            poller.poll_all()
        poller.poll_all()  # round number `batas` -> the bulk alarm fires
        not_raises = True
    except Exception as e:
        not_raises = False
        print(f"       melempar: {e}")
    finally:
        patch("cek_port_banyak", original_many)
        patch("cek_port_terbuka", original_unit)
        patch("ping_banyak", original_ping)

    benar("poll_all tidak melempar walau borongan port gagal", not_raises)
    cek("SELURUH device jatuh ke pemeriksaan satuan",
        sorted(compute["satuan_ip"]),
        ["192.168.56.240", "192.168.56.241", "192.168.56.242"])

    # =====================================================================
    print("\n7. kerjakan_bersamaan membawa pulang galat, tidak melemparnya")
    # =====================================================================
    def kadang_meledak(x):
        if x == 3:
            raise ValueError("device ketiga bermasalah (disengaja)")
        return x * 10

    hasil = poller.kerjakan_bersamaan([1, 2, 3, 4], kadang_meledak)
    cek("jumlah hasil sama dengan jumlah masukan", len(hasil), 4)
    cek("urutannya mengikuti masukan, bukan siapa selesai duluan",
        [x for x, _, _ in hasil], [1, 2, 3, 4])
    cek("yang berhasil tetap membawa keluarannya",
        [k for _, k, g in hasil if g is None], [10, 20, 40])
    benar("yang gagal membawa galatnya, bukan menghentikan sisanya",
          isinstance(hasil[2][2], ValueError), f"-> {hasil[2]}")
    cek("daftar kosong dijawab daftar kosong",
        poller.kerjakan_bersamaan([], kadang_meledak), [])

    t0 = time.time()
    poller.kerjakan_bersamaan(list(range(6)), lambda _x: time.sleep(TUNGGU))
    old = time.time() - t0
    print(f"       6 pekerjaan x {TUNGGU} dtk selesai dalam {old:.2f} dtk")
    benar("enam pekerjaan tidak lagi mengantre",
          old < TUNGGU * 3, f"-> {old:.2f} dtk")

    # =====================================================================
    print("\n8. cap waktu sampel bandwidth diambil SESUDAH pembacaan")
    # =====================================================================
    db.query(models.Device).delete()
    db.query(models.StatusLog).delete()
    db.query(models.DeviceEvent).delete()
    db.query(models.BandwidthSample).delete()
    db.commit()
    db.add_all([
        models.Device(id=20, name="BW satu", ip_address="192.168.56.250",
                      device_type="server", platform="linux", aktif=1,
                      username="u", password="p"),
        models.Device(id=21, name="BW dua", ip_address="192.168.56.251",
                      device_type="server", platform="linux", aktif=1,
                      username="u", password="p"),
        models.Device(id=22, name="BW gagal", ip_address="192.168.56.252",
                      device_type="server", platform="linux", aktif=1,
                      username="u", password="p"),
    ])
    db.commit()

    class PembacaLambat:
        def __init__(self, ip):
            self.ip = ip

        def get_bandwidth(self):
            time.sleep(TUNGGU)
            if self.ip.endswith(".252"):
                raise OSError("SSH ditolak (disengaja, ini uji)")
            return {"enp0s3": {"in_octets": 1000.0, "out_octets": 2000.0}}

    asli_pembaca = poller.pilih_pembaca
    patch("pilih_pembaca", lambda s: (PembacaLambat(s.ip_address), "ssh"))
    try:
        t0 = time.time()
        poller.poll_bandwidth()
        old_bw = time.time() - t0
    finally:
        patch("pilih_pembaca", asli_pembaca)

    print(f"       3 device x {TUNGGU} dtk selesai dalam {old_bw:.2f} dtk")
    benar("pembacaan tiga device tidak lagi mengantre",
          old_bw < TUNGGU * 2, f"-> {old_bw:.2f} dtk")

    sample = db.query(models.BandwidthSample).all()
    cek("dua device berhasil menulis sampel", len(sample), 2)
    benar("device yang gagal tidak menghentikan device lain",
          {s.device_id for s in sample} == {20, 21},
          f"-> {[s.device_id for s in sample]}")
    benar("cap waktu diambil sesudah pembacaan, bukan sebelum",
          all(s.timestamp >= datetime.fromtimestamp(t0 + TUNGGU) for s in sample),
          f"-> t0+{TUNGGU} = {datetime.fromtimestamp(t0 + TUNGGU)}, "
          f"cap waktu {[s.timestamp for s in sample]}")

    print("\n   laju dihitung dari selisih dua sampel, bukan dari sampel pertama")
    benar("sampel pertama belum punya laju",
          all(s.in_bps is None for s in sample),
          f"-> {[s.in_bps for s in sample]}")

    # =====================================================================
    print("\n9. posisi baca access log hanya maju kalau barisnya tersimpan")
    # =====================================================================
    db.query(models.Device).delete()
    db.query(models.StatusLog).delete()
    db.query(models.DeviceEvent).delete()
    db.commit()
    db.add_all([
        models.Device(id=30, name="Web sehat", ip_address="192.168.56.253",
                      device_type="server", platform="linux", aktif=1,
                      username="u", password="p"),
        models.Device(id=31, name="Web gagal", ip_address="192.168.56.254",
                      device_type="server", platform="linux", aktif=1,
                      username="u", password="p"),
    ])
    db.add_all([
        models.Service(id=1, device_id=30, nama="Apache", jenis="http",
                       port=80, aktif=1),
        models.Service(id=2, device_id=31, nama="Apache", jenis="http",
                       port=80, aktif=1),
    ])
    db.commit()

    # Task shape is `(Sasaran, [(path, position), ...])` since one machine can serve
    # several webs with their own logs. The invariant is unchanged: the read position
    # advances only if the rows were really stored.
    def baca_palsu(tugas):
        s, list_log, _list_sftp, _list_smb, _daftar_perintah = tugas
        if s.id == 31:
            raise OSError("SSH putus di tengah jalan (disengaja, ini uji)")
        return {
            "log": [{
                "jalur": list_log[0][0],
                "galat": None,
                "entri": [{
                    "waktu": datetime.now(), "ip_klien": "192.168.56.1",
                    "metode": "GET", "path": "/hello.php",
                    "protokol": "HTTP/1.1", "status": 200,
                    "byte_kirim": 423.0, "byte_terima": None,
                    "rujukan": None, "user_agent": "uji", "dari_nsm": 0,
                }],
                "posisi_baru": 4321,
                "diputar": False,
            }],
            "flow": [{
                "ip_lokal": "192.168.56.253", "port_lokal": 80,
                "ip_lawan": "192.168.56.1", "port_lawan": 51234,
                "byte_masuk": 10.0, "byte_keluar": 20.0, "keadaan": "ESTAB",
            }],
        }

    asli_baca_trf = poller.baca_traffic_device
    patch("baca_traffic_device", baca_palsu)
    try:
        poller.poll_traffic()
    finally:
        patch("baca_traffic_device", asli_baca_trf)

    cek("baris access log device yang berhasil tersimpan",
        db.query(models.AksesWeb).filter(models.AksesWeb.device_id == 30).count(), 1)
    cek("baris flow-nya juga",
        db.query(models.Flow).filter(models.Flow.device_id == 30).count(), 1)
    p30 = (db.query(models.PosisiLog)
           .filter(models.PosisiLog.device_id == 30).first())
    cek("posisi bacanya maju", p30.posisi if p30 else None, 4321)

    print("\n   PENJAGA ARAH SEBALIKNYA")
    cek("device yang gagal tidak menyimpan baris apa pun",
        db.query(models.AksesWeb).filter(models.AksesWeb.device_id == 31).count(), 0)
    benar("dan posisi bacanya TIDAK maju",
          db.query(models.PosisiLog)
            .filter(models.PosisiLog.device_id == 31).first() is None,
          "-> posisi yang maju tanpa baris tersimpan membuat barisnya hilang")

    # =====================================================================
    print("\n10. Sasaran membawa semua bidang yang dibutuhkan connector")
    # =====================================================================
    d = models.Device(id=40, name="Lengkap", ip_address="192.168.56.255",
                      device_type="router", platform="cisco_ios", aktif=1,
                      username="u", password="p", ssh_key_path=None,
                      snmp_user="nsm", snmp_auth_pass="a", snmp_priv_pass="b",
                      snmp_auth_proto="SHA", snmp_priv_proto="AES",
                      snmp_port=161)
    db.add(d)
    db.commit()
    s = poller.sasaran(d)
    benar("semua bidang tersalin apa adanya",
          all(getattr(s, n) == getattr(d, n) for n in poller.Sasaran._fields),
          f"-> {s}")

    from_device, source_device = poller.pilih_pembaca(d)
    from_target, source_target = poller.pilih_pembaca(s)
    cek("pilih_pembaca memilih jalur yang sama untuk keduanya",
        (source_device, source_target), ("snmp", "snmp"))
    cek("dan connector yang sama jenisnya",
        type(from_target).__name__, type(from_device).__name__)

    # The copy must no longer be session-bound: if it were still a Device object,
    # `expire_on_commit` would make field reads from the worker thread silently run a new SELECT.
    benar("salinan tidak terikat sesi basis data",
          not isinstance(s, models.Device), f"-> {type(s).__name__}")

    db.close()
    database.engine, database.SessionLocal = original_engine, original_session


if __name__ == "__main__":
    uji()
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

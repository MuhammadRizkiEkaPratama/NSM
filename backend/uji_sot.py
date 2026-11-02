"""Tests for the source of truth: catalog, render and service.
 1. The catalog rejects what it should; intent values end up as CLI lines on real devices, so injection forms are tested explicitly.
 2. Rendering is deterministic: same input gives identical output, checked by comparing fingerprints.
 3. The service stores, reconciles and records correctly (temporary SQLite; never touches the real database).
 4. No device access: no connector imports (`connectors.ssh`, `connectors.perintah`, ...) anywhere in the `sot/` package.
Run: py uji_sot.py
"""
import os
import re
import sys
import tempfile

lolos = 0
gagal = 0


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print(f"  LOLOS  {nama}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama} {ket}")


def cek(nama, dapat, harap):
    global lolos, gagal
    if dapat == harap:
        lolos += 1
        print(f"  LOLOS  {nama}: {dapat!r}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama}: dapat {dapat!r}, harusnya {harap!r}")


def ditolak(nama, fungsi):
    """Run `fungsi()`; passes only if it raises `katalog.Ditolak`."""
    global lolos, gagal
    from sot import katalog as k
    try:
        hasil = fungsi()
        gagal += 1
        print(f"  GAGAL  {nama}: seharusnya ditolak, malah mengembalikan {hasil!r}")
    except k.Ditolak as e:
        lolos += 1
        print(f"  LOLOS  {nama}: ditolak -> {str(e)[:70]}")


def siapkan_db():
    """Temporary SQLite database with 3 sample devices."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    file = os.path.join(tempfile.mkdtemp(prefix="uji_sot_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    r1 = models.Device(name="Router Uji", ip_address="192.168.56.60",
                       device_type="router", platform="cisco_ios")
    linux1 = models.Device(name="Server Uji", ip_address="192.168.56.103",
                           device_type="server", platform="linux")
    without_platform = models.Device(name="Tanpa Platform", ip_address="1.2.3.4",
                                   device_type="pc", platform=None)
    db.add_all([r1, linux1, without_platform])
    db.commit()
    return db, r1, linux1, without_platform


# =============================================================================
print("=" * 74)
print("1. KATALOG -- validasi & penolakan")
print("=" * 74)

from sot import katalog as k  # noqa: E402

cek("hostname sah", k.periksa("hostname", "R1"), "R1")
cek("hostname di-strip", k.periksa("hostname", "  R1  "), "R1")
cek("daftar IP dipecah dari koma", k.periksa("ntp_server", "192.168.56.104, 192.168.56.104"),
    ["192.168.56.104"])
cek("bool 'ya' -> True", k.periksa("ssh_saja", "ya"), True)
cek("bool 'tidak' -> False", k.periksa("ssh_saja", "tidak"), False)
cek("angka string -> int", k.periksa("exec_timeout_menit", "10"), 10)

ditolak("kunci asing", lambda: k.periksa("kunci_yang_tidak_ada", "x"))
ditolak("hostname dgn baris baru (injeksi)", lambda: k.periksa("hostname", "R1\nenable"))
ditolak("hostname dgn tab", lambda: k.periksa("hostname", "R1\tenable"))
ditolak("hostname melebihi batas", lambda: k.periksa("hostname", "a" * 64))
ditolak("hostname bentuk tak sah", lambda: k.periksa("hostname", "R1!"))
ditolak("zona waktu di luar pilihan", lambda: k.periksa("zona_waktu", "Mars/Olympus"))
ditolak("angka di luar rentang", lambda: k.periksa("exec_timeout_menit", 0))
ditolak("angka bukan bilangan", lambda: k.periksa("exec_timeout_menit", "sepuluh"))
ditolak("bool nilai ambigu", lambda: k.periksa("ssh_saja", "mungkin"))
ditolak("daftar IP berisi bukan-IP", lambda: k.periksa("ntp_server", "bukan-ip"))
ditolak("daftar IP melebihi batas item", lambda: k.periksa("vty_izin", ", ".join(["1.1.1.%d" % i for i in range(20)])))
ditolak("daftar teks dgn baris baru di salah satu item", lambda: k.periksa("dns_server", "192.168.56.104\n8.8.8.8"))

benar("kunci wajib cisco_ios mencakup hostname",
     any(s["kunci"] == "hostname" for s in k.untuk_platform("cisco_ios")))
benar("kunci vty_izin TIDAK berlaku untuk linux",
     not any(s["kunci"] == "vty_izin" for s in k.untuk_platform("linux")))

ditolak("periksa_lengkap platform asing",
       lambda: k.periksa_lengkap("mikrotik_routeros", {}))
ditolak("periksa_lengkap kunci tak berlaku utk platform",
       lambda: k.periksa_lengkap("linux", {"vty_izin": "1.1.1.1"}))
ditolak("periksa_lengkap tanpa kunci wajib",
       lambda: k.periksa_lengkap("cisco_ios", {"hostname": "R1"}))

lengkap = k.periksa_lengkap("cisco_ios", {
    "hostname": "R1", "zona_waktu": "Asia/Jakarta", "ntp_server": "192.168.56.104",
    "exec_timeout_menit": 10, "ssh_saja": "ya", "layanan_http_mati": "ya",
})
benar("periksa_lengkap sukses saat semua wajib terisi", lengkap.get("hostname") == "R1")

kurang = k.kekurangan("cisco_ios", {"hostname": "R1"})
benar("kekurangan() melaporkan sisa kunci wajib", len(kurang) == 5,
     "-> dapat %d" % len(kurang))
benar("kekurangan() kosong saat semua wajib terisi",
     k.kekurangan("cisco_ios", lengkap) == [])

# --- interface / vlan / rute ---
iface = k.periksa_interface({"nama": "FastEthernet0/0", "ip": "192.168.56.60",
                             "mask": "255.255.255.0"})
cek("interface sah tersimpan bentuk kanonik", iface["nama"], "FastEthernet0/0")
ditolak("interface IP tanpa mask", lambda: k.periksa_interface(
    {"nama": "Fa0/0", "ip": "1.2.3.4"}))
ditolak("interface mask tanpa IP", lambda: k.periksa_interface(
    {"nama": "Fa0/0", "mask": "255.255.255.0"}))
ditolak("interface nama tak sah", lambda: k.periksa_interface({"nama": "; rm -rf"}))
ditolak("interface deskripsi dgn baris baru", lambda: k.periksa_interface(
    {"nama": "Fa0/0", "deskripsi": "baris satu\nenable"}))

ditolak("VLAN di luar rentang", lambda: k.periksa_vlan({"vlan_id": 5000}))
ditolak("VLAN nama berisi spasi", lambda: k.periksa_vlan(
    {"vlan_id": 10, "nama": "nama vlan"}))

ditolak("rute tanpa next_hop", lambda: k.periksa_rute(
    {"tujuan": "10.0.0.0", "mask": "255.255.255.0"}))
ditolak("rute next_hop bukan IP", lambda: k.periksa_rute(
    {"tujuan": "10.0.0.0", "mask": "255.255.255.0", "next_hop": "bukan-ip"}))


# =============================================================================
print()
print("=" * 74)
print("2. RENDER -- determinisme, dan kunci tidak boleh diam-diam menghilang")
print("=" * 74)

from sot import render as r  # noqa: E402

nilai = k.periksa_lengkap("cisco_ios", {
    "hostname": "R1", "domain": "bsp.id", "zona_waktu": "Asia/Jakarta",
    "ntp_server": "192.168.56.104", "exec_timeout_menit": 10,
    "ssh_saja": "ya", "layanan_http_mati": "ya",
    "vty_izin": "192.168.56.156, 192.168.56.1",
})
iface_list = [k.periksa_interface({"nama": "FastEthernet0/0", "ip": "192.168.56.60",
                                   "mask": "255.255.255.0", "deskripsi": "LAN A"}),
             k.periksa_interface({"nama": "FastEthernet1/1", "shutdown": True})]
vlan_list = [k.periksa_vlan({"vlan_id": 10, "nama": "DATA"})]
rute_list = [k.periksa_rute({"tujuan": "10.10.20.0", "mask": "255.255.255.0",
                             "next_hop": "10.10.10.2"})]

hasil1 = r.render("cisco_ios", nilai, iface_list, vlan_list, rute_list)
sidik_ulang = {r.render("cisco_ios", nilai, iface_list, vlan_list, rute_list)["sidik"]
              for _ in range(8)}
benar("render deterministik: 1 sidik unik dari 8 kali render",
     len(sidik_ulang) == 1 and next(iter(sidik_ulang)) == hasil1["sidik"],
     "-> dapat %d sidik unik" % len(sidik_ulang))

benar("hostname R1 muncul di keluaran", "hostname R1" in hasil1["teks"])
benar("server NTP muncul di keluaran", "ntp server 192.168.56.104" in hasil1["teks"])
benar("access-class VTY-IZIN TIDAK terduplikasi per-IP",
     hasil1["teks"].count("access-class VTY-IZIN in") == 1,
     "-> muncul %d kali (bug lama: sekali per IP)"
     % hasil1["teks"].count("access-class VTY-IZIN in"))
benar("kedua alamat vty_izin tetap tercetak sebagai permit terpisah",
     hasil1["teks"].count("permit host") == 2)
benar("interface shutdown dinyatakan `shutdown`, bukan `no shutdown`",
     re.search(r"interface FastEthernet1/1\n shutdown\n", hasil1["teks"]) is not None)
benar("teks berakhir dengan tepat SATU baris baru (bentuk kanonik)",
     hasil1["teks"].endswith("\n") and not hasil1["teks"].endswith("\n\n"))

ditolak_render = False
try:
    r.render("mikrotik_routeros", {})
except Exception as e:
    ditolak_render = type(e).__name__ == "GagalRender"
benar("platform tanpa template -> GagalRender, bukan galat mentah", ditolak_render)

try:
    r.render("cisco_ios", dict(nilai, kunci_typo_yang_tak_ada="x"))
    benar("kunci asing di nilai (tak dibaca template) tidak memicu galat", True)
except r.GagalRender as e:
    benar("kunci asing di nilai (tak dibaca template) tidak memicu galat",
         False, "-> malah meledak: %s" % e)

# Call render() directly, bypassing `katalog.periksa_lengkap`, with a required key missing from `nilai`: StrictUndefined must raise and surface as GagalRender, not produce a silent empty line.
meledak_terbaca = False
try:
    r.render("cisco_ios", {"hostname": "R1"})  # ntp_server dkk sengaja hilang
except r.GagalRender as e:
    meledak_terbaca = "UndefinedError" in str(e) or "undefined" in str(e).lower()
benar("kunci WAJIB hilang dari nilai (lewat render() langsung) -> "
     "StrictUndefined meledak TERBACA, bukan mencetak baris kosong diam-diam",
     meledak_terbaca)

sidik_tpl_1 = r.sidik_template("cisco_ios")
sidik_tpl_2 = r.sidik_template("cisco_ios")
cek("sidik_template stabil dipanggil dua kali", sidik_tpl_1, sidik_tpl_2)


# =============================================================================
print()
print("=" * 74)
print("3. SERVICE -- simpan, selaraskan, riwayat, dan render_intent")
print("=" * 74)

from sot import service as svc  # noqa: E402

db, r1, linux1, without_platform = siapkan_db()

a0 = svc.ambil(db, r1.id)
benar("device baru: belum lengkap", a0["lengkap"] is False)
benar("device baru: semua kunci wajib masuk daftar kurang",
     len(a0["kurang"]) == sum(1 for s in k.untuk_platform("cisco_ios") if s["wajib"]))

ditolak("device tanpa platform ditolak service",
       lambda: svc.ambil(db, without_platform.id))

hasil_simpan = svc.simpan_nilai(db, r1.id, {"hostname": "R1"}, oleh="uji")
cek("simpan_nilai pertama: 1 baris ditambah", hasil_simpan["berubah"], 1)

hasil_simpan_ulang = svc.simpan_nilai(db, r1.id, {"hostname": "R1"}, oleh="uji")
cek("simpan_nilai dgn nilai IDENTIK: 0 baris berubah (tidak menulis sia-sia)",
    hasil_simpan_ulang["berubah"], 0)

ditolak("render_intent saat belum lengkap", lambda: svc.render_intent(db, r1.id))

svc.simpan_nilai(db, r1.id, {
    "zona_waktu": "Asia/Jakarta", "ntp_server": "192.168.56.104",
    "exec_timeout_menit": 10, "ssh_saja": "ya", "layanan_http_mati": "ya",
}, oleh="uji")
a1 = svc.ambil(db, r1.id)
benar("intent lengkap sesudah semua wajib diisi", a1["lengkap"] is True)

hasil_render = svc.render_intent(db, r1.id)
benar("render_intent menghasilkan teks", "hostname R1" in hasil_render["teks"])

svc.simpan_nilai(db, r1.id, {"exec_timeout_menit": 20}, oleh="uji2")
riw = svc.riwayat(db, r1.id)
cek("riwayat tercatat 'ubah' utk exec_timeout_menit", riw[0]["aksi"], "ubah")
cek("riwayat lama/baru benar", (riw[0]["lama"], riw[0]["baru"]), (10, 20))
cek("riwayat mencatat siapa mengubah", riw[0]["oleh"], "uji2")

# --- selaraskan interface: tambah, ubah, hapus ---
svc.simpan_interface(db, r1.id, [
    {"nama": "Fa0/0", "ip": "192.168.56.60", "mask": "255.255.255.0"},
    {"nama": "Fa0/1", "shutdown": True},
], oleh="uji")
a2 = svc.ambil(db, r1.id)
cek("2 interface tersimpan", len(a2["interface"]), 2)

svc.simpan_interface(db, r1.id, [
    {"nama": "Fa0/0", "ip": "192.168.56.61", "mask": "255.255.255.0"},  # IP diubah
], oleh="uji3")
a3 = svc.ambil(db, r1.id)
cek("sesudah selaras ulang: 1 interface tersisa", len(a3["interface"]), 1)
cek("IP interface yang tersisa sudah ter-update", a3["interface"][0]["ip"], "192.168.56.61")

riw2 = svc.riwayat(db, r1.id)
kategori_iface = [x for x in riw2 if x["kategori"] == "interface"]
aksi_terlihat = {x["aksi"] for x in kategori_iface}
benar("riwayat interface mencakup tambah, ubah, DAN hapus",
     aksi_terlihat == {"tambah", "ubah", "hapus"},
     "-> dapat %s" % aksi_terlihat)

ditolak("interface duplikat dalam satu pengiriman",
       lambda: svc.simpan_interface(db, r1.id, [{"nama": "Fa0/0"}, {"nama": "Fa0/0"}], oleh="x"))
ditolak("VLAN duplikat dalam satu pengiriman",
       lambda: svc.simpan_vlan(db, r1.id, [{"vlan_id": 1}, {"vlan_id": 1}], oleh="x"))

# --- ringkasan() ---
svc.simpan_nilai(db, linux1.id, {"hostname": "web1"}, oleh="uji")
ring = svc.ringkasan(db)
nama_di_ringkasan = {x["device"] for x in ring}
benar("ringkasan mencakup device cisco_ios dan linux yang punya katalog",
     {"Router Uji", "Server Uji"} <= nama_di_ringkasan)
benar("ringkasan TIDAK menyertakan device tanpa platform yg didukung",
     "Tanpa Platform" not in nama_di_ringkasan)

db.close()


# =============================================================================
print()
print("=" * 74)
print("4. NOL SENTUHAN KE PERANGKAT -- sot/ tidak boleh impor connector apa pun")
print("=" * 74)

FOLDER = os.path.dirname(os.path.abspath(__file__))
folder_sot = os.path.join(FOLDER, "sot")
terlarang = re.compile(r"^\s*(from connectors|import connectors|from paramiko"
                       r"|import paramiko|from netmiko|import netmiko)\b",
                       re.MULTILINE)
bersih = True
for nama_berkas in os.listdir(folder_sot):
    if not nama_berkas.endswith(".py"):
        continue
    isi = open(os.path.join(folder_sot, nama_berkas), encoding="utf-8").read()
    if terlarang.search(isi):
        bersih = False
        print(f"  GAGAL  {nama_berkas} mengimpor sesuatu yang menyentuh perangkat")
benar("tidak ada satu pun berkas di sot/ yang mengimpor connector jaringan",
     bersih)


if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

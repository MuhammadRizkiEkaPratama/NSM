"""Test of device dependencies: cause vs effect.

The main scenario comes from a real incident: R1 went down and took R2, SW-B,
and the LDAP directory with it (docs/POSTMORTEM-R1.md). The topology matches
the primary lab instance's `device_link`, copied from `isi_device_link.py`.

Proven:
  1. R1 down -> R2/SW-B/LDAP are recognized as effects, not causes
  2. R1 up, LDAP down alone -> recognized as a cause
  3. Incomplete graph -> "cannot be determined", not "none"
  4. Recovery and notification treat "doubtful" differently, per their roles
  5. The candidate filter holds back effects and returns the reason

Run: py uji_ketergantungan.py
"""
import os
import sys
import tempfile
from datetime import datetime

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


import models  # noqa: E402
import ketergantungan as kt  # noqa: E402


def siapkan_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    file = os.path.join(tempfile.mkdtemp(prefix="uji_ketergantungan_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


# Topology matches the primary lab instance (`isi_device_link.py`).
#
#   nsm-app(.156) ┐
#   Server Web    ├─ SW-A ── R1 ══ISP══ R2 ── SW-B ── LDAP(.20.101)
#   Server Data   ┤
#   SMB(.105)     ┘
PERANGKAT = [
    # (ip, nama, platform, gns3_node)
    ("192.168.56.156", "NSM (nsm-app)",   "lokal",     None),
    ("192.168.56.103", "Server Web",      "linux",     None),
    ("192.168.56.104", "Server Data",     "linux",     None),
    ("192.168.56.105", "Server Berkas",   "linux",     None),
    ("192.168.56.61",  "Switch Lokasi A", "cisco_ios", "SW-A"),
    ("192.168.56.60",  "Router Lokasi A", "cisco_ios", "R1"),
    ("192.168.20.1",   "Router Lokasi B", "cisco_ios", "R2"),
    ("192.168.20.2",   "Switch Lokasi B", "cisco_ios", "SW-B"),
    ("192.168.20.101", "Direktori LDAP",  "linux",     None),
]

KABEL = [
    ("192.168.56.156", "192.168.56.61"),
    ("192.168.56.103", "192.168.56.61"),
    ("192.168.56.104", "192.168.56.61"),
    ("192.168.56.105", "192.168.56.61"),
    ("192.168.56.61",  "192.168.56.60"),
    ("192.168.56.60",  "192.168.20.1"),
    ("192.168.20.1",   "192.168.20.2"),
    ("192.168.20.101", "192.168.20.2"),
]


def prepare_lab(db, yang_mati=()):
    """Build the lab topology and mark `yang_mati` (list of names) as down."""
    per_ip = {}
    for ip, nama, platform, node in PERANGKAT:
        d = models.Device(name=nama, ip_address=ip, device_type="server",
                          platform=platform, gns3_node=node, aktif=1)
        db.add(d)
        db.commit()
        per_ip[ip] = d
    for a, b in KABEL:
        db.add(models.DeviceLink(device_a_id=per_ip[a].id,
                                 device_b_id=per_ip[b].id, jenis="uji"))
    db.commit()
    for ip, d in per_ip.items():
        db.add(models.StatusLog(device_id=d.id, timestamp=datetime.now(),
                                is_reachable=(0 if d.name in yang_mati else 1)))
    db.commit()
    return {d.name: d for d in per_ip.values()}


# =============================================================================
print("=" * 74)
print("1. SKENARIO INSIDEN R1 (14 Agustus 2026): R1 mati menyeret tiga lainnya")
print("=" * 74)

db = siapkan_db()
per_nama = prepare_lab(db, yang_mati=(
    "Router Lokasi A", "Router Lokasi B", "Switch Lokasi B", "Direktori LDAP"))

r1 = kt.penyebab_hulu(db, per_nama["Router Lokasi A"].id)
cek("R1 sendiri -> SEBAB (tidak ada hulu yang mati)", r1["status"], kt.TIDAK_ADA)

for nama in ("Router Lokasi B", "Switch Lokasi B", "Direktori LDAP"):
    h = kt.penyebab_hulu(db, per_nama[nama].id)
    cek("%s -> AKIBAT" % nama, h["status"], kt.ADA_PENYEBAB)
    benar("  dan menyebut R1 sebagai penyebabnya",
         any("Router Lokasi A" in m["nama"] for m in h["hulu_mati"]))

h_ldap = kt.penyebab_hulu(db, per_nama["Direktori LDAP"].id)
benar("LDAP menyebut SELURUH hulu yang mati (R1, R2, SW-B), bukan cuma satu",
     len(h_ldap["hulu_mati"]) == 3)
benar("jalur yang dilaporkan lengkap dari NSM sampai LDAP (6 lompatan)",
     len(h_ldap["jalur"]) == 6, "-> %s" % h_ldap["jalur"])

sehat = kt.penyebab_hulu(db, per_nama["Server Web"].id)
cek("Server Web (hidup, Lokasi A) -> tidak ada penyebab hulu",
    sehat["status"], kt.TIDAK_ADA)


# =============================================================================
print()
print("=" * 74)
print("2. LAWAN KASUSNYA: LDAP mati SENDIRI, jalur utuh -> harus SEBAB")
print("=" * 74)

db = siapkan_db()
per_nama = prepare_lab(db, yang_mati=("Direktori LDAP",))
h = kt.penyebab_hulu(db, per_nama["Direktori LDAP"].id)
cek("LDAP mati sendirian -> SEBAB, bukan ditekan salah", h["status"], kt.TIDAK_ADA)
benar("alasannya menyebut jalurnya utuh", "menjawab normal" in h["alasan"])

boleh, alasan = kt.boleh_ditindak(db, per_nama["Direktori LDAP"].id)
benar("pemulih BOLEH bertindak untuk kasus ini", boleh is True)


# =============================================================================
print()
print("=" * 74)
print("3. GRAF TIDAK LENGKAP -> 'tidak bisa dipastikan', BUKAN 'tidak ada'")
print("   (kebohongan paling halus: benar secara bentuk, salah secara arti)")
print("=" * 74)

db = siapkan_db()
per_nama = prepare_lab(db, yang_mati=())
yatim = models.Device(name="Server Baru", ip_address="192.168.56.199",
                      device_type="server", platform="linux", aktif=1)
db.add(yatim)
db.commit()
db.add(models.StatusLog(device_id=yatim.id, timestamp=datetime.now(), is_reachable=0))
db.commit()

h = kt.penyebab_hulu(db, yatim.id)
cek("device di luar graf -> TIDAK BISA DIPASTIKAN", h["status"], kt.TIDAK_BISA_DIPASTIKAN)
benar("alasannya TEGAS menyatakan ini bukan bukti jalur sehat",
     "BUKAN berarti jalurnya sehat" in h["alasan"])

boleh_pemulih, _ = kt.boleh_ditindak(db, yatim.id)
cek("PEMULIH saat ragu -> TIDAK bertindak (bawaan aman)", boleh_pemulih, False)

boleh_notif, _ = kt.boleh_ditindak(db, yatim.id, izinkan_kalau_ragu=True)
cek("NOTIFIKASI saat ragu -> TETAP kabari (diam bukan keadaan aman utk kabar)",
    boleh_notif, True)

db2 = siapkan_db()
d = models.Device(name="Sendirian", ip_address="10.0.0.1", device_type="server",
                  platform="linux", aktif=1)
db2.add(d)
db2.commit()
h2 = kt.penyebab_hulu(db2, d.id)
cek("tanpa device platform 'lokal' -> TIDAK BISA DIPASTIKAN",
    h2["status"], kt.TIDAK_BISA_DIPASTIKAN)
benar("alasannya menyebut titik pandang yang hilang",
     "lokal" in h2["alasan"])


# =============================================================================
print()
print("=" * 74)
print("4. saring_kandidat(): yang AKIBAT ditahan, alasannya DIKEMBALIKAN")
print("   (kandidat yang hilang tanpa jejak = kelas bug yang sudah berulang)")
print("=" * 74)

db = siapkan_db()
per_nama = prepare_lab(db, yang_mati=(
    "Router Lokasi A", "Router Lokasi B", "Switch Lokasi B", "Direktori LDAP"))

kandidat = [per_nama[n] for n in
            ("Router Lokasi A", "Router Lokasi B", "Switch Lokasi B", "Direktori LDAP")]
diteruskan, ditahan = kt.filter_candidate(db, kandidat, lambda d: d)

cek("dari 4 kandidat, hanya 1 diteruskan (akar masalahnya saja)",
    len(diteruskan), 1)
benar("yang diteruskan adalah R1, si akar masalah",
     diteruskan and diteruskan[0].name == "Router Lokasi A")
cek("3 sisanya ditahan", len(ditahan), 3)
benar("tiap yang ditahan membawa device DAN alasannya",
     all(t.get("device") is not None and t.get("alasan") for t in ditahan))

# candidate tuple shape (used by service/interface/config)
kandidat_tuple = [(per_nama["Direktori LDAP"], "FastEthernet0/0"),
                  (per_nama["Router Lokasi A"], "FastEthernet0/0")]
dit, tah = kt.filter_candidate(db, kandidat_tuple, lambda it: it[0])
cek("bentuk kandidat tuple juga tersaring benar", len(dit), 1)
benar("dan yang lolos tetap tuple utuh (bukan cuma device-nya)",
     dit and isinstance(dit[0], tuple) and dit[0][1] == "FastEthernet0/0")


# =============================================================================
print()
print("=" * 74)
print("5. jalur() -- BFS stabil dan benar")
print("=" * 74)

db = siapkan_db()
per_nama = prepare_lab(db, yang_mati=())
nsm = kt.titik_pandang(db)
benar("titik_pandang() menemukan device ber-platform 'lokal'",
     nsm is not None and nsm.name == "NSM (nsm-app)")

j = kt.jalur(db, nsm.id, per_nama["Direktori LDAP"].id)
nama_jalur = [db.get(models.Device, i).name for i in j]
cek("jalur NSM -> LDAP persis mengikuti kabel sungguhan", nama_jalur, [
    "NSM (nsm-app)", "Switch Lokasi A", "Router Lokasi A",
    "Router Lokasi B", "Switch Lokasi B", "Direktori LDAP"])

j2 = kt.jalur(db, nsm.id, per_nama["Direktori LDAP"].id)
benar("dipanggil dua kali -> hasil IDENTIK (BFS stabil, bukan acak)", j == j2)

benar("device yang tidak tersambung -> None (bukan jalur kosong)",
     kt.jalur(db, nsm.id, 99999) is None)


if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

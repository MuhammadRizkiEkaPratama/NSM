"""Test of notifications: one email per INCIDENT, not per EVENT.

Notifications are the one part of NSM that touches real inboxes, and errors go
both ways:

  1. Too many: four emails for one fault, three accusing healthy devices.
  2. Too few: a module that never sends anything would pass a test that only
     checks "no excess emails". That is costlier: a real fault nobody hears about.

So each section is paired: proven SILENT when it should be silent, AND proven to
SEND when it should send.

Pure test: temporary SQLite, `pengirim` replaced by a recorder; no real email,
no Spring Boot, no network.

Run: py uji_notifikasi_insiden.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

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


def cek(nama, dapat, harap):
    global lolos, gagal
    if dapat == harap:
        lolos += 1
        print("  LOLOS  %s: %r" % (nama, dapat))
    else:
        gagal += 1
        print("  GAGAL  %s: dapat %r, harusnya %r" % (nama, dapat, harap))


import config  # noqa: E402
import korelasi as K  # noqa: E402
import models  # noqa: E402
import notifikasi_insiden as NI  # noqa: E402

SEKARANG = datetime(2026, 8, 23, 10, 0, 0)


class Perekam:
    """Replacement for `titip_gabungan_ke_java`. Records, does not send."""

    def __init__(self, meledak=False):
        self.pesan = []
        self.meledak = meledak

    def __call__(self, cfg, subjek, isi, device_ids):
        if self.meledak:
            raise RuntimeError("server email pura-pura mati")
        self.pesan.append({"subjek": subjek, "isi": isi,
                           "device_ids": list(device_ids)})
        return {"terkirim": 1, "pelanggan": 1}


def siapkan_db():
    """Same small topology as uji_korelasi: NSM-R1-R2-SW-B-LDAP."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    file = os.path.join(tempfile.mkdtemp(prefix="uji_notifins_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    nama = ["NSM", "R1", "R2", "SW-B", "LDAP"]
    dev = {}
    for i, n in enumerate(nama, start=1):
        d = models.Device(name=n, ip_address="192.168.9.%d" % i,
                          device_type="router" if n != "NSM" else "server",
                          platform="lokal" if n == "NSM" else "cisco_ios",
                          aktif=True)
        db.add(d)
        dev[n] = d
    db.commit()
    for a, b in (("NSM", "R1"), ("R1", "R2"), ("R2", "SW-B"), ("SW-B", "LDAP")):
        db.add(models.DeviceLink(device_a_id=dev[a].id, device_b_id=dev[b].id))
    db.commit()
    return db, dev


def matikan(db, dev, nama, waktu=None):
    db.add(models.DeviceEvent(device_id=dev[nama].id, event_type="DOWN",
                              timestamp=waktu or SEKARANG))
    db.commit()


def hidupkan(db, dev, nama, waktu=None):
    db.add(models.DeviceEvent(device_id=dev[nama].id, event_type="UP",
                              timestamp=waktu or SEKARANG))
    db.commit()


# The switch is replaced inside the test process only; `.env` on disk is untouched.
#
# `config._baca()` reads `.env` from the working directory, so setting
# `os.environ` has no effect. Section "0" below checks that the switch is really
# read as ON before any behavior is tested; without that guard the whole file
# could pass while the kill switch is off. Same replacement pattern as `uji_slo.py`.
_baca_asli = config._baca
_setelan = {}


def setel(**kv):
    _setelan.update({k: str(v) for k, v in kv.items()})
    config._baca = lambda: dict(_setelan)


setel(NOTIF_PER_INSIDEN=1, NOTIF_ENABLED=1, NOTIF_INSIDEN_PULIH=1)


print("=" * 74)
print("Uji PAKET B4 -- notifikasi per INSIDEN")
print("=" * 74)

print("\n0. Saklarnya benar-benar terbaca menyala")
benar("NOTIF_PER_INSIDEN terbaca nyala", config.get_notif_per_insiden(),
      "-> kalau mati, SELURUH uji di bawah akan lolos palsu karena "
      "modulnya memang tidak mengirim apa-apa")
benar("NOTIF_INSIDEN_PULIH terbaca nyala", config.get_notif_insiden_pulih())


# ===========================================================================
print()
print("=" * 74)
print("1. EMPAT GEJALA -> SATU EMAIL. Ini seluruh alasan B4 ada.")
print("=" * 74)

db, dev = siapkan_db()
for n in ("R2", "SW-B", "LDAP"):
    matikan(db, dev, n)
matikan(db, dev, "R1")
K.proses(db, sekarang=SEKARANG)

ins = db.query(models.Insiden).all()
cek("keempat perangkat jadi 1 insiden", len(ins), 1)
cek("dengan 4 gejala", db.query(models.InsidenGejala).count(), 4)

rek = Perekam()
h = NI.proses(db, pengirim=rek, sekarang=SEKARANG)
cek("satu email dikirim, bukan empat", len(rek.pesan), 1)
cek("dan dilaporkan sebagai 1 insiden baru", h["baru"], 1)

if rek.pesan:
    p = rek.pesan[0]
    benar("subjeknya menyebut AKAR, bukan perangkat hilir",
          "R1" in p["subjek"], "-> %r" % p["subjek"])
    benar("subjeknya menyebut nomor insiden",
          "#%d" % ins[0].id in p["subjek"], "-> %r" % p["subjek"])
    # Recipients are the UNION over all devices, not just the root: someone subscribed
    # to LDAP cares about LDAP, which is unusable.
    cek("dikirim atas nama KEEMPAT device (union pelanggan)",
        len(p["device_ids"]), 4)
    benar("isinya menyebut keempat perangkat",
          all(n in p["isi"] for n in ("R1", "R2", "SW-B", "LDAP")),
          "-> perangkat yang tidak disebut memaksa penerimanya membuka "
          "halaman hanya untuk tahu perangkat mana")


# ===========================================================================
print()
print("=" * 74)
print("2. PUTARAN KEDUA TIDAK MENGIRIM APA-APA (idempoten)")
print("=" * 74)

h2 = NI.proses(db, pengirim=rek, sekarang=SEKARANG + timedelta(seconds=60))
cek("tidak ada email tambahan", len(rek.pesan), 1)
cek("dilaporkan nol", (h2["baru"], h2["naik"], h2["pulih"]), (0, 0, 0))

matikan(db, dev, "R2", SEKARANG + timedelta(seconds=90))
K.proses(db, sekarang=SEKARANG + timedelta(seconds=90))
NI.proses(db, pengirim=rek, sekarang=SEKARANG + timedelta(seconds=90))
cek("gejala berulang tetap tidak mengirim", len(rek.pesan), 1)


# ===========================================================================
print()
print("=" * 74)
print("3. KEPARAHAN NAIK -> SATU email susulan. Ini satu-satunya susulan")
print("   yang dijanjikan B4, dan tanpa uji ini ia akan diam-diam hilang.")
print("=" * 74)

db3, dev3 = siapkan_db()
K.record_symptom(db3, "layanan", 1, dev3["LDAP"].id, SEKARANG,
               "Layanan LDAP lambat", keparahan="perhatian",
               akar_id=dev3["LDAP"].id, akar_pasti=True, sekarang=SEKARANG)
rek3 = Perekam()
NI.proses(db3, pengirim=rek3, sekarang=SEKARANG)
cek("email pertama terkirim", len(rek3.pesan), 1)

i3 = db3.query(models.Insiden).first()
cek("keparahan yang tercatat di kolom notif", i3.notif_keparahan, "perhatian")

K.record_symptom(db3, "layanan", 2, dev3["LDAP"].id, SEKARANG + timedelta(seconds=30),
               "Layanan LDAP lambat lagi", keparahan="perhatian",
               akar_id=dev3["LDAP"].id, akar_pasti=True,
               sekarang=SEKARANG + timedelta(seconds=30))
NI.proses(db3, pengirim=rek3, sekarang=SEKARANG + timedelta(seconds=30))
cek("keparahan SAMA -> tetap satu email", len(rek3.pesan), 1)

K.record_symptom(db3, "device", 3, dev3["LDAP"].id, SEKARANG + timedelta(seconds=60),
               "Device LDAP tidak terjangkau", keparahan="bahaya",
               akar_id=dev3["LDAP"].id, akar_pasti=True,
               sekarang=SEKARANG + timedelta(seconds=60))
h3 = NI.proses(db3, pengirim=rek3, sekarang=SEKARANG + timedelta(seconds=60))
cek("keparahan NAIK -> email susulan", len(rek3.pesan), 2)
cek("dilaporkan sebagai kenaikan", h3["naik"], 1)
if len(rek3.pesan) > 1:
    benar("subjek susulan mengatakan MEMBURUK, bukan mengulang subjek lama",
          "MEMBURUK" in rek3.pesan[1]["subjek"],
          "-> %r" % rek3.pesan[1]["subjek"])
    benar("dan subjeknya BERBEDA dari email pertama",
          rek3.pesan[1]["subjek"] != rek3.pesan[0]["subjek"])

K.record_symptom(db3, "device", 4, dev3["LDAP"].id, SEKARANG + timedelta(seconds=90),
               "Device LDAP masih tidak terjangkau", keparahan="bahaya",
               akar_id=dev3["LDAP"].id, akar_pasti=True,
               sekarang=SEKARANG + timedelta(seconds=90))
NI.proses(db3, pengirim=rek3, sekarang=SEKARANG + timedelta(seconds=90))
cek("sudah di puncak -> tidak ada susulan ketiga", len(rek3.pesan), 2)


# ===========================================================================
print()
print("=" * 74)
print("4. INSIDEN PULIH -> satu email penutup, SEKALI saja")
print("=" * 74)

db4, dev4 = siapkan_db()
matikan(db4, dev4, "R2")
K.proses(db4, sekarang=SEKARANG)
rek4 = Perekam()
NI.proses(db4, pengirim=rek4, sekarang=SEKARANG)
cek("email gangguan terkirim", len(rek4.pesan), 1)

hidupkan(db4, dev4, "R2", SEKARANG + timedelta(seconds=30))
K.proses(db4, sekarang=SEKARANG + timedelta(seconds=40))
NI.proses(db4, pengirim=rek4, sekarang=SEKARANG + timedelta(seconds=40))
cek("insiden belum ditutup -> belum ada email pulih", len(rek4.pesan), 1)

K.proses(db4, sekarang=SEKARANG + timedelta(seconds=K.JEDA_TUTUP_DETIK + 60))
i4 = db4.query(models.Insiden).first()
cek("insiden ditutup", i4.status, "pulih")

h4 = NI.proses(db4, pengirim=rek4,
               sekarang=SEKARANG + timedelta(seconds=K.JEDA_TUTUP_DETIK + 60))
cek("email pulih terkirim", len(rek4.pesan), 2)
cek("dilaporkan sebagai pulih", h4["pulih"], 1)
if len(rek4.pesan) > 1:
    benar("subjeknya mengatakan PULIH", "PULIH" in rek4.pesan[1]["subjek"],
          "-> %r" % rek4.pesan[1]["subjek"])
    benar("isinya menyebut MTTR", "MTTR" in rek4.pesan[1]["isi"])

NI.proses(db4, pengirim=rek4,
          sekarang=SEKARANG + timedelta(seconds=K.JEDA_TUTUP_DETIK + 120))
cek("putaran berikutnya TIDAK mengirim pulih kedua", len(rek4.pesan), 2)


# ===========================================================================
print()
print("=" * 74)
print("5. ARAH GAGAL: pengiriman yang GAGAL tidak boleh ditandai terkirim")
print("   Menandainya berarti gangguan yang sedang berlangsung tidak pernah")
print("   diberitahukan kepada siapa pun, dan tidak ada yang akan tahu.")
print("=" * 74)

db5, dev5 = siapkan_db()
matikan(db5, dev5, "R2")
K.proses(db5, sekarang=SEKARANG)

rusak = Perekam(meledak=True)
h5 = NI.proses(db5, pengirim=rusak, sekarang=SEKARANG)
cek("tidak ada email yang tercatat terkirim", len(rusak.pesan), 0)
cek("kegagalannya DILAPORKAN, bukan ditelan", h5["gagal"], 1)

i5 = db5.query(models.Insiden).first()
benar("insidennya TIDAK ditandai sudah dinotifikasi",
      not i5.notif_terkirim, "-> %r" % i5.notif_terkirim)

# The next healthy round MUST succeed in sending; this pairs with the failure
# marking above to show the module is not simply broken.
sehat = Perekam()
h5b = NI.proses(db5, pengirim=sehat, sekarang=SEKARANG + timedelta(seconds=60))
cek("putaran berikutnya berhasil mengirim", len(sehat.pesan), 1)
cek("dan dilaporkan sebagai insiden baru", h5b["baru"], 1)


# ===========================================================================
print()
print("=" * 74)
print("6. KILL-SWITCH: NOTIF_PER_INSIDEN=0 -> tidak mengirim apa pun")
print("=" * 74)

db6, dev6 = siapkan_db()
matikan(db6, dev6, "R2")
K.proses(db6, sekarang=SEKARANG)

setel(NOTIF_PER_INSIDEN=0)
rek6 = Perekam()
h6 = NI.proses(db6, pengirim=rek6, sekarang=SEKARANG)
cek("nol email saat saklar mati", len(rek6.pesan), 0)
cek("alasannya disebut, bukan diam-diam", h6.get("alasan"),
    "NOTIF_PER_INSIDEN=0")

setel(NOTIF_PER_INSIDEN=1)
h6b = NI.proses(db6, pengirim=rek6, sekarang=SEKARANG)
cek("dinyalakan lagi -> mengirim", len(rek6.pesan), 1)
cek("dan dilaporkan", h6b["baru"], 1)

# The master switch is tested too: NOTIF_ENABLED=0 turns everything off.
db6c, dev6c = siapkan_db()
matikan(db6c, dev6c, "R2")
K.proses(db6c, sekarang=SEKARANG)
setel(NOTIF_ENABLED=0)
rek6c = Perekam()
h6c = NI.proses(db6c, pengirim=rek6c, sekarang=SEKARANG)
cek("NOTIF_ENABLED=0 juga mematikan jalur ini", len(rek6c.pesan), 0)
cek("alasannya jelas", h6c.get("alasan"), "notifikasi dimatikan")
setel(NOTIF_ENABLED=1)


# ===========================================================================
print()
print("=" * 74)
print("7. Penyusunan pesan tidak jatuh pada data yang tidak lengkap")
print("=" * 74)

db7, dev7 = siapkan_db()
i7 = models.Insiden(mulai=SEKARANG, status="terbuka", akar_device_id=None,
                    akar_pasti=False, keparahan=None, jumlah_gejala=0,
                    notif_terkirim=False)
db7.add(i7)
db7.commit()

cfg = config.get_notif_config()
subjek, isi = NI.susun_pesan(db7, i7, cfg, jenis="baru")
benar("subjek tetap tersusun tanpa akar", bool(subjek), "-> %r" % subjek)
benar("dan mengatakan akarnya belum pasti",
      "belum bisa dipastikan" in subjek or "belum pasti" in isi)
benar("isinya tidak memuat teks 'None'", "None" not in isi,
      "-> nilai kosong yang bocor ke email terbaca seperti kerusakan")

# Device names containing HTML characters must not break the email; names are
# typed by people, and injectable HTML mail is as dangerous as an injectable page.
db7.query(models.Device).filter_by(name="R2").first().name = "<b>nakal</b>"
db7.commit()
i7b = models.Insiden(mulai=SEKARANG, status="terbuka",
                     akar_device_id=dev7["R2"].id, akar_pasti=True,
                     keparahan="bahaya", jumlah_gejala=0, notif_terkirim=False)
db7.add(i7b)
db7.commit()
_s, isi7b = NI.susun_pesan(db7, i7b, cfg, jenis="baru")
benar("nama device ber-HTML di-escape di badan email",
      "&lt;b&gt;nakal&lt;/b&gt;" in isi7b and "<b>nakal</b>" not in isi7b,
      "-> nama device bisa diketik orang")


config._baca = _baca_asli

print()
print("=" * 74)
print("%d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

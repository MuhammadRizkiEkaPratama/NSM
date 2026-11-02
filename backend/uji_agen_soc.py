"""Tests for the SOC agent.

Guards the architectural promises, not the quality of the narrative:
    1. The agent never touches a device.
    2. Its proposals go through the same gates as the regular recoverer, none
       skipped, loosened or duplicated.
    3. It is off by default, and the default mode only proposes.

Most important (section 5): 'usul' (propose) mode must not consume the real
recoverer's rate-limit budget, otherwise repeated questions would make the
recoverer refuse real actions with "rate limit reached".

Pure test: temporary SQLite, mocked AI call and action executor. No network, no devices.

Run: py uji_agen_soc.py
"""
import json
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


import agen_soc as A  # noqa: E402
import config  # noqa: E402
import korelasi as K  # noqa: E402
import models  # noqa: E402
import pagar_otomasi  # noqa: E402

# Moving time anchor (same reasoning as `uji_pola_log.py`): `agen_soc.ringkas(db, jam=...)`
# queries a window computed from the real `datetime.now()`, so a fixed past date
# eventually falls outside it. The largest forward offset here is +120 s, so 30
# minutes back leaves enough margin.
SEKARANG = datetime.now().replace(microsecond=0) - timedelta(minutes=30)

_baca_asli = config._baca
_setelan = {}


def setel(**kv):
    _setelan.update({k: str(v) for k, v in kv.items()})
    config._baca = lambda: dict(_setelan)


# `PAGAR_JAM_MULAI`/`PAGAR_JAM_SELESAI`: `config.get_pagar_jam_kerja()` reads these two
# keys; nothing reads a `PAGAR_JAM_KERJA` name, so setting that would have no effect.
setel(AGEN_SOC_AKTIF=1, AGEN_SOC_MODE="usul", AGEN_SOC_NARASI=0,
      PAGAR_DAFTAR_PUTIH="gns3_restart",
      PAGAR_JAM_MULAI=0, PAGAR_JAM_SELESAI=24)


def siapkan_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    file = os.path.join(tempfile.mkdtemp(prefix="uji_agensoc_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    dev = {}
    spec = [("NSM", "lokal", None), ("R1", "cisco_ios", "R1"),
            ("R2", "cisco_ios", "R2"), ("SW-B", "cisco_ios", "SW-B"),
            ("LDAP", "linux", None)]
    for i, (n, plate, node) in enumerate(spec, start=1):
        d = models.Device(name=n, ip_address="192.168.9.%d" % i,
                          device_type="router" if n != "NSM" else "server",
                          platform=plate, gns3_node=node, aktif=True)
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


def insiden_r1(db, dev):
    """Real incident: R1 down, three downstream devices went dark."""
    for n in ("R1", "R2", "SW-B", "LDAP"):
        matikan(db, dev, n)
    K.proses(db, sekarang=SEKARANG)
    return db.query(models.Insiden).first()


print("=" * 74)
print("Uji PAKET C4 -- agen SOC")
print("=" * 74)

# ===========================================================================
print("\n0. JANJI PALING DASAR: agen tidak punya kode yang menyentuh perangkat")
sumber = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "agen_soc.py"), encoding="utf-8").read()
TERLARANG = ["netmiko", "ConnectHandler", "paramiko", "subprocess",
             "urllib.request", "socket."]
ada = [t for t in TERLARANG if t in sumber]
cek("nol pustaka yang bisa menyentuh perangkat/jaringan diimpor", ada, [])
benar("dan tidak memanggil connectors apa pun",
      "from connectors" not in sumber and "import connectors" not in sumber)

# ===========================================================================
print("\n1. KILL-SWITCH: bawaannya MATI dan mode bawaannya cuma mengusulkan")
setel(AGEN_SOC_AKTIF=0)
db0, dev0 = siapkan_db()
ins0 = insiden_r1(db0, dev0)
h0 = A.proses(db0, sekarang=SEKARANG)
cek("agen tidak jalan", h0["jalan"], False)
cek("alasannya disebut", h0["alasan"], "AGEN_SOC_AKTIF=0")
cek("nol usulan tercatat", db0.query(models.UsulanAgen).count(), 0)

setel(AGEN_SOC_AKTIF=1)
h0b = A.proses(db0, sekarang=SEKARANG)
cek("dinyalakan -> menangani 1 insiden", h0b["ditangani"], 1)
cek("dan modenya 'usul'", h0b["mode"], "usul")

# ===========================================================================
print("\n2. TRIASE membawa riwayat, bukan cuma keparahan")
db, dev = siapkan_db()
ins = insiden_r1(db, dev)
tri = A.triase(db, ins, sekarang=SEKARANG)
cek("akarnya R1", tri["akar"], "R1")
cek("keparahannya terbawa", tri["keparahan"], "bahaya")
cek("empat perangkat terdampak", len(tri["device_terdampak"]), 4)
cek("belum pernah terjadi", tri["kebiasaan"], "belum_pernah")
benar("riwayatnya berupa kalimat", "BELUM PERNAH" in tri["riwayat"],
      "-> %r" % tri["riwayat"])

for k in range(3):
    db.add(models.Insiden(mulai=SEKARANG - timedelta(days=k + 1),
                          selesai=SEKARANG - timedelta(days=k + 1),
                          status="pulih", akar_device_id=dev["R1"].id,
                          akar_pasti=True, keparahan="bahaya",
                          jumlah_gejala=1, mttr_detik=120))
db.commit()
tri2 = A.triase(db, ins, sekarang=SEKARANG)
cek("tiga insiden serupa ditemukan", tri2["serupa_30_hari"], 3)
cek("semuanya pulih sendiri", tri2["kebiasaan"], "selalu_pulih_sendiri")
benar("dan MTTR rata-ratanya disebut", "2 menit" in tri2["riwayat"],
      "-> %r" % tri2["riwayat"])

# ===========================================================================
print("\n3. BUKTI: butir yang gagal dikumpulkan DISEBUT, bukan dihilangkan")
bukti = A.kumpulkan_bukti(db, ins, sekarang=SEKARANG)
benar("membawa daftar device terdampak", len(bukti["device_ids"]) == 4)
benar("punya medan syslog", "syslog" in bukti)
benar("punya medan hulu", "hulu" in bukti)
benar("punya medan anggaran", "anggaran" in bukti)
benar("punya medan baseline", "baseline" in bukti)
benar("punya daftar bagian yang gagal dikumpulkan",
      isinstance(bukti["gagal_dikumpulkan"], list))
print("       gagal dikumpulkan: %r" % bukti["gagal_dikumpulkan"])

# Syslog sungguhan ikut terbawa.
db.add(models.SyslogPesan(waktu=SEKARANG, device_id=dev["R1"].id,
                          alamat="192.168.9.2", facility=23, severity=3,
                          tag="%LINK-3-UPDOWN",
                          pesan="%LINK-3-UPDOWN: Interface Fa0/0, changed "
                                "state to down", sidik_templat="a"))
db.commit()
bukti2 = A.kumpulkan_bukti(db, ins, sekarang=SEKARANG)
benar("pesan syslog terbawa sebagai bukti", len(bukti2["syslog"]) >= 1)
cek("dan ditandai berasal dari device terdampak",
    bukti2["syslog_terdampak"], 1)

# ===========================================================================
print("\n4. NARASI templat: bersumber dari bukti, tanpa AI, selalu tersedia")
teks, sumber_n = A.narasi_ai(db, ins, tri2, bukti2)
print("       [%s] %s" % (sumber_n, teks[:220]))
benar("sumbernya templat karena AGEN_SOC_NARASI=0",
      sumber_n.startswith("templat"), "-> %r" % sumber_n)
benar("menyebut akarnya", "R1" in teks)
benar("menyebut jumlah perangkat terdampak", "3 perangkat lain" in teks,
      "-> %r" % teks)
benar("menyebut riwayatnya", "3x" in teks or "3 x" in teks, "-> %r" % teks)
benar("menyebut pesan syslog yang sungguhan diterima",
      "LINK-3-UPDOWN" in teks, "-> %r" % teks)

# AI enabled, but the call is replaced by a stub -- no network.
setel(AGEN_SOC_NARASI=1)
dipanggil = {}


def ai_palsu(sistem, bukti_json):
    dipanggil["sistem"] = sistem
    dipanggil["bukti"] = bukti_json
    return "Narasi buatan AI untuk pengujian."


teks_ai, sumber_ai = A.narasi_ai(db, ins, tri2, bukti2, _panggil=ai_palsu)
cek("sumbernya 'ai'", sumber_ai, "ai")
cek("teksnya dari AI", teks_ai, "Narasi buatan AI untuk pengujian.")
benar("perintah sistemnya melarang mengarang",
      "Jangan menambah" in dipanggil["sistem"])
benar("dan bukti templat ikut dikirim sebagai acuan",
      "narasi_templat" in dipanggil["bukti"])


# AI FAILS -> falls back to the template, and the failure is REPORTED.
def ai_meledak(sistem, bukti_json):
    raise RuntimeError("jaringan mati")


teks_g, sumber_g = A.narasi_ai(db, ins, tri2, bukti2, _panggil=ai_meledak)
benar("AI gagal -> jatuh ke templat", sumber_g.startswith("templat (AI gagal"),
      "-> %r" % sumber_g)
benar("dan teksnya tetap berisi", "R1" in teks_g)


# An EMPTY AI reply must also fall back to the template (an empty reply is a failure that does not raise).
def ai_kosong(sistem, bukti_json):
    return "   "


teks_k, sumber_k = A.narasi_ai(db, ins, tri2, bukti2, _panggil=ai_kosong)
benar("balasan kosong -> jatuh ke templat",
      sumber_k == "templat (balasan AI kosong)", "-> %r" % sumber_k)
setel(AGEN_SOC_NARASI=0)

# ===========================================================================
print("\n5. UJI PALING PENTING: mode 'usul' TIDAK menghabiskan jatah pagar")
db5, dev5 = siapkan_db()
ins5 = insiden_r1(db5, dev5)
setel(AGEN_SOC_MODE="usul")

sebelum = db5.query(models.PagarTindakan).count()
for _ in range(6):
    A.usul_tindakan(db5, ins5, {}, sekarang=SEKARANG)
sesudah = db5.query(models.PagarTindakan).count()
cek("enam usulan -> NOL baris pagar tertulis", sesudah - sebelum, 0)

# The real recoverer must still be allowed afterwards: a proposal must not write an
# 'izin' row that exhausts the rate limit.
kep = pagar_otomasi.putuskan(db5, dev5["R1"].id, "pemulih", "gns3_restart",
                             oleh="pemulih_gns3", sekarang=SEKARANG)
benar("pemulih sungguhan TETAP diizinkan sesudahnya", kep.izin,
      "-> %r" % kep.alasan)
cek("dan barisnya memang tertulis untuk yang sungguhan",
    db5.query(models.PagarTindakan).count() - sesudah, 1)

db5b, dev5b = siapkan_db()
ins5b = insiden_r1(db5b, dev5b)
setel(AGEN_SOC_MODE="jalan")
A.usul_tindakan(db5b, ins5b, {}, sekarang=SEKARANG,
                _pelaksana=lambda *a: {"berhasil": True, "tiruan": True})
benar("mode 'jalan' menulis baris pagar",
      db5b.query(models.PagarTindakan).count() >= 1,
      "-> %d" % db5b.query(models.PagarTindakan).count())
setel(AGEN_SOC_MODE="usul")

# ===========================================================================
print("\n6. PAGAR MENOLAK -> tidak ada tindakan, tapi usulannya TETAP terlihat")
db6, dev6 = siapkan_db()
ins6 = insiden_r1(db6, dev6)
# Empty the allowlist: gate 2 will refuse.
setel(PAGAR_DAFTAR_PUTIH="")
u6 = A.usul_tindakan(db6, ins6, {}, sekarang=SEKARANG)
cek("vonis pagar TOLAK", u6.vonis_pagar, "tolak")
cek("runbook yang diusulkan tetap dicatat", u6.tindakan, "gns3_restart")
benar("alasan penolakannya ikut tercatat lengkap",
      "daftar putih" in (u6.alasan_pagar or "").lower(),
      "-> %r" % u6.alasan_pagar)
setel(PAGAR_DAFTAR_PUTIH="gns3_restart")

# ===========================================================================
print("\n7. Tidak ada runbook yang cocok -> jatuh ke manusia, bukan dipaksakan")
db7, dev7 = siapkan_db()
# LDAP down on its own: not a GNS3 node, so no safe runbook.
matikan(db7, dev7, "LDAP")
K.proses(db7, sekarang=SEKARANG)
ins7 = db7.query(models.Insiden).first()
u7 = A.usul_tindakan(db7, ins7, {}, sekarang=SEKARANG)
cek("tidak ada tindakan yang diusulkan", u7.tindakan, None)
cek("dan pagar tidak pernah diminta", u7.vonis_pagar, "tidak_diminta")
benar("alasannya menjelaskan kenapa",
      "GNS3" in (u7.alasan_pagar or "") or "runbook" in (u7.alasan_pagar or ""),
      "-> %r" % u7.alasan_pagar)
cek("dan nol baris pagar tertulis", db7.query(models.PagarTindakan).count(), 0)

# ===========================================================================
print("\n8. IDEMPOTEN: putaran kedua tidak membanjiri dengan narasi ulang")
db8, dev8 = siapkan_db()
insiden_r1(db8, dev8)
setel(AGEN_SOC_AKTIF=1)
h8a = A.proses(db8, sekarang=SEKARANG)
n8a = db8.query(models.UsulanAgen).count()
cek("putaran pertama menangani 1 insiden", h8a["ditangani"], 1)
benar("dan menulis empat jenis usulan", n8a == 4, "-> %d" % n8a)

h8b = A.proses(db8, sekarang=SEKARANG + timedelta(seconds=120))
cek("putaran kedua menangani NOL", h8b["ditangani"], 0)
cek("dan tidak menambah baris apa pun",
    db8.query(models.UsulanAgen).count(), n8a)

# ===========================================================================
print("\n9. Ringkasan menjawab 'seberapa sering pagar setuju dengan agen'")
r = A.ringkas(db8, jam=24)
benar("menyebut keadaan saklarnya", r["aktif"] is True and r["mode"] == "usul")
benar("membawa daftar usulan", len(r["usulan"]) == n8a,
      "-> %d vs %d" % (len(r["usulan"]), n8a))
benar("dan menghitung setuju/tidak",
      isinstance(r["diizinkan_pagar"], int)
      and isinstance(r["ditolak_pagar"], int))
print("       diusulkan=%d izin=%d tolak=%d"
      % (r["diusulkan"], r["diizinkan_pagar"], r["ditolak_pagar"]))

narasi = [u for u in r["usulan"] if u["jenis"] == "narasi"]
benar("baris narasi ada", len(narasi) == 1, "-> %d" % len(narasi))
if narasi:
    benar("dan isinya terurai jadi objek", "teks" in narasi[0]["isi"],
          "-> %r" % narasi[0]["isi"])

# ===========================================================================
print("\n10. Mode yang salah ketik TIDAK berarti izin bertindak")
setel(AGEN_SOC_MODE="JALANKAN_SAJA_LAH")
cek("nilai tak dikenal jatuh ke 'usul'", config.get_agen_soc_mode(), "usul")
setel(AGEN_SOC_MODE="jalan")
cek("dan 'jalan' tetap terbaca 'jalan'", config.get_agen_soc_mode(), "jalan")
setel(AGEN_SOC_MODE="usul")

config._baca = _baca_asli

# ===========================================================================
print("\n14. 'SUDAH PULIH' dan 'TIDAK ADA RUNBOOK' harus terbaca BERBEDA")
# Regression found by running the agent on a real incident (Location A router,
# GNS3 node 'R1'). Refusing to propose was right, since all four symptoms had
# recovered and restarting a recovered router is harmful, but the recorded reason
# wrongly said no runbook matched. The runbook exists; the reason must say "already recovered".
db14, dev14 = siapkan_db()
r1_14 = dev14["R1"]


def _insiden_kosong(dbx, dev_akar, gejala):
    """Bare incident plus exactly the requested symptoms. Not via correlation: this tests `pilih_runbook`."""
    ins = models.Insiden(mulai=SEKARANG, status="terbuka",
                         akar_device_id=dev_akar.id, akar_pasti=True,
                         keparahan="bahaya", jumlah_gejala=len(gejala))
    dbx.add(ins)
    dbx.commit()
    for jenis, dev_g, already_recover in gejala:
        dbx.add(models.InsidenGejala(
            insiden_id=ins.id, jenis=jenis, device_id=dev_g.id,
            waktu=SEKARANG, jumlah=1, pulih=already_recover))
    dbx.commit()
    return ins


# (a) device symptom is STILL LIVE on the GNS3 node -> GNS3 runbook selected
insA = _insiden_kosong(db14, r1_14, [("device", r1_14, False)])
rb_a, alasan_a = A.pilih_runbook(db14, insA, {})
cek("gejala hidup di node GNS3 -> runbook GNS3", rb_a, A.RUNBOOK_GNS3)

# (b) same symptoms but already recovered -> not proposed, different reason
insB = _insiden_kosong(db14, r1_14, [("device", r1_14, True)])
rb_b, alasan_b = A.pilih_runbook(db14, insB, {})
benar("gejala sudah pulih -> tidak ada usulan", rb_b is None, "-> %r" % rb_b)
benar("alasannya menyebut sudah pulih", "pulih" in (alasan_b or "").lower(),
      "-> %r" % alasan_b)
benar("dan TIDAK berkata runbooknya tidak ada",
      "tidak cocok dengan satu pun runbook" not in (alasan_b or ""),
      "-> %r" % alasan_b)
print("       (a) %s" % alasan_a[:96])
print("       (b) %s" % alasan_b[:96])

# (c) incident with no symptoms on the root device -> the old sentence, which is correct there.
insC = _insiden_kosong(db14, r1_14, [])
rb_c, alasan_c = A.pilih_runbook(db14, insC, {})
benar("tanpa gejala apa pun -> tetap tidak ada usulan", rb_c is None,
      "-> %r" % rb_c)
benar("dan alasannya BUKAN 'sudah pulih'",
      "pulih" not in (alasan_c or "").lower(), "-> %r" % alasan_c)
print("       (c) %s" % alasan_c[:96])

# ===========================================================================
print("\n15. NARASI tidak boleh mengulang klaim 'pola baru' yang kosong")
# `pola_log.ringkas()` reports when the whole syslog history is younger than its
# window (which makes every pattern count as "never seen"). `agen_soc` must carry
# that note through: the narrative also goes into the AI prompt, and a model told
# five patterns are new would build a story on an empty foundation.
tri15 = {"riwayat": "Pola ini BELUM PERNAH terjadi dalam 30 hari terakhir."}
pola5 = [{"jumlah": 1, "templat": "x"}] * 5

# (a) history still young -> the sentence must reduce confidence
n_muda = A.narasi_templat(db, ins, tri15, {
    "insiden_id": ins.id, "pola_baru": pola5,
    "pola_riwayat_muda": True, "pola_riwayat_jam": 8.3})
benar("riwayat muda -> narasi menyebut umur riwayatnya",
      "8.3" in n_muda, "-> %r" % n_muda[-260:])
benar("dan TIDAK berkata 'BELUM PERNAH terlihat sebelumnya'",
      "BELUM PERNAH terlihat sebelumnya" not in n_muda,
      "-> %r" % n_muda[-260:])
benar("dan menyatakan ini belum bisa dijadikan petunjuk",
      "belum bisa dijadikan petunjuk" in n_muda, "-> %r" % n_muda[-200:])

# (b) long history -> the claim may stand in full
n_tua = A.narasi_templat(db, ins, tri15, {
    "insiden_id": ins.id, "pola_baru": pola5,
    "pola_riwayat_muda": False, "pola_riwayat_jam": 240.0})
benar("riwayat panjang -> klaimnya berdiri penuh",
      "BELUM PERNAH terlihat" in n_tua, "-> %r" % n_tua[-200:])
benar("dan tidak ada peringatan umur riwayat di situ",
      "belum bisa dijadikan petunjuk" not in n_tua, "-> %r" % n_tua[-200:])

# (c) the collected evidence really carries that note, otherwise the branches above never apply to real data
b15 = A.kumpulkan_bukti(db, ins, sekarang=SEKARANG)
benar("kumpulkan_bukti membawa 'pola_riwayat_muda'",
      "pola_riwayat_muda" in b15, "-> kunci: %r" % sorted(b15))
benar("dan membawa 'pola_riwayat_jam'", "pola_riwayat_jam" in b15)
print("       (a) %s" % n_muda[-150:])
print("       (b) %s" % n_tua[-100:])

print()
print("=" * 74)
print("%d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

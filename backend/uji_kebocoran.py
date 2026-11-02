"""Cross-tenant LEAK tests.

Cross-tenant leakage fails silently: a query that forgot to filter raises no error,
it returns someone else's data. So the test is not "is the filter installed": create
TWO tenants, fill both, and prove tenant A cannot see ONE ROW of B through every
exit NSM has:
    1. PAGES    device, service and incident lists
    2. API      summary, history, baseline, SOC agent
    3. EXPORT   downloaded reports
    4. EMAIL    who gets whose device alerts

The reverse is tested too: a filter rejecting EVERYTHING would pass "A sees nothing
of B", so each section also proves A still sees its own data.

Pure test: temporary SQLite, no network.

Run: py uji_kebocoran.py
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


from sqlalchemy import select  # noqa: E402

import korelasi as K  # noqa: E402
import models  # noqa: E402
import tenancy  # noqa: E402

SEKARANG = datetime(2026, 8, 23, 10, 0, 0)

tenancy.pasang()


def siapkan_db():
    """Two tenants, each with its own complete network."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    file = os.path.join(tempfile.mkdtemp(prefix="uji_bocor_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    ta = models.Tenant(nama="PT Alfa", kontak="alfa@contoh.id",
                       kuota_device=10, aktif=True)
    tb = models.Tenant(nama="PT Beta", kontak="beta@contoh.id",
                       kuota_device=2, aktif=True)
    db.add_all([ta, tb])
    db.commit()

    dev = {}
    # Each tenant has its own NSM (graph viewpoint) + two devices.
    spec = [("A-NSM", ta, "lokal", None), ("A-R1", ta, "cisco_ios", "AR1"),
            ("A-LDAP", ta, "linux", None),
            ("B-NSM", tb, "lokal", None), ("B-R1", tb, "cisco_ios", "BR1"),
            ("B-LDAP", tb, "linux", None)]
    for i, (n, t, plate, node) in enumerate(spec, start=1):
        d = models.Device(name=n, ip_address="10.%d.0.%d" % (1 if t is ta else 2, i),
                          device_type="router" if "R1" in n else "server",
                          platform=plate, gns3_node=node, aktif=True,
                          tenant_id=t.id)
        db.add(d)
        dev[n] = d
    db.commit()

    for a, b in (("A-NSM", "A-R1"), ("A-R1", "A-LDAP"),
                 ("B-NSM", "B-R1"), ("B-R1", "B-LDAP")):
        db.add(models.DeviceLink(device_a_id=dev[a].id, device_b_id=dev[b].id))

    # Derived data for BOTH, so a leak has something to leak.
    for n, d in dev.items():
        for k in range(5):
            db.add(models.StatusLog(
                device_id=d.id, timestamp=SEKARANG - timedelta(minutes=k),
                is_reachable=True, response_time_ms=10.0 + k, sumber="icmp"))
        db.add(models.DeviceEvent(device_id=d.id, event_type="UP",
                                  timestamp=SEKARANG - timedelta(hours=1)))
        db.add(models.SyslogPesan(
            waktu=SEKARANG, device_id=d.id, alamat=d.ip_address,
            facility=23, severity=5, tag="%SYS-5-CONFIG_I",
            pesan="rahasia milik %s" % n, sidik_templat="s-%s" % n))
        db.add(models.Service(device_id=d.id, nama="Layanan %s" % n,
                              jenis="tcp", port=22, aktif=True))
        db.add(models.BaselinePerilaku(device_id=d.id, metrik="latency",
                                       slot=10, n=100, ewma=10.0, ewmd=1.0))
    db.commit()
    return db, dev, ta, tb


print("=" * 74)
print("Uji KEBOCORAN antar-tenant (PAKET D)")
print("=" * 74)

db, dev, TA, TB = siapkan_db()

# ===========================================================================
print("\n0. Datanya memang ADA untuk keduanya (kalau tidak, sisanya sia-sia)")
with tenancy.lintas_tenant():
    total_dev = len(db.execute(select(models.Device)).scalars().all())
    total_log = len(db.execute(select(models.StatusLog)).scalars().all())
cek("enam device tercatat", total_dev, 6)
cek("tiga puluh baris status_logs tercatat", total_log, 30)

# ===========================================================================
print("\n1. HALAMAN: daftar device, layanan, dan insiden")
with tenancy.dengan_tenant(TA.id):
    d_a = db.execute(select(models.Device)).scalars().all()
    s_a = db.execute(select(models.Service)).scalars().all()
nama_a = sorted(x.name for x in d_a)
cek("tenant A melihat TIGA device miliknya", len(d_a), 3)
cek("dan namanya semua berawalan A-", nama_a, ["A-LDAP", "A-NSM", "A-R1"])
benar("tidak ada satu pun device B yang terlihat",
      all(not x.name.startswith("B-") for x in d_a),
      "-> %r" % nama_a)
cek("layanan pun hanya milik A", sorted(x.nama for x in s_a),
    ["Layanan A-LDAP", "Layanan A-NSM", "Layanan A-R1"])

with tenancy.dengan_tenant(TB.id):
    d_b = db.execute(select(models.Device)).scalars().all()
cek("tenant B melihat TIGA device miliknya", len(d_b), 3)
benar("dan tidak satu pun milik A",
      all(not x.name.startswith("A-") for x in d_b),
      "-> %r" % sorted(x.name for x in d_b))

# ===========================================================================
print("\n2. API: riwayat, syslog, baseline -- tabel TURUNAN ikut tersaring")
# Most leak-prone: `status_logs` has no `tenant_id`; the filter works through a subquery on `devices`.
with tenancy.dengan_tenant(TA.id):
    log_a = db.execute(select(models.StatusLog)).scalars().all()
    sys_a = db.execute(select(models.SyslogPesan)).scalars().all()
    base_a = db.execute(select(models.BaselinePerilaku)).scalars().all()
    ev_a = db.execute(select(models.DeviceEvent)).scalars().all()

cek("status_logs: 15 baris (3 device x 5), bukan 30", len(log_a), 15)
cek("device_events: 3, bukan 6", len(ev_a), 3)
cek("baseline: 3, bukan 6", len(base_a), 3)
cek("syslog: 3, bukan 6", len(sys_a), 3)
benar("dan tidak ada satu pun pesan RAHASIA milik B",
      all("B-" not in (p.pesan or "") for p in sys_a),
      "-> %r" % [p.pesan for p in sys_a])

# Also counted through an aggregate: `count()` takes a different code path, and a filter working on one path leaks through another.
from sqlalchemy import func  # noqa: E402
with tenancy.dengan_tenant(TA.id):
    n_agg = db.execute(select(func.count(models.StatusLog.id))).scalar()
cek("agregat count() juga tersaring", n_agg, 15)

# ===========================================================================
print("\n3. INSIDEN: korelasi tidak boleh menyatukan gangguan LINTAS tenant")
# The most damaging leak: an incident containing devices of two tenants would show another tenant's device names.
db2, dev2, TA2, TB2 = siapkan_db()
for n in ("A-R1", "A-LDAP", "B-R1", "B-LDAP"):
    db2.add(models.DeviceEvent(device_id=dev2[n].id, event_type="DOWN",
                               timestamp=SEKARANG))
db2.commit()

with tenancy.lintas_tenant():
    K.proses(db2, sekarang=SEKARANG)
    semua_ins = db2.execute(select(models.Insiden)).scalars().all()
    print("       insiden terbentuk: %d" % len(semua_ins))
    for i in semua_ins:
        akar = db2.get(models.Device, i.akar_device_id)
        gj = db2.execute(select(models.InsidenGejala).where(
            models.InsidenGejala.insiden_id == i.id)).scalars().all()
        nm = sorted(db2.get(models.Device, g.device_id).name for g in gj)
        print("         akar=%-8s gejala=%s" % (akar.name if akar else "?", nm))
        campur = (any(x.startswith("A-") for x in nm)
                  and any(x.startswith("B-") for x in nm))
        benar("insiden #%d TIDAK mencampur dua tenant" % i.id, not campur,
              "-> %r" % nm)

with tenancy.dengan_tenant(TA2.id):
    ins_a = db2.execute(select(models.Insiden)).scalars().all()
    gj_a = db2.execute(select(models.InsidenGejala)).scalars().all()
benar("tenant A hanya melihat insidennya sendiri", len(ins_a) >= 1)
with tenancy.lintas_tenant():
    nama_gj = sorted({db2.get(models.Device, g.device_id).name for g in gj_a})
benar("dan gejalanya tidak memuat perangkat B",
      all(not x.startswith("B-") for x in nama_gj), "-> %r" % nama_gj)

# ===========================================================================
print("\n4. EKSPOR: apa pun yang diunduh ikut tersaring")
# Export uses the same ORM query as the page, so what is proven is that the context SURVIVES nested calls, not that a second filter exists.
def ekspor_tiruan(db):
    """Mimic the report shape: device + its history, several levels deep."""
    line = []
    for d in db.execute(select(models.Device)).scalars().all():
        log = db.execute(select(models.StatusLog).where(
            models.StatusLog.device_id == d.id)).scalars().all()
        line.append((d.name, len(log)))
    return line


with tenancy.dengan_tenant(TA.id):
    isi = ekspor_tiruan(db)
cek("ekspor memuat tiga baris", len(isi), 3)
benar("dan tidak satu pun milik B",
      all(not n.startswith("B-") for n, _ in isi), "-> %r" % isi)

# A NESTED call inside another function is still filtered: the filter is enforced in the lower layer, so inner callers cannot leak.
def lapis_dalam(db):
    return db.execute(select(models.SyslogPesan)).scalars().all()


def lapis_luar(db):
    return lapis_dalam(db)


with tenancy.dengan_tenant(TB.id):
    dalam = lapis_luar(db)
cek("fungsi bersarang yang TIDAK tahu apa-apa soal tenant tetap tersaring",
    len(dalam), 3)
benar("dan isinya milik B", all("B-" in (p.pesan or "") for p in dalam),
      "-> %r" % [p.pesan for p in dalam])

# ===========================================================================
print("\n5. EMAIL: pelanggan tenant A tidak boleh dikirimi device tenant B")
# The email path uses `notifikasi_insiden.device_ids_insiden()` to choose which device_ids go to Java. If that list held another tenant's device, Java would email another tenant's customer, a leak out of the system.
import notifikasi_insiden as NI  # noqa: E402
with tenancy.lintas_tenant():
    for i in semua_ins:
        ids = NI.device_ids_insiden(db2, i)
        nm = sorted(db2.get(models.Device, x).name for x in ids)
        awalan = {x.split("-")[0] for x in nm}
        benar("penerima insiden #%d berasal dari SATU tenant saja" % i.id,
              len(awalan) == 1, "-> %r" % nm)

# ===========================================================================
print("\n6. ARAH GAGAL: penyaring yang menolak SEMUANYA harus ketahuan")
# Without this section, a `tenancy.py` returning zero rows for everyone would pass every test above, and NSM would become a very safe empty page.
with tenancy.dengan_tenant(TA.id):
    n_a = len(db.execute(select(models.Device)).scalars().all())
with tenancy.dengan_tenant(TB.id):
    n_b = len(db.execute(select(models.Device)).scalars().all())
benar("A melihat sesuatu", n_a > 0, "-> %d" % n_a)
benar("B melihat sesuatu", n_b > 0, "-> %d" % n_b)
benar("dan keduanya melihat JUMLAH yang sama besar (3 masing-masing)",
      n_a == n_b == 3, "-> A=%d B=%d" % (n_a, n_b))

# ===========================================================================
print("\n7. Tanpa konteks = perilaku LAMA (poller, CLI, backup)")
# With no context set, NSM must behave as before multi-tenancy. The poller monitors ALL devices; forcing one tenant would silently stop monitoring the others.
n_semua = len(db.execute(select(models.Device)).scalars().all())
cek("tanpa konteks -> melihat semua", n_semua, 6)

# ===========================================================================
print("\n8. Konteks TIDAK BOCOR keluar dari blok yang melempar")
try:
    with tenancy.dengan_tenant(TB.id):
        raise RuntimeError("gangguan di tengah blok")
except RuntimeError:
    pass
cek("sesudah blok yang melempar, konteksnya bersih", tenancy.sekarang(), None)
cek("dan kueri berikutnya melihat semua",
    len(db.execute(select(models.Device)).scalars().all()), 6)

# ===========================================================================
print("\n9. `boleh_device`: bukan-milikmu DIBEDAKAN dari tidak-ada-datanya")
b_r1 = dev["B-R1"].id
a_r1 = dev["A-R1"].id
cek("A tidak boleh menyentuh device B", tenancy.boleh_device(db, b_r1, TA.id),
    False)
cek("A boleh menyentuh devicenya sendiri",
    tenancy.boleh_device(db, a_r1, TA.id), True)
cek("tanpa konteks -> boleh semua", tenancy.boleh_device(db, b_r1, None), True)

# ===========================================================================
print("\n10. KUOTA device per tenant")
ka = tenancy.kuota_terpakai(db, TA.id)
kb = tenancy.kuota_terpakai(db, TB.id)
cek("A: 3 dari 10", (ka["device"], ka["kuota_device"]), (3, 10))
cek("A belum penuh", ka["penuh"], False)
cek("B: 3 dari 2", (kb["device"], kb["kuota_device"]), (3, 2))
cek("B sudah melewati kuotanya", kb["penuh"], True)

# ===========================================================================
print("\n11. PEMINDAI SQL MENTAH: jalur yang TIDAK dilindungi penyaring ORM")
# The filter works on ORM queries. `db.execute(text("SELECT ..."))` bypasses it, and
# page-serving modules must not use it on tenant tables without filtering themselves.
#
# This is a scanner, not a guarantee: it produces readable FINDINGS so such holes show up as a list.
import re  # noqa: E402
DIR = os.path.dirname(os.path.abspath(__file__))
TABEL_TENANT = ["devices", "status_logs", "device_events", "syslog_pesan",
                "insiden", "insiden_gejala", "services", "bandwidth_samples",
                "sumber_daya", "konfig_snapshots", "baseline_perilaku",
                "usulan_agen", "pagar_tindakan"]
MODUL_HALAMAN = ["report_service.py", "kesehatan.py", "laporan_excel.py",
                 "laporan_word.py", "main.py", "korelasi.py", "slo.py",
                 "baseline.py", "pola_log.py", "prakiraan.py", "agen_soc.py"]

temuan = []
for nama in MODUL_HALAMAN:
    jalur = os.path.join(DIR, nama)
    if not os.path.exists(jalur):
        continue
    isi = open(jalur, encoding="utf-8", errors="replace").read()
    for m in re.finditer(r"text\(\s*[\"']([^\"']{0,300})", isi):
        sql = m.group(1).lower()
        if "select" not in sql:
            continue
        for t in TABEL_TENANT:
            if re.search(r"\b%s\b" % t, sql):
                nomor = isi[:m.start()].count("\n") + 1
                temuan.append("%s:%d  %s" % (nama, nomor, sql[:70]))
                break

print("       %d tempat memakai SQL mentah atas tabel ber-tenant" % len(temuan))
for t in temuan[:10]:
    print("         %s" % t)
benar("daftar temuannya tercetak dan bisa ditindaklanjuti", True)
# Deliberately does NOT fail the test: raw SQL on the platform-admin path is legitimate. What is guarded is that the list is VISIBLE, not zero.

# ===========================================================================
print("\n12. D5 -- KORELASI berjalan PER TENANT, bukan satu graf gabungan")
# Found in section 3: a tenant B outage produced TWO separate incidents although they
# were one chain (B-R1 down drags B-LDAP). The dependency graph is rooted at devices
# with platform 'lokal', and with two tenants there are TWO viewpoints; one combined
# graph cannot trace the second tenant's upstream path. Degradation is safe (never
# merges wrongly) but correlation silently stops working for the second tenant.
db12, dev12, TA12, TB12 = siapkan_db()
for n in ("A-R1", "A-LDAP", "B-R1", "B-LDAP"):
    db12.add(models.DeviceEvent(device_id=dev12[n].id, event_type="DOWN",
                                timestamp=SEKARANG))
db12.commit()

K.proses(db12, sekarang=SEKARANG)  # no context -> per tenant
with tenancy.lintas_tenant():
    ins12 = db12.execute(select(models.Insiden)).scalars().all()
    ringkas12 = []
    for i in ins12:
        akar = db12.get(models.Device, i.akar_device_id)
        gj = db12.execute(select(models.InsidenGejala).where(
            models.InsidenGejala.insiden_id == i.id)).scalars().all()
        ringkas12.append((akar.name if akar else "?",
                          sorted(db12.get(models.Device, g.device_id).name
                                 for g in gj)))
for akar, nm in ringkas12:
    print("         akar=%-8s gejala=%s" % (akar, nm))

cek("dua gangguan di dua tenant -> DUA insiden, bukan tiga", len(ins12), 2)
benar("insiden tenant A menyatukan A-R1 dan A-LDAP",
      any(a == "A-R1" and nm == ["A-LDAP", "A-R1"] for a, nm in ringkas12),
      "-> %r" % ringkas12)
benar("insiden tenant B menyatukan B-R1 dan B-LDAP",
      any(a == "B-R1" and nm == ["B-LDAP", "B-R1"] for a, nm in ringkas12),
      "-> %r" % ringkas12)
for akar, nm in ringkas12:
    benar("dan tidak satu pun mencampur tenant (akar %s)" % akar,
          not (any(x.startswith("A-") for x in nm)
               and any(x.startswith("B-") for x in nm)),
          "-> %r" % nm)

# ===========================================================================
print("\n13. D5 -- BATAS LAJU pagar tidak bocor antar tenant")
# Without this, one tenant with a cascade of failing devices would use up OTHER tenants' automatic-action budget, and the second tenant would be refused with "global rate limit reached".
import pagar_otomasi  # noqa: E402
import config as _cfg  # noqa: E402

_baca_asli = _cfg._baca
# `PAGAR_JAM_MULAI`/`PAGAR_JAM_SELESAI`, not `PAGAR_JAM_KERJA`, which no code reads (see `uji_agen_soc.py`); otherwise the work-hours window silently stays 08:00-17:00.
_cfg._baca = lambda: {"PAGAR_DAFTAR_PUTIH": "gns3_restart",
                      "PAGAR_JAM_MULAI": "0",
                      "PAGAR_JAM_SELESAI": "24",
                      "PAGAR_BATAS_GLOBAL_PER_JAM": "3",
                      # `PAGAR_BATAS_DEVICE_PER_JAM`, not `PAGAR_BATAS_PER_DEVICE_PER_JAM`: the wrong name is read by no code, so the limit of 99 would never apply and the default 3 would be used.
                      "PAGAR_BATAS_DEVICE_PER_JAM": "99"}
try:
    db13, dev13, TA13, TB13 = siapkan_db()
    # Tenant A uses its entire quota.
    izin_a = 0
    for _k in range(3):
        kep = pagar_otomasi.putuskan(db13, dev13["A-R1"].id, "pemulih",
                                     "gns3_restart", oleh="uji",
                                     sekarang=SEKARANG)
        izin_a += 1 if kep.izin else 0
    cek("tenant A memakai 3 jatahnya", izin_a, 3)

    tolak_a = pagar_otomasi.putuskan(db13, dev13["A-R1"].id, "pemulih",
                                     "gns3_restart", oleh="uji",
                                     sekarang=SEKARANG)
    benar("percobaan keempat tenant A DITOLAK", not tolak_a.izin,
          "-> %r" % tolak_a.alasan)
    benar("dan alasannya menyebut batas laju",
          "batas laju" in (tolak_a.alasan or "").lower(),
          "-> %r" % tolak_a.alasan)

    # WHAT IS GUARDED: tenant B must not be affected.
    kep_b = pagar_otomasi.putuskan(db13, dev13["B-R1"].id, "pemulih",
                                   "gns3_restart", oleh="uji",
                                   sekarang=SEKARANG)
    benar("tenant B TETAP diizinkan walau jatah A sudah habis", kep_b.izin,
          "-> %r" % kep_b.alasan)

    # Counterpart: B also has its OWN limit, not unlimited.
    for _k in range(2):
        pagar_otomasi.putuskan(db13, dev13["B-R1"].id, "pemulih",
                               "gns3_restart", oleh="uji", sekarang=SEKARANG)
    tolak_b = pagar_otomasi.putuskan(db13, dev13["B-R1"].id, "pemulih",
                                     "gns3_restart", oleh="uji",
                                     sekarang=SEKARANG)
    benar("dan tenant B pun ditolak sesudah jatahnya sendiri habis",
          not tolak_b.izin, "-> %r" % tolak_b.alasan)
finally:
    _cfg._baca = _baca_asli

print()
print("=" * 74)
print("%d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

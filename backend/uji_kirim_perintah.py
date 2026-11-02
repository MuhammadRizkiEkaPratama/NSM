"""Test of the configuration-command send path.

No device is contacted in this file, and that is itself under test: `kirim()`
defaults to `sungguhan=False`, and the whole flow must complete without opening
a connection. A safe default means a forgotten argument does nothing.

Covered, most critical first:
  1. correct order: `reload in` first, then the command
  2. guards reject: identity, interval, platform, catalog, credentials
  3. guards do not reject valid requests
  4. safe mode is really safe
  5. `batalkan` deliberately sends nothing
  6. `write memory` is never sent automatically

Order comes first because it cannot be fixed afterward: a safety net installed
after a connection-cutting command is useless.
"""
import os
import re
import sys
import tempfile

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

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


def ditolak_karena(nama, fungsi, kata):
    """The function must raise Ditolak, and the reason must mention `kata`."""
    global lolos, gagal
    try:
        fungsi()
    except kp.Ditolak as e:
        if kata.lower() in str(e).lower():
            lolos += 1
            print("  LOLOS  %s" % nama)
        else:
            gagal += 1
            print("  GAGAL  %s -> ditolak, tetapi alasannya %r" % (nama, str(e)))
        return
    except Exception as e:
        gagal += 1
        print("  GAGAL  %s -> melempar %s, bukan Ditolak: %s"
              % (nama, type(e).__name__, e))
        return
    gagal += 1
    print("  GAGAL  %s -> TIDAK ditolak sama sekali" % nama)


import kirim_perintah as kp
import identitas as idn


KONFIG = """hostname R1
!
interface FastEthernet0/0
 ip address 192.168.56.60 255.255.255.0
 no shutdown
!
interface FastEthernet0/1
 shutdown
!
end
"""


def siapkan(vonis=idn.SAMA, aktif=True, platform="cisco_ios", kredensial=True,
            gns3_node=None):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    file = os.path.join(tempfile.mkdtemp(prefix="uji_kirim_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    d = models.Device(name="Router Uji", ip_address="192.168.56.60",
                      device_type="router", platform=platform, aktif=aktif,
                      identitas_vonis=vonis, gns3_node=gns3_node)
    if kredensial:
        d.username = "nsm"
        d.password = "rahasia"
    db.add(d)
    db.commit()
    db.add(models.KonfigSnapshot(device_id=d.id, teks=KONFIG, sidik="a" * 8))
    db.commit()
    return db, d


NILAI = {"interface": "FastEthernet0/0", "teks": "uji jalur kirim"}


# ---------------------------------------------------------------------------
print("\n1. URUTAN: JARING PENGAMAN DIPASANG SEBELUM PERINTAHNYA")
print("   (yang dipasang sesudah tidak berguna untuk perintah yang memutus")
print("    sambungan: begitu putus, tidak ada lagi jalan memasang apa pun)")

db, d = siapkan()
r = kp.kirim(db, d.id, "iface_keterangan", NILAI)
urutan = r["urutan"]
for b in urutan:
    print("        %s" % b)

i_reload = next((i for i, b in enumerate(urutan) if b.startswith("reload in")), None)
i_conf = next((i for i, b in enumerate(urutan) if b.startswith("configure terminal")), None)
benar("ada `reload in` di rencana", i_reload is not None)
benar("ada `configure terminal` di rencana", i_conf is not None)
benar("`reload in` MENDAHULUI perintahnya",
      i_reload is not None and i_conf is not None and i_reload < i_conf,
      "-> reload di posisi %s, configure di posisi %s" % (i_reload, i_conf))
benar("lama reload ikut disebut, dan angkanya yang berlaku",
      str(kp.MENIT_RELOAD) in urutan[i_reload],
      "-> %r sedangkan MENIT_RELOAD=%s" % (urutan[i_reload], kp.MENIT_RELOAD))
# Five minutes proved too short in a real test: the operator chose to keep the
# change, but `reload cancel` arrived after R1 had already shut down. The deadline
# must allow time for a human to read and decide.
benar("tenggatnya tidak lagi sependek 5 menit", kp.MENIT_RELOAD >= 10,
      "-> %s menit" % kp.MENIT_RELOAD)
benar("perintahnya utuh di rencana",
      any("description uji jalur kirim" in b for b in urutan),
      "-> %r" % urutan)

# ---------------------------------------------------------------------------
print("\n2. MODE AMAN BENAR-BENAR AMAN")

benar("bawaannya TIDAK mengirim", r["terkirim"] is False)
benar("alasannya disebut", "sungguhan=False" in (r.get("kenapa") or ""))
benar("tidak ada keluaran perangkat", "keluaran" not in r)

# If `sungguhan` defaulted to True, running this suite would contact a real device.
import inspect
tanda = inspect.signature(kp.kirim).parameters["sungguhan"]
benar("nilai bawaan parameter `sungguhan` adalah False", tanda.default is False,
      "-> uji apa pun akan menyentuh perangkat sungguhan")
tanda2 = inspect.signature(kp.putuskan).parameters["sungguhan"]
benar("putuskan() juga bawaannya False", tanda2.default is False)
tanda3 = inspect.signature(kp.simpan_permanen).parameters["sungguhan"]
benar("simpan_permanen() juga bawaannya False", tanda3.default is False)

# ---------------------------------------------------------------------------
print("\n3. PENJAGA MENOLAK, DAN ALASANNYA DISEBUT")

db2, d2 = siapkan(vonis=idn.BERTENTANGAN)
ditolak_karena("identitas bertentangan ditolak",
               lambda: kp.kirim(db2, d2.id, "iface_keterangan", NILAI), "identitas")

db3, d3 = siapkan(vonis=idn.KEMUNGKINAN_SAMA)
ditolak_karena("identitas cuma 'kemungkinan sama' ditolak",
               lambda: kp.kirim(db3, d3.id, "iface_keterangan", NILAI), "identitas")

db4, d4 = siapkan(vonis=idn.BELUM_DIKETAHUI)
ditolak_karena("identitas belum dikumpulkan ditolak",
               lambda: kp.kirim(db4, d4.id, "iface_keterangan", NILAI), "identitas")

db5, d5 = siapkan(aktif=False)
db5.query(type(d5)).filter_by(id=d5.id).update({"jeda_alasan": "sedang di luar lokasi"})
db5.commit()
ditolak_karena("perangkat yang DIJEDA ditolak",
               lambda: kp.kirim(db5, d5.id, "iface_keterangan", NILAI), "dijeda")

db6, d6 = siapkan(platform="linux")
ditolak_karena("platform tanpa jalur kirim ditolak",
               lambda: kp.kirim(db6, d6.id, "iface_keterangan", NILAI), "platform")

db7, d7 = siapkan(kredensial=False)
ditolak_karena("perangkat tanpa kredensial ditolak",
               lambda: kp.kirim(db7, d7.id, "iface_keterangan", NILAI), "kredensial")

ditolak_karena("perintah di luar katalog ditolak",
               lambda: kp.kirim(db, d.id, "hapus_semua_config", NILAI), "tidak tersedia")

ditolak_karena("perangkat yang tidak ada ditolak",
               lambda: kp.kirim(db, 9999, "iface_keterangan", NILAI), "tidak ada")

ditolak_karena("interface yang tidak ada di perangkat ditolak",
               lambda: kp.kirim(db, d.id, "iface_keterangan",
                                {"interface": "FastEthernet9/9", "teks": "x"}),
               "parameter")

# ---------------------------------------------------------------------------
print("\n4. PENJAGA TIDAK MENOLAK YANG BENAR")
print("   (penjaga yang menolak semuanya sama tidak bergunanya dengan yang")
print("    meloloskan semuanya; bedanya yang pertama akan dimatikan orang)")

db8, d8 = siapkan(vonis=idn.SAMA)
r8 = kp.kirim(db8, d8.id, "iface_keterangan", NILAI)
benar("perangkat yang memenuhi semua syarat diloloskan", r8.get("urutan") is not None)
benar("dan rencananya lengkap", len(r8["urutan"]) >= 4)

r9 = kp.kirim(db8, d8.id, "iface_mati", {"interface": "FastEthernet0/1"})
benar("perintah yang MEMUTUS tetap boleh disusun", r9.get("urutan") is not None)
benar("dan ditandai memutus", r9.get("memutus") is True)
benar("jaring pengamannya tetap dipasang lebih dulu",
      r9["urutan"][0].startswith("reload in"))

# ---------------------------------------------------------------------------
print("\n5. `BATALKAN` SENGAJA TIDAK MENGIRIM APA PUN")
print("   (perangkat sudah memegang jawabannya sendiri: reload in masih")
print("    berjalan, startup-config masih berisi keadaan sebelum perubahan)")

b = kp.putuskan(db8, d8.id, "batalkan")
benar("batalkan tidak mengirim satu perintah pun", b["dikirim"] == [],
      "-> %r" % b["dikirim"])
benar("alasannya dijelaskan, bukan didiamkan",
      "reload" in b["hasil"].lower() and len(b["hasil"]) > 80)

p = kp.putuskan(db8, d8.id, "pertahankan")
benar("pertahankan mengirim `reload cancel`", p["dikirim"] == ["reload cancel"],
      "-> %r" % p["dikirim"])
benar("pertahankan pun tidak mengirim di mode aman", p["terkirim"] is False)

ditolak_karena("tindakan yang tidak dikenal ditolak",
               lambda: kp.putuskan(db8, d8.id, "hapus_semuanya"), "tidak dikenal")

# ---------------------------------------------------------------------------
print("\n6. MENYIMPAN PERMANEN TIDAK PERNAH IKUT OTOMATIS")
print("   (selama belum disimpan, menyalakan ulang masih membatalkan; itu")
print("    jalan pulang yang tidak menuntut ketelitian siapa pun)")

isi = open(os.path.join(DIR, "kirim_perintah.py"), encoding="utf-8").read()
tanpa_komentar = re.sub(r"#[^\n]*", " ", re.sub(r'""".*?"""', " ", isi, flags=re.S))

badan_kirim = tanpa_komentar[tanpa_komentar.find("def kirim("):]
badan_kirim = badan_kirim[:badan_kirim.find("\ndef ")]
benar("kirim() tidak memanggil simpan_permanen()",
      "simpan_permanen" not in badan_kirim)
benar("kirim() tidak mengirim `write`",
      "write memory" not in badan_kirim and "wr mem" not in badan_kirim)

badan_putus = tanpa_komentar[tanpa_komentar.find("def putuskan("):]
badan_putus = badan_putus[:badan_putus.find("\ndef ")]
benar("putuskan() tidak memanggil simpan_permanen()",
      "simpan_permanen" not in badan_putus)
benar("putuskan() tidak mengirim `write`", "write memory" not in badan_putus)

s = kp.simpan_permanen(db8, d8.id)
benar("simpan_permanen ada dan bawaannya tidak mengirim", s["terkirim"] is False)
benar("yang akan dikirim disebut apa adanya", s["dikirim"] == ["write memory"])

# ---------------------------------------------------------------------------
print("\n7. PROMPT `Save?` SAAT RELOAD WAJIB DIJAWAB `no`")
print("   (menjawab `yes` menyimpan konfigurasi yang mau dibatalkan ke")
print("    startup-config — jaring pengamannya berubah jadi alat yang")
print("    mempermanenkan kesalahan)")

jawab = tanpa_komentar[tanpa_komentar.find("def _jawab_prompt("):]
jawab = jawab[:jawab.find("\ndef ")]
benar("prompt `save?` dikenali", "save?" in jawab.lower())
benar("dijawab dengan `no`", re.search(r'send_command_timing\(\s*["\']no["\']\s*\)',
                                       jawab) is not None,
      "-> %r" % jawab[:300])
benar("TIDAK ada tempat yang menjawab `yes`",
      not re.search(r'send_command_timing\(\s*["\']yes["\']', tanpa_komentar))

# ---------------------------------------------------------------------------
print("\n8. KOLOM INTEGER TIDAK DIBANDINGKAN DENGAN `is False`")
print("   (cacat nyata 8 Agu 2026: `aktif` bertipe INTEGER, nilainya 0/1, dan")
print("    `0 is False` di Python adalah False — penjaga 'perangkat dijeda'")
print("    tidak pernah menyala sekali pun)")

import models
for kolom in ("aktif", "penting"):
    jenis = str(models.Device.__table__.c[kolom].type).upper()
    if "INT" not in jenis:
        continue
    for file in ("kirim_perintah.py", "identitas.py", "poller.py", "main.py"):
        jalur = os.path.join(DIR, file)
        if not os.path.exists(jalur):
            continue
        teks = open(jalur, encoding="utf-8").read()
        teks = re.sub(r"#[^\n]*", " ", re.sub(r'""".*?"""', " ", teks, flags=re.S))
        pola = re.compile(r"\.%s\s+is\s+(False|True)\b" % kolom)
        benar("%s tidak membandingkan .%s dengan `is False/True`"
              % (file, kolom), pola.search(teks) is None,
              "-> kolomnya %s; pakai `== 0` seperti seluruh poller" % jenis)

# ---------------------------------------------------------------------------
print("\n8b. JARING PENGAMAN DILEPAS BEGITU ANCAMANNYA LEWAT")
print("    (cacat nyata 8 Agu 2026: satu pengatur waktu dipakai untuk DUA")
print("     tugas berbeda — menyelamatkan sambungan yang putus, dan memberi")
print("     manusia tenggat memutuskan. Yang pertama selesai dalam hitungan")
print("     detik; yang kedua tidak perlu tenggat sama sekali)")

tanda_lepas = inspect.signature(kp.kirim).parameters["lepas_setelah_terbukti"]
benar("bawaannya melepas jaring sesudah terbukti", tanda_lepas.default is True)

badan_k = tanpa_komentar[tanpa_komentar.find("def kirim("):]
badan_k = badan_k[:badan_k.find("\ndef ")]
# The reload safety-net commands (`reload in N`, `show reload`, `reload cancel`)
# are read from `perangkat/<platform>.yaml` (`tulis.jaring_pengaman`). This test
# checks that the confirm step comes after the proof step, not that specific
# strings appear.
i_terbukti = badan_k.find("masih menjawab sesudah perubahan")
i_lepas = badan_k.find('net["kukuhkan"]')
benar("dilepas SESUDAH perangkat terbukti menjawab, bukan sebelum",
      i_terbukti != -1 and i_lepas != -1 and i_terbukti < i_lepas,
      "-> bukti di %s, lepas di %s" % (i_terbukti, i_lepas))
benar("pelepasannya juga dibuktikan, bukan diandaikan",
      "penanda_lepas" in badan_k)

# ---------------------------------------------------------------------------
print("\n9. JARING PENGAMAN DIBUKTIKAN TERPASANG, BUKAN DIANDAIKAN")
print("   (perintah reload bisa gagal diam-diam; kalau itu terjadi dan kita")
print("    lanjut, perintahnya berjalan TANPA pengaman — persis keadaan yang")
print("    seluruh rancangan ini ada untuk mencegahnya)")

badan_kirim2 = tanpa_komentar[tanpa_komentar.find("def kirim("):]
badan_kirim2 = badan_kirim2[:badan_kirim2.find("\ndef ")]
benar("perintah pembuktian dipakai sebagai bukti",
      'net["bukti"]' in badan_kirim2)
i_bukti = badan_kirim2.find('net["bukti"]')
i_config = badan_kirim2.find("send_config_set")
benar("buktinya diperiksa SEBELUM perintah dikirim",
      i_bukti != -1 and i_config != -1 and i_bukti < i_config,
      "-> bukti di %s, kirim di %s" % (i_bukti, i_config))
benar("gagal membuktikan = berhenti, bukan lanjut",
      "raise Ditolak" in badan_kirim2[i_bukti:i_config],
      "-> tidak ada penolakan di antara pembuktian dan pengiriman")

# ---------------------------------------------------------------------------
print("\n10. CEGAH KIRIM PERINTAH MEMUTUS KE INTERFACE MANAJEMEN SENDIRI")
print("    (temuan nyata: enam percobaan iface_mati/iface_hidup sejak 13")
print("     Agustus 2026 semuanya gagal terkirim, ke dua perangkat yang")
print("     NSM sendiri jangkau lewat alamat yang sama -- docs/POSTMORTEM-R1.md")
print("     §5a. Router uji ini beralamat 192.168.56.60, persis di")
print("     FastEthernet0/0 pada KONFIG di atas.)")

ditolak_karena(
    "iface_mati ke interface sendiri DITOLAK",
    lambda: kp.kirim(db, d.id, "iface_mati", {"interface": "FastEthernet0/0"}),
    "sendiri")

r10 = kp.kirim(db, d.id, "iface_mati", {"interface": "FastEthernet0/1"})
benar("iface_mati ke interface LAIN tetap boleh disusun",
      r10.get("urutan") is not None, "-> %r" % r10)

r11 = kp.kirim(db, d.id, "iface_hidup", {"interface": "FastEthernet0/0"})
benar("iface_hidup (memutus=False) ke interface sendiri TIDAK diblokir "
      "pengaman ini -- cuma perintah MEMUTUS yang diperiksa",
      r11.get("urutan") is not None, "-> %r" % r11)

r12 = kp.kirim(db, d.id, "iface_keterangan",
               {"interface": "FastEthernet0/0", "teks": "x"})
benar("iface_keterangan (memutus=False) ke interface sendiri TIDAK diblokir",
      r12.get("urutan") is not None, "-> %r" % r12)

# ---------------------------------------------------------------------------
print("\n11. NODE GNS3: TIDAK PERNAH `reload in N`, PEMULIHAN LEWAT API")
print("    (di GNS3/Dynamips, `reload` MEMATIKAN mesin emulasinya secara")
print("     PERMANEN, bukan reboot -- insiden R1 mati, 14 Agustus 2026)")

dbg, dg = siapkan(gns3_node="R1")
rg = kp.kirim(dbg, dg.id, "iface_keterangan", NILAI)
benar("TIDAK ADA `reload in` di rencana node GNS3",
      not any(b.startswith("reload in") for b in rg["urutan"]),
      "-> %r" % rg["urutan"])
benar("`configure terminal` tetap ada", "configure terminal" in rg["urutan"])
benar("menit_reload dilaporkan None (tidak relevan)",
      rg.get("menit_reload") is None)
benar("catatan_jaring menyebut nama node-nya",
      "R1" in (rg.get("catatan_jaring") or ""), "-> %r" % rg.get("catatan_jaring"))

r_fisik = kp.kirim(db, d.id, "iface_keterangan", NILAI)
benar("perangkat FISIK (gns3_node=None) TETAP memakai reload in N seperti semula",
      any(b.startswith("reload in") for b in r_fisik["urutan"]))

badan_kirim3 = tanpa_komentar[tanpa_komentar.find("def kirim("):]
badan_kirim3 = badan_kirim3[:badan_kirim3.find("\ndef ")]
benar("pemulihan GNS3 di blok except DIJAGA is_gns3 DAN memutus "
      "-- tidak dipicu untuk perintah yang tidak memutus sambungan",
      "if is_gns3 and pratinjau[\"memutus\"]:" in badan_kirim3
      or "if is_gns3 and pratinjau['memutus']:" in badan_kirim3,
      "-> penjaga pemicu pemulihan tidak ditemukan persis seperti diharapkan")
benar("pemulihan GNS3 memanggil gns3_pemulihan.pulihkan(d.gns3_node)",
      "gns3_pemulihan.pulihkan(d.gns3_node)" in badan_kirim3)

# ---------------------------------------------------------------------------
print("\n12. putuskan(): NODE GNS3 TIDAK PERNAH MENGIRIM `reload` MENTAH")
print("    (celah TERPISAH dari kirim(): `batalkan_sekarang` lama mengirim")
print("     `reload` lewat SSH tanpa syarat apa pun -- perintah IOS yang")
print("     SAMA PERSIS yang mematikan R1 permanen di Dynamips)")

p_tahan = kp.putuskan(dbg, dg.id, "pertahankan", sungguhan=False)
benar("`pertahankan` untuk node GNS3 TIDAK mengirim `reload cancel`",
      "reload cancel" not in p_tahan.get("dikirim", []),
      "-> %r" % p_tahan.get("dikirim"))

p_batal = kp.putuskan(dbg, dg.id, "batalkan_sekarang", sungguhan=False)
benar("`batalkan_sekarang` untuk node GNS3 TIDAK mengirim `reload` mentah",
      "reload" not in p_batal.get("dikirim", []),
      "-> %r" % p_batal.get("dikirim"))
benar("melainkan menyebut API GNS3",
      any("API GNS3" in str(x) or "gns3" in str(x).lower()
          for x in p_batal.get("dikirim", [])),
      "-> %r" % p_batal.get("dikirim"))

p_batal_fisik = kp.putuskan(db, d.id, "batalkan_sekarang", sungguhan=False)
benar("perangkat FISIK tetap memakai `reload` mentah seperti semula",
      "reload" in p_batal_fisik.get("dikirim", []),
      "-> %r" % p_batal_fisik.get("dikirim"))

# Structural proof: the `is_gns3` branch in the real (`sungguhan=True`) path must
# `return` before `_sambung(d)` is called, so GNS3 nodes never reach the raw
# `_jawab_prompt(conn, "reload")` line. Text position serves as evidence of order.
badan_putus2 = tanpa_komentar[tanpa_komentar.find("def putuskan("):]
badan_putus2 = badan_putus2[:badan_putus2.find("\ndef simpan_permanen")]
i_is_gns3 = badan_putus2.find("if is_gns3:")
i_sambung = badan_putus2.find("conn = _sambung(d)")
i_reload_mentah = badan_putus2.find('_jawab_prompt(conn, "reload")')
benar("cabang is_gns3 diperiksa SEBELUM _sambung(d) dipanggil",
      i_is_gns3 != -1 and i_sambung != -1 and i_is_gns3 < i_sambung,
      "-> is_gns3 di %s, _sambung di %s" % (i_is_gns3, i_sambung))
benar("baris `reload` mentah ADA SESUDAH _sambung(d) "
      "-- hanya terjangkau lewat jalur non-GNS3",
      i_reload_mentah != -1 and i_sambung != -1 and i_sambung < i_reload_mentah,
      "-> _sambung di %s, reload mentah di %s" % (i_sambung, i_reload_mentah))
benar("pemulihan batalkan_sekarang GNS3 memanggil gns3_pemulihan.pulihkan",
      "gns3_pemulihan.pulihkan(d.gns3_node)" in badan_putus2)

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

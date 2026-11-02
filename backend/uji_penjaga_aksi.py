"""Test of guard execution (Stage 3): `penjaga_aksi.py`.

This path really WRITES to device firewalls by delegating to `ubah_firewall`.
`uji_ubah_firewall.py` covers the lower layer; this covers the layer above it:

  1. The broad allowlist (`daftar_dilindungi`) is checked AT THE POINT OF
     EXECUTION, not just trusted from the caller.
  2. `blokir()` is idempotent: an already-banned IP is not written twice.
  3. `buka_blokir()` never lets a technical error (e.g. unreachable SSH) escape
     as a raw exception; it returns `{"ok": False, ...}`.
  4. `kedaluwarsa()` processes ALL expired bans in a round; one ban whose device
     cannot be reached must not abort the others.

Items 3 and 4 are regressions for a defect where `ubah_firewall.buka()` could
raise a non-`Ditolak` exception (e.g. SSH error from `_sambung()`, outside its
try/finally) that propagated into the `kedaluwarsa()` loop
(docs/design/AUTO-BAN.md).

Runs on a TEMPORARY database. No real SSH: the executor is replaced via `_exec`.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

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


def sama(nama, dapat, harap):
    benar(nama, dapat == harap, "-> dapat %r, harusnya %r" % (dapat, harap))


def siapkan():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    file = os.path.join(tempfile.mkdtemp(prefix="uji_penjagaaksi_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    server = models.Device(id=1, name="Server Sehat", ip_address="192.168.56.200",
                           device_type="server", platform="linux", aktif=1,
                           username="nsmro", ssh_key_path="/x/kunci")
    # Router (cisco_ios) for ACL block tests: its platform makes `kedaluwarsa()`/`buka_blokir_apa_pun()` choose the ACL path, not ufw.
    router = models.Device(id=2, name="Router Lokasi B", ip_address="192.168.20.1",
                           device_type="router", platform="cisco_ios", aktif=1,
                           username="nsm", password="x")
    db.add_all([server, router])
    db.commit()
    return db


print("=" * 74)
print("UJI EKSEKUSI PENJAGAAN (penjaga_aksi.py)")
print("=" * 74)

db = siapkan()
import penjaga_aksi as pa
import ubah_firewall as uf
from models import BanAktif, Device


def _exec_sukses(db, device_id, ip, menit, alasan, oleh, sungguhan=True):
    return {"hasil": "BERHASIL", "sungguhan": True, "bukti": "ok",
            "catatan": "diblokir (tiruan)"}


def _exec_ditolak_server(db, device_id, ip, menit, alasan, oleh, sungguhan=True):
    return {"hasil": "DITOLAK_SERVER", "catatan": "server menolak (tiruan)",
            "bukti": "tiruan"}


def _exec_ditolak_python(db, device_id, ip, menit, alasan, oleh, sungguhan=True):
    raise uf.Ditolak("ditolak lapis ubah_firewall (tiruan)")


def _exec_buka_sukses(db, device_id, ip, oleh, sungguhan=True):
    return {"hasil": "BERHASIL", "bukti": "dibuka (tiruan)"}


def _exec_buka_galat_ssh(db, device_id, ip, oleh, sungguhan=True):
    # NOT Denied: mimics a technical error (SSH unreachable).
    raise ConnectionError("timed out (tiruan)")


# ---------------------------------------------------------------------------
print("\n1. ALLOWLIST DIPERIKSA DI TITIK EKSEKUSI, SEBELUM DELEGASI")
print("   (bukan cuma dipercayakan ke pemanggil.)")

for ip, ket in (("192.168.56.200", "alamat device terdaftar"),
                ("192.168.56.1", "alamat NSM sendiri")):
    try:
        pa.blokir(db, ip, device_id=1, alasan="uji", oleh="rina",
                 _exec=_exec_sukses)
        gagal += 1
        print("  GAGAL  %-28s ditolak -> TIDAK DITOLAK (%s)" % (ip, ket))
    except pa.DitolakPengaman as e:
        lolos += 1
        print("  LOLOS  %-28s ditolak (%s)" % (ip, ket))

benar("tidak ada BanAktif tertulis dari percobaan yang ditolak",
      db.query(BanAktif).count() == 0,
      "-> %d baris" % db.query(BanAktif).count())

benar("alamat tidak sah ditolak juga",
      True,
      "")
for buruk in ("bukan-ip", "300.1.1.1", "", None):
    try:
        pa.blokir(db, buruk, device_id=1, alasan="uji", oleh="rina",
                 _exec=_exec_sukses)
        gagal += 1
        print("  GAGAL  alamat %r -> TIDAK DITOLAK" % (buruk,))
    except pa.DitolakPengaman:
        lolos += 1
        print("  LOLOS  alamat %r ditolak" % (buruk,))

# ---------------------------------------------------------------------------
print("\n2. BLOKIR SUNGGUHAN (delegasi ke ubah_firewall via _exec tiruan)")

r = pa.blokir(db, "10.20.30.40", device_id=1, alasan="uji tembus",
             pola="tembus", oleh="rina", _exec=_exec_sukses,
             _notif=lambda *a, **k: None)
sama("berhasil -> ok True", r.get("ok"), True)
benar("ban_id tertulis", r.get("ban_id") is not None)
benar("kedaluwarsa tertulis (ban SEMENTARA)", r.get("kedaluwarsa") is not None)

ban = db.query(BanAktif).filter(BanAktif.ip == "10.20.30.40").first()
benar("baris BanAktif benar-benar tersimpan", ban is not None)
sama("aktif=1", ban.aktif, 1)
sama("pola tersimpan", ban.pola, "tembus")

# ---------------------------------------------------------------------------
print("\n3. IDEMPOTEN — IP yang sudah diban tidak ditulis dua kali")

sebelum = db.query(BanAktif).filter(BanAktif.ip == "10.20.30.40").count()
r2 = pa.blokir(db, "10.20.30.40", device_id=1, alasan="uji lagi",
              pola="gigih", oleh="rina", _exec=_exec_sukses)
sesudah = db.query(BanAktif).filter(BanAktif.ip == "10.20.30.40").count()
sama("baris tidak bertambah", sesudah, sebelum)
sama("jawabannya menandai sudah_diban", r2.get("sudah_diban"), True)

# ---------------------------------------------------------------------------
print("\n4. DEVICE TARGET TIDAK DIKETAHUI DITOLAK RAPI")

r3 = pa.blokir(db, "10.20.30.41", device_id=None, alasan="uji", oleh="rina",
              _exec=_exec_sukses)
sama("ok False", r3.get("ok"), False)
benar("tidak ada BanAktif untuk IP ini",
      db.query(BanAktif).filter(BanAktif.ip == "10.20.30.41").count() == 0)

# ---------------------------------------------------------------------------
print("\n5. PENOLAKAN DARI LAPIS ubah_firewall DITERUSKAN SEBAGAI DitolakPengaman")

try:
    pa.blokir(db, "10.20.30.42", device_id=1, alasan="uji", oleh="rina",
             _exec=_exec_ditolak_python)
    gagal += 1
    print("  GAGAL  penolakan ubah_firewall -> TIDAK DITERUSKAN")
except pa.DitolakPengaman as e:
    lolos += 1
    print("  LOLOS  penolakan ubah_firewall diteruskan sebagai DitolakPengaman")
    benar("pesannya menyebut sebab aslinya",
          "ditolak lapis ubah_firewall" in str(e), "-> %r" % str(e))

# ---------------------------------------------------------------------------
print("\n6. EKSEKUSI GAGAL (server menolak) -> jawaban rapi, BUKAN ban tertulis")

r4 = pa.blokir(db, "10.20.30.43", device_id=1, alasan="uji", oleh="rina",
              _exec=_exec_ditolak_server)
sama("ok False", r4.get("ok"), False)
benar("tidak ada BanAktif untuk IP yang gagal ditulis",
      db.query(BanAktif).filter(BanAktif.ip == "10.20.30.43").count() == 0)

# ---------------------------------------------------------------------------
print("\n6b. GALAT TEKNIS SAAT BLOKIR (BUKAN Ditolak) TIDAK BOLEH NAIK MENTAH")
print("    (ditemukan 18 Agustus lewat uji live berulang §E3: galat SSH")
print("     transien nyata membuat blokir() melempar exception mentah dan")
print("     endpoint Python membalas 500 — celah yang sama dengan §D2.3,")
print("     tapi di jalur blokir(), bukan buka_blokir(). Untuk poll_auto_ban")
print("     (§E3), ini berarti satu galat SSH sesaat menjatuhkan SELURUH")
print("     putaran, termasuk kandidat lain yang device-nya sehat.)")


def _exec_blokir_galat_ssh(db, device_id, ip, menit, alasan, oleh, sungguhan=True):
    raise ConnectionError("Error reading SSH protocol banner (tiruan)")


try:
    r4b = pa.blokir(db, "10.20.30.44", device_id=1, alasan="uji", oleh="rina",
                    _exec=_exec_blokir_galat_ssh, _notif=lambda *a, **k: None)
    lolos += 1
    print("  LOLOS  blokir() tidak crash walau _exec melempar galat teknis")
    sama("ok False", r4b.get("ok"), False)
    benar("pesan galat disebutkan", "ssh protocol banner" in
          (r4b.get("error") or "").lower(), "-> %r" % r4b.get("error"))
except Exception as e:
    gagal += 1
    print("  GAGAL  blokir() CRASH mentah: %r (INI YANG DITEMUKAN LIVE)" % e)

benar("tidak ada BanAktif untuk IP yang gagal karena galat teknis",
      db.query(BanAktif).filter(BanAktif.ip == "10.20.30.44").count() == 0)


def _exec_acl_blokir_galat_ssh(db, device_id, ip, menit, alasan, oleh,
                               sungguhan=True):
    raise ConnectionError("Error reading SSH protocol banner (tiruan)")


try:
    r4c = pa.block_acl(db, "10.20.30.45", device_id=2, alasan="uji",
                        oleh="rina", _exec=_exec_acl_blokir_galat_ssh,
                        _notif=lambda *a, **k: None)
    lolos += 1
    print("  LOLOS  blokir_acl() juga tidak crash walau _exec melempar galat teknis")
    sama("ok False", r4c.get("ok"), False)
except Exception as e:
    gagal += 1
    print("  GAGAL  blokir_acl() CRASH mentah: %r" % e)

# ---------------------------------------------------------------------------
print("\n6c. BERHASIL_TANPA_BUKTI DIPERLAKUKAN SAMA DENGAN BERHASIL")
print("    (ditemukan 18 Agustus lewat uji live §E3: perubahan sungguhan")
print("     SUDAH terkirim ke perangkat, hanya pembuktian/pembatalan")
print("     SESUDAHNYA yang gagal -- menolak mencatat BanAktif di sini")
print("     berarti NSM kehilangan jejak ban yang SUNGGUHAN aktif.)")


def _exec_tanpa_bukti(db, device_id, ip, menit, alasan, oleh, sungguhan=True):
    return {"hasil": "BERHASIL_TANPA_BUKTI", "bukti": "acl (tiruan)",
            "catatan": "terpasang tapi tak terbukti (tiruan)"}


r4d = pa.blokir(db, "10.20.30.46", device_id=1, alasan="uji", oleh="rina",
                _exec=_exec_tanpa_bukti, _notif=lambda *a, **k: None)
sama("ok True (diperlakukan sebagai berhasil)", r4d.get("ok"), True)
benar("BanAktif TETAP tercatat walau tanpa bukti",
      db.query(BanAktif).filter(BanAktif.ip == "10.20.30.46",
                                BanAktif.aktif == 1).first() is not None)

r4e = pa.block_acl(db, "10.20.30.47", device_id=2, alasan="uji",
                    oleh="rina", _exec=_exec_tanpa_bukti,
                    _notif=lambda *a, **k: None)
sama("blokir_acl juga ok True", r4e.get("ok"), True)
benar("BanAktif ACL TETAP tercatat walau tanpa bukti",
      db.query(BanAktif).filter(BanAktif.ip == "10.20.30.47",
                                BanAktif.aktif == 1).first() is not None)

# ---------------------------------------------------------------------------
print("\n7. BUKA BLOKIR")

r5 = pa.unblock(db, "99.99.99.99", oleh="rina")
sama("IP tanpa ban aktif -> tidak_ada_ban", r5.get("tidak_ada_ban"), True)
sama("dan tetap ok True (bukan galat)", r5.get("ok"), True)

r6 = pa.unblock(db, "10.20.30.40", oleh="rina", _exec=_exec_buka_sukses)
sama("buka sukses -> ok True", r6.get("ok"), True)
db.refresh(ban)
sama("ban.aktif jadi 0", ban.aktif, 0)
benar("waktu_buka tertulis", ban.waktu_buka is not None)

# ---------------------------------------------------------------------------
print("\n8. GALAT TEKNIS SAAT BUKA (BUKAN Ditolak) TIDAK BOLEH NAIK MENTAH")
print("   (regresi §D2.3: sebelum diperbaiki, exception non-Ditolak dari")
print("    ubah_firewall.buka() naik tanpa tertangkap.)")

ban2 = BanAktif(ip="10.20.30.44", device_id=1, alasan="uji", pola="manual",
                oleh="rina", waktu_ban=datetime.now(),
                waktu_kedaluwarsa=datetime.now() + timedelta(minutes=30),
                aktif=1)
db.add(ban2)
db.commit()

try:
    r7 = pa.unblock(db, "10.20.30.44", oleh="rina",
                        _exec=_exec_buka_galat_ssh)
    lolos += 1
    print("  LOLOS  galat SSH tertangkap, tidak melempar exception")
    sama("ok False", r7.get("ok"), False)
    benar("pesan galat disebutkan", "timed out" in (r7.get("error") or ""),
          "-> %r" % r7.get("error"))
except Exception as e:
    gagal += 1
    print("  GAGAL  galat SSH NAIK MENTAH sebagai %r, bukan jawaban rapi" % e)

db.refresh(ban2)
sama("ban tetap aktif=1 (belum terbukti terbuka, akan dicoba lagi)",
     ban2.aktif, 1)

# ---------------------------------------------------------------------------
print("\n9. KEDALUWARSA — sapuan ban yang sudah lewat waktunya")

sekarang = datetime.now()
lewat1 = BanAktif(ip="10.30.0.1", device_id=1, alasan="uji", pola="gigih",
                  oleh="auto", waktu_ban=sekarang - timedelta(hours=2),
                  waktu_kedaluwarsa=sekarang - timedelta(hours=1), aktif=1)
lewat2 = BanAktif(ip="10.30.0.2", device_id=1, alasan="uji", pola="memindai",
                  oleh="auto", waktu_ban=sekarang - timedelta(hours=2),
                  waktu_kedaluwarsa=sekarang - timedelta(minutes=1), aktif=1)
belum = BanAktif(ip="10.30.0.3", device_id=1, alasan="uji", pola="memindai",
                 oleh="auto", waktu_ban=sekarang,
                 waktu_kedaluwarsa=sekarang + timedelta(hours=1), aktif=1)
# Permanent (expiry None); this job must NEVER touch it.
permanen = BanAktif(ip="10.30.0.4", device_id=1, alasan="uji manual",
                    pola="manual", oleh="rina", waktu_ban=sekarang,
                    waktu_kedaluwarsa=None, aktif=1)
db.add_all([lewat1, lewat2, belum, permanen])
db.commit()

dibuka = pa.kedaluwarsa(db, _exec=_exec_buka_sukses)
sama("dua ban yang lewat waktu dibuka", dibuka, 2)
db.refresh(lewat1); db.refresh(lewat2); db.refresh(belum); db.refresh(permanen)
sama("lewat1 aktif=0", lewat1.aktif, 0)
sama("lewat2 aktif=0", lewat2.aktif, 0)
sama("belum (belum kedaluwarsa) TETAP aktif=1", belum.aktif, 1)
sama("permanen (kedaluwarsa None) TIDAK PERNAH disentuh", permanen.aktif, 1)

# ---------------------------------------------------------------------------
print("\n10. SATU BAN GAGAL TIDAK BOLEH MEMBATALKAN BAN LAIN DI PUTARAN YANG SAMA")
print("    (regresi §D2.3 — inti dari perbaikannya.)")

sekarang = datetime.now()
gagal_ssh = BanAktif(ip="10.40.0.1", device_id=1, alasan="uji", pola="gigih",
                     oleh="auto", waktu_ban=sekarang - timedelta(hours=2),
                     waktu_kedaluwarsa=sekarang - timedelta(hours=1), aktif=1)
sehat_a = BanAktif(ip="10.40.0.2", device_id=1, alasan="uji", pola="gigih",
                   oleh="auto", waktu_ban=sekarang - timedelta(hours=2),
                   waktu_kedaluwarsa=sekarang - timedelta(hours=1), aktif=1)
sehat_b = BanAktif(ip="10.40.0.3", device_id=1, alasan="uji", pola="gigih",
                   oleh="auto", waktu_ban=sekarang - timedelta(hours=2),
                   waktu_kedaluwarsa=sekarang - timedelta(hours=1), aktif=1)
db.add_all([gagal_ssh, sehat_a, sehat_b])
db.commit()


def _exec_campuran(db, device_id, ip, oleh, sungguhan=True):
    if ip == "10.40.0.1":
        raise ConnectionError("device ini tak terjangkau (tiruan)")
    return {"hasil": "BERHASIL", "bukti": "dibuka (tiruan)"}


try:
    dibuka2 = pa.kedaluwarsa(db, _exec=_exec_campuran)
    lolos += 1
    print("  LOLOS  kedaluwarsa() tidak crash walau satu ban gagal")
except Exception as e:
    gagal += 1
    dibuka2 = -1
    print("  GAGAL  kedaluwarsa() CRASH: %r" % e)

sama("dua ban yang sehat berhasil dibuka (bukan 0, bukan crash)", dibuka2, 2)
db.refresh(gagal_ssh); db.refresh(sehat_a); db.refresh(sehat_b)
sama("ban yang device-nya gagal dihubungi TETAP aktif=1 (dicoba lagi nanti)",
     gagal_ssh.aktif, 1)
sama("ban sehat A ikut dibuka walau ban lain gagal", sehat_a.aktif, 0)
sama("ban sehat B ikut dibuka walau ban lain gagal", sehat_b.aktif, 0)

# ---------------------------------------------------------------------------
print("\n11. DAFTAR BAN AKTIF — untuk ditampilkan halaman")

daftar = pa.daftar_ban_aktif(db)
ips = {b["ip"] for b in daftar}
benar("hanya ban aktif=1 yang muncul",
      "10.40.0.1" in ips and "10.30.0.1" not in ips,
      "-> %r" % sorted(ips))
# Checked via a specific IP, not "all rows": active bans also exist on other
# devices, so "all rows" says nothing about the device-name mapping.
per_ip = {b["ip"]: b for b in daftar}
benar("nama device ikut disertakan dan benar (device ufw)",
      per_ip.get("10.40.0.1", {}).get("device") == "Server Sehat")
benar("nama device ikut disertakan dan benar (device ACL)",
      per_ip.get("10.20.30.47", {}).get("device") == "Router Lokasi B")

# ---------------------------------------------------------------------------
print("\n12. NOTIFIKASI DIKIRIM SAAT BLOKIR BERHASIL (D2.8)")
print("    (dan galatnya TIDAK BOLEH membuat blokir() ikut gagal — blokirnya")
print("     sendiri sudah terjadi dan sudah tercatat lengkap di tempat lain.)")

dipanggil = {}


def _notif_rekam(db, ban, nama_device):
    dipanggil["ip"] = ban.ip
    dipanggil["nama_device"] = nama_device
    dipanggil["pola"] = ban.pola


r8 = pa.blokir(db, "10.50.0.1", device_id=1, alasan="uji notif",
              pola="memindai", oleh="rina", _exec=_exec_sukses,
              _notif=_notif_rekam)
sama("blokir tetap berhasil", r8.get("ok"), True)
sama("notifikasi dipanggil dengan IP yang benar", dipanggil.get("ip"),
     "10.50.0.1")
sama("dan nama device yang benar", dipanggil.get("nama_device"), "Server Sehat")
sama("dan pola yang benar", dipanggil.get("pola"), "memindai")


def _notif_meledak(db, ban, nama_device):
    raise RuntimeError("SMTP tidak terjangkau (tiruan)")


try:
    r9 = pa.blokir(db, "10.50.0.2", device_id=1, alasan="uji notif gagal",
                   pola="gigih", oleh="rina", _exec=_exec_sukses,
                   _notif=_notif_meledak)
    lolos += 1
    print("  LOLOS  blokir() tidak crash walau _notif melempar")
except Exception as e:
    gagal += 1
    r9 = {}
    print("  GAGAL  blokir() CRASH karena notifikasi: %r" % e)

sama("blokir tetap dilaporkan berhasil walau notifikasi gagal",
     r9.get("ok"), True)
benar("ban tetap benar-benar tersimpan walau notifikasi gagal",
      db.query(BanAktif).filter(BanAktif.ip == "10.50.0.2").first() is not None)

# ---------------------------------------------------------------------------
print("\n13. BLOKIR ACL (§E2) — ARSITEKTUR SAMA DENGAN blokir() UFW,")
print("    TAPI BARIS BanAktif TERPISAH UNTUK DEVICE YANG BEDA")

import ubah_acl_router as uar


def _exec_acl_sukses(db, device_id, ip, menit, alasan, oleh, sungguhan=True):
    return {"hasil": "BERHASIL", "sungguhan": True, "bukti": "acl (tiruan)",
            "seq": 1}


def _exec_acl_buka_sukses(db, device_id, ip, oleh, sungguhan=True):
    return {"hasil": "BERHASIL", "bukti": "acl dibuka (tiruan)"}


r10 = pa.block_acl(db, "10.60.0.1", device_id=2, alasan="uji acl",
                    pola="tembus", oleh="rina", _exec=_exec_acl_sukses,
                    _notif=lambda *a, **k: None)
sama("blokir_acl berhasil", r10.get("ok"), True)
ban_acl = db.query(BanAktif).filter(BanAktif.ip == "10.60.0.1",
                                    BanAktif.device_id == 2).first()
benar("baris BanAktif tersimpan untuk device ROUTER (id=2)", ban_acl is not None)

# ---------------------------------------------------------------------------
print("\n14. SATU IP, DUA LAPIS SEKALIGUS — ufw DAN ACL TIDAK SALING")
print("    MENGANGGAP 'SUDAH DIBAN' (regresi kunci idempotensi ip+device_id)")

r11 = pa.blokir(db, "10.60.0.2", device_id=1, alasan="uji dua lapis - ufw",
                pola="tembus", oleh="rina", _exec=_exec_sukses,
                _notif=lambda *a, **k: None)
r12 = pa.block_acl(db, "10.60.0.2", device_id=2,
                    alasan="uji dua lapis - acl", pola="tembus", oleh="rina",
                    _exec=_exec_acl_sukses, _notif=lambda *a, **k: None)
sama("blokir ufw untuk IP ini berhasil", r11.get("ok"), True)
sama("blokir ACL untuk IP YANG SAMA juga berhasil (bukan 'sudah_diban')",
     r12.get("ok"), True)
benar("bukan sudah_diban (regresi: sebelum diperbaiki, ini akan True)",
      not r12.get("sudah_diban"))
jumlah_ban = (db.query(BanAktif)
             .filter(BanAktif.ip == "10.60.0.2", BanAktif.aktif == 1).count())
sama("DUA baris BanAktif aktif untuk IP yang sama (ufw + ACL)", jumlah_ban, 2)

# ---------------------------------------------------------------------------
print("\n15. buka_blokir_acl() — perlu device_id eksplisit (tidak bisa tebak)")

r13 = pa.unblock_acl(db, "10.60.0.1", device_id=2, oleh="rina",
                         _exec=_exec_acl_buka_sukses)
sama("buka_blokir_acl berhasil", r13.get("ok"), True)
db.refresh(ban_acl)
sama("ban_acl.aktif jadi 0", ban_acl.aktif, 0)

r14 = pa.unblock_acl(db, "99.99.99.99", device_id=2, oleh="rina")
sama("IP tanpa ban ACL aktif -> tidak_ada_ban", r14.get("tidak_ada_ban"), True)

# ---------------------------------------------------------------------------
print("\n16. buka_blokir_apa_pun() — satu pintu, dispatch dari platform device")

r15 = pa.unblock_any(db, "10.60.0.2", device_id=1, oleh="rina",
                             _exec=_exec_buka_sukses)
sama("device_id=1 (linux) -> jalur ufw, berhasil", r15.get("ok"), True)
r16 = pa.unblock_any(db, "10.60.0.2", device_id=2, oleh="rina",
                             _exec_acl=_exec_acl_buka_sukses)
sama("device_id=2 (cisco_ios) -> jalur ACL, berhasil", r16.get("ok"), True)
jumlah_aktif = (db.query(BanAktif)
               .filter(BanAktif.ip == "10.60.0.2", BanAktif.aktif == 1).count())
sama("KEDUA ban (ufw + ACL) untuk IP ini sekarang tertutup", jumlah_aktif, 0)

pa.blokir(db, "10.60.0.3", device_id=1, alasan="uji tutup semua",
         pola="tembus", oleh="rina", _exec=_exec_sukses,
         _notif=lambda *a, **k: None)
pa.block_acl(db, "10.60.0.3", device_id=2, alasan="uji tutup semua",
             pola="tembus", oleh="rina", _exec=_exec_acl_sukses,
             _notif=lambda *a, **k: None)
r17 = pa.unblock_any(db, "10.60.0.3", oleh="rina",
                             _exec=_exec_buka_sukses,
                             _exec_acl=_exec_acl_buka_sukses)
sama("tanpa device_id -> ok True (semua berhasil ditutup)", r17.get("ok"), True)
jumlah_sisa = (db.query(BanAktif)
              .filter(BanAktif.ip == "10.60.0.3", BanAktif.aktif == 1).count())
sama("kedua ban untuk 10.60.0.3 ikut tertutup tanpa device_id disebut",
     jumlah_sisa, 0)

# ---------------------------------------------------------------------------
print("\n17. kedaluwarsa() MENDISPATCH KE JALUR YANG BENAR (ufw vs ACL)")
print("    untuk ban campuran dalam SATU putaran")

# Clean up leftovers from an earlier section (kept active=1 on purpose to prove
# "retry later"); otherwise `kedaluwarsa()` would sweep them and break the exact-count check below.
db.query(BanAktif).filter(BanAktif.ip == "10.40.0.1").update({"aktif": 0})
db.commit()

sekarang = datetime.now()
kadaluwarsa_ufw = BanAktif(ip="10.70.0.1", device_id=1, alasan="uji", pola="gigih",
                          oleh="auto", waktu_ban=sekarang - timedelta(hours=2),
                          waktu_kedaluwarsa=sekarang - timedelta(hours=1), aktif=1)
kadaluwarsa_acl = BanAktif(ip="10.70.0.2", device_id=2, alasan="uji", pola="gigih",
                          oleh="auto", waktu_ban=sekarang - timedelta(hours=2),
                          waktu_kedaluwarsa=sekarang - timedelta(hours=1), aktif=1)
db.add_all([kadaluwarsa_ufw, kadaluwarsa_acl])
db.commit()

dipanggil_acl = {"jumlah": 0}


def _exec_acl_buka_rekam(db, device_id, ip, oleh, sungguhan=True):
    dipanggil_acl["jumlah"] += 1
    return {"hasil": "BERHASIL", "bukti": "acl dibuka (tiruan)"}


dibuka2 = pa.kedaluwarsa(db, _exec=_exec_buka_sukses,
                         _exec_acl=_exec_acl_buka_rekam)
sama("dua ban (ufw + ACL) sama-sama terbuka", dibuka2, 2)
sama("jalur ACL benar-benar dipanggil (bukan ufw dipakai untuk keduanya)",
     dipanggil_acl["jumlah"], 1)
db.refresh(kadaluwarsa_ufw)
db.refresh(kadaluwarsa_acl)
sama("ban ufw tertutup", kadaluwarsa_ufw.aktif, 0)
sama("ban ACL tertutup", kadaluwarsa_acl.aktif, 0)

# ---------------------------------------------------------------------------
print("\n18. daftar_ban_aktif() MENYERTAKAN device_id DAN jenis (ufw/acl)")

pa.blokir(db, "10.80.0.1", device_id=1, alasan="uji daftar", pola="tembus",
         oleh="rina", _exec=_exec_sukses, _notif=lambda *a, **k: None)
pa.block_acl(db, "10.80.0.2", device_id=2, alasan="uji daftar", pola="tembus",
             oleh="rina", _exec=_exec_acl_sukses, _notif=lambda *a, **k: None)
daftar2 = {b["ip"]: b for b in pa.daftar_ban_aktif(db)}
sama("ban ufw bertanda jenis 'ufw'", daftar2["10.80.0.1"]["jenis"], "ufw")
sama("ban ACL bertanda jenis 'acl'", daftar2["10.80.0.2"]["jenis"], "acl")
sama("device_id ufw benar", daftar2["10.80.0.1"]["device_id"], 1)
sama("device_id ACL benar", daftar2["10.80.0.2"]["device_id"], 2)

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

"""Tests for the syslog receiver: parsing, templates, storage, throttling.
The receiver takes raw, unauthenticated network data, so:
  1. It must not crash: malformed, empty or binary datagrams must not stop later messages.
  2. Templates must merge the same event: the same event on different devices must have the same fingerprint (the hostname must not enter the template), and different events must differ.
Parsing is pure; storage uses a temporary SQLite database.
Run: py uji_syslog.py
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
        print(f"  LOLOS  {nama}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama} {ket}")


import models  # noqa: E402
import syslog_service as ss  # noqa: E402
from syslog_terima import penting, sidik_templat, templat, urai  # noqa: E402


def siapkan_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    file = os.path.join(tempfile.mkdtemp(prefix="uji_syslog_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    r1 = models.Device(name="Router Lokasi A", ip_address="192.168.56.60",
                       device_type="router", platform="cisco_ios", aktif=True)
    r2 = models.Device(name="Router Lokasi B", ip_address="192.168.20.1",
                       device_type="router", platform="cisco_ios", aktif=True)
    db.add_all([r1, r2])
    db.commit()
    return db, r1, r2


# =============================================================================
print("=" * 74)
print("1. PARSING PESAN CISCO SUNGGUHAN")
print("=" * 74)

h = urai(b"<187>Aug 23 08:12:01 R1 %LINK-3-UPDOWN: Interface FastEthernet1/1, "
         b"changed state to down", "192.168.56.60")
benar("PRI diurai jadi facility+severity",
      h["facility"] == 23 and h["severity"] == 3,
      "-> %r/%r" % (h["facility"], h["severity"]))
benar("tag Cisco dikenali", h["tag"] == "%LINK-3-UPDOWN", "-> %r" % h["tag"])
benar("severity 3 (error) dianggap penting", penting(h) is True)
benar("kepala (waktu + nama host) DIBUANG dari pesan",
      not h["pesan"].startswith("Aug") and "R1 " not in h["pesan"],
      "-> %r" % h["pesan"][:50])

h2 = urai(b"<38>Aug 23 08:12:09 ldap sshd[2211]: Failed password for invalid "
          b"user admin from 192.168.56.9 port 51234 ssh2", "192.168.20.101")
benar("tag gaya Unix dikenali (butuh kepala dibuang dulu)",
      h2["tag"] == "sshd", "-> %r" % h2["tag"])


# =============================================================================
print()
print("=" * 74)
print("2. TEMPLAT MENYATUKAN YANG SAMA, MEMISAHKAN YANG BEDA")
print("   Ini sifat yang menentukan. Kalau salah, seluruh penambangan pola")
print("   log di Paket C berdiri di atas pasir.")
print("=" * 74)

a = urai(b"<187>Aug 23 08:12:01 R1 %LINK-3-UPDOWN: Interface FastEthernet1/1, "
         b"changed state to down", "192.168.56.60")
b = urai(b"<187>Aug 24 19:44:52 R2 %LINK-3-UPDOWN: Interface FastEthernet0/0, "
         b"changed state to down", "192.168.20.1")
print("   -> %s" % templat(a["pesan"]))
benar("kejadian SAMA di device BERBEDA -> sidik sama",
      a["sidik_templat"] == b["sidik_templat"],
      "\n         %s\n         %s" % (templat(a["pesan"]), templat(b["pesan"])))

c = urai(b"<187>Aug 23 08:12:01 R1 %LINK-3-UPDOWN: Interface FastEthernet1/1, "
         b"changed state to up", "192.168.56.60")
benar("down vs up -> sidik BERBEDA",
      a["sidik_templat"] != c["sidik_templat"])

d = urai(b"<189>Aug 23 08:12:03 R1 %SYS-5-CONFIG_I: Configured from console "
         b"by vty0 (192.168.56.1)", "192.168.56.60")
benar("kejadian jenis lain -> sidik berbeda lagi",
      d["sidik_templat"] not in (a["sidik_templat"], c["sidik_templat"]))
benar("alamat IP dinormalkan, bukan dibiarkan mentah",
      "<IP>" in templat(d["pesan"]), "-> %s" % templat(d["pesan"]))


# =============================================================================
print()
print("=" * 74)
print("3. MASUKAN BURUK TIDAK MENJATUHKAN PENERIMA")
print("   Penerima yang bisa dijatuhkan satu paket UDP adalah lubang, bukan")
print("   fitur -- siapa pun di jaringan bisa mengirimnya.")
print("=" * 74)

buruk = [b"", b"\x00\x00\x00", b"<>", b"<999>", b"<abc>halo",
         bytes(range(0, 32)), b"<187>", "pesan unicode ✓ é".encode(),
         b"x" * 9000]
aman = True
for x in buruk:
    try:
        r = urai(x, "10.0.0.1")
        if not isinstance(r, dict) or "pesan" not in r:
            aman = False
    except Exception as e:
        aman = False
        print("      MELEMPAR pada %r: %s" % (x[:20], e))
benar("9 bentuk masukan buruk -> semua menghasilkan dict, nol lemparan", aman)

r = urai(b"pesan tanpa PRI sama sekali", "10.0.0.1")
benar("pesan tak berbentuk syslog TETAP disimpan, tidak dibuang",
      r["pesan"] == "pesan tanpa PRI sama sekali")
benar("...dan dianggap PENTING (justru paling tidak biasa)",
      penting(r) is True)


# =============================================================================
print()
print("=" * 74)
print("4. PEMETAAN ALAMAT -> DEVICE, DAN PENGIRIM ASING")
print("=" * 74)

db, r1, r2 = siapkan_db()
peta = ss.peta_alamat(db)
benar("dua device aktif terpetakan", len(peta) == 2, "-> %r" % peta)

b1 = ss.simpan(db, urai(b"<187>Aug 23 08:00:00 R1 %LINK-3-UPDOWN: Interface "
                        b"FastEthernet1/1, changed state to down",
                        "192.168.56.60"), peta=peta)
benar("pesan dari alamat dikenal -> device_id terisi",
      b1 is not None and b1.device_id == r1.id,
      "-> %r" % (b1.device_id if b1 else None))

b2 = ss.simpan(db, urai(b"<187>Aug 23 08:00:00 X %SEC-6-IPACCESSLOGP: list 101 "
                        b"denied tcp", "203.0.113.77"), peta=peta)
benar("pesan dari alamat ASING tetap DISIMPAN (device_id NULL)",
      b2 is not None and b2.device_id is None)
benar("...dan alamatnya dicatat apa adanya untuk diperiksa",
      b2.alamat == "203.0.113.77", "-> %r" % b2.alamat)


# =============================================================================
print()
print("=" * 74)
print("5. PEREDAMAN BANJIR PER TEMPLAT, BUKAN PER PESAN")
print("   Satu interface berkedip bisa mengirim ratusan pesan per menit.")
print("   Membatasi 'maksimal N pesan' akan membuang pesan LAIN yang mungkin")
print("   penting; membatasi per templat membuang pengulangannya saja.")
print("=" * 74)

db2, d1, d2 = siapkan_db()
peta2 = ss.peta_alamat(db2)
kedip = (b"<187>Aug 23 08:00:00 R1 %LINK-3-UPDOWN: Interface "
         b"FastEthernet1/1, changed state to down")
pertama = ss.simpan(db2, urai(kedip, "192.168.56.60"), peta=peta2)
kedua = ss.simpan(db2, urai(kedip, "192.168.56.60"), peta=peta2)
benar("pesan pertama disimpan", pertama is not None)
benar("pengulangan dalam jendela redam -> DIREDAM", kedua is None)

lain = ss.simpan(db2, urai(
    b"<189>Aug 23 08:00:01 R1 %SYS-5-CONFIG_I: Configured from console by "
    b"vty0 (192.168.56.1)", "192.168.56.60"), peta=peta2)
benar("pesan BERBEDA di jendela yang sama TIDAK ikut diredam",
      lain is not None)

lewat = urai(kedip, "192.168.56.60")
lewat["waktu"] = datetime.now() + timedelta(
    seconds=ss.JENDELA_REDAM_DETIK + 5)
ketiga = ss.simpan(db2, lewat, peta=peta2)
benar("sesudah jendela lewat -> pengulangan disimpan lagi", ketiga is not None)


# =============================================================================
print()
print("=" * 74)
print("6. TEMPLAT BARU = SINYAL PALING BERHARGA")
print("=" * 74)

db3, e1, e2 = siapkan_db()
peta3 = ss.peta_alamat(db3)
p = ss.simpan(db3, urai(b"<187>Aug 23 08:00:00 R1 %LINK-3-UPDOWN: Interface "
                        b"FastEthernet1/1, changed state to down",
                        "192.168.56.60"), peta=peta3)
benar("pola yang baru pertama kali muncul -> dikenali BARU",
      ss.templat_baru(db3, p.sidik_templat) is True)

q = urai(b"<187>Aug 23 08:01:00 R2 %LINK-3-UPDOWN: Interface FastEthernet0/0, "
         b"changed state to down", "192.168.20.1")
q["waktu"] = datetime.now() + timedelta(seconds=ss.JENDELA_REDAM_DETIK + 5)
p2 = ss.simpan(db3, q, peta=peta3)
benar("pola yang SUDAH pernah muncul -> tidak lagi baru",
      ss.templat_baru(db3, p2.sidik_templat) is False)


# =============================================================================
print()
print("=" * 74)
print("7. PEMICU PEMERIKSAAN KONFIG (bukan pemicu TINDAKAN)")
print("   Syslog mudah dipalsukan, jadi ia tidak pernah boleh langsung")
print("   menyentuh perangkat. Ia hanya boleh menyuruh NSM MEMERIKSA.")
print("=" * 74)

konfig = urai(b"<189>Aug 23 08:12:03 R1 %SYS-5-CONFIG_I: Configured from "
              b"console by vty0 (192.168.56.1)", "192.168.56.60")
benar("%SYS-5-CONFIG_I memicu pemeriksaan konfigurasi",
      ss.perlu_periksa_konfig(konfig) is True)
benar("pesan biasa TIDAK memicu apa pun",
      ss.perlu_periksa_konfig(a) is False)
benar("dan pesannya menyimpan SIAPA + DARI MANA",
      "vty0" in konfig["pesan"] and "192.168.56.1" in konfig["pesan"],
      "-> %r" % konfig["pesan"])


# =============================================================================
print()
print("=" * 74)
print("PENANDA MUTU JAM CISCO ADA DUA, BUKAN SATU (cacat 23 Agustus 2026)")
print("   Cisco menandai stempel waktunya sendiri:")
print("     *Aug 22 22:17:18.158 UTC:   jam TIDAK otoritatif")
print("     .Aug 23 01:27:28.791 UTC:   otoritatif, TAPI NTP tidak sinkron")
print("      Aug 23 01:27:28.791 UTC:   otoritatif dan sinkron")
print("   Versi lama hanya mengenali '*'. Pesan dengan '.' lolos dengan")
print("   stempelnya utuh.")
print("   AKIBATNYA DIUKUR, bukan diperkirakan: peredam banjir TIDAK rusak")
print("   (penormalan <N> sudah meratakan angka stempelnya). Yang rusak:")
print("   pesan yang SAMA dari perangkat berpenanda jam BERBEDA bersidik")
print("   berbeda -- satu kejadian terbaca sebagai dua pola. Penambangan")
print("   Drain3 kena lebih keras: 13 pola turun jadi 10 sesudah diperbaiki.")
print("=" * 74)

_ASAL = "192.168.56.60"

_TIGA = [
    ("titik (NTP tidak sinkron)",
     b"<188>Aug 23 01:27:28 R1 123: .Aug 23 01:27:28.791 UTC: "
     b"%SYS-6-LOGGINGHOST_STARTSTOP: Logging to host 192.168.56.156 started"),
    ("bintang (jam tak otoritatif)",
     b"<188>Aug 22 22:17:18 R1 45: *Aug 22 22:17:18.158 UTC: "
     b"%CDP-4-DUPLEX_MISMATCH: duplex mismatch discovered on FastEthernet0/0"),
    ("tanpa penanda",
     b"<188>Aug 23 01:27:28 R1 9: Aug 23 01:27:28.791 UTC: "
     b"%SYS-5-CONFIG_I: Configured from console by nsm"),
]
for _ket, _mentah in _TIGA:
    _h = urai(_mentah, _ASAL)
    benar("stempel Cisco dibuang -- %s" % _ket,
          _h["pesan"].lstrip().startswith("%"),
          "-> %r" % _h["pesan"][:80])

_utuh = urai(b"<187>Aug 23 08:12:01 R1 %LINK-3-UPDOWN: Interface "
             b"FastEthernet1/1, changed state to down", _ASAL)
benar("pesan tanpa stempel Cisco tetap UTUH",
      "Interface FastEthernet1/1" in _utuh["pesan"],
      "-> %r" % _utuh["pesan"])

# Two messages with the same content but different timestamps must get the same fingerprint.
_a = urai(b"<188>Aug 23 01:00:00 R1 1: .Aug 23 01:00:00.111 UTC: "
          b"%SYS-5-CONFIG_I: Configured from console by nsm", _ASAL)
_b = urai(b"<188>Aug 23 09:30:00 R1 2: .Aug 23 09:30:00.999 UTC: "
          b"%SYS-5-CONFIG_I: Configured from console by nsm", _ASAL)
benar("pesan sama, stempel beda -> sidik templat SAMA",
      _a["sidik_templat"] == _b["sidik_templat"],
      "-> %s vs %s" % (_a["sidik_templat"], _b["sidik_templat"]))

# The converse: different content must stay different, otherwise over-aggressive normalization that merges everything would pass.
_c = urai(b"<188>Aug 23 09:30:00 R1 2: .Aug 23 09:30:00.999 UTC: "
          b"%SYS-5-CONFIG_I: Configured from console by budi", _ASAL)
benar("pesan yang isinya BERBEDA tetap bersidik berbeda",
      _a["sidik_templat"] != _c["sidik_templat"],
      "-> keduanya %s" % _a["sidik_templat"])


if __name__ == "__main__":
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

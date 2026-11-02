"""Tests for device identity beyond the IP address.

Answers "is the machine at this address really the device I mean?" before NSM
touches it. The `reload in 5` safety net does not answer that; it protects against
a wrong command, not a wrong device.

 1. `hostname` is read from the Cisco IOS configuration snapshot.
 2. Four verdicts are distinguished; `belum_diketahui` is NOT `bertentangan`.
 3. A conflicting marker does not overwrite the old one; history is kept.
 4. The verdict is computed BEFORE the value is stored, so the first comparison
    does not match itself.
 5. `boleh_ditulisi` refuses every verdict except `sama`.
 6. Reverse guard: a device whose identity really matches is NOT blocked.

Run: py uji_identitas.py
"""
import sys
from datetime import datetime, timedelta

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


KONFIG_R1 = """version 15.2
!
hostname R1
!
interface FastEthernet0/0
 ip address 192.168.56.60 255.255.255.0
!
end
"""

KONFIG_LAIN = KONFIG_R1.replace("hostname R1", "hostname SWITCH-KANTOR")


def uji():
    print("=" * 74)
    print("Identitas perangkat selain alamat IP")
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
    import identitas as idn

    db.add(models.Device(id=1, name="Router Uji", ip_address="192.168.56.60",
                         device_type="router", platform="cisco_ios", aktif=1))
    db.commit()

    # --- 1. hostname terbaca -------------------------------------------
    print("\n1. hostname terbaca dari potret konfigurasi")
    cek("hostname R1", idn.hostname_dari_konfig(KONFIG_R1), "R1")
    cek("hostname lain", idn.hostname_dari_konfig(KONFIG_LAIN), "SWITCH-KANTOR")
    cek("konfigurasi tanpa hostname", idn.hostname_dari_konfig("version 15.2"), None)
    cek("teks kosong", idn.hostname_dari_konfig(""), None)

    # --- 2. empat vonis dibedakan --------------------------------------
    print("\n2. Empat vonis dibedakan")
    v, _r = idn.vonis(db, 1)
    cek("perangkat baru: belum diketahui", v, idn.BELUM_DIKETAHUI)

    idn.catat(db, 1, "hostname", "R1", "konfig")
    db.commit()
    v, r = idn.vonis(db, 1, {"hostname": "R1"})
    cek("satu penanda cocok: kemungkinan sama", v, idn.KEMUNGKINAN_SAMA)
    cek("cacah cocoknya satu", r["cocok"], 1)

    idn.catat(db, 1, "serial", "FTX1234ABCD", "ssh")
    db.commit()
    v, r = idn.vonis(db, 1, {"hostname": "R1", "serial": "FTX1234ABCD"})
    cek("dua penanda cocok: sama", v, idn.SAMA)

    v, r = idn.vonis(db, 1, {"hostname": "SWITCH-KANTOR"})
    cek("penanda berbeda: bertentangan", v, idn.BERTENTANGAN)
    benar("alasannya menyebut kedua nilainya",
          any("R1" in a and "SWITCH-KANTOR" in a for a in r["alasan"]),
          f"-> {r['alasan']}")

    print("\n   PEMBEDAAN YANG MENENTUKAN")
    v_empty, _r = idn.vonis(db, 1, {"mac": None})
    benar("penanda KOSONG tidak dibaca sebagai bertentangan",
          v_empty != idn.BERTENTANGAN, f"-> {v_empty}")
    v_new, r_new = idn.vonis(db, 1, {"mac": "aa:bb:cc:dd:ee:ff"})
    benar("penanda yang belum pernah tercatat juga bukan pertentangan",
          v_new != idn.BERTENTANGAN, f"-> {v_new}")
    benar("dan itu dikatakan terus terang di alasannya",
          any("baru pertama kali" in a for a in r_new["alasan"]),
          f"-> {r_new['alasan']}")
    print("       (kosong berarti NSM belum pernah bertanya; bertentangan")
    print("        berarti NSM bertanya dan mendapat jawaban berbeda.")
    print("        Menyamakannya membuat fitur ini dimatikan orang hari itu juga)")

    # 3. old value not overwritten
    print("\n3. Nilai yang bertentangan TIDAK menimpa yang lama")
    before = (db.query(models.IdentitasPerangkat)
               .filter(models.IdentitasPerangkat.jenis == "hostname").count())
    _b, changed, old = idn.catat(db, 1, "hostname", "SWITCH-KANTOR", "konfig")
    db.commit()
    after = (db.query(models.IdentitasPerangkat)
               .filter(models.IdentitasPerangkat.jenis == "hostname").count())
    cek("barisnya bertambah, bukan tergantikan", (before, after), (1, 2))
    cek("perubahan dilaporkan", changed, True)
    cek("nilai lamanya ikut disebut", old, "R1")
    nilai = sorted(p.nilai for p in db.query(models.IdentitasPerangkat)
                   .filter(models.IdentitasPerangkat.jenis == "hostname").all())
    cek("kedua nilai tersimpan", nilai, ["R1", "SWITCH-KANTOR"])
    print("       (nilai yang ditimpa menghapus satu-satunya bukti bahwa")
    print("        pernah ada perbedaan)")

    # 4. value BEFORE saving
    print("\n4. Vonis dihitung SEBELUM nilainya disimpan")
    db.query(models.IdentitasPerangkat).delete()
    db.query(models.Device).delete()
    db.commit()
    db.add(models.Device(id=2, name="Router Baru", ip_address="10.0.0.1",
                         device_type="router", platform="cisco_ios", aktif=1))
    db.add(models.KonfigSnapshot(id=1, device_id=2, waktu=datetime.now(),
                                 sidik="x", teks=KONFIG_R1))
    db.commit()

    catatan = idn.kumpulkan_dari_konfig(db)
    db.commit()
    d = db.query(models.Device).filter(models.Device.id == 2).first()
    cek("pengumpulan PERTAMA: belum ada pembanding",
        d.identitas_vonis, idn.BELUM_DIKETAHUI)
    benar("tetapi nilainya tetap tersimpan",
          db.query(models.IdentitasPerangkat).count() == 1)
    print("       (menyimpan lalu menilai membuat pembandingan pertama cocok")
    print("        dengan dirinya sendiri, dan 'bukti' semacam itu muncul")
    print("        justru saat sebuah perangkat pertama kali dikenali)")

    idn.kumpulkan_dari_konfig(db)
    db.commit()
    d = db.query(models.Device).filter(models.Device.id == 2).first()
    cek("pengumpulan KEDUA: barulah jadi bukti",
        d.identitas_vonis, idn.KEMUNGKINAN_SAMA)

    print("\n5. Jalur MENULIS hanya terbuka untuk vonis `sama`")
    for v_test, harap in ((idn.SAMA, True),
                         (idn.KEMUNGKINAN_SAMA, False),
                         (idn.BERTENTANGAN, False),
                         (idn.BELUM_DIKETAHUI, False),
                         (None, False)):
        d.identitas_vonis = v_test
        db.commit()
        allowed, _v, alasan = idn.boleh_ditulisi(db, 2)
        cek(f"vonis {v_test!r}", allowed, harap)
    cek("perangkat yang tidak ada", idn.boleh_ditulisi(db, 999)[0], False)

    # --- 6. penjaga arah sebaliknya ------------------------------------
    print("\n6. PENJAGA ARAH SEBALIKNYA")
    d.identitas_vonis = idn.SAMA
    db.commit()
    allowed, v, alasan = idn.boleh_ditulisi(db, 2)
    benar("perangkat yang identitasnya terbukti TIDAK ikut diblokir", allowed,
          f"-> {alasan}")
    print("       (penjaga yang menolak semua keadaan sama tidak bergunanya")
    print("        dengan yang meloloskan semuanya; bedanya cuma yang pertama")
    print("        membuat fiturnya dimatikan orang, bukan diabaikan)")

    db.close()
    database.engine, database.SessionLocal = original_engine, original_session


if __name__ == "__main__":
    uji()
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

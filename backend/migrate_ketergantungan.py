"""Create table `layanan_bergantung` and fill in the real dependencies.

DEPENDENCIES ARE DERIVED FROM OBSERVATION, NOT INVENTED
-------------------------------------------------------
Each row below points to evidence that exists in this lab:

    E-Canteen -> MySQL   `application.properties` on .103 names
                         jdbc:mysql://192.168.56.104:3306/ecanteen
    E-Canteen -> LDAP    the same file names ldap://192.168.20.101:389
    SSH .103  -> LDAP    `sssd.conf` on .103 uses that directory to recognize
                         users; if the directory is down, LDAP account logins are
                         rejected even though sshd is healthy

Same rule as the ACL permissions: a row may exist only if it can be traced to a
real user. An invented dependency would make NSM call something an "effect" when
it is a cause, and a wrongly downgraded alarm is more dangerous than a noisy one.

Safe to re-run.
"""
import sys

from sqlalchemy import select

import database
import models

# (dependent service name, required service name, reason)
KETERGANTUNGAN = [
    ("E-Canteen v2", "MySQL (Server Data)",
     "E-Canteen menyimpan seluruh datanya di basis data ini; tanpa itu "
     "halamannya terbuka tetapi tiap login dan tiap menu gagal"),
    ("E-Canteen v2", "LDAP Direktori (Lokasi B)",
     "sandi diperiksa ke direktori, bukan ke basis data; tanpa direktori "
     "tidak ada yang bisa masuk walau basis datanya sehat"),
    ("SSH testUbuntu", "LDAP Direktori (Lokasi B)",
     "sssd mengenali pemakai dari direktori; matinya direktori membuat login "
     "akun LDAP ditolak walau sshd sendiri sehat"),
    ("SSH Server Data", "LDAP Direktori (Lokasi B)",
     "sama seperti server web: pengenalan pemakai datang dari direktori"),
]


def main():
    path = "--jalan" in sys.argv
    md = database.Base.metadata

    print("=" * 74)
    print("Ketergantungan antar layanan")
    print("=" * 74)

    md.tables["layanan_bergantung"].create(database.engine, checkfirst=True)
    print("  tabel siap")

    db = database.SessionLocal()
    try:
        per_name = {s.nama: s for s in db.execute(
            select(models.Service)).scalars()}

        print()
        plan = []
        for require, needed, alasan in KETERGANTUNGAN:
            a, b = per_name.get(require), per_name.get(needed)
            if not a or not b:
                print("  LEWAT  %-22s -> %-26s (layanan tidak ditemukan)"
                      % (require, needed))
                continue
            already = db.execute(
                select(models.LayananBergantung).where(
                    models.LayananBergantung.layanan_id == a.id,
                    models.LayananBergantung.pada_layanan_id == b.id)).first()
            mark = "sudah ada" if already else "AKAN DITAMBAH"
            print("  %-13s %-22s -> %s" % (mark, require, needed))
            if not already:
                plan.append(models.LayananBergantung(
                    layanan_id=a.id, pada_layanan_id=b.id, alasan=alasan))

        if not plan:
            print()
            print("Tidak ada yang perlu ditambah.")
            return 0

        if not path:
            print()
            print("Ini baru rencana. Jalankan dengan --jalan untuk menyimpan.")
            return 0

        for r in plan:
            db.add(r)
        db.commit()
        print()
        print("%d ketergantungan disimpan." % len(plan))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

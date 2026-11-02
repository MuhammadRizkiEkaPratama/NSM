"""Prove NSM keeps recording when its database is truly unreachable.

The outage is simulated with a firewall rule on .103, not by stopping MySQL:
stopping `mysqld` gives a FAST connection refusal, while real network trouble
drops packets silently and clients hang until timeout, the failure most likely
to freeze the poller. Packets to 3306 are dropped without reply.

Safety net: the firewall rule is restored in a `finally` block, and SSH to .103
is never cut, since the way in to repair must not pass through what is being broken.

This test WRITES real rows to the database (a dozen or so, for existing devices);
that is the price of proving the recovery path works.
"""
import io
import sys
import time

import paramiko

import database
import models  # noqa: F401
import penyangga
from sqlalchemy import func, select

# The database address is read from `.env`, not hardcoded. A hardcoded address
# would make this test cut port 3306 on the wrong machine after the database moved,
# and the test itself would not turn red.
HOST_DB = database.ENV.get("NSM_DB_HOST", "192.168.56.103")
ADMIN = "doni"

lolos, gagal = [], []


def catat(ok, judul, ket=""):
    (lolos if ok else gagal).append(judul)
    print("  %-6s %s%s" % ("LOLOS" if ok else "GAGAL", judul,
                           ("  — " + ket) if ket else ""))


def sandi_admin():
    """Read from .env, not written in this file."""
    for line in io.open(".env", encoding="utf-8"):
        if line.startswith("UJI_103_PASS="):
            return line.split("=", 1)[1].strip()
    return None


def ssh():
    s = sandi_admin()
    if not s:
        return None
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST_DB, username=ADMIN, password=s, timeout=30,
              banner_timeout=40, allow_agent=False, look_for_keys=False)
    return c


def sudo(c, perintah, t=120):
    s = sandi_admin()
    _i, o, e = c.exec_command("echo %s | sudo -S -p '' %s" % (s, perintah),
                              timeout=t)
    return (o.read() + e.read()).decode("utf-8", "replace").strip()


def jumlah_mysql():
    with database.engine.connect() as k:
        return k.execute(
            select(func.count()).select_from(
                database.Base.metadata.tables["status_logs"])).scalar()


def main():
    print("=" * 74)
    print("Penyangga lokal: NSM saat basis datanya tidak terjangkau")
    print("=" * 74)

    if not database.PAKAI_MYSQL:
        print("NSM sedang memakai SQLite — uji ini tidak berlaku.")
        return 0

    c = ssh()
    if c is None:
        print("UJI_103_PASS belum ada di .env — uji ini butuh akses admin")
        print("ke %s untuk memutus port 3306 sementara." % HOST_DB)
        return 2

    penyangga.siapkan()
    before = jumlah_mysql()
    print("\nBaris status_logs di MySQL sebelum uji: %d" % before)

    try:
        # --- 1. Keadaan sehat --------------------------------------------
        db, buffered = penyangga.sesi()
        catat(not buffered, "saat sehat, sesi menunjuk ke MySQL")
        penyangga.cermin_acuan(db)
        db.close()

        with database.engine_penyangga.connect() as p:
            n_dev = p.execute(select(func.count()).select_from(
                database.Base.metadata.tables["devices"])).scalar()
        catat(n_dev > 0, "daftar device tercermin ke penyangga",
              "%d device" % n_dev)

        # --- 2. Putuskan jalurnya ----------------------------------------
        print("\n  memutus port 3306 di %s (SSH sengaja TIDAK diputus)" % HOST_DB)
        # `ufw delete allow ...`, NOT `ufw deny ...`. ufw identifies a rule by its match
        # criteria, so adding a `deny` with identical criteria OVERWRITES the existing
        # `allow` instead of adding a second rule. Deleting the `deny` afterward leaves
        # ZERO rules for 3306 and the default `deny incoming` takes over silently.
        sudo(c, "ufw delete allow from 192.168.56.1 to any port 3306 proto tcp")
        # ufw applies new rules to NEW connections only. The SQLAlchemy connection pool
        # still holds old ones, so it is disposed first; otherwise the test would pass on
        # a connection that should no longer exist.
        database.engine.dispose()
        penyangga._gagal_sejak = None
        penyangga._coba_berikutnya = 0.0

        catat(not penyangga.mysql_hidup(), "MySQL terbukti tidak terjangkau")

        db, buffered = penyangga.sesi()
        catat(buffered, "sesi otomatis beralih ke penyangga lokal")

        # 3. The poller still has its work list
        devices = db.query(models.Device).all()
        catat(len(devices) > 0,
              "poller masih bisa membaca daftar device saat basis data mati",
              "%d device" % len(devices))
        # Take the id NOW, while the object is still session-bound; after `db.close()`
        # every attribute read raises DetachedInstanceError, far from its cause.
        id_device = [d.id for d in devices]

        # 4. Measurements are still recorded
        from datetime import datetime
        tulis = 0
        for did in id_device[:5]:
            db.add(models.StatusLog(device_id=did, timestamp=datetime.now(),
                                    is_reachable=True, response_time_ms=1.0,
                                    sumber="uji"))
            tulis += 1
        db.commit()
        db.close()

        held = penyangga.jumlah_tertahan()
        catat(held.get("status_logs", 0) >= tulis,
              "hasil pengukuran tersimpan di penyangga",
              "%d baris tertahan" % held.get("status_logs", 0))

        # 4b. Parent-child pairs created during the outage
        #
        # Draining the buffer used to drop the parent `id` so MySQL would assign a new one,
        # while the child kept the old number; config snapshots then landed in MySQL with
        # no compliance findings, and the Compliance page showed the device as clean. This
        # checks not just that rows arrive, but that the child still points to the right parent.
        db, _ = penyangga.sesi()
        snapshot = models.KonfigSnapshot(
            device_id=id_device[0], waktu=datetime.now(),
            sidik="uji" + "0" * 61, teks="uji penyangga induk-anak",
            baris_tambah=0, baris_hapus=0)
        db.add(snapshot)
        db.flush()
        id_buffer = snapshot.id
        for n in range(3):
            db.add(models.KonfigTemuan(
                snapshot_id=snapshot.id, device_id=id_device[0],
                aturan_id="uji_penyangga_%d" % n, hasil="TIDAK_BERLAKU",
                keparahan="rendah", dinilai=datetime.now()))
        db.commit()
        db.close()
        catat(True, "potret + 3 temuan ditulis ke penyangga",
              "snapshot_id di penyangga = %d" % id_buffer)

    finally:
        print("\n  mengembalikan aturan firewall")
        sudo(c, "ufw allow from 192.168.56.1 to any port 3306 proto tcp "
                "comment 'MySQL NSM - hanya dari laptop NSM'")
        database.engine.dispose()
        penyangga._gagal_sejak = None
        penyangga._coba_berikutnya = 0.0
        time.sleep(1)

    # 5. Recovery and delivery of the backlog
    catat(penyangga.mysql_hidup(), "MySQL terjangkau lagi setelah aturan dicabut")

    moved = penyangga.kosongkan()
    after = jumlah_mysql()
    catat(after >= before + tulis,
          "baris yang tertahan sampai ke MySQL setelah pulih",
          "%d -> %d (+%d)" % (before, after, after - before))

    remaining = penyangga.jumlah_tertahan()
    catat(not remaining, "penyangga kosong setelah dikirim",
          "sisa: %s" % (remaining or "tidak ada"))

    # The most important check in this file: after arrival, does the CHILD still point
    # to the CORRECT parent?
    from sqlalchemy import text as _t
    with database.engine.connect() as k:
        line = k.execute(_t(
            "SELECT t.snapshot_id, s.sidik, COUNT(*) "
            "FROM konfig_temuan t "
            "LEFT JOIN konfig_snapshots s ON s.id = t.snapshot_id "
            "WHERE t.aturan_id LIKE 'uji_penyangga_%' "
            "GROUP BY t.snapshot_id, s.sidik")).all()
    catat(len(line) == 1 and line[0][2] == 3,
          "ketiga temuan mendarat di SATU induk yang sama",
          "-> %r" % (line,))
    catat(bool(line) and line[0][1] is not None
          and line[0][1].startswith("uji"),
          "induknya adalah potret yang benar, bukan potret milik orang lain",
          "-> sidik %r" % (line[0][1] if line else None))
    catat(bool(line) and line[0][0] != id_buffer,
          "nomor induk sudah digeser, bukan nomor penyangga yang dipakai apa adanya",
          "-> penyangga %s, MySQL %s" % (id_buffer,
                                         line[0][0] if line else None))

    # Test rows are removed: they are synthetic, and the Compliance page must not show a snapshot named "uji penyangga".
    with database.engine.begin() as k:
        k.execute(_t("DELETE FROM konfig_temuan "
                     "WHERE aturan_id LIKE 'uji_penyangga_%'"))
        k.execute(_t("DELETE FROM konfig_snapshots WHERE sidik LIKE 'uji%'"))

    with database.engine.begin() as k:
        sl = database.Base.metadata.tables["status_logs"]
        k.execute(sl.delete().where(sl.c.sumber == "uji"))

    c.close()
    print()
    print("=" * 74)
    print("HASIL: %d lolos, %d gagal" % (len(lolos), len(gagal)))
    print("=" * 74)
    return 1 if gagal else 0


if __name__ == "__main__":
    sys.exit(main())

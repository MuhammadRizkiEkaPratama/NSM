"""Test of the System Health page, with faults planted first.

A monitor that has never been proven able to raise an alarm proves nothing when
it is silent. Each test plants one condition, calls `kesehatan.ringkasan()`, and
checks the verdict. Everything runs on a temporary database; `nsm.db` is untouched.

Run: py uji_kesehatan.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

lolos = 0
gagal = 0


def cek(nama, dapat, harap):
    global lolos, gagal
    if dapat == harap:
        lolos += 1
        print(f"  LOLOS  {nama}: {dapat}")
    else:
        gagal += 1
        print(f"  GAGAL  {nama}: dapat {dapat}, harusnya {harap}")


def bagian(hasil, nama):
    for b in hasil["bagian"]:
        if b["nama"] == nama:
            return b
    return {"vonis": "(bagian tidak ada)", "nilai": None}


def main():
    folder = tempfile.mkdtemp(prefix="nsm-sehat-")
    lama_cwd = os.getcwd()
    path_test = os.path.join(folder, "nsm.db")

    # The working directory is still changed, but only as a fence: if a new relative
    # path ever slips into `kesehatan.py`, it lands in this temp folder instead of the
    # real backend folder. The database is redirected explicitly via `database.JALUR_DB`.
    os.chdir(folder)

    mesin = create_engine("sqlite:///" + path_test.replace(os.sep, "/"))

    # Match WAL mode with the real database; otherwise the Database section would
    # report a warning on the healthy baseline.
    @event.listens_for(mesin, "connect")
    def _atur(sambungan, _c):
        k = sambungan.cursor()
        k.execute("PRAGMA journal_mode=WAL")
        k.close()

    session = sessionmaker(bind=mesin)

    sys.path.insert(0, lama_cwd)
    import database
    database.engine = mesin
    database.SessionLocal = session
    database.JALUR_DB = path_test
    import models
    models.Base.metadata.create_all(mesin)

    import config
    import kesehatan

    config.get_interval = lambda: 5
    config.get_bandwidth_interval = lambda: 30
    config.get_bandwidth_enabled = lambda: True
    config.get_service_interval = lambda: 30
    config.get_service_enabled = lambda: True
    config.get_traffic_interval = lambda: 60
    config.get_traffic_enabled = lambda: True
    config.get_notif_enabled = lambda: True
    config.get_notif_interval = lambda: 20
    config.get_backup_dir = lambda: os.path.join(folder, "backup")

    db = session()
    db.add(models.Device(id=1, name="Uji", ip_address="10.0.0.1",
                         device_type="server", platform="linux", aktif=1))
    db.commit()

    # service_checks points to `services`, not `devices`, so its foreign-key column differs.
    column_pointer = {"service_checks": "service_id"}

    def isi(tabel, kolom, detik_lalu, jumlah=1):
        """Plant a row with a given age."""
        pointer = column_pointer.get(tabel, "device_id")
        t = datetime.now() - timedelta(seconds=detik_lalu)
        for i in range(jumlah):
            db.execute(text(
                f"INSERT INTO {tabel}({pointer},{kolom}) VALUES(1,:t)"),
                {"t": (t - timedelta(seconds=i * 5)).isoformat(sep=" ")})
        db.commit()

    os.makedirs(os.path.join(folder, "backup"), exist_ok=True)

    print("=" * 74)
    print("1. SEMUA SEHAT (dasar pembanding)")
    print("=" * 74)
    isi("status_logs", "timestamp", 2, jumlah=200)
    isi("bandwidth_samples", "timestamp", 5)
    isi("service_checks", "timestamp", 5)
    isi("flow_koneksi", "waktu", 10)
    with open(os.path.join(folder, "backup", "nsm-backup-uji.zip"), "wb") as f:
        f.write(b"x" * 100)
    h = kesehatan.ringkasan(db)
    cek("job ping", bagian(h, "Poller (job ping)")["vonis"], "sehat")
    cek("job bandwidth", bagian(h, "Job bandwidth")["vonis"], "sehat")
    cek("backup", bagian(h, "Backup")["vonis"], "sehat")
    # Failures name the failing section and reason. Some sections (e.g. replica state)
    # touch the real network, so a failure may mean the lab, not the code.
    if h["vonis"] != "sehat":
        print("     [diagnosa] bagian yang tidak sehat:")
        for b in h.get("bagian", []):
            if b.get("vonis") not in ("sehat", "mati-sengaja"):
                print("       - %-26s %-12s %s"
                      % (b.get("nama"), b.get("vonis"), str(b.get("ket"))[:70]))

    # The overall verdict is checked on a copy with the real-network sections (replica
    # state, backup restore) neutralized, so lab availability cannot fail the baseline test.
    network_alive = {"Replika basis data (Lokasi B)", "Pemulihan backup"}
    verdict_code = kesehatan._gabung([
        b.get("vonis") for b in h.get("bagian", [])
        if b.get("nama") not in network_alive])
    cek("vonis keseluruhan (tanpa bagian jaringan hidup)", verdict_code, "sehat")

    print()
    print("=" * 74)
    print("2. KERUSAKAN DITANAM: poller berhenti 10 menit lalu")
    print("=" * 74)
    db.execute(text("DELETE FROM status_logs"))
    db.commit()
    isi("status_logs", "timestamp", 600, jumlah=5)
    h = kesehatan.ringkasan(db)
    b = bagian(h, "Poller (job ping)")
    cek("job ping berteriak", b["vonis"], "bahaya")
    cek("vonis keseluruhan ikut naik", h["vonis"], "bahaya")
    cek("masalahnya disebut", any("status_logs" in m for m in h["masalah"]), True)
    print(f"         pesannya: {b['ket'][:100]}...")

    print()
    print("=" * 74)
    print("3. KERUSAKAN DITANAM: job bandwidth telat, belum mati")
    print("=" * 74)
    db.execute(text("DELETE FROM status_logs"))
    db.execute(text("DELETE FROM bandwidth_samples"))
    db.commit()
    isi("status_logs", "timestamp", 2, jumlah=200)
    isi("bandwidth_samples", "timestamp", 30 * 5)      # 5x interval
    h = kesehatan.ringkasan(db)
    cek("telat -> perhatian, bukan bahaya",
        bagian(h, "Job bandwidth")["vonis"], "perhatian")
    cek("job ping tetap sehat", bagian(h, "Poller (job ping)")["vonis"], "sehat")

    print()
    print("=" * 74)
    print("4. KERUSAKAN DITANAM: putaran ping melar berkali-kali")
    print("=" * 74)
    db.execute(text("DELETE FROM status_logs"))
    db.commit()
    # Dense every 5 seconds, BUT with five 20-second jumps inserted.
    t = datetime.now() - timedelta(minutes=30)
    lompat_ke = {40, 80, 120, 160, 200}
    for i in range(300):
        t += timedelta(seconds=20 if i in lompat_ke else 5)
        if t > datetime.now():
            break
        db.execute(text("INSERT INTO status_logs(device_id,timestamp) "
                        "VALUES(1,:t)"), {"t": t.isoformat(sep=" ")})
    db.commit()
    h = kesehatan.ringkasan(db)
    b = bagian(h, "Kerapatan putaran ping")
    cek("lompatan terdeteksi", b["vonis"], "bahaya")
    cek("jumlahnya benar", b["nilai"], "5 melar / 1 jam")
    cek("lompatan terpanjang dilaporkan", max(b["lompatan"]), 20.0)

    print()
    print("=" * 74)
    print("5. KERUSAKAN DITANAM: backup basi 3 hari")
    print("=" * 74)
    jalur = os.path.join(folder, "backup", "nsm-backup-uji.zip")
    old_age = (datetime.now() - timedelta(days=3)).timestamp()
    os.utime(jalur, (old_age, old_age))
    h = kesehatan.ringkasan(db)
    cek("backup basi berteriak", bagian(h, "Backup")["vonis"], "bahaya")

    print()
    print("=" * 74)
    print("6. KERUSAKAN DITANAM: folder backup hilang sama sekali")
    print("=" * 74)
    os.remove(jalur)
    os.rmdir(os.path.join(folder, "backup"))
    h = kesehatan.ringkasan(db)
    cek("folder hilang berteriak", bagian(h, "Backup")["vonis"], "perhatian")

    print()
    print("=" * 74)
    print("7. JOB YANG SENGAJA DIMATIKAN bukan kerusakan")
    print("=" * 74)
    config.get_traffic_enabled = lambda: False
    config.get_notif_enabled = lambda: False
    h = kesehatan.ringkasan(db)
    cek("job traffic dimatikan", bagian(h, "Job lalu lintas")["vonis"],
        "mati-sengaja")
    cek("tidak ikut menurunkan vonis keseluruhan",
        "mati-sengaja" not in [v for v in h["masalah"]], True)
    cek("job notifikasi tidak pernah dinilai dari umur data",
        bagian(h, "Job notifikasi")["vonis"], "mati-sengaja")

    db.close()
    mesin.dispose()
    os.chdir(lama_cwd)


if __name__ == "__main__":
    main()
    print()
    print("=" * 74)
    print(f"HASIL: {lolos} lolos, {gagal} gagal")
    print("=" * 74)
    sys.exit(1 if gagal else 0)

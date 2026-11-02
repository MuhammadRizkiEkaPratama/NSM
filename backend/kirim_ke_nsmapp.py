"""Push code from the laptop to `nsm-app`.

Used once, supervised, with explicit approval. NOT daily automation and must not
run in CI.

WHAT IS SENT, AND WHAT IS NOT
-----------------------------
Sent:     `.py` files in `backend/`, and `.java/.html/.js/.css` sources in
          `frontend/src/`. Exactly the same scope as `cek_sinkron_nsmapp.py`, so
          after this script that checker can prove zero differences.
NOT sent: `.env` (primary lab instance settings, which differ on purpose),
          `venv/`, `__pycache__/`, `.git/`, `target/`, and the runtime database.

`.env` is excluded absolutely: it holds the database address, credentials, AND the
automation kill switches. Overwriting it with the laptop's copy would repoint the
primary lab instance at laptop settings and could ENABLE the recovery that is
deliberately off.

ORDER, AND WHY
--------------
1. Back up the running `.jar`           -> so it can be reversed
2. Send backend files                   -> no effect yet
3. Run database migrations              -> adds columns/tables, never deletes
4. Restart the backend service          -> new code goes live
5. Send `.jar` + frontend sources       -> riskiest step, so it goes last: the
6. Restart the frontend                    backend is proven healthy first

Kill switches are NOT touched. All automation stays OFF after this script until
someone enables it in the primary instance's `.env`.

Run: venv\\Scripts\\python.exe kirim_ke_nsmapp.py [--jalankan]
Without `--jalankan` it only REPORTS what it would do.
"""
import hashlib
import os
import posixpath
import sys

import config
import time

import paramiko

HOST = "192.168.56.156"
USER = "nsmapp"
SANDI = config.get_nsmapp_sandi()

LOKAL_AKAR = r"C:\Users\<user>\NSM"
REMOTE_AKAR = "/home/nsmapp/NSM"

CAKUPAN = [
    ("backend", "backend", (".py",)),
    # `.svg` and `.woff2` are included because the icon sprite and fonts ship inside the
    # `.jar`; without their sources on nsm-app, anyone reading the static folder there
    # would conclude the old sprite and system fonts are still in use.
    (os.path.join("frontend", "src"), "frontend/src",
     (".java", ".html", ".js", ".css", ".svg", ".woff2")),
]
LEWATI_FOLDER = {"venv", "__pycache__", ".git", "target", "node_modules"}
LEWATI_BERKAS = {"penyangga.db", "penyangga.db-shm", "penyangga.db-wal"}

# Files that are useless on the primary lab instance despite the .py extension: they
# touch real devices and only make sense when supervised.
LEWATI_KIRIM = {"injeksi_r1.py", "kirim_ke_nsmapp.py"}

JAR_LOKAL = os.path.join(LOKAL_AKAR, "frontend", "target")
# EXACT path used by the systemd unit, read from `systemctl cat nsm-frontend`, not guessed.
JAR_REMOTE = "/home/nsmapp/NSM/frontend/target/frontend-0.0.1-SNAPSHOT.jar"

LAYANAN_BACKEND = ["nsm-poller", "nsm-api"]
LAYANAN_FRONTEND = "nsm-frontend"

kering = "--jalankan" not in sys.argv


def judul(t):
    print()
    print("=" * 70)
    print(t)
    print("=" * 70)


def sidik_lokal(jalur):
    with open(jalur, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def kumpulkan_lokal(akar, ekstensi):
    hasil = {}
    for dirpath, dirnames, filenames in os.walk(akar):
        dirnames[:] = [d for d in dirnames if d not in LEWATI_FOLDER]
        for nama in filenames:
            if not nama.endswith(ekstensi):
                continue
            if nama in LEWATI_BERKAS or nama in LEWATI_KIRIM:
                continue
            full = os.path.join(dirpath, nama)
            rel = os.path.relpath(full, akar).replace("\\", "/")
            hasil[rel] = full
    return hasil


def fingerprint_remote(ssh, jalur):
    _i, o, _e = ssh.exec_command("sha256sum '%s' 2>/dev/null" % jalur)
    keluar = o.read().decode().strip()
    return keluar.split()[0] if keluar else None


def jalankan(ssh, perintah, tampilkan=True, sandi=None):
    _i, o, e = ssh.exec_command(perintah)
    if sandi is not None:
        _i.write(sandi + "\n")
        _i.flush()
    kode = o.channel.recv_exit_status()
    keluar = o.read().decode(errors="replace").strip()
    galat = e.read().decode(errors="replace").strip()
    if tampilkan:
        if keluar:
            for line in keluar.splitlines()[:12]:
                print("      | %s" % line)
        if galat and kode != 0:
            for line in galat.splitlines()[:8]:
                print("      ! %s" % line)
    return kode, keluar, galat


def sudo(ssh, perintah, tampilkan=True):
    """Run a command with sudo, feeding the password over stdin.

    `sudo` on `nsm-app` has no passwordless rule and a non-interactive SSH session has
    no TTY, so a plain `sudo systemctl restart` FAILS SILENTLY: it prints "a password is
    required" to stderr, exits non-zero, and nothing else happens. See
    `periksa_restart()` for why the check was fooled as well.
    """
    return jalankan(ssh, "sudo -S -p '' %s" % perintah, tampilkan=tampilkan,
                    sandi=SANDI)


def waktu_aktif(ssh, svc):
    _k, keluar, _e = jalankan(
        ssh, "systemctl show %s -p ActiveEnterTimestamp --value" % svc,
        tampilkan=False)
    return keluar.strip()


def periksa_restart(ssh, svc, sebelum):
    """True if the service really RESTARTED, not merely is alive.

    `systemctl is-active` says "active" for an old process that never stopped, so it
    cannot tell a successful restart from none at all. `ActiveEnterTimestamp` can: if it
    did not change, the service was never restarted, whatever `is-active` says.
    """
    _k, aktif, _e = jalankan(ssh, "systemctl is-active %s" % svc,
                             tampilkan=False)
    after = waktu_aktif(ssh, svc)
    return aktif.strip() == "active" and after != sebelum, aktif.strip(), after


def pastikan_folder(sftp, jalur):
    section = jalur.strip("/").split("/")
    current = ""
    for b in section:
        current += "/" + b
        try:
            sftp.stat(current)
        except IOError:
            sftp.mkdir(current)


def main():
    if kering:
        print("MODE LAPORAN — tidak ada yang dikirim.")
        print("Tambahkan --jalankan untuk benar-benar mengirim.")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=SANDI, timeout=15)
    sftp = ssh.open_sftp()
    summarize = []

    try:
        # ---------------------------------------------------------------
        judul("1. CADANGKAN .jar YANG SEDANG BERJALAN")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = "%s.sebelum-%s" % (JAR_REMOTE, stamp)
        kode, keluar, _ = jalankan(ssh, "ls -l '%s'" % JAR_REMOTE)
        if kode != 0:
            print("  [BERHENTI] .jar yang berjalan tidak ditemukan di %s"
                  % JAR_REMOTE)
            print("  Perbaiki dulu jalurnya sebelum melanjutkan.")
            return 1
        if not kering:
            k2, _, _ = jalankan(ssh, "cp -p '%s' '%s'" % (JAR_REMOTE, backup))
            if k2 != 0:
                print("  [BERHENTI] gagal mencadangkan .jar")
                return 1
            print("  Cadangan: %s" % backup)
        else:
            print("  akan dicadangkan ke: %s" % backup)
        summarize.append(("cadangan jar", backup))

        # ---------------------------------------------------------------
        judul("2. KIRIM BERKAS SUMBER (backend + frontend/src)")
        total_send = 0
        for sub_local, sub_remote, ekstensi in CAKUPAN:
            root_cause_local = os.path.join(LOKAL_AKAR, sub_local)
            root_cause_remote = posixpath.join(REMOTE_AKAR, sub_remote)
            local = kumpulkan_lokal(root_cause_local, ekstensi)
            print("\n  %s -> %s  (%d berkas)"
                  % (sub_local, root_cause_remote, len(local)))

            need = []
            for rel, full in sorted(local.items()):
                destination = posixpath.join(root_cause_remote, rel)
                if fingerprint_remote(ssh, destination) != sidik_lokal(full):
                    need.append((rel, full, destination))

            print("    %d berkas berbeda / belum ada" % len(need))
            for rel, full, destination in need:
                if kering:
                    print("      akan dikirim: %s" % rel)
                    continue
                pastikan_folder(sftp, posixpath.dirname(destination))
                sftp.put(full, destination)
                if fingerprint_remote(ssh, destination) != sidik_lokal(full):
                    print("      [GAGAL] sidik tidak cocok sesudah kirim: %s"
                          % rel)
                    return 1
                print("      terkirim: %s" % rel)
                total_send += 1
        summarize.append(("berkas sumber terkirim", total_send))

        # ---------------------------------------------------------------
        judul("3a. PUSTAKA BARU DI LAB")
        # The only new library installed: drain3 (log template mining).
        #
        # `river` is deliberately NOT installed: it drags in numpy and scipy (about 100 MB
        # more) for an EWMA formula that fits in roughly sixty lines. That formula is written
        # directly in `baseline.py`, and river serves only as the reference check in
        # `uji_baseline.py`, on the laptop.
        #
        # Network note: from `nsm-app`, DNS for pypi.org returns only IPv6 addresses and the
        # VM has no IPv6 route, so `curl https://pypi.org/simple/` fails even though the VM
        # has internet. `pip` uses IPv4 and works normally.
        if kering:
            print("  akan memastikan drain3 terpasang")
        else:
            kode, keluar, _ = jalankan(
                ssh, "cd %s/backend && ./venv/bin/python -c "
                     "\"import drain3; print(drain3.__file__)\" 2>/dev/null"
                     % REMOTE_AKAR)
            if kode == 0 and keluar.strip():
                print("  drain3 sudah terpasang: %s" % keluar.strip()[:70])
            else:
                print("  drain3 belum ada -- memasang...")
                kode2, keluar2, galat2 = jalankan(
                    ssh, "cd %s/backend && ./venv/bin/pip install --no-input "
                         "drain3 2>&1 | tail -5" % REMOTE_AKAR)
                print("    %s" % (keluar2 or galat2).strip()[:300])
                # "No error" is not proof of success: it is proven by IMPORTING the library, not by
                # pip's exit code.
                kode3, keluar3, _ = jalankan(
                    ssh, "cd %s/backend && ./venv/bin/python -c "
                         "\"import drain3; print('OK', drain3.__file__)\""
                         % REMOTE_AKAR)
                if kode3 == 0 and "OK" in keluar3:
                    print("    terpasang dan bisa diimpor: %s"
                          % keluar3.strip()[:70])
                else:
                    # NOT a failure that stops the deploy: `pola_log.py` reports plainly when drain3 is
                    # missing, and the rest of NSM does not depend on it.
                    print("    [PERINGATAN] drain3 TIDAK bisa diimpor di "
                          "nsm-app. Penambangan pola log (C2) akan mati")
                    print("    sendiri dan mengatakannya; sisa NSM tidak "
                          "terpengaruh.")

        # ---------------------------------------------------------------
        judul("3. MIGRASI BASIS DATA (menambah, tidak menghapus)")
        for skrip in ("migrate_pagar.py", "migrate_pemulih.py",
                      # Paket B (23 Agustus 2026)
                      "migrate_insiden.py",
                      "migrate_gejala_pulih_pada.py",
                      "migrate_notif_insiden.py",
                      # Paket C
                      "migrate_paket_c.py",
                      # Deliberately no `--tenant-bawaan`: assigning device ownership changes WHO can see
                      # what, which a deploy script should not decide silently. The column is created;
                      # filling it is a separate, conscious step.
                      "migrate_tenant.py",
                      "migrate_backup_laporan.py"):
            print("\n  %s" % skrip)
            if kering:
                print("    akan dijalankan")
                continue
            kode, _, _ = jalankan(
                ssh, "cd %s/backend && ./venv/bin/python %s"
                     % (REMOTE_AKAR, skrip))
            print("    kode keluar: %s" % kode)
            if kode != 0:
                print("    [PERINGATAN] migrasi mengembalikan kode bukan 0.")
                print("    Migrasi proyek ini bersifat idempoten (memakai")
                print("    inspect() lalu melewati yang sudah ada), jadi ini")
                print("    biasanya berarti 'sudah pernah dijalankan'.")

        # ---------------------------------------------------------------
        judul("4. RESTART LAYANAN BACKEND")
        for svc in LAYANAN_BACKEND:
            if kering:
                print("  akan restart: %s" % svc)
                continue
            sebelum = waktu_aktif(ssh, svc)
            sudo(ssh, "systemctl restart %s" % svc, tampilkan=False)
            time.sleep(4)
            ok, aktif, after = periksa_restart(ssh, svc, sebelum)
            print("  %-14s -> %s  (mulai aktif: %s)" % (svc, aktif, after))
            if not ok:
                print("    [GAGAL] layanan TIDAK benar-benar dimulai ulang.")
                print("    sebelum: %s" % sebelum)
                print("    sesudah: %s" % after)
                if sebelum == after:
                    print("    Waktunya tidak berubah -- perintah restart tidak")
                    print("    pernah dijalankan (biasanya sudo gagal), dan")
                    print("    lab masih menjalankan kode LAMA.")
                sudo(ssh, "journalctl -u %s -n 25 --no-pager" % svc)
                return 1

        # "active" only means the process is ALIVE, not that it ANSWERS. Ask the API for
        # real before moving on to the riskier part.
        print("\n  Memastikan API benar-benar menjawab...")
        # RETRIED: uvicorn needs a few seconds to bind its port after systemd says "active",
        # so a single probe right after restart can return 000 for a healthy API and abort a
        # deploy whose important steps all succeeded.
        keluar = ""
        for percobaan in range(1, 7):
            _k, keluar, _e = jalankan(
                ssh, "curl -s -o /dev/null -w '%{http_code}' "
                     "http://127.0.0.1:8000/devices", tampilkan=False)
            if keluar in ("200", "307", "401", "403"):
                break
            print("    percobaan %d/6 -> %s, menunggu..."
                  % (percobaan, keluar or "000"))
            time.sleep(4)
        print("    GET /devices -> HTTP %s" % (keluar or "tidak ada jawaban"))
        if keluar not in ("200", "307", "401", "403"):
            print("    [GAGAL] API tidak menjawab sebagaimana mestinya.")
            sudo(ssh, "journalctl -u nsm-api -n 30 --no-pager")
            return 1

        # ---------------------------------------------------------------
        judul("5. KIRIM .jar BARU")
        jar_new = None
        if os.path.isdir(JAR_LOKAL):
            candidate = [f for f in os.listdir(JAR_LOKAL)
                        if f.endswith(".jar") and "sources" not in f
                        and "original" not in f]
            if candidate:
                candidate.sort(
                    key=lambda f: os.path.getmtime(os.path.join(JAR_LOKAL, f)))
                jar_new = os.path.join(JAR_LOKAL, candidate[-1])
        if not jar_new:
            print("  [BERHENTI] tidak ada .jar hasil build di %s" % JAR_LOKAL)
            print("  Jalankan `mvnw package` dulu.")
            return 1
        mb = os.path.getsize(jar_new) / 1024 / 1024
        print("  sumber: %s (%.1f MB)" % (os.path.basename(jar_new), mb))
        jar_replaced = False
        if not kering and fingerprint_remote(ssh, JAR_REMOTE) == sidik_lokal(jar_new):
            print("  .jar di nsm-app SUDAH sama persis -- tidak dikirim ulang.")
        elif not kering:
            jar_replaced = True
            temporary = JAR_REMOTE + ".baru"
            sftp.put(jar_new, temporary)
            if fingerprint_remote(ssh, temporary) != sidik_lokal(jar_new):
                print("  [GAGAL] sidik .jar tidak cocok sesudah kirim.")
                jalankan(ssh, "rm -f '%s'" % temporary, tampilkan=False)
                return 1
            print("  terkirim dan sidiknya cocok")
            jalankan(ssh, "mv '%s' '%s'" % (temporary, JAR_REMOTE),
                     tampilkan=False)

        # ---------------------------------------------------------------
        judul("6. RESTART FRONTEND — langkah paling berisiko, paling akhir")
        if kering:
            print("  akan restart: %s (hanya kalau .jar-nya berubah)"
                  % LAYANAN_FRONTEND)
        elif not jar_replaced:
            # What runs on nsm-app is the `.jar`, not the sources on disk. If the jar did not
            # change, restarting the frontend changes nothing; it only logs everyone out and
            # makes the page unavailable for a few seconds.
            print("  .jar TIDAK berubah -> frontend tidak di-restart.")
            print("  Sumber frontend yang ikut terkirim hanya menyamakan disk")
            print("  dengan laptop; runtime-nya tetap .jar yang sama persis.")
        else:
            before_fe = waktu_aktif(ssh, LAYANAN_FRONTEND)
            sudo(ssh, "systemctl restart %s" % LAYANAN_FRONTEND,
                 tampilkan=False)
            aktif = False
            for _ in range(20):
                time.sleep(3)
                ok_fe, _a, after_fe = periksa_restart(
                    ssh, LAYANAN_FRONTEND, before_fe)
                if ok_fe:
                    aktif = True
                    break
            print("  %s -> %s" % (LAYANAN_FRONTEND,
                                  "dimulai ulang" if aktif else "GAGAL"))
            if not aktif:
                print("\n  [PEMULIHAN OTOMATIS] mengembalikan .jar lama...")
                jalankan(ssh, "cp -p '%s' '%s'" % (backup, JAR_REMOTE),
                         tampilkan=False)
                sudo(ssh, "systemctl restart %s" % LAYANAN_FRONTEND,
                     tampilkan=False)
                time.sleep(10)
                _k, keluar, _ = jalankan(
                    ssh, "systemctl is-active %s" % LAYANAN_FRONTEND,
                    tampilkan=False)
                print("  sesudah dibalik: %s" % keluar)
                sudo(ssh, "journalctl -u %s -n 30 --no-pager"
                     % LAYANAN_FRONTEND)
                return 1

        # ---------------------------------------------------------------
        judul("7. BUKTI KILL-SWITCH MASIH MATI")
        kode, keluar, _ = jalankan(
            ssh, "cd %s/backend && ./venv/bin/python -c \""
                 "import config;"
                 "print('daftar_putih=%%r' %% (config.get_pagar_daftar_putih(),));"
                 "print('gns3=%%s layanan=%%s interface=%%s konfig=%%s' %% ("
                 "config.get_pemulih_gns3_aktif(),"
                 "config.get_pemulih_layanan_aktif(),"
                 "config.get_pemulih_interface_aktif(),"
                 "config.get_pemulih_konfig_aktif()));"
                 # The SOC agent switch is proven too, not just the recovery. It decides whether an AI
                 # component may PROPOSE actions on network devices, and `AGEN_SOC_NARASI` decides
                 # whether device names and event sequences may be sent OUTSIDE the lab network.
                 #
                 # A deploy must not enable anything. If this line ever prints something other than
                 # `(False, 'usul', False)`, someone's decision changed, and that must show in the
                 # deploy output.
                 "print('agen_aktif=%%s agen_mode=%%r agen_narasi=%%s' %% ("
                 "config.get_agen_soc_aktif(),"
                 "config.get_agen_soc_mode(),"
                 "config.get_agen_soc_narasi()))\"" % REMOTE_AKAR)
        if kode != 0:
            print("  [PERINGATAN] tidak bisa memeriksa kill-switch.")
        elif "agen_aktif=False" not in (keluar or ""):
            # Stated LOUDLY, not printed quietly in the middle of the output.
            print("  " + "!" * 66)
            print("  PERHATIAN: AGEN_SOC_AKTIF di nsm-app TIDAK False.")
            print("  Agen SOC akan mulai menganalisis insiden dan mengusulkan")
            print("  tindakan. Pastikan itu memang keputusan yang diambil")
            print("  sadar oleh seseorang, bukan akibat sampingan deploy ini.")
            print("  " + "!" * 66)

        # Step 8: prove the source there equals the source here.
        #
        # `cek_sinkron_nsmapp.py` runs automatically on every deploy. Otherwise the `.jar` on
        # nsm-app could be newer than the sources there (or the reverse), and someone would
        # read code that is NOT what is running, with no error to warn them.
        #
        # A difference does NOT fail the send (the files are already delivered and the
        # services are up); it is reported loudly so it gets acted on.
        judul("8. SUMBER DI nsm-app == SUMBER DI LAPTOP  (P0.5)")
        try:
            import subprocess as _sp
            h = _sp.run([sys.executable, "cek_sinkron_nsmapp.py"],
                        cwd=os.path.dirname(os.path.abspath(__file__)),
                        capture_output=True, text=True, timeout=300)
            tail = [b for b in (h.stdout or "").splitlines() if b.strip()][-6:]
            for b in tail:
                print("      | " + b)
            if h.returncode == 0:
                print("  NOL perbedaan — yang berjalan di sana sama dengan yang dibaca di sini.")
                summarize.append(("sinkron sumber (P0.5)", "nol perbedaan"))
            else:
                print("  [PERHATIAN] ADA PERBEDAAN. Kode yang berjalan di nsm-app "
                      "TIDAK sama dengan yang ada di laptop.")
                print(r"  Jalankan: venv\Scripts\python.exe cek_sinkron_nsmapp.py")
                summarize.append(("sinkron sumber (P0.5)", "ADA PERBEDAAN — periksa"))
        except Exception as e:
            print("  [PERINGATAN] pemeriksa sinkron tidak bisa dijalankan: %s"
                  % str(e)[:140])
            summarize.append(("sinkron sumber (P0.5)", "tidak terperiksa"))

        judul("RINGKAS")
        for k, v in summarize:
            print("  %-26s %s" % (k, v))
        print("\n  Untuk membalik .jar secara manual:")
        print("    ssh %s@%s" % (USER, HOST))
        print("    cp -p '%s' '%s'" % (backup, JAR_REMOTE))
        print("    sudo systemctl restart %s" % LAYANAN_FRONTEND)
        return 0

    finally:
        sftp.close()
        ssh.close()


if __name__ == "__main__":
    sys.exit(main())

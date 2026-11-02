"""CI runner: run tests unattended and report only when something is RED.

Unlike `jalankan_semua_uji.py` (interactive, runs and prints everything), this is
meant for a scheduler:

    * It uses `ci_manifest.json` (produced by `ci_klasifikasi.py`) to select a tier.
      Tests that need the live lab are excluded from `murni` mode, so CI does not
      go red every time a lab VM is powered off; an alarm that is always on stops
      being read.
    * It stays quiet when everything is green.
    * Its exit code is meaningful, so the scheduler can act on it.

MODES
-----
    murni   (default)  only tests proven not to need outbound network access.
                       Suitable for daily/per-commit runs.
    lab                only tests that need live lab devices. Run when the lab
                       is actually up, not on a blind schedule.
    `semua`            both.

    venv\\Scripts\\python.exe jalankan_ci.py            # murni mode
    venv\\Scripts\\python.exe jalankan_ci.py --mode lab
    venv\\Scripts\\python.exe jalankan_ci.py `--keluar-berkas` hasil.txt

EXIT CODES: 0 = all green. 1 = something red. 2 = manifest missing.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(DIR, "ci_manifest.json")
BATAS_DETIK = 300

# Some tests legitimately take longer; a single limit for all of them only produces
# meaningless red runs. `uji_pulih_incremental` restores a real database with over a
# million rows into a scratch database and compares row counts per table, which
# takes time by design. A CI that fails on its own timeouts trains people to ignore it.
BATAS_KHUSUS = {
    "uji_pulih_incremental.py": 900,
    # A full run takes about 280 s (mysqldump of the primary lab instance + restore into a
    # scratch database + compare 6 tables). The general limit would cut it off, and the CI
    # classifier would record it as RED and drop it from every mode.
    "uji_pulih_backup.py": 900,
}


def batas_untuk(berkas):
    return BATAS_KHUSUS.get(os.path.basename(berkas), BATAS_DETIK)


def muat_manifest():
    if not os.path.exists(MANIFEST):
        print("BERHENTI: %s belum ada." % MANIFEST)
        print("Jalankan dulu:  venv\\Scripts\\python.exe ci_klasifikasi.py")
        sys.exit(2)
    with open(MANIFEST, encoding="utf-8") as f:
        return json.load(f)


def tak_terklasifikasi(m):
    """`uji_*.py` files on disk that are in none of the buckets.

    Such files would never be run by CI nor appear in its report, a silent false green.
    The list is compared directly against the folder contents.
    """
    recorded = set()
    for kunci in ("murni", "butuh_lab", "merah_saat_diukur",
                  "tidak_terukur", "dikecualikan"):
        value = m.get(kunci) or []
        recorded |= set(value)

    at_disk = set(os.path.basename(x)
                  for x in glob.glob(os.path.join(DIR, "uji_*.py")))
    return sorted(at_disk - recorded)


def run_one(berkas):
    t = time.time()
    limit = batas_untuk(berkas)
    try:
        # `-X utf8` forces the child to write UTF-8, and `errors="replace"` keeps decoding
        # intact if stray bytes appear (e.g. cp1252 output from mysqldump or net.exe).
        #
        # Without both, a single 0x97 byte silently kills the subprocess reader thread
        # (`tanpa` = without):
        #     tanpa encoding: stdout = None,                kode = 1
        #     with encoding : stdout = "before � after", kode = 1
        #
        # `subprocess.run` still returns normally, `(h.stdout or "")` becomes an empty string,
        # and the report says "MERAH: uji_x" with no output, exactly where it matters most.
        h = subprocess.run([sys.executable, "-X", "utf8", berkas], cwd=DIR,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=limit)
        return h.returncode == 0, (h.stdout or "") + (h.stderr or ""), time.time() - t
    except subprocess.TimeoutExpired as e:
        output = ((e.stdout or "") + (e.stderr or ""))
        if isinstance(output, bytes):
            output = output.decode("utf-8", "replace")
        return False, output + "\n[CI] kehabisan waktu %d detik" % BATAS_DETIK, BATAS_DETIK


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["murni", "lab", "semua"], default="murni")
    p.add_argument("--keluar-berkas", default=None,
                   help="tulis laporan ke berkas (untuk penjadwal)")
    p.add_argument("--verbose", action="store_true",
                   help="cetak juga yang hijau, bukan cuma yang merah")
    arg = p.parse_args()

    m = muat_manifest()
    if arg.mode == "murni":
        daftar = m["murni"]
    elif arg.mode == "lab":
        daftar = m["butuh_lab"]
    else:
        daftar = m["murni"] + m["butuh_lab"]

    start = time.time()
    line = []

    def catat(s):
        line.append(s)
        print(s)

    catat("CI NSM -- mode '%s', %d berkas uji, %s"
          % (arg.mode, len(daftar), time.strftime("%Y-%m-%d %H:%M:%S")))
    catat("Manifest diukur: %s" % m.get("dibuat", "?"))
    catat("")

    hijau, merah = [], []
    for b in daftar:
        ok, output, dtk = run_one(b)
        if ok:
            hijau.append(b)
            if arg.verbose:
                catat("  HIJAU  %-34s %5.1f dtk" % (b, dtk))
        else:
            merah.append((b, output))
            catat("  MERAH  %-34s %5.1f dtk" % (b, dtk))

    catat("")
    catat("=" * 70)
    catat("%d hijau, %d MERAH  (%.0f detik)"
          % (len(hijau), len(merah), time.time() - start))
    catat("=" * 70)

    # Print failing output in full, not just the file name, so nobody has to rerun the
    # test by hand to see what failed.
    for b, output in merah:
        catat("")
        catat("-" * 70)
        catat("MERAH: %s" % b)
        catat("-" * 70)
        for l in [x for x in output.splitlines() if x.strip()][-30:]:
            catat("  " + l)

    # Reported before the green/red summary and also fails the exit code; a warning
    # buried in long CI output is never read, and the scheduler only sees the exit code.
    not_yet = tak_terklasifikasi(m)
    if not_yet:
        catat("")
        catat("!" * 70)
        catat("%d berkas uji ADA DI DISK tetapi tidak ada di manifest, jadi"
              % len(not_yet))
        catat("TIDAK IKUT DIJALANKAN dan tidak terhitung di angka mana pun")
        catat("di atas. Angka hijau di atas benar tentang yang dijalankan,")
        catat("dan menyesatkan tentang yang diperiksa.")
        catat("")
        for b in not_yet:
            catat("    %s" % b)
        catat("")
        catat("Ukur ulang:  venv\\Scripts\\python.exe ci_klasifikasi.py")
        catat("!" * 70)

    if m.get("merah_saat_diukur"):
        catat("")
        catat("Catatan: %d berkas sudah MERAH sejak manifest diukur "
              "(tidak ikut dijalankan di mode mana pun): %s"
              % (len(m["merah_saat_diukur"]), ", ".join(m["merah_saat_diukur"])))

    if arg.keluar_berkas:
        with open(arg.keluar_berkas, "w", encoding="utf-8") as f:
            f.write("\n".join(line) + "\n")
        print("\nLaporan ditulis ke %s" % arg.keluar_berkas)

    # A stale manifest fails CI; a mere warning would be ignored.
    return 1 if (merah or not_yet) else 0


if __name__ == "__main__":
    sys.exit(main())

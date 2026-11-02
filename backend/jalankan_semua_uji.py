"""Run every `uji_*.py` file and summarize the results.

Pass/fail is decided by the exit code, NOT by the word "LOLOS" in the output: a test
that crashes with a traceback prints nothing, and searching the output would read
that as "nothing failed".

Some tests need other machines up (LDAP, SSH, GNS3). On failure an excerpt of the
output is printed, not just the file name, so a code defect can be told apart from
a server that is down without rerunning.
"""
import glob
import os
import subprocess
import sys
import time

DIR = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

# Tests in `BERBAHAYA` (below) change real devices; they are skipped unless `--semua`
# is given, so a full run never silently blocks addresses on the firewall or sends
# commands to routers.
#
# Per-file limit: 1800 s. `uji_ldap_hidup.py` takes 675-880 s on an idle machine and
# can exceed 900 s under load; a tight limit would turn healthy tests red.
BATAS_DETIK = 1800


class _Hasil:
    """Minimal stand-in for a `subprocess.run` result, used for tests that hang.

    Lets the reporting code treat failed and hung tests the same way.
    """

    def __init__(self, keluaran, sebab):
        self.stdout = keluaran
        self.stderr = "\n[runner] " + sebab
        self.returncode = -1


BERBAHAYA = {
    "uji_ubah_firewall.py",
    "uji_kirim_perintah.py",
    # Cuts port 3306 on .103 and restores it. The restore lives in a `finally` block,
    # but `finally` does not run if the process is killed, which would leave the NSM
    # database unreachable. So this test is only run deliberately, on its own.
    "uji_penyangga.py",
}


def main():
    semua = "--semua" in sys.argv
    file = sorted(os.path.basename(p)
                    for p in glob.glob(os.path.join(DIR, "uji_*.py")))

    passed, fail, skipped = [], [], []
    start = time.time()

    for nama in file:
        if nama in BERBAHAYA and not semua:
            skipped.append(nama)
            print("  LEWAT  %-28s (mengubah perangkat; pakai --semua)" % nama)
            continue

        t = time.time()
        # Catch timeouts instead of letting them propagate: an uncaught `TimeoutExpired`
        # would kill the runner and silently skip every remaining test, leaving a result
        # list that looks complete but is not.
        try:
            hasil = subprocess.run([PY, "-X", "utf8", nama], cwd=DIR,
                                   capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   timeout=BATAS_DETIK)
        except subprocess.TimeoutExpired as e:
            second = time.time() - t
            keluaran = ((e.stdout or "") + (e.stderr or ""))
            fail.append((nama, _Hasil(keluaran,
                                       "kehabisan waktu %d detik" % BATAS_DETIK)))
            print("  MACET  %-28s %5.1f dtk  (batas %d dtk)"
                  % (nama, second, BATAS_DETIK))
            continue

        second = time.time() - t
        if hasil.returncode == 0:
            passed.append(nama)
            print("  LOLOS  %-28s %5.1f dtk" % (nama, second))
        else:
            fail.append((nama, hasil))
            print("  GAGAL  %-28s %5.1f dtk  (keluar %d)"
                  % (nama, second, hasil.returncode))

    print()
    print("=" * 74)
    print("%d lolos, %d gagal, %d dilewati  (%.0f detik)"
          % (len(passed), len(fail), len(skipped), time.time() - start))
    print("=" * 74)

    for nama, hasil in fail:
        print()
        print("-" * 74)
        print("GAGAL: %s" % nama)
        print("-" * 74)
        keluaran = (hasil.stdout or "") + (hasil.stderr or "")
        line = [b for b in keluaran.splitlines() if b.strip()]
        for b in line[-25:]:
            print("  " + b)

    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())

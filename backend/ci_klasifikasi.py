"""Measure which tests need the LIVE LAB and which can run anywhere.

Measured, not hand-listed. Guessing from file contents ("imports paramiko
means it needs the lab") is wrong both ways: a file importing paramiko may
inject a fake, and a file importing nothing may reach MySQL via `SessionLocal`.
A grep attempt flagged 30 of 72 files, clearly too many to trust.

Method: run each test file TWICE, once normally and once with ALL outbound
network connections BLOCKED. A file that still passes when blocked is PURE;
one that fails needs the lab. That is evidence rather than a guess, and it
stays correct when a test later changes.

Blocking: `socket.socket.connect` is patched to raise for non-loopback
addresses. Loopback stays allowed because some tests use a fake server on
`127.0.0.1`, which needs no lab. The patch is applied through `sitecustomize.py`
in a temporary folder added to `PYTHONPATH`; Python imports it automatically
before the test runs, so none of the test files need changes.

The result is written to `ci_manifest.json`, read by `jalankan_ci.py`.

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\python.exe ci_klasifikasi.py
"""
import glob
import json
import os
import subprocess
import sys
import tempfile
import time

DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(DIR, "ci_manifest.json")

# There is deliberately NO `BATAS_DETIK` here. Two files governing the same
# thing drift apart, and here that was costly: a test that timed out was
# recorded "MERAH" and dropped from ALL CI modes forever. The timeout is
# borrowed via `batas_untuk()` below; to change it, change `jalankan_ci.py`, the
# single place for both tools.

# Tests deliberately NEVER run automatically, whatever the measurement says,
# because both CHANGE real state outside the test process.
DIKECUALIKAN = {
    # Temporarily cuts port 3306 on .103 and restores it. If interrupted midway
    # (e.g. CI killed), the port stays closed.
    "uji_penyangga.py",
    # Runs all the other test files; if registered, CI would run everything twice,
    # nested.
    "jalankan_semua_uji.py",
    # FLAKY, and the automatic measurement cannot catch it. It passed twice while
    # measured, including with the network blocked, then went RED minutes later in
    # real CI with the same failures seen earlier that day (an SSH login and an
    # LDAP authentication on .103).
    #
    # The cause is not NSM code: LDAP authentication through sssd on .103 sometimes
    # answers and sometimes does not. The measurement blocks the SOCKET, and a
    # paramiko that fails to connect can still end up "passing" on certain test
    # paths, so it reads as PURE though it clearly needs the lab.
    #
    # Excluded, NOT moved to the `butuh_lab` tier: even there it would be red half
    # the time and train people to ignore CI reports. It can still be run by hand.
    # The real fix is sssd stability on .103, separate from CI work.
    "uji_ldap_ssh.py",
}

PENAMBAL = '''
import socket as _s

_asli = _s.socket.connect
_asli_ex = _s.socket.connect_ex


def _lokal(alamat):
    try:
        tuan = alamat[0]
    except Exception:
        return True
    return tuan in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def _blokir(self, alamat, *a, **kw):
    if not _lokal(alamat):
        raise OSError("CI: koneksi keluar diblokir (%r)" % (alamat,))
    return _asli(self, alamat, *a, **kw)


def _blokir_ex(self, alamat, *a, **kw):
    if not _lokal(alamat):
        return 1
    return _asli_ex(self, alamat, *a, **kw)


_s.socket.connect = _blokir
_s.socket.connect_ex = _blokir_ex
'''


# ONE SOURCE OF TRUTH for timeouts, borrowed from the runner. The measurer used
# a flat 180 s while `jalankan_ci.py` holds a special 900 s limit for the backup
# restore tests, so it sent tests the runner had already provisioned for into
# the "red" bucket.
from jalankan_ci import batas_untuk


# Special value for "timed out". NOT False: a test cut off midway was never
# shown to fail, and conflating the two is a measurement failure read as a result.
TIDAK_TERUKUR = "tidak_terukur"


def jalankan(berkas, env):
    t = time.time()
    limit = batas_untuk(berkas)
    try:
        h = subprocess.run([sys.executable, "-X", "utf8", berkas], cwd=DIR,
                           env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=limit)
        return h.returncode == 0, round(time.time() - t, 1)
    except subprocess.TimeoutExpired:
        return TIDAK_TERUKUR, limit


def _keranjang_bersih(data, nama):
    """Remove `nama` from every bucket so it is never recorded twice with two verdicts."""
    for k in ("murni", "butuh_lab", "merah_saat_diukur", "tidak_terukur"):
        if nama in (data.get(k) or []):
            data[k] = [x for x in data[k] if x != nama]
    return data


def main():
    # `--berkas a.py b.py` re-measures only SOME files and merges into the existing
    # manifest. A full measurement takes about 40 minutes; if updating one changed
    # file means waiting that long, people skip re-measuring and the manifest goes
    # stale.
    sebagian = []
    if "--berkas" in sys.argv:
        sebagian = [a for a in sys.argv[sys.argv.index("--berkas") + 1:]
                    if not a.startswith("-")]

    file_test = sorted(os.path.basename(p)
                        for p in glob.glob(os.path.join(DIR, "uji_*.py")))
    file_test = [b for b in file_test if b not in DIKECUALIKAN]

    if sebagian:
        not_exists = [b for b in sebagian if b not in file_test]
        if not_exists:
            print("BERHENTI: bukan berkas uji yang bisa diukur: %s"
                  % ", ".join(not_exists))
            print("(mungkin salah ketik, atau ada di DIKECUALIKAN)")
            return 2
        file_test = [b for b in file_test if b in sebagian]
        print("Mengukur ULANG %d berkas saja; sisanya dibiarkan apa adanya.\n"
              % len(file_test))

    folder = tempfile.mkdtemp(prefix="ci_blokir_")
    with open(os.path.join(folder, "sitecustomize.py"), "w") as f:
        f.write(PENAMBAL)

    env_block = dict(os.environ)
    env_block["PYTHONPATH"] = folder + os.pathsep + env_block.get("PYTHONPATH", "")

    murni, butuh_lab, broken, tak_terukur = [], [], [], []
    print("Mengukur %d berkas uji (masing-masing 2x jalan)...\n" % len(file_test))

    for i, b in enumerate(file_test, 1):
        ok_normal, dtk1 = jalankan(b, dict(os.environ))
        ok_block, dtk2 = jalankan(b, env_block)

        if TIDAK_TERUKUR in (ok_normal, ok_block):
            # TIMED OUT, not failed. A test cut off midway was never shown to fail, and
            # putting it in the "red" bucket would drop it from ALL CI modes permanently.
            # It goes in `butuh_lab` so it still RUNS (modes 'lab' and 'semua', with a looser
            # limit), and is recorded separately so it stays visible in the report.
            tak_terukur.append(b)
            butuh_lab.append(b)
            mark = "TAK TERUKUR"
        elif ok_normal and ok_block:
            murni.append(b)
            mark = "MURNI    "
        elif ok_normal and not ok_block:
            butuh_lab.append(b)
            mark = "BUTUH LAB"
        else:
            # Fails even with the network AVAILABLE: not a tier issue, this test is really
            # red. Recorded separately so it is not silently counted as "needs lab".
            broken.append(b)
            mark = "MERAH    "

        print("  [%2d/%d] %s %-34s %.0f+%.0f dtk"
              % (i, len(file_test), mark, b, dtk1, dtk2))

    if sebagian:
        # Merge into the old manifest: what was NOT re-measured must stay intact.
        # Overwriting with a partial measurement would erase about 90 other files.
        with open(MANIFEST, encoding="utf-8") as f:
            data = json.load(f)
        for b in file_test:
            _keranjang_bersih(data, b)
        for kunci, content in (("murni", murni), ("butuh_lab", butuh_lab),
                           ("merah_saat_diukur", broken),
                           ("tidak_terukur", tak_terukur)):
            data[kunci] = sorted(set((data.get(kunci) or []) + content))
        data["dibuat"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        data["dikecualikan"] = sorted(DIKECUALIKAN)
        with open(MANIFEST, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print()
        print("%d berkas diukur ulang dan disatukan ke %s"
              % (len(file_test), MANIFEST))
        for b in file_test:
            at = [k for k in ("murni", "butuh_lab", "merah_saat_diukur",
                              "tidak_terukur") if b in data.get(k, [])]
            print("   %-34s -> %s" % (b, ", ".join(at) or "(tidak masuk mana pun)"))
        return 0

    data = {
        "dibuat": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "murni": murni,
        "butuh_lab": butuh_lab,
        "merah_saat_diukur": broken,
        "tidak_terukur": tak_terukur,
        "dikecualikan": sorted(DIKECUALIKAN),
    }
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 74)
    print("MURNI (bisa jalan di CI mana pun) : %d" % len(murni))
    print("BUTUH LAB (perlu perangkat hidup) : %d" % len(butuh_lab))
    print("MERAH saat diukur                 : %d" % len(broken))
    print("TIDAK TERUKUR (kehabisan waktu)   : %d" % len(tak_terukur))
    print("Dikecualikan (efek samping)       : %d" % len(DIKECUALIKAN))
    print("=" * 74)
    print("Ditulis ke %s" % MANIFEST)
    if broken:
        print("\nYang MERAH (gagal walau jaringan tersedia -- periksa ini):")
        for b in broken:
            print("   - %s" % b)
    if tak_terukur:
        print("\nYang TIDAK TERUKUR (kehabisan waktu, BUKAN gagal):")
        for b in tak_terukur:
            print("   - %s (batas %d dtk)" % (b, batas_untuk(b)))
        print("Naikkan batasnya di BATAS_KHUSUS pada jalankan_ci.py kalau "
              "uji ini memang panjang.")


if __name__ == "__main__":
    # Exit code is meaningful: 2 = wrong file name given to --berkas.
    sys.exit(main() or 0)

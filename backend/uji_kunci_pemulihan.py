"""Test of the recovery lock, which serializes tests that share one dump database.

Two restores running at once against the same dump database delete each other's
data mid-run and produce false failures that accuse an intact backup. The old
lock was never acquired when stale (it wrote the pid but never read it), and
after waiting 15 minutes it ran without the lock anyway.

The tests are deliberately paired: a lock whose holder died must be TAKEN OVER,
and a lock whose holder is ALIVE must NOT be. Proving only the first would pass
a class that takes any lock.

Touches no network, database, or device. Safe at any time.

Run: py uji_kunci_pemulihan.py
"""
import os
import subprocess
import sys
import time

from uji_pulih_backup import KunciPemulihan, _proses_hidup

lolos = 0
gagal = 0


def cek(nama, dapat, harap):
    global lolos, gagal
    if dapat == harap:
        lolos += 1
        print("  LOLOS  %s: %r" % (nama, dapat))
    else:
        gagal += 1
        print("  GAGAL  %s: dapat %r, harusnya %r" % (nama, dapat, harap))


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print("  LOLOS  %s" % nama)
    else:
        gagal += 1
        print("  GAGAL  %s %s" % (nama, ket))


def _pid_mati():
    """A pid that certainly no longer exists: a process that just finished.

    A made-up number like 999999 would test the "invalid pid" path, not the "pid
    existed and died" path that occurs when a test is killed midway.
    """
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    time.sleep(0.3)
    return p.pid


def nama_uji(sufiks):
    return "ujikunci-%d-%s" % (os.getpid(), sufiks)


def _hapus(jalur):
    try:
        os.remove(jalur)
    except OSError:
        pass


print("=" * 74)
print("Uji KunciPemulihan -- giliran memakai basis data pembuangan")
print("=" * 74)

# ---------------------------------------------------------------------------
print("\n1. `_proses_hidup` menjawab benar untuk ketiga arah")

cek("proses sendiri terbaca hidup", _proses_hidup(os.getpid()), True)

mati = _pid_mati()
cek("proses yang baru saja selesai terbaca MATI (pid %d)" % mati,
    _proses_hidup(mati), False)

# "Unknown" is deliberately distinguished from "dead": answering "dead" when
# unsure would take the lock from a running process.
cek("pid 0 dijawab 'tidak bisa dipastikan', bukan 'mati'",
    _proses_hidup(0), None)
cek("pid None dijawab 'tidak bisa dipastikan'", _proses_hidup(None), None)

# ---------------------------------------------------------------------------
print("\n2. Jalur mulus: kunci bisa diambil, lalu dilepas")
k = KunciPemulihan(nama_uji("mulus"))
k.__enter__()
benar("kunci didapat", k.dipegang)
benar("berkas kuncinya benar-benar ada di disk", os.path.exists(k.jalur))
cek("isinya pid proses ini", k._pemilik(), os.getpid())
k.__exit__(None, None, None)
benar("berkas kunci hilang sesudah dilepas", not os.path.exists(k.jalur))

# ---------------------------------------------------------------------------
print("\n3. CACAT 23 AGUSTUS: kunci milik proses MATI harus direbut, cepat")
k2 = KunciPemulihan(nama_uji("basi"))
with open(k2.jalur, "w", encoding="utf-8") as f:
    f.write(str(_pid_mati()))

umur = time.time() - os.path.getmtime(k2.jalur)
benar("kunci ujinya memang MUDA (%.1f dtk, jauh di bawah batas basi %d)"
      % (umur, KunciPemulihan.BATAS_BASI), umur < 60)

t0 = time.time()
k2.__enter__()
lama = time.time() - t0
benar("kunci direbut", k2.dipegang)
benar("direbut SEKETIKA, bukan sesudah menunggu (%.2f dtk)" % lama, lama < 3.0,
      "-> masih menunggu berarti pid-nya lagi-lagi tidak dibaca")
cek("pemiliknya sekarang proses ini", k2._pemilik(), os.getpid())
k2.__exit__(None, None, None)

# ---------------------------------------------------------------------------
print("\n4. ARAH SEBALIKNYA: kunci milik proses HIDUP TIDAK BOLEH direbut")
k3 = KunciPemulihan(nama_uji("hidup"))
penghuni = subprocess.Popen([sys.executable, "-c",
                             "import time; time.sleep(60)"])
try:
    with open(k3.jalur, "w", encoding="utf-8") as f:
        f.write(str(penghuni.pid))
    benar("pemegangnya benar-benar hidup", _proses_hidup(penghuni.pid) is True)

    # The wait is shortened so the test finishes in seconds; behavior is tested, not duration.
    asli = KunciPemulihan.TUNGGU_DETIK
    KunciPemulihan.TUNGGU_DETIK = 6
    try:
        t0 = time.time()
        k3.__enter__()
        lama = time.time() - t0
    finally:
        KunciPemulihan.TUNGGU_DETIK = asli

    benar("kunci TIDAK didapat (pemegangnya masih bekerja)", not k3.dipegang,
          "-> kunci direbut dari proses yang masih hidup")
    benar("benar-benar menunggu dulu (%.1f dtk), bukan langsung menyerah"
          % lama, lama >= 5.0)

    # It also must not delete another holder's lock file when giving up.
    k3.__exit__(None, None, None)
    benar("berkas kunci milik proses lain TIDAK dihapus",
          os.path.exists(k3.jalur))
    cek("dan isinya masih pid pemegang aslinya", k3._pemilik(), penghuni.pid)
finally:
    penghuni.kill()
    penghuni.wait()
    _hapus(k3.jalur)

# ---------------------------------------------------------------------------
print("\n5. Jaring TERAKHIR: pid tak terbaca + umur lewat batas -> direbut")
# If the pid cannot be read at all (empty file, file from another machine), the
# age limit is the last-resort safety net, not the first determinant.
k4 = KunciPemulihan(nama_uji("takterbaca"))
with open(k4.jalur, "w", encoding="utf-8") as f:
    f.write("bukan angka")
cek("pemiliknya tidak terbaca", k4._pemilik(), None)
tua = time.time() - (KunciPemulihan.BATAS_BASI + 60)
os.utime(k4.jalur, (tua, tua))
t0 = time.time()
k4.__enter__()
lama = time.time() - t0
benar("kunci basi tanpa pid direbut", k4.dipegang)
benar("dan tetap cepat (%.2f dtk)" % lama, lama < 3.0)
k4.__exit__(None, None, None)

# The counterpart, so the age limit does not silently become "take any lock":
k5 = KunciPemulihan(nama_uji("mudataktbaca"))
with open(k5.jalur, "w", encoding="utf-8") as f:
    f.write("bukan angka")
asli = KunciPemulihan.TUNGGU_DETIK
KunciPemulihan.TUNGGU_DETIK = 6
try:
    k5.__enter__()
finally:
    KunciPemulihan.TUNGGU_DETIK = asli
benar("kunci MUDA tanpa pid TIDAK direbut", not k5.dipegang,
      "-> berkas kunci yang baru dibuat proses lain diambil begitu saja")
k5.__exit__(None, None, None)
benar("dan berkasnya tidak dihapus", os.path.exists(k5.jalur))
_hapus(k5.jalur)

print()
print("=" * 74)
print("%d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

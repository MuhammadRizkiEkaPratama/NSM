"""Prove that backups can be restored, on a schedule, and record the result.
Runs the two existing tests (`uji_pulih_backup.py`: full daily archive; `uji_pulih_incremental.py`: incremental parent), each restoring into a scratch database, comparing row counts with the live one, then dropping it. No row of the live database is touched.
The result is written where the Health page reads it; a restore test nobody sees is the same as one that does not run.
Run manually: venv\\Scripts\\python.exe verifikasi_pulih.py
"""
import json
import os
import subprocess
import sys
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))

# Written here and read by `kesehatan._pemulihan_backup()`. A plain file, not a database row, so it stays readable if the database itself is broken.
HASIL = os.path.join(DIR, "verifikasi-pulih-terakhir.json")

UJI = ["uji_pulih_backup.py", "uji_pulih_incremental.py"]

# Restoring millions of rows is slow by nature, so the limit is looser than normal CI.
BATAS_DETIK = 1800


def jalankan(berkas):
    start = datetime.now()
    try:
        h = subprocess.run([sys.executable, berkas], cwd=DIR,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=BATAS_DETIK)
        keluar = (h.stdout or "") + (h.stderr or "")
        return {
            "berkas": berkas,
            "lolos": h.returncode == 0,
            "kode": h.returncode,
            "detik": round((datetime.now() - start).total_seconds(), 1),
            # Only the summary is kept, so this file does not grow without bound.
            "ringkas": _baris_hasil(keluar),
        }
    except subprocess.TimeoutExpired:
        return {"berkas": berkas, "lolos": False, "kode": None,
                "detik": BATAS_DETIK,
                "ringkas": "kehabisan waktu %d detik" % BATAS_DETIK}
    except Exception as e:
        return {"berkas": berkas, "lolos": False, "kode": None, "detik": None,
                "ringkas": "gagal dijalankan: %s" % str(e)[:160]}


def _baris_hasil(teks):
    for line in reversed((teks or "").splitlines()):
        if "HASIL:" in line:
            return line.strip()
    return (teks or "").strip().splitlines()[-1:] and \
        (teks or "").strip().splitlines()[-1][:160] or "(tanpa keluaran)"


def ram_bebas_mb():
    """Free physical RAM on the host in MB, or None if unreadable."""
    try:
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        s = Status()
        s.dwLength = ctypes.sizeof(Status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
            return None
        return int(s.ullAvailPhys / 1024 / 1024)
    except Exception:
        return None


RAM_MIN_MB = 1536


def main():
    # Host load guard. The restore tests load the machine heavily, and the same host runs six VMs. Running them with only 1-2 GB of host RAM free once hung `nsm-app` completely (kernel workqueue starvation, including the NIC watchdog). When the host is tight, this check postpones itself and records why instead of forcing a run.
    bebas = ram_bebas_mb()
    if bebas is not None and bebas < RAM_MIN_MB:
        catatan = {
            "waktu": datetime.now().isoformat(),
            "semua_lolos": None,
            "ditunda": True,
            "alasan": ("Sisa RAM host cuma %d MB (batas %d MB). Uji pemulihan "
                       "memulihkan jutaan baris dan pernah membuat VM nsm-app "
                       "menggantung total saat host sesak. Ditunda sampai "
                       "jadwal berikutnya." % (bebas, RAM_MIN_MB)),
            "hasil": [],
        }
        with open(HASIL, "w", encoding="utf-8") as f:
            json.dump(catatan, f, indent=2, ensure_ascii=False)
        print("DITUNDA: " + catatan["alasan"])
        return 0

    print("=" * 70)
    print("VERIFIKASI PEMULIHAN BACKUP  %s"
          % datetime.now().strftime("%d %B %Y %H:%M:%S"))
    print("=" * 70)

    hasil = []
    for berkas in UJI:
        print("\n-> %s" % berkas)
        r = jalankan(berkas)
        hasil.append(r)
        print("   %s  (%s detik)  %s"
              % ("LOLOS" if r["lolos"] else "GAGAL", r["detik"], r["ringkas"]))

    semua_lolos = all(r["lolos"] for r in hasil)
    catatan = {
        "waktu": datetime.now().isoformat(),
        "semua_lolos": semua_lolos,
        "hasil": hasil,
    }
    with open(HASIL, "w", encoding="utf-8") as f:
        json.dump(catatan, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 70)
    print("%s  — dicatat di %s"
          % ("SEMUA LOLOS" if semua_lolos else "ADA YANG GAGAL",
             os.path.basename(HASIL)))
    print("=" * 70)
    return 0 if semua_lolos else 1


if __name__ == "__main__":
    sys.exit(main())

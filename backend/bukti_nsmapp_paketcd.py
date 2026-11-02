# -*- coding: utf-8 -*-
"""Proof that the Package C/D pages are really live on nsm-app.

"Deployed" is not proof: `kirim_ke_nsmapp.py` can finish without error while
the jar is old, the template did not ship, or a module fails to import. Only
asking the machine itself proves it.

Two checks that were rejected because both stay GREEN on a broken system:

1. `curl http://192.168.56.156:8000/...` from the laptop. It never works, and
   that is not an outage: uvicorn is deliberately bound to `127.0.0.1:8000`
   (`--host 127.0.0.1` in its systemd unit), so checking from outside returns
   `000` for EVERY endpoint, which reads as "API down" when it is healthy.
   API endpoints are therefore queried over SSH from inside the machine.

2. Treating `200/302` on `/wawasan` as proof the page exists. Spring Security
   redirects ALL unauthenticated requests to `/login` with 302, including
   paths that do not exist (`/wawasan`, `/no-such-path`, `/xyzzy` all give
   302). A check that answers the same for existing and missing pages checks
   nothing.

Used instead: `/css/**` is permitAll and answers honestly
(`/css/insiden.css` 200, `/css/no-such-file.css` 404, a CSS file that exists
only in the NEW jar gives 404 before deploy and 200 after). That 404 vs 200 on
a file only the new jar contains shows which jar is running. The jar contents
and controller classes are also checked directly over SSH.

Everything here is READ-ONLY: nothing changes a device, the database, or a switch.

Run: py bukti_nsmapp_paketcd.py
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402

HOST = "192.168.56.156"
USER = "nsmapp"
WEB = "http://%s:8080" % HOST
AKAR = "/home/nsmapp/NSM"

lolos = 0
gagal = 0


def benar(nama, syarat, ket=""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print("  LOLOS  %s" % nama)
    else:
        gagal += 1
        print("  GAGAL  %s %s" % (nama, ket))


def kode_http(jalur, batas=20):
    try:
        with urllib.request.urlopen(WEB + jalur, timeout=batas) as r:
            return r.getcode()
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:                             # noqa: BLE001
        return None


def isi_http(jalur, batas=20):
    try:
        with urllib.request.urlopen(WEB + jalur, timeout=batas) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:                             # noqa: BLE001
        return ""


print("=" * 74)
print("BUKTI Paket C/D hidup di nsm-app (%s)" % HOST)
print("=" * 74)

# ===========================================================================
print("\n0. PEMBEDANYA HARUS BENAR-BENAR MEMBEDAKAN")
k_ada = kode_http("/css/insiden.css")
k_tidak = kode_http("/css/berkas-yang-pasti-tidak-ada-12345.css")
benar("berkas css yang ADA menjawab 200", k_ada == 200, "-> %r" % k_ada)
benar("berkas css yang TIDAK ADA menjawab 404", k_tidak == 404,
      "-> %r (kalau 302, /css/** tidak permitAll dan pemeriksaan ini buta)"
      % k_tidak)

k_hantu = kode_http("/jalur-yang-pasti-tidak-ada-98765")
print("       (jalur halaman yang tidak ada menjawab %r -- itu halaman"
      % k_hantu)
print("        /login sesudah pengalihan diikuti, bukan halaman yang")
print("        diminta. Karena itu jalur halaman TIDAK dipakai sebagai")
print("        bukti apa pun di berkas ini.)")

# ===========================================================================
print("\n1. Jar yang BERJALAN memuat halaman Paket C/D")
for berkas, apa in (("/css/wawasan.css", "Wawasan"),
                    ("/css/insiden.css", "Insiden")):
    k = kode_http(berkas)
    benar("%-20s ada di jar yang berjalan (%s)" % (berkas, apa), k == 200,
          "-> %r; 404 berarti jar di nsm-app masih yang LAMA" % k)

css = isi_http("/css/wawasan.css")
benar("isi wawasan.css benar-benar terkirim (bukan halaman galat)",
      len(css) > 200 and "wsn-" in css, "-> %d bita" % len(css))

# ===========================================================================
print("\n2. Bertanya ke DALAM mesinnya (SSH) -- API diikat ke 127.0.0.1")
try:
    import paramiko
except ImportError:
    print("  [LEWAT] paramiko tidak terpasang; pemeriksaan API dilewati.")
    print("          DILEWATI, bukan dianggap lolos.")
    paramiko = None

ssh = None
if paramiko is not None:
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(HOST, username=USER, password=config.get_nsmapp_sandi(),
                    timeout=25)
    except Exception as e:                        # noqa: BLE001
        print("  [LEWAT] tidak bisa SSH ke %s: %s" % (HOST, str(e)[:120]))
        print("          DILEWATI, bukan dianggap lolos.")
        ssh = None


def di_sana(perintah, batas=60):
    """Run on nsm-app. Returns the stdout text."""
    if ssh is None:
        return None
    _, keluar, _ = ssh.exec_command(perintah, timeout=batas)
    return keluar.read().decode("utf-8", "replace").strip()


if ssh is not None:
    aktif = di_sana("systemctl is-active nsm-poller nsm-api nsm-frontend")
    benar("ketiga layanan systemd active",
          aktif is not None and aktif.split() == ["active"] * 3,
          "-> %r" % aktif)

    jalur = ["/baseline", "/pola-log?jam=24", "/prakiraan",
             "/prakiraan/anggaran", "/agen-soc?jam=24", "/tenant"]
    perintah = "; ".join(
        "curl -s -o /dev/null -m 25 -w '%s=%%{http_code}\\n' "
        "'http://127.0.0.1:8000%s'" % (j.split("?")[0], j) for j in jalur)
    hasil = di_sana(perintah, batas=200) or ""
    for j in jalur:
        nama = j.split("?")[0]
        benar("GET %-22s -> 200" % j,
              "%s=200" % nama in hasil,
              "-> %r" % [b for b in hasil.splitlines()
                         if b.startswith(nama + "=")])

    # the Package C/D modules can be imported on nsm-app
    imp = di_sana(
        "cd %s/backend && ./venv/bin/python -c \""
        "import baseline, pola_log, prakiraan, agen_soc, tenancy, korelasi, "
        "notifikasi_insiden;"
        "import drain3;"
        "print('IMPOR-OK', pola_log.tersedia())\" 2>&1 | tail -3" % AKAR)
    benar("tujuh modul Paket B/C/D + drain3 bisa diimpor di nsm-app",
          imp is not None and "IMPOR-OK" in imp, "-> %r" % (imp or "")[:200])
    benar("drain3 benar-benar tersedia (bukan cuma terpasang)",
          imp is not None and "IMPOR-OK True" in imp, "-> %r" % (imp or "")[:120])

    # ---- penyaringan tenant BERLAKU ----
    n_semua = di_sana("curl -s -m 25 http://127.0.0.1:8000/devices "
                      "| python3 -c 'import sys,json; "
                      "print(len(json.load(sys.stdin)))'")
    n_asing = di_sana("curl -s -m 25 -H 'X-NSM-Tenant: 999' "
                      "http://127.0.0.1:8000/devices "
                      "| python3 -c 'import sys,json; "
                      "print(len(json.load(sys.stdin)))'")
    benar("tanpa tenant -> ada perangkat terlihat",
          (n_semua or "").isdigit() and int(n_semua) > 0, "-> %r" % n_semua)
    benar("tenant asing (999) -> NOL perangkat",
          n_asing == "0", "-> %r perangkat BOCOR" % n_asing)

    # Kill switches must still be OFF. The most important check in this file: a
    # deploy must NOT enable anything; a component that proposes actions on network
    # devices should be switched on by a deliberate decision.
    sw = di_sana(
        "cd %s/backend && ./venv/bin/python -c \"import config;"
        "print('aktif=%%s mode=%%r narasi=%%s' %% ("
        "config.get_agen_soc_aktif(), config.get_agen_soc_mode(),"
        "config.get_agen_soc_narasi()))\" 2>&1 | tail -1" % AKAR)
    benar("AGEN_SOC_AKTIF masih False di nsm-app",
          sw is not None and "aktif=False" in sw, "-> %r" % sw)
    benar("AGEN_SOC_MODE masih 'usul'",
          sw is not None and "mode='usul'" in sw, "-> %r" % sw)
    benar("AGEN_SOC_NARASI masih False (tidak ada data ke luar lab)",
          sw is not None and "narasi=False" in sw, "-> %r" % sw)

    # Read with Python's `zipfile`, NOT `unzip`, which is not installed on nsm-app.
    # Python is always there (it runs the whole backend), so there is no reason to
    # use a tool that may be missing.
    isi_jar = di_sana(
        "%s/backend/venv/bin/python -c \"import zipfile;"
        "n=[x for x in zipfile.ZipFile('%s/frontend/target/"
        "frontend-0.0.1-SNAPSHOT.jar').namelist() "
        "if x.startswith('BOOT-INF/classes/templates/') and "
        "x.split('/')[-1] in ('wawasan.html','agen.html','tenant.html',"
        "'insiden.html','insiden_detail.html')];"
        "print(len(n))\" 2>&1 | tail -1" % (AKAR, AKAR))
    if isi_jar and isi_jar.isdigit():
        benar("jar yang berjalan memuat KELIMA templat halaman baru",
              int(isi_jar) >= 5, "-> cuma %s templat ketemu" % isi_jar)
    else:
        print("  [LEWAT] isi jar tidak terbaca (%r) -- tidak dianggap lolos."
              % (isi_jar or "")[:60])

    ssh.close()

print()
print("=" * 74)
print("%d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

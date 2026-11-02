# -*- coding: utf-8 -*-
"""Proof that the UI redesign is really live on nsm-app.

Separate from `bukti_nsmapp_paketcd.py`, which knows nothing about the Manrope
font, the Tabler sprite, the libraries under /vendor/, or the Syslog page.
Everything checked here can fail SILENTLY:

  * font not shipped        -> page falls back to a system font, no error
  * icon sprite missing     -> `<use>` draws zero pixels
  * ECharts missing         -> charts are empty, the page still returns 200
  * `/vendor/**` not allowed by Spring Security -> everything is answered with
    the login page, the browser fails to parse it, and no message appears

The method follows `bukti_nsmapp_paketcd.py`: `/css/**` and `/vendor/**` are
permitAll and answer honestly with 200 or 404, while PAGE paths always return
302 to /login whether or not they exist.

Run: venv\\Scripts\\python.exe bukti_nsmapp_tampilan.py
"""
import sys

import config
import paramiko

HOST = "192.168.56.156"
USER = "nsmapp"
JAR = "/home/nsmapp/NSM/frontend/target/frontend-0.0.1-SNAPSHOT.jar"

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


def jalankan(ssh, perintah):
    _i, o, e = ssh.exec_command(perintah, timeout=40)
    return o.read().decode("utf-8", "replace").strip(), e.read().decode("utf-8", "replace").strip()


ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=config.get_nsmapp_sandi(), timeout=25)

print("=" * 74)
print("BUKTI redesign tampilan hidup di nsm-app (%s)" % HOST)
print("=" * 74)

# -------------------------------------------------------------------------
print()
print("0. PEMBEDANYA HARUS BENAR-BENAR MEMBEDAKAN")


def kode(jalur):
    keluar, _ = jalankan(
        ssh, "curl -s -o /dev/null -w '%%{http_code}' http://127.0.0.1:8080%s" % jalur)
    return keluar.strip()


ada = kode("/css/nsm.css")
tak_ada = kode("/css/berkas-yang-pasti-tidak-ada-xyz.css")
benar("berkas css yang ADA menjawab 200", ada == "200", "-> %s" % ada)
benar("berkas css yang TIDAK ADA menjawab 404", tak_ada == "404", "-> %s" % tak_ada)

# -------------------------------------------------------------------------
print()
print("1. BERKAS BARU BENAR-BENAR DILAYANI (bukan dibalas halaman login)")

for jalur, nama in [
    ("/css/syslog.css", "gaya halaman Syslog"),
    ("/ikon-tabler.svg", "sprite ikon Tabler"),
    ("/js/tema.js", "saklar tema"),
    ("/js/latar-bsp.js", "latar shader & jaring"),
    ("/vendor/echarts.min.js", "ECharts"),
    ("/vendor/three.min.js", "Three.js"),
    ("/vendor/vanta.net.min.js", "Vanta.NET"),
    ("/vendor/font/manrope.css", "CSS huruf Manrope"),
    ("/vendor/font/manrope-latin-400.woff2", "berkas huruf Manrope"),
]:
    k = kode(jalur)
    benar("%-26s %s -> 200" % (nama, jalur), k == "200", "-> %s" % k)

# -------------------------------------------------------------------------
print()
print("2. ISINYA BENAR, BUKAN SEKADAR ADA")

# Read the WHOLE file, not the first 400 bytes: the first 400 bytes are still
# a license comment, so a partial read reports "absent" for things that exist.
n_face, _ = jalankan(
    ssh, "curl -s http://127.0.0.1:8080/vendor/font/manrope.css | grep -c '@font-face'")
benar("manrope.css memuat @font-face sungguhan", n_face.strip() == "10",
      "-> %r blok (diharapkan 10: latin & latin-ext x 5 bobot)" % n_face)

n_lokal, _ = jalankan(
    ssh, "curl -s http://127.0.0.1:8080/vendor/font/manrope.css | grep -c '/vendor/font/'")
n_luar, _ = jalankan(
    ssh, "curl -s http://127.0.0.1:8080/vendor/font/manrope.css | grep -c 'gstatic'")
benar("semua src menunjuk berkas LOKAL, nol ke fonts.gstatic.com",
      n_lokal.strip() == "10" and n_luar.strip() == "0",
      "-> lokal %r, gstatic %r" % (n_lokal, n_luar))

isi_svg, _ = jalankan(
    ssh, "curl -s http://127.0.0.1:8080/ikon-tabler.svg | grep -c '<symbol'")
try:
    n_simbol = int(isi_svg.strip() or 0)
except ValueError:
    n_simbol = 0
benar("sprite memuat 65 simbol", n_simbol == 65, "-> %d" % n_simbol)

kunci, _ = jalankan(
    ssh, "curl -s http://127.0.0.1:8080/css/nsm.css | grep -c 'data-theme=\"light\"'")
benar("nsm.css memuat blok mode terang", kunci.strip() not in ("", "0"),
      "-> %r" % kunci)

# -------------------------------------------------------------------------
print()
print("3. JAR YANG BERJALAN MEMUAT HALAMAN SYSLOG")

CEK_JAR = (
    "/home/nsmapp/NSM/backend/venv/bin/python -c "
    "\"import zipfile,sys; n=zipfile.ZipFile(sys.argv[1]).namelist(); "
    "print(sum(1 for x in n if x.endswith(sys.argv[2])))\" %s '%s'")

for berkas in ["templates/syslog.html", "static/syslog.js",
               "static/vendor/font/manrope-latin-700.woff2"]:
    keluar, galat = jalankan(ssh, CEK_JAR % (JAR, berkas))
    benar("jar memuat %s" % berkas, keluar.strip() not in ("", "0"),
          "-> %r %s" % (keluar, galat[:60]))

# -------------------------------------------------------------------------
print()
print("4. API SYSLOG MENJAWAB DARI DALAM MESINNYA")

for jalur in ["/syslog/dasbor?jam=24", "/syslog/pesan?jam=24&per_halaman=5"]:
    keluar, _ = jalankan(
        ssh, "curl -s -o /dev/null -w '%%{http_code}' http://127.0.0.1:8000%s" % jalur)
    benar("GET %-34s -> 200" % jalur, keluar.strip() == "200", "-> %s" % keluar)

isi, _ = jalankan(
    ssh, "curl -s 'http://127.0.0.1:8000/syslog/dasbor?jam=24' | head -c 200")
benar("dasbor mengembalikan JSON berisi total", '"total"' in isi,
      "-> %r" % isi[:70])

ssh.close()

print()
print("=" * 74)
print("%d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

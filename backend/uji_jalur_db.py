"""Tests for the database path: does NSM always open the right `backend/nsm.db`?

Most NSM code used to open its database through RELATIVE paths (`sqlite:///nsm.db`,
`sqlite3.connect("nsm.db")`), so the working directory decided which file was
opened. `sqlite3.connect()` on a missing file does not raise; it CREATES an empty
one, so running from the wrong folder gives "zero rows" with a healthy-looking
page. A 0-byte `nsm.db` in the repo root went unnoticed for days (e.g. from running
`migrate_snmp_columns.py` at the repo root).

Guards:
  1. `database.JALUR_DB` points to `backend/nsm.db` from ANY cwd
  2. importing `database` from the repo root creates no stray file
  3. `kesehatan.py` reports the real size, not 0.0 MB
  4. a code scanner: relative-path patterns must not reappear

Number 4 lasts longest: it stops new files copied from old ones from reviving the trap.

Safe to run any time: writes nothing to `nsm.db`.

    cd C:\\Users\\<user>\\NSM\\backend
    venv\\Scripts\\activate
    python uji_jalur_db.py
"""
import ast
import os
import re
import subprocess
import sys
import tempfile

DIR = os.path.dirname(os.path.abspath(__file__))
AKAR = os.path.dirname(DIR)

sys.path.insert(0, DIR)

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


def judul(teks):
    print()
    print("=" * 74)
    print(teks)
    print("=" * 74)


# ===========================================================================
judul("1. database.JALUR_DB menunjuk ke berkas yang sama dari cwd mana pun")
# Run as a SEPARATE process per working folder: changing cwd inside this process
# proves nothing, since `database` is already imported and its path computed once at import.
PROG = ("import sys; sys.path.insert(0, r'%s'); import database; "
        "print(database.JALUR_DB)" % DIR)

jalur_per_cwd = {}
for label, cwd in (("backend (benar)", DIR),
                   ("akar repo", AKAR),
                   ("C:\\", "C:\\"),
                   ("folder sementara", tempfile.gettempdir())):
    hasil = subprocess.run([sys.executable, "-c", PROG], cwd=cwd,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    jalur = hasil.stdout.strip()
    jalur_per_cwd[label] = jalur
    benar("dijalankan dari %-18s -> %s" % (label, jalur or "(GAGAL)"),
          jalur == os.path.join(DIR, "nsm.db"),
          "-> galat: %s" % hasil.stderr.strip()[-200:])

benar("keempat folder kerja menghasilkan jalur yang identik",
      len(set(jalur_per_cwd.values())) == 1,
      "-> %r" % jalur_per_cwd)

import database  # noqa: E402  (sesudah sys.path diatur di atas)

# `str(...)` is needed: `engine.url` is a NamedTuple, so `"%s" % url` treats it as a tuple.
#
# Two correct answers now: the main engine is MySQL, but the danger moves to
# `penyangga.db`, the local SQLite buffer used while the database is unreachable.
# A buffer born in the wrong folder would hold measurements during an outage and be
# left behind. So: with MySQL the address must be complete, and whatever the engine,
# the buffer path must be absolute.
url = str(database.engine.url)
if database.PAKAI_MYSQL:
    benar("URL engine MySQL menyebut host dan nama basis data",
          url.startswith("mysql+pymysql://")
          and database.ENV.get("NSM_DB_HOST", "") in url
          and url.rstrip("/").split("/")[-1].split("?")[0] != "",
          # The password is not printed; do not rely on SQLAlchemy masking it in `str(url)`.
          "-> %s" % url.split("@")[-1])

    benar("basis datanya benar-benar berisi, bukan skema kosong",
          database.engine.connect().execute(
              __import__("sqlalchemy").text(
                  "SELECT COUNT(*) FROM status_logs")).scalar() > 1000,
          "-> %s" % database.keterangan())
else:
    benar("URL engine memakai jalur mutlak, bukan 'sqlite:///nsm.db'",
          url.startswith("sqlite:///") and url != "sqlite:///nsm.db"
          and "/" in url[len("sqlite:///"):],
          "-> %s" % url)

    benar("berkas yang ditunjuk benar-benar ada dan berisi",
          os.path.exists(database.JALUR_DB)
          and os.path.getsize(database.JALUR_DB) > 1024 * 1024,
          "-> %s" % database.JALUR_DB)

benar("jalur penyangga lokal mutlak, tidak bergantung folder kerja",
      os.path.isabs(database.JALUR_PENYANGGA)
      and os.path.dirname(database.JALUR_PENYANGGA) == database.DIR,
      "-> %s" % database.JALUR_PENYANGGA)


# ===========================================================================
judul("2. Dijalankan dari akar repo, tidak ada berkas liar yang tercipta")
# Run inside an EMPTY temporary folder, not the real repo root: if the code still creates a stray file, it lands in the trash instead of polluting the repo.
sementara = tempfile.mkdtemp(prefix="nsm-jalur-")

# Goes as far as opening a real connection: `create_engine()` is lazy and touches no disk until the first connection, which is when the bug appears.
PROG2 = ("import sys; sys.path.insert(0, r'%s'); import database; "
         "s = database.engine.connect(); s.close()" % DIR)
hasil = subprocess.run([sys.executable, "-c", PROG2], cwd=sementara,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")

sisa = sorted(os.listdir(sementara))
benar("membuka sambungan dari folder asing: berjalan tanpa galat",
      hasil.returncode == 0, "-> %s" % hasil.stderr.strip()[-300:])
benar("folder asing tetap KOSONG sesudahnya (tidak ada nsm.db liar)",
      sisa == [], "-> tersisa %r" % sisa)

os.rmdir(sementara) if not sisa else None


# ===========================================================================
judul("3. Halaman Kesehatan melaporkan ukuran sungguhan, bukan 0.0 MB")
# Guarded defect: a relative `os.path.getsize("nsm.db")` made the Health page show
# "0.0 MB" when uvicorn started from the wrong folder.
#
# Run in a TEMPORARY folder, not the repo root: an earlier version used the repo root
# and, when the relative path was deliberately re-planted, wrote a new `nsm.db` there.
# The temporary folder proves the same thing ("cwd is not backend") without being able to pollute the repo.
sementara3 = tempfile.mkdtemp(prefix="nsm-jalur3-")
PROG3 = (
    "import sys, os; sys.path.insert(0, r'%s')\n"
    "import kesehatan, database\n"
    "from database import SessionLocal\n"
    "db = SessionLocal()\n"
    "try:\n"
    "    h = kesehatan._basis_data(db)\n"
    "finally:\n"
    "    db.close()\n"
    # The card name follows the engine ("Ukuran nsm.db" for SQLite, "Ukuran basis data" for MySQL). What is guarded is that the card holds a real number, not 0.0 MB.
    "for r in h['rincian']:\n"
    "    if r['label'] in ('Ukuran nsm.db', 'Ukuran basis data'):\n"
    "        print(r['nilai'])\n" % DIR)

hasil = subprocess.run([sys.executable, "-c", PROG3], cwd=sementara3,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
nilai = hasil.stdout.strip()
angka = float(nilai.split()[0].replace(",", ".")) if nilai else 0.0

benar("dijalankan dari folder asing, kartu ukuran basis data terisi",
      bool(nilai), "-> galat: %s" % hasil.stderr.strip()[-300:])
benar("ukurannya bukan 0.0 MB (nilai: %s)" % nilai, angka > 1.0,
      "-> justru inilah gejalanya kalau jalurnya kembali relatif")

# Also checked: this section must leave no trace in the folder it runs in.
sisa3 = sorted(os.listdir(sementara3))
benar("bagian ini tidak meninggalkan berkas apa pun di folder kerjanya",
      sisa3 == [], "-> tersisa %r" % sisa3)
if not sisa3:
    os.rmdir(sementara3)


# ===========================================================================
judul("4. Pemindai kode: pola jalur relatif tidak boleh muncul lagi")
# Parts 1-3 prove today's state; this one guards tomorrow: new files are copied from
# old ones, so a copied `DB = "nsm.db"` would revive the trap.
#
# The CODE is checked, not raw text, since files here contain comments that MENTION
# the old pattern; a grep-based checker would fail on its own comments.
NAMA_DB = re.compile(r"^(nsm\.db|sqlite:///nsm\.db|file:nsm\.db(\?.*)?)$")


def _nama_fungsi(simpul):
    """'os.path.join' of an ast.Call, as far as it can be read statically."""
    section = []
    f = simpul.func
    while isinstance(f, ast.Attribute):
        section.append(f.attr)
        f = f.value
    if isinstance(f, ast.Name):
        section.append(f.id)
    return ".".join(reversed(section))


temuan = []
for nama in sorted(os.listdir(DIR)):
    if not nama.endswith(".py"):
        continue
    with open(os.path.join(DIR, nama), encoding="utf-8") as f:
        isi = f.read()
    try:
        pohon = ast.parse(isi)
    except SyntaxError as e:
        temuan.append("%s: tidak bisa diurai (%s)" % (nama, e))
        continue

    for simpul in ast.walk(pohon):
        # a. penugasan telanjang: DB = "nsm.db"
        if isinstance(simpul, ast.Assign) and isinstance(simpul.value, ast.Constant):
            if isinstance(simpul.value.value, str) and NAMA_DB.match(simpul.value.value):
                temuan.append("%s:%d penugasan langsung ke %r"
                              % (nama, simpul.lineno, simpul.value.value))

        # b. used directly as an argument: sqlite3.connect("nsm.db"),
        #    os.path.getsize("nsm.db"), create_engine("sqlite:///nsm.db").
        #
        #    `os.path.join` is EXCLUDED: in `os.path.join(DIR, "nsm.db")` the string is just
        #    a file name appended to an anchored folder, which is the correct form.
        if isinstance(simpul, ast.Call) and _nama_fungsi(simpul) != "os.path.join":
            for arg in simpul.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if NAMA_DB.match(arg.value):
                        temuan.append("%s:%d argumen jalur relatif %r"
                                      % (nama, simpul.lineno, arg.value))

benar("tidak ada jalur relatif ke nsm.db tersisa di backend/*.py",
      temuan == [], "-> %d temuan:\n       %s"
      % (len(temuan), "\n       ".join(temuan)))


# ===========================================================================
judul("KONFIGURASI: `.env` juga tidak boleh bergantung folder kerja")
# Same defect in `config._baca()`: it opens `".env"` as a RELATIVE path and swallows
# `FileNotFoundError`, so a process started from another folder gets ALL default
# values (empty LDAP_URL, switches off, default thresholds) without any error.
# systemd services are safe because the unit sets `WorkingDirectory`; hand-run
# scripts started elsewhere are not.

import subprocess  # noqa: E402

_BE = os.path.dirname(os.path.abspath(__file__))
_PY = sys.executable


def _baca_dari(folder, kunci):
    """Run config in a NEW process with cwd `folder` and read one value.

    A new process, not `os.chdir()` here: `config` is already imported and computed its path at import.
    """
    code = ("import sys; sys.path.insert(0, %r); import config; "
            "print(repr(config.%s()))" % (_BE, kunci))
    h = subprocess.run([_PY, "-c", code], cwd=folder, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=60)
    return h.stdout.strip()


_ada_env = os.path.exists(os.path.join(_BE, ".env"))
benar(".env ada untuk diuji (uji ini tak boleh lolos karena kosong)", _ada_env,
      "-> tidak ada %s" % os.path.join(_BE, ".env"))

if _ada_env:
    dari_backend = _baca_dari(_BE, "get_ldap_url")
    dari_atas = _baca_dari(os.path.dirname(_BE), "get_ldap_url")
    dari_akar = _baca_dari(os.path.abspath(os.sep), "get_ldap_url")

    benar("dibaca dari backend/ menghasilkan nilai, bukan kosong",
          dari_backend not in ("''", '""', ""), "-> %s" % dari_backend)
    benar("dari folder proyek: SAMA dengan dari backend/",
          dari_atas == dari_backend, "-> %s vs %s" % (dari_atas, dari_backend))
    benar("dari akar disk: SAMA dengan dari backend/",
          dari_akar == dari_backend, "-> %s vs %s" % (dari_akar, dari_backend))

    # The path used must be absolute; if relative, the test above could pass by accident on some machines.
    import config as _cfg  # noqa: E402
    benar("config memakai jalur .env yang ABSOLUT",
          os.path.isabs(getattr(_cfg, "_ENV", ".env")),
          "-> %r" % getattr(_cfg, "_ENV", "(tidak ada _ENV)"))


# ===========================================================================
judul("RINGKASAN")
# ===========================================================================
print("  lolos : %d" % lolos)
print("  gagal : %d" % gagal)
print()
if gagal:
    print("  ADA YANG GAGAL. Jangan diabaikan: bentuk kegagalan jalur relatif")
    print("  adalah 'nol baris', bukan pesan galat, jadi ia tidak akan")
    print("  memberi tahu dirinya sendiri di layar mana pun.")
else:
    print("  Semua lolos. Basis data yang dibuka selalu backend/nsm.db,")
    print("  dari folder kerja mana pun perintahnya dijalankan.")
sys.exit(1 if gagal else 0)

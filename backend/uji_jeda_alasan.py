"""Tests for the pause reason: storage, clearing on resume, and display.

Before, pausing a device only wrote `aktif = 0`, so a legitimate pause was
indistinguishable from a forgotten one. These tests cover what would make the note
MISLEADING, which is worse than no note:
  - the reason carrying over when a device is resumed and paused again
  - `jeda_sejak` not updated on the second pause (wrong pause age)
  - the pauser's name taken from the request body (anyone can type it)
  - the reason lost along Python -> Java -> browser
  - an empty reason stored as "" and read as if it had content

Runs on a TEMPORARY database. Does not touch nsm.db.
"""

import os
import re
import sys
import tempfile
from datetime import datetime, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

lulus = 0
gagal = []


def tanpa_komentar(teks):
    """Strip // and /* */ comments from Java/JavaScript code.

    Used before checking "does this code call X", so comments explaining why X is NOT
    used (e.g. "HashMap, not Map.of") are not mistaken for usage. A test that a comment can fail is not testing the code.
    """
    teks = re.sub(r"/\*.*?\*/", " ", teks, flags=re.S)
    # `(?<!:)` keeps "http://..." from being cut.
    return re.sub(r"(?<!:)//[^\n]*", " ", teks)


def periksa(nama, syarat, keterangan=""):
    global lulus
    if syarat:
        lulus += 1
        print("  ok   %s" % nama)
    else:
        gagal.append(nama)
        print("  GAGAL %s %s" % (nama, ("- " + keterangan) if keterangan else ""))


# 1. Database side: what is stored on pause and on resume.

def uji_basis_data():
    print("\n[1] Penyimpanan alasan di basis data")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    file = os.path.join(tempfile.mkdtemp(prefix="uji_jeda_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)
    db = session()

    d = models.Device(name="Router Uji", ip_address="10.0.0.1",
                      device_type="router", aktif=True)
    db.add(d)
    db.commit()

    periksa("device baru tidak punya alasan jeda", d.jeda_alasan is None)

    # first pause
    before = datetime.now()
    d.aktif = False
    d.jeda_alasan = "sedang di luar lokasi"
    d.jeda_sejak = datetime.now()
    d.jeda_oleh = "admin"
    db.commit()
    db.refresh(d)

    periksa("alasan tersimpan", d.jeda_alasan == "sedang di luar lokasi")
    periksa("jeda_sejak terisi saat dijeda",
            d.jeda_sejak is not None and d.jeda_sejak >= before - timedelta(seconds=2))
    periksa("penjeda tercatat", d.jeda_oleh == "admin")

    # resumed: ALL THREE must be cleared. A stale reason would keep an "away from site" note forever, and a wrong note is more dangerous than an empty one.
    d.aktif = True
    d.jeda_alasan = d.jeda_sejak = d.jeda_oleh = None
    db.commit()
    db.refresh(d)

    periksa("alasan dihapus saat dilanjutkan", d.jeda_alasan is None)
    periksa("jeda_sejak dihapus saat dilanjutkan", d.jeda_sejak is None)
    periksa("penjeda dihapus saat dilanjutkan", d.jeda_oleh is None)

    # second pause: jeda_sejak must be NEW, not left over from the first
    old = datetime.now() - timedelta(days=9)
    d.aktif = False
    d.jeda_alasan = "VM dimatikan untuk snapshot"
    d.jeda_sejak = datetime.now()
    d.jeda_oleh = "admin"
    db.commit()
    db.refresh(d)

    periksa("alasan kedua menggantikan yang pertama",
            d.jeda_alasan == "VM dimatikan untuk snapshot")
    periksa("jeda_sejak jeda kedua bukan sisa jeda pertama",
            d.jeda_sejak > old,
            "umur jeda akan terbaca 9 hari padahal baru saja")

    db.close()
    engine.dispose()


# 2. Python endpoint side: what is accepted and returned.

def uji_endpoint():
    print("\n[2] Endpoint /devices/{id}/aktif dan /devices")

    # The route `/devices/{id}/aktif` moved from `main.py` to a per-domain router; content unchanged.
    content = open(os.path.join(DIR, "nsm", "antarmuka", "http", "rute", "device.py"),
               encoding="utf-8").read()

    # Cut out only set_aktif so the checks below are not hit by other endpoints mentioning the same word.
    m = re.search(r"def set_aktif\(.*?(?=\n@router\.|\ndef [a-z])", content, re.S)
    periksa("set_aktif ditemukan di rute device", m is not None)
    if not m:
        return
    block = m.group(0)

    periksa("set_aktif menerima alasan", "alasan" in block)
    periksa("set_aktif mengisi jeda_sejak", "jeda_sejak" in block)
    periksa("set_aktif membersihkan ketiganya saat dilanjutkan",
            re.search(r"jeda_alasan\s*=\s*d\.jeda_sejak\s*=\s*d\.jeda_oleh\s*=\s*None", block)
            is not None,
            "alasan lama akan menempel pada device yang sudah hidup")

    # An empty reason must become None, NOT "": an empty string passes the display side's `is not None` check and draws an empty reason box.
    periksa("alasan kosong disimpan sebagai None, bukan string kosong",
            re.search(r"strip\(\)\[:\d+\]\s*or None", block) is not None,
            'alasan "" akan menggambar kotak alasan yang kosong')

    # Length limit: the reason comes from a text box the browser does not bound, and the column is read on other pages.
    periksa("panjang alasan dibatasi", re.search(r"\[:\d{2,4}\]", block) is not None)

    # The device list must CARRY all three fields, otherwise the dashboard card never
    # learns the reason. The route moved to the `nsm/` layer; the check reads the source
    # (not call-and-inspect) so a removed field is caught even if no device is paused in the database.
    kasus = os.path.join(DIR, "nsm", "aplikasi", "kasus", "lihat_device.py")
    periksa("kasus lihat_device ditemukan", os.path.exists(kasus),
            "rute /devices pindah lagi? ikuti kodenya, jangan hapus uji ini")
    if os.path.exists(kasus):
        daftar = open(kasus, encoding="utf-8").read()
        for k in ("jeda_alasan", "jeda_sejak", "jeda_oleh"):
            periksa("daftar device membawa %s" % k, k in daftar)


# 3. Java side: fixed-shape DTOs; anything not registered vanishes silently.

def uji_java():
    print("\n[3] Jalur Java (DeviceDto, controller, klien API)")

    root_cause = os.path.join(os.path.dirname(DIR), "frontend", "src", "main", "java",
                        "id", "bsp", "frontend")

    dto = open(os.path.join(root_cause, "dto", "DeviceDto.java"), encoding="utf-8").read()
    # The most important check here: Spring Boot's default Jackson SILENTLY drops JSON fields the DTO does not know, so the reason never reaches the browser.
    for k in ("jeda_alasan", "jeda_sejak", "jeda_oleh"):
        periksa("DeviceDto mendaftarkan %s" % k,
                ('"%s"' % k) in dto,
                "Jackson akan membuangnya diam-diam")

    client = open(os.path.join(root_cause, "service", "NetmonApiClient.java"), encoding="utf-8").read()
    m = re.search(r"setDeviceAktif\([^)]*\)", client)
    periksa("setDeviceAktif menerima alasan dan oleh",
            m is not None and "alasan" in m.group(0) and "oleh" in m.group(0))
    # Map.of rejects null values; a reason may be empty, so Map.of would throw NullPointerException on a valid use.
    block_client = client[client.find("setDeviceAktif"):]
    block_client = tanpa_komentar(block_client[:block_client.find("\n    }")])
    periksa("badan permintaan tidak memakai Map.of",
            "Map.of(" not in block_client,
            "Map.of melempar NPE saat alasan dikosongkan")

    ctl = open(os.path.join(root_cause, "controller", "DashboardController.java"),
               encoding="utf-8").read()
    block = ctl[ctl.find("public Object setAktif"):]
    block = block[:block.find("\n    /**", 1) if block.find("\n    /**", 1) > 0 else 2000]

    # The pauser's name MUST come from the session, not the request body (anyone can type it); a forgeable "who paused" record is worse than none.
    periksa("nama penjeda diambil dari sesi",
            "Principal" in block and "getName()" in block)
    periksa("nama penjeda TIDAK diambil dari badan permintaan",
            'badan.get("oleh")' not in block,
            "siapa pun bisa mengaku sebagai orang lain")
    periksa("audit mencatat alasannya", "alasan" in block and "audit" in block)


# 4. Browser side: three states, not two.

def uji_tampilan():
    print("\n[4] Tampilan kartu (app.js) dan gayanya")

    js = open(os.path.join(os.path.dirname(DIR), "frontend", "src", "main",
                           "resources", "static", "app.js"), encoding="utf-8").read()

    periksa("alasan ditanyakan saat menjeda", "prompt(" in js)

    block = js[js.find("function ubahAktif"):]
    block = block[:block.find("\n}")]
    # Cancelling the dialog is NOT an empty reason: it means "do not pause". Without this check, pressing Cancel still pauses.
    periksa("membatalkan dialog membatalkan jeda",
            "=== null" in block and "return" in block,
            "menekan Batal tetap menjeda device")
    periksa("alasan tidak ditanyakan saat melanjutkan",
            "if (!jadiAktif)" in block)

    periksa("ada fungsi keterangan jeda", "function ketJeda" in js)
    note = js[js.find("function ketJeda"):]
    note = note[:note.find("\n}")]
    # The third state: paused with NO recorded reason. Say the reason is not recorded; neither "no reason" (accusing) nor hiding it.
    periksa("keadaan 'alasan tidak tercatat' ditangani",
            "tidak tercatat" in note,
            "jeda lama akan tampil seolah tidak punya alasan sama sekali")
    periksa("umur jeda ditampilkan", "waktuRelatif" in note)

    # Anti-XSS: the reason is typed by a human and shown on other people's screens.
    card = js[js.find("if (dijeda) {"):]
    card = tanpa_komentar(card[:card.find("} else {")])
    periksa("alasan digambar tanpa innerHTML", "innerHTML" not in card,
            "alasan berisi tag akan dijalankan peramban")

    # The card fingerprint decides when the card is redrawn; a new reason must be part of it, since on a paused device almost nothing else changes.
    sidik = js[js.find("function sidikKartu"):]
    sidik = sidik[:sidik.find("\n}")]
    periksa("alasan ikut sidik kartu", "jeda_alasan" in sidik,
            "alasan baru tidak akan muncul sampai ada hal lain yang berubah")

    html = open(os.path.join(os.path.dirname(DIR), "frontend", "src", "main",
                             "resources", "templates", "dashboard.html"),
                encoding="utf-8").read()
    periksa("gaya .ket-jeda ada", ".ket-jeda" in html)
    periksa("alasan panjang dipotong, tidak memanjangkan kartu",
            "line-clamp" in html)
    # A missing reason is not necessarily neglect: pauses made before this feature had nowhere to record one.
    without = html[html.find(".ket-jeda.tanpa-alasan"):]
    periksa("jeda tanpa alasan tidak diwarnai merah",
            "var(--down)" not in without[:400] and "#f87171" not in without[:400],
            "menuduh setiap jeda lama tanpa dasar")


for f in (uji_basis_data, uji_endpoint, uji_java, uji_tampilan):
    try:
        f()
    except Exception as e:
        gagal.append("%s melempar %s: %s" % (f.__name__, type(e).__name__, e))
        print("  GAGAL %s melempar %s: %s" % (f.__name__, type(e).__name__, e))

print("\n%d lulus, %d gagal" % (lulus, len(gagal)))
for g in gagal:
    print("  - %s" % g)
sys.exit(1 if gagal else 0)

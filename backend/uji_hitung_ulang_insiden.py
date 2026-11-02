"""Test `hitung_ulang_insiden.py`, focused on `hitung_ulang_device()`.

That pure function replays synthetic `status_logs` rows (not real database data)
and the test checks the events it yields. A test database is used only so
`jeda.tak_terpantau_antara()` has a session; with no `jeda` rows it returns 0, so
durations are never truncated unless stated.

Never touches the real `device_events`/`status_logs`, never calls `main()` (interactive, writes).

Run: py uji_hitung_ulang_insiden.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
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


import hitung_ulang_insiden as hu


def siapkan_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    file = os.path.join(tempfile.mkdtemp(prefix="uji_hu_"), "coba.db")
    engine = create_engine("sqlite:///" + file)
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


class Baris:
    """Fake `StatusLog`: only the four attributes `hitung_ulang_device()` reads."""
    def __init__(self, t, is_reachable, sumber="icmp", rtt=None):
        self.timestamp = t
        self.is_reachable = is_reachable
        self.sumber = sumber
        self.response_time_ms = rtt


MULAI = datetime(2026, 8, 1, 10, 0, 0)
INTERVAL = 10  # seconds; keep equal to .env POLL_INTERVAL in this test


def deret(mulai, pola, interval=INTERVAL):
    """`pola` = string like 'UUUDDDDDU' -> series of rows `interval` seconds apart,
    U=is_reachable True, D=False.
    """
    return [Baris(mulai + timedelta(seconds=i * interval), c == "U")
            for i, c in enumerate(pola)]


db = siapkan_db()

# ---------------------------------------------------------------------------
print("1. UP -> DOWN -> UP, GAGAL BERUNTUN MENCAPAI AMBANG")
print("   (ambang 5x -- 5 gagal beruntun harus tercatat DOWN, pulih tercatat UP)")

baris1 = deret(MULAI, "UUDDDDDU")  # index 2..6 gagal (5x), index 7 pulih
ev1 = hu.hitung_ulang_device(db, 1, baris1, batas=5)

benar("tepat DUA event (satu DOWN, satu UP)", len(ev1) == 2, "-> %r" % ev1)
if len(ev1) == 2:
    benar("event pertama DOWN", ev1[0]["event_type"] == "DOWN")
    benar("kategorinya 'dead'", ev1[0]["category"] == "dead")
    benar("DOWN tercatat TEPAT saat gagal beruntun mencapai 5",
          ev1[0]["timestamp"] == baris1[6].timestamp,
          "-> %r, harusnya %r" % (ev1[0]["timestamp"], baris1[6].timestamp))
    benar("event kedua UP", ev1[1]["event_type"] == "UP")
    benar("kategorinya 'recovered' (sumber icmp)", ev1[1]["category"] == "recovered")

# ---------------------------------------------------------------------------
print("\n2. GAGAL BERUNTUN TIDAK MENCAPAI AMBANG -> NOL EVENT")
print("   (derau 1-4 ping hilang bukan gangguan -- ini persis alasan ambang")
print("    dinaikkan 19 Agustus 2026)")

baris2 = deret(MULAI, "UUDDDDU")  # only 4 consecutive failures, threshold 5
ev2 = hu.hitung_ulang_device(db, 1, baris2, batas=5)
benar("nol event -- 4 gagal beruntun TIDAK mencapai ambang 5", ev2 == [],
      "-> %r" % ev2)

# ---------------------------------------------------------------------------
print("\n3. B1 -- LUBANG WAKTU MEMUTUS HITUNGAN GAGAL BERUNTUN")
print("   (dua kegagalan terpisah 1 jam TIDAK boleh terbaca 'beruntun' cuma")
print("    karena baris di antaranya memang tidak pernah tercatat)")

baris3 = [
    Baris(MULAI, True),
    Baris(MULAI + timedelta(seconds=10), False),   # 1 gagal
    Baris(MULAI + timedelta(seconds=20), False),   # 2 gagal (beruntun)
    # 1-hour time gap: poller down
    Baris(MULAI + timedelta(hours=1), False),      # gagal, TAPI terpisah
    Baris(MULAI + timedelta(hours=1, seconds=10), False),
    Baris(MULAI + timedelta(hours=1, seconds=20), False),
    Baris(MULAI + timedelta(hours=1, seconds=30), True),
]
ev3 = hu.hitung_ulang_device(db, 1, baris3, batas=5)
benar("nol event -- 2+3 gagal terpisah lubang waktu TIDAK pernah mencapai "
      "5 beruntun", ev3 == [], "-> %r" % ev3)

# Control: WITHOUT a time gap, the same 5 consecutive failures (2 + 3) MUST be
# detected, proving the gap really matters.
baris3b = [
    Baris(MULAI, True),
    Baris(MULAI + timedelta(seconds=10), False),
    Baris(MULAI + timedelta(seconds=20), False),
    Baris(MULAI + timedelta(seconds=30), False),
    Baris(MULAI + timedelta(seconds=40), False),
    Baris(MULAI + timedelta(seconds=50), False),
    Baris(MULAI + timedelta(seconds=60), True),
]
ev3b = hu.hitung_ulang_device(db, 1, baris3b, batas=5)
benar("pembanding TANPA lubang waktu: 5 gagal beruntun (jumlah SAMA) "
      "TETAP terdeteksi -- B1 benar-benar berpengaruh, bukan kebetulan",
      len(ev3b) == 2, "-> %r" % ev3b)

# ---------------------------------------------------------------------------
print("\n4. B2 -- PEMULIHAN LEWAT TCP DITANDAI 'ping_blocked', BUKAN 'recovered'")
print("   (dibaca LANGSUNG dari kolom sumber, tidak menebak ulang)")

baris4 = deret(MULAI, "UDDDDD")
baris4.append(Baris(MULAI + timedelta(seconds=60), True, sumber="tcp"))
ev4 = hu.hitung_ulang_device(db, 1, baris4, batas=5)
benar("tepat dua event", len(ev4) == 2, "-> %r" % ev4)
if len(ev4) == 2:
    benar("event pemulihan berkategori 'ping_blocked'",
          ev4[1]["category"] == "ping_blocked", "-> %r" % ev4[1])

# ---------------------------------------------------------------------------
print("\n5. BASELINE (baris pertama) TIDAK IKUT MENJADI EVENT")
print("   (B3/B4 -- baseline sudah disalin apa adanya oleh main(), fungsi")
print("    ini tidak boleh menerbitkan baseline KEDUA)")

baris5 = deret(MULAI, "D")  # a single row, DOWN
ev5 = hu.hitung_ulang_device(db, 1, baris5, batas=5)
benar("satu baris pertama -> nol event (jadi acuan status, bukan event)",
      ev5 == [], "-> %r" % ev5)

# ---------------------------------------------------------------------------
print("\n6. DURASI DIHITUNG DARI JARAK KE EVENT SEBELUMNYA")

baris6 = deret(MULAI, "UUDDDDDU")
ev6 = hu.hitung_ulang_device(db, 1, baris6, batas=5)
if len(ev6) == 2:
    # DOWN is recorded at row index 6 (index 0 = baseline, not counted as a "previous
    # event"; the first DOWN duration is measured from the baseline).
    durasi_up = ev6[1]["duration_sec"]
    jarak_asli = (baris6[7].timestamp - baris6[6].timestamp).total_seconds()
    benar("durasi UP = jarak DOWN->UP (tidak ada jeda tercatat -> tidak "
          "dipotong)", durasi_up == jarak_asli,
          "-> %r, harusnya %r" % (durasi_up, jarak_asli))
else:
    benar("dua event untuk uji durasi", False, "-> %r" % ev6)

print()
print("=" * 74)
print("HASIL: %d lolos, %d gagal" % (lolos, gagal))
print("=" * 74)
sys.exit(1 if gagal else 0)

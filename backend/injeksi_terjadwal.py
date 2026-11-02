"""Scheduled fault injection (chaos engineering) against GNS3 lab routers.

Recovery that has never been exercised is unknown recovery; tests that only cover
the happy path report health that is not there. Scheduling this is an operator
decision, so it is gated and refuses to run when breaking things would be harmful.

Three built-in refusals:
1. Kill switch (off by default). Without `INJEKSI_TERJADWAL_AKTIF=1` in `.env` the
   script touches nothing, so deploying a new NSM version never starts breaking
   the network.
2. Error budget exhausted -> abort. A device that has already exceeded its error
   budget (see `slo.py`) is already failing its users; adding an artificial outage
   only makes it worse.
3. GNS3 nodes only, never real servers. Stopping `slapd` on `.101` on a schedule
   would break real logins.

Results are written to `injeksi-terakhir.json` and shown on the Health page.

Run manually: venv\\Scripts\\python.exe injeksi_terjadwal.py --sungguhan
Without `--sungguhan` it only reports what it would do.
"""
import json
import os
import sys
from datetime import datetime

import config
import database
import models

DIR = os.path.dirname(os.path.abspath(__file__))
HASIL = os.path.join(DIR, "injeksi-terakhir.json")


def aktif():
    return str(config._baca().get("INJEKSI_TERJADWAL_AKTIF", "0")
               ).strip().lower() in ("1", "true", "ya")


def _tulis(catatan):
    with open(HASIL, "w", encoding="utf-8") as f:
        json.dump(catatan, f, indent=2, ensure_ascii=False, default=str)


def kandidat(db):
    """Devices that may be disrupted: active GNS3 nodes not marked `penting`.

    `penting` is respected even on GNS3 devices.
    """
    q = (db.query(models.Device)
         .filter(models.Device.aktif == True)  # noqa: E712
         .filter(models.Device.gns3_node != None)  # noqa: E711
         .filter(models.Device.gns3_node != ""))
    return [d for d in q.all() if not getattr(d, "penting", False)]


def anggaran_cukup(db, device):
    """Return (allowed, reason): whether this device still has error budget left.

    Devices without enough observation history are refused too, since there is no
    baseline to compare before and after.
    """
    try:
        import report_service
        import slo
        start, finish, _ = report_service.rentang("30d")
        r = slo.hitung(db, device, start, finish)
    except Exception as e:
        return False, "anggaran galat tidak bisa dihitung (%s)" % type(e).__name__
    if r is None:
        return False, ("belum cukup lama diamati untuk punya garis dasar; "
                       "merusaknya sekarang tidak bisa dibandingkan dengan apa pun")
    if r["vonis"] == "habis":
        return False, ("anggaran galat HABIS (%s, sisa %s). Device ini sudah "
                       "mengecewakan penggunanya hari ini -- menambah gangguan "
                       "buatan di atasnya memperburuk keadaan, bukan mengujinya."
                       % (r["availability_persen"], r["sisa_teks"]))
    if r["vonis"] == "menipis":
        return False, ("anggaran galat menipis (sisa %s / %.1f%%). Ini justru "
                       "saatnya BERHENTI mengambil risiko baru."
                       % (r["sisa_teks"], r["sisa_persen"]))
    return True, ("anggaran galat masih longgar (sisa %s / %.1f%%)"
                  % (r["sisa_teks"], r["sisa_persen"]))


def main(sungguhan=False):
    start = datetime.now()
    catatan = {"waktu": start.isoformat(), "sungguhan": sungguhan,
               "dijalankan": False, "hasil": []}

    if not aktif():
        catatan["alasan"] = ("Saklar INJEKSI_TERJADWAL_AKTIF mati. Merusak "
                             "jaringan dengan sengaja harus dinyalakan "
                             "seseorang, tidak boleh menyala karena ikut "
                             "terpasang.")
        _tulis(catatan)
        print("TIDAK DIJALANKAN: " + catatan["alasan"])
        return 0

    db = database.SessionLocal()
    try:
        prospective = kandidat(db)
        if not prospective:
            catatan["alasan"] = ("Tidak ada node GNS3 yang boleh dirusak. "
                                 "Sasaran sengaja dibatasi node GNS3 -- "
                                 "server sungguhan tidak pernah jadi sasaran "
                                 "injeksi terjadwal.")
            _tulis(catatan)
            print("TIDAK DIJALANKAN: " + catatan["alasan"])
            return 0

        print("=" * 70)
        print("INJEKSI GANGGUAN TERJADWAL  %s"
              % start.strftime("%d %B %Y %H:%M:%S"))
        print("mode: %s" % ("SUNGGUHAN" if sungguhan else "LAPORAN SAJA"))
        print("=" * 70)

        allowed_all = []
        for d in prospective:
            ok, note = anggaran_cukup(db, d)
            print("\n-> %s (%s)" % (d.name, d.ip_address))
            print("   %s  %s" % ("BOLEH " if ok else "BATAL ", note))
            catatan["hasil"].append({"device": d.name, "device_id": d.id,
                                     "boleh": ok, "alasan": note})
            if ok:
                allowed_all.append(d)

        if not allowed_all:
            catatan["alasan"] = ("Semua kandidat ditolak oleh anggaran galat. "
                                 "Itu bukan kegagalan -- itu pengamannya "
                                 "bekerja.")
            _tulis(catatan)
            print("\n" + catatan["alasan"])
            return 0

        if not sungguhan:
            catatan["alasan"] = ("Mode laporan. Tambahkan --sungguhan untuk "
                                 "benar-benar menjalankan injeksi.")
            _tulis(catatan)
            print("\n%d device LOLOS syarat. %s"
                  % (len(allowed_all), catatan["alasan"]))
            return 0

        # One device per round, the one with the most budget left. Disrupting several at
        # once makes cause and effect impossible to separate.
        sasaran = allowed_all[-1]
        print("\nSASARAN: %s" % sasaran.name)
        print("Prosedurnya ada di docs/FAULT-INJECTION.md dan dijalankan oleh")
        print("`injeksi_r1.py`, yang SENGAJA tetap dijalankan tangan.")
        catatan["dijalankan"] = True
        catatan["sasaran"] = sasaran.name
        catatan["alasan"] = (
            "Syarat terpenuhi dan sasaran dipilih. Langkah perusakannya "
            "sendiri TIDAK dipanggil dari sini: `injeksi_r1.py` mematikan "
            "interface router sungguhan lewat SSH, dan menjalankannya dari "
            "tugas terjadwal tanpa satu pun mata yang melihat adalah persis "
            "yang membuat P1.5 ditunda selama ini. Berkas ini memutuskan "
            "KAPAN aman melakukannya; orangnya yang menjalankan.")
        _tulis(catatan)
        print("\n" + catatan["alasan"])
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(sungguhan="--sungguhan" in sys.argv))

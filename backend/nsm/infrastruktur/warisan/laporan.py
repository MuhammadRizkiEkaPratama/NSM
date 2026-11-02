"""Wrapper around `report_service`: a retaining wall during the migration.

`report_service.py` is about 6,000 lines and imported by 43 files. Rewriting it
at once is a gamble: its availability math holds lessons not visible from the
function signatures (`jeda` windows excluded from the denominator, rollups that
store sum and count because an average of averages is wrong, the "ping blocked"
vs "down" distinction). Every retyped line risks silently losing one of them.

So the new layers do NOT import `report_service`. They hold the
`aplikasi.kontrak.Laporan` contract, and the class below connects it to the
old code:

  * now   - identical behavior, because the same code runs;
  * later - functions move one at a time into `aplikasi/kasus/`, changing only
            this file; no route, test, or other caller is touched;
  * done  - this file is deleted, which is how the migration's success is
            measured.

The database session is passed in, never created here. The wrapper must not
own a session lifetime of its own.
"""
import report_service


class LaporanWarisan:
    """Fulfill the `Laporan` contract by forwarding to `report_service` as is."""

    def __init__(self, db):
        self._db = db

    def ringkasan(self, period):
        return report_service.ringkasan(self._db, period)

    def ketersediaan(self, period):
        return report_service.availability_semua(self._db, period)

    def sparkline(self, period, kotak=40):
        return report_service.sparkline_semua(self._db, period, kotak)

    def riwayat_device(self, device_id, period, batas=100):
        return report_service.riwayat_device(self._db, device_id, period, batas)

    def data_grafik(self, device_id, titik=60):
        return report_service.data_grafik(self._db, device_id, titik)

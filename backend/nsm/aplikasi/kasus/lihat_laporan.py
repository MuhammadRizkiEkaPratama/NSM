"""Report use cases, deliberately thin.

While `report_service` still holds the calculations, this class is nearly
empty. It is a seam: routes call use cases, use cases call contracts. When a
calculation moves into the application layer, only this class changes;
routes, route tests, and pages stay the same. Without it, every such move
would touch routes and risk the JSON shape the pages already read.
"""


class LihatRingkasan:
    def __init__(self, laporan):
        self._laporan = laporan

    def jalankan(self, period="24h"):
        return self._laporan.ringkasan(period)


class LihatKetersediaan:
    def __init__(self, laporan):
        self._laporan = laporan

    def jalankan(self, period="24h"):
        return self._laporan.ketersediaan(period)


class LihatSparkline:
    def __init__(self, laporan):
        self._laporan = laporan

    def jalankan(self, period="24h", kotak=40):
        return self._laporan.sparkline(period, kotak)

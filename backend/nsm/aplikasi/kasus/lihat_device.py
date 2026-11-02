"""Use case: list devices with their latest state.

Kept out of the route so its rules (a device is active if `aktif != 0`,
important if `penting == 1`, and which fields reach the page) can be tested
without HTTP and reused by the Excel/Word reports. It takes a repository and
returns data: no FastAPI, no `SessionLocal`, no `.env`. A test can pass a
plain list as the repository.

The output shape matches `/devices` exactly, including the English keys
`ip_address`, `is_reachable`, `response_time_ms`, and `last_checked`, which
the Java pages and JavaScript read by name. Renaming them would be a
behavior change.
"""


class LihatDevice:
    def __init__(self, gudang_device, gudang_denyut):
        self._device = gudang_device
        self._denyut = gudang_denyut

    def jalankan(self):
        # ONE query for the whole fleet's heartbeat, not one per device.
        #
        # Querying the latest `StatusLog` inside the device loop costs 1+N queries
        # per page against a MySQL server across the network. Row order still follows
        # `devices`; only how the heartbeats are fetched differs.
        #
        # `uji_arsitektur_baru.py` confirmed both approaches return the same
        # heartbeat for every device on real data.
        pulse_all = self._denyut.terakhir_semua()
        hasil = []
        for d in self._device.semua():
            pulse = pulse_all.get(d.id)
            hasil.append({
                "id": d.id,
                "name": d.nama,
                "ip_address": d.ip,
                "device_type": d.tipe,
                "platform": d.platform,
                "location": d.lokasi,
                "aktif": d.aktif,
                "penting": d.penting,
                "jeda_alasan": d.jeda_alasan,
                "jeda_sejak": d.jeda_sejak.isoformat() if d.jeda_sejak else None,
                "jeda_oleh": d.jeda_oleh,
                "is_reachable": pulse.terjangkau if pulse else None,
                "response_time_ms": pulse.rtt_ms if pulse else None,
                "last_checked": pulse.waktu.isoformat() if pulse else None,
            })
        return hasil

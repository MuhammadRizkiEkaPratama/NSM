"""Automatic recovery (layer L4 of docs/design/CLOSED-LOOP-AUTOMATION.md), four
cases (stages 4-7): dead GNS3 node, dead service, dead interface, drifted
config, in order of rising risk.

Every function here MUST call `pagar_otomasi.putuskan()` BEFORE touching a
device and check `.izin` before acting. There is no direct path to a device
that bypasses the guardrail.

Modules:
  gns3.py       (low)     node already proven dead; no rollback concept, since
                          the "before" state is the broken state being fixed.
  layanan.py    (medium)  code complete, but the `nsmro` account needs a sudo
                          grant for `systemctl restart` (see
                          `config.get_pemulih_layanan_aktif()`).
  interface.py  (medium)  uses the existing `iface_hidup` catalog entry in
                          `connectors/perintah.py` via `kirim_perintah.kirim()`.
  konfig.py     (high)    built after rollback.py. Limited to keys that have
                          catalog commands (hostname, ntp_server, banner_masuk);
                          other keys are detected but reported as not fixable
                          automatically.
  rollback.py             shared bookkeeping for `state_sebelum` in
                          `PagarTindakan`. The actual rollback logic stays in
                          each module, since rolling back an interface is not
                          the same as rolling back a config.

All four kill switches are OFF by default (`config.get_pemulih_*_aktif()`), and
gate 2 of the guardrail (`PAGAR_DAFTAR_PUTIH`) must also be filled separately:
two different keys to enable anything that touches a device.
"""

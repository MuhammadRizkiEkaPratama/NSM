"""Settings as an OBJECT, not 60 global functions that read the disk.

THE PROBLEM THIS FIXES
----------------------
`config.py` has ~60 `get_*` functions, and ALMOST EVERY ONE of them calls
`_baca()` — which opens, reads, and parses the `.env` file from disk — on
every single call. One `poll_all` round over 46 addresses touches that file
dozens of times to obtain values that have not changed since the process
started.

More expensive than the I/O is what it does to the design: because values
arrive through a global module import, there is no way to run a piece of code
"with AUTO_BAN_AKTIF switched on" other than WRITING a real `.env`.
Configuration becomes global state, and global state cannot be tested two ways
at once.

HOW IT IS FIXED WITHOUT CHANGING BEHAVIOUR
------------------------------------------
This class copies NOT ONE default value out of `config.py`. It calls
`config.get_*()` once and keeps the result. Which means: the single source of
truth is still `config.py`, and it is impossible for a default here to drift
away from the one there in silence — the very defect most likely to appear if
the values were retyped.

  * in production : `Pengaturan.dari_env()` — exactly what happens today,
                    only read once per process;
  * under test    : `Pengaturan(interval_poll=5, auto_ban_aktif=True)` —
                    no file, no disk, no interference between tests.

`muat_ulang()` exists because `.env` really is edited sometimes while the
service is running. What was lost is not that ability, only its accidental
form.
"""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Pengaturan:
    interval_poll: int = 30
    ambang_down: int = 2
    interval_layanan: int = 30
    layanan_aktif: bool = True
    interval_bandwidth: int = 30
    bandwidth_aktif: bool = True
    interval_trafik: int = 60
    trafik_aktif: bool = True
    interval_firewall: int = 300
    firewall_aktif: bool = True
    auto_ban_aktif: bool = False
    auto_ban_maks_per_putaran: int = 5
    auto_ban_interval: int = 60
    ldap_url: str = ""
    ldap_basis: str = ""
    interval_ldap: int = 1800

    @classmethod
    def dari_env(cls):
        """Read `.env` ONCE through `config.py`, so defaults are never duplicated."""
        import config
        return cls(
            interval_poll=config.get_interval(),
            ambang_down=config.get_down_threshold(),
            interval_layanan=config.get_service_interval(),
            layanan_aktif=config.get_service_enabled(),
            interval_bandwidth=config.get_bandwidth_interval(),
            bandwidth_aktif=config.get_bandwidth_enabled(),
            interval_trafik=config.get_traffic_interval(),
            trafik_aktif=config.get_traffic_enabled(),
            interval_firewall=config.get_firewall_interval(),
            firewall_aktif=config.get_firewall_enabled(),
            auto_ban_aktif=config.get_auto_ban_enabled(),
            auto_ban_maks_per_putaran=config.get_auto_ban_maks_per_putaran(),
            auto_ban_interval=config.get_auto_ban_interval(),
            ldap_url=config.get_ldap_url(),
            ldap_basis=config.get_ldap_basis(),
            interval_ldap=config.get_ldap_interval(),
        )

    def dengan(self, **ubah):
        """A copy with some values replaced. Used by tests; the original stays frozen."""
        return replace(self, **ubah)


_tersimpan = None


def pengaturan():
    """This process's settings. Read from disk on the first call only."""
    global _tersimpan
    if _tersimpan is None:
        _tersimpan = Pengaturan.dari_env()
    return _tersimpan


def muat_ulang():
    """Drop the cached copy so `.env` is re-read on the next request."""
    global _tersimpan
    _tersimpan = None

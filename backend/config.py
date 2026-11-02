import contextlib
import os

# The `.env` path is resolved from this file's location, not the working directory, so
# scripts run from any directory see the same settings (a relative path silently fell back
# to all defaults).
_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


# Cached `.env` contents plus the file fingerprint at read time.
# The cache is keyed on the fingerprint rather than blind because `.env` is edited while
# services run (automation switches, thresholds) and edits must take effect without a
# restart. `os.stat` is far cheaper than open+read+parse; `st_mtime_ns` plus size guards
# against coarse timestamps.
_TERSIMPAN = None
_SIDIK = None

# Active override from `sementara()`, or None.
# A separate flag, not a sentinel fingerprint: a sentinel never matches the current file
# fingerprint, so `_baca()` would re-read the file and discard the override.
_TIMPA = None


def _sidik_env():
    try:
        st = os.stat(_ENV)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _baca():
    global _TERSIMPAN, _SIDIK

    if _TIMPA is not None:
        return dict(_TIMPA)

    sidik = _sidik_env()
    if _TERSIMPAN is not None and sidik == _SIDIK:
        # Return a copy so callers that edit the result cannot change settings for everyone
        # else.
        return dict(_TERSIMPAN)

    data = {}
    try:
        with open(_ENV) as f:
            for line in f:
                line = line.strip()
                if line and "=" in line:
                    k, v = line.split("=", 1)
                    data[k] = v
    except FileNotFoundError:
        pass

    _TERSIMPAN, _SIDIK = data, sidik
    return dict(data)


def muat_ulang():
    """Drop the cache so `.env` is re-read on the next call. Rarely needed: only for a file
    replaced with identical size and mtime.
    """
    global _TERSIMPAN, _SIDIK
    _TERSIMPAN = _SIDIK = None


@contextlib.contextmanager
def sementara(**nilai):
    """Run code with overridden settings without touching the disk, for example
    `with config.sementara(AUTO_BAN_AKTIF="1"):`.
    Other values still come from `.env`. Can be nested; the innermost wins for the same key.
    """
    global _TIMPA
    before = _TIMPA
    base = dict(_TIMPA) if _TIMPA is not None else _baca()
    base.update({k: str(v) for k, v in nilai.items()})
    _TIMPA = base
    try:
        yield
    finally:
        # In `finally` so an error mid-block cannot leave overrides in place for the rest of
        # the process.
        _TIMPA = before

def get_interval():
    return int(_baca().get("POLL_INTERVAL", 30))

def get_ssh_user():
    return _baca().get("DEVICE_SSH_USER", "")

def get_ssh_pass():
    return _baca().get("DEVICE_SSH_PASS", "")


# ---------------------------------------------------------------------------
# Fase A (Report) — pengaturan deteksi transisi UP/DOWN
# ---------------------------------------------------------------------------

def get_down_threshold():
    """Consecutive failed pings before a device is declared DOWN (5 x 5 s = 25 s).
    Dynamips routers in GNS3 delay ICMP replies when the host CPU is busy, which produced
    hundreds of false incidents per day at the old threshold of 2, while real outages last
    far longer. Recovery to UP needs only one success. See docs/design/NETWORK-STATUS.md.
    """
    return int(_baca().get("DOWN_THRESHOLD", 5))


def get_probe_ports():
    raw = _baca().get("PROBE_PORTS", "22,80,443")
    hasil = []
    for section in raw.split(","):
        section = section.strip()
        if section.isdigit():
            hasil.append(int(section))
    return hasil or [22]


def get_stabil_min_siklus():
    """DOWN events within the window before a device is marked UNSTABLE.
    Hysteresis: deliberately hard to enter and harder to leave (see
    `get_stabil_pulih_menit`), so the status says how long a device has been flaky. See
    docs/design/NETWORK-STATUS.md.
    """
    try:
        return max(2, int(_baca().get("STABIL_MIN_SIKLUS", 3)))
    except ValueError:
        return 3


def get_stabil_jendela_menit():
    """Time window (minutes) over which get_stabil_min_siklus() is computed."""
    try:
        return max(1, int(_baca().get("STABIL_JENDELA_MENIT", 15)))
    except ValueError:
        return 15


def get_stabil_pulih_menit():
    """Minutes of silence (no DOWN at all) before an unstable device counts as STABLE again.
    Deliberately longer than the entry window so a brief lull inside a flaky pattern does
    not clear the status.
    """
    try:
        return max(1, int(_baca().get("STABIL_PULIH_MENIT", 10)))
    except ValueError:
        return 10




# ---------------------------------------------------------------------------
# Monitoring LAYANAN (services)
# ---------------------------------------------------------------------------

def get_service_interval():
    """Seconds between service checks. Slower than ping because each check opens a real TCP
    connection (and fetches a page for HTTP services), which shows up in the server's access
    log.
    """
    try:
        return max(10, int(_baca().get("SERVICE_INTERVAL", 30)))
    except ValueError:
        return 30


def get_service_enabled():
    return _baca().get("SERVICE_ENABLED", "1").strip() not in ("0", "false", "no")


def get_service_down_threshold():
    try:
        return max(1, int(_baca().get("SERVICE_DOWN_THRESHOLD", 2)))
    except ValueError:
        return 2


def get_traffic_interval():
    """Seconds between access-log and flow reads. Each round opens one SSH session per device.
    Access logs carry per-request timestamps, so late reads lose nothing; flow is a
    snapshot, so short connections can be missed.
    """
    try:
        return max(20, int(_baca().get("TRAFFIC_INTERVAL", 60)))
    except ValueError:
        return 60


def get_sadap_interval():
    """Seconds between HTTP capture windows. Capture listens for the whole window, so the
    interval must exceed the duration (see `get_sadap_durasi`) to avoid overlap. The default
    leaves a gap of about 10 s per minute, which the UI states openly.
    """
    try:
        return max(30, int(_baca().get("SADAP_INTERVAL", 60)))
    except ValueError:
        return 60


def get_sadap_durasi():
    try:
        d = int(_baca().get("SADAP_DURASI", 50))
    except ValueError:
        d = 50
    return max(10, min(d, get_sadap_interval() - 5))


def get_sadap_enabled():
    """HTTP capture is OFF by default, on purpose: it is the only part of NSM that reads packet
    payloads. Enabling it must be a conscious operator decision via `.env`.
    """
    return str(_baca().get("SADAP_HTTP", "0")).strip().lower() in ("1", "true", "ya")


def get_traffic_enabled():
    return _baca().get("TRAFFIC_ENABLED", "1").strip() not in ("0", "false", "no")


def get_replikasi_enabled():
    """Check the MySQL replica at site B (`REPLIKASI_ENABLED=0` disables). ON by default: a
    check that has to be enabled by hand tends never to be, and an unmonitored replica gives
    false assurance.
    """
    return _baca().get("REPLIKASI_ENABLED", "1").strip() not in ("0", "false", "no")


def get_replikasi_host():
    """Host running the replica. EMPTY unless set: a hardcoded lab address would make NSM probe
    someone else's machine on other installs and report a nonexistent replica as broken.
    With no address, nothing is checked.
    """
    return _baca().get("REPLIKASI_HOST", "").strip()


def get_access_log_path():
    """Access log path on the web server device."""
    return _baca().get("ACCESS_LOG", "/var/log/apache2/access.log").strip()


def get_firewall_interval():
    """Seconds between firewall rule reads (300). Rules change a few times a month, and each
    read costs one sudo call per device, so polling faster only repeats identical answers.
    """
    try:
        return max(60, int(_baca().get("FIREWALL_INTERVAL", "300")))
    except ValueError:
        return 300


def get_firewall_enabled():
    """Reading the firewall needs limited sudo rights on the server. Until they are installed
    the job fails each round with a clear message; `FIREWALL_ENABLED=0` is for installs
    where NSM should not use sudo at all.
    """
    return _baca().get("FIREWALL_ENABLED", "1").strip() not in (
        "0", "false", "no")


def get_ldap_url():
    """LDAP directory URL, used to read people's names and titles.
    Empty disables the feature completely: the poller never touches the directory and pages
    show the raw uid. Enabling it makes NSM store full names and titles in its database, so
    it must be a deliberate decision.
    Not read from the Java app's `application.properties` on purpose: each program should
    own its config file, so moving one file cannot break the other with a misleading error.
    """
    return _baca().get("LDAP_URL", "").strip()


def get_ldap_basis():
    """Base DN direktori."""
    return _baca().get("LDAP_BASIS", "dc=bsp,dc=id").strip()


def get_ldap_interval():
    try:
        return max(60, int(_baca().get("LDAP_INTERVAL", "1800")))
    except ValueError:
        return 1800


def get_diagnosa_enabled():
    return _baca().get("DIAGNOSA_ENABLED", "1").strip() not in ("0", "false", "no")


# ---------------------------------------------------------------------------
# Fase B (Bandwidth)
# ---------------------------------------------------------------------------

def get_bandwidth_interval():
    return int(_baca().get("BANDWIDTH_INTERVAL", 30))


def get_bandwidth_enabled():
    return _baca().get("BANDWIDTH_ENABLED", "1").strip() not in ("0", "false", "no")


# ---------------------------------------------------------------------------
# Fase E (Backup otomatis)
# ---------------------------------------------------------------------------

def get_backup_dir():
    """Primary backup folder. Defaults to `<project folder>/backup` (relative, so valid on both
    Windows and Linux); `BACKUP_DIR` in `.env` still overrides it.
    """
    import os
    diminta = _baca().get("BACKUP_DIR", "").strip()
    if diminta:
        return diminta
    root_cause = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root_cause, "backup")


def get_backup_dir2():
    """Second backup folder, ideally on a different disk (e.g. a cloud-synced folder). Leave
    empty to disable. A backup on the same disk as its data is not a backup.
    """
    return _baca().get("BACKUP_DIR2", "").strip()


def get_backup_keep():
    try:
        return max(1, int(_baca().get("BACKUP_KEEP", 14)))
    except ValueError:
        return 14


def get_mysqldump_path():
    """Location of mysqldump.exe. Empty = search PATH."""
    return _baca().get("MYSQLDUMP_PATH", "").strip()


def get_mysql_path():
    return _baca().get("MYSQL_PATH", "").strip()


def baca_application_properties(
        berkas=r"..\frontend\src\main\resources\application.properties"):
    """Read MySQL credentials from the Java app's config file instead of copying them into
    `.env`: a password stored in two places drifts, and backups then fail silently while the
    app looks healthy.
    """
    hasil = {}
    try:
        with open(berkas, encoding="utf-8") as f:
            for baris in f:
                baris = baris.strip()
                if not baris or baris.startswith("#") or "=" not in baris:
                    continue
                k, v = baris.split("=", 1)
                hasil[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return hasil


def get_notif_config():
    """Where the poller hands off device alerts.
    The poller sends no email and reads no user list; it posts to Spring Boot, which owns
    users and their emails. This keeps accounts on the Java side and devices on the Python
    side.
    """
    props = baca_application_properties()
    env = _baca()
    base = (env.get("JAVA_URL", "").strip()
             or props.get("nsm.base-url", "http://localhost:8080"))
    return {
        "url": base.rstrip("/") + "/internal/notifikasi-device",
        "url_gabungan": base.rstrip("/") + "/internal/notifikasi-gabungan",
        "base_url": base.rstrip("/"),
    }


def get_notif_enabled():
    return _baca().get("NOTIF_ENABLED", "1").strip() not in ("0", "false", "no")


def get_notif_jeda_menit():
    try:
        return max(0, int(_baca().get("NOTIF_JEDA_MENIT", 5)))
    except ValueError:
        return 5


# ---------------------------------------------------------------------------
# PAKET C4 -- agen SOC (23 Agustus 2026)
# ---------------------------------------------------------------------------

def get_agen_soc_aktif():
    """Kill switch for the SOC agent. OFF by default.
    The agent never touches devices; enabling the switch only lets it triage, gather
    evidence, write narratives and propose actions. Proposals still pass through
    `pagar_otomasi.putuskan()` (the same gate as the auto-recoverers), and `AGEN_SOC_MODE`
    keeps them propose-only. Three layers on purpose.
    """
    return _baca().get("AGEN_SOC_AKTIF", "0").strip().lower() in (
        "1", "true", "ya")


def get_agen_soc_mode():
    """'usul' (default) or 'jalan'.
    'usul': the agent logs what it WOULD do without doing it. 'jalan': proposals go to the
    gate, which decides.
    Default is propose-only so its proposals can be compared with real human decisions
    before it is trusted. Unknown values are treated as 'usul': a typo in `.env` must not
    become permission to act.
    """
    nilai = _baca().get("AGEN_SOC_MODE", "usul").strip().lower()
    return "jalan" if nilai == "jalan" else "usul"


def get_agen_soc_narasi():
    """May the agent call the external LLM API to narrate incidents? OFF by default.
    Separate from the main kill switch because it is the only part of the agent that sends
    data (device names, IP addresses, event sequences) out of the lab network.
    """
    return _baca().get("AGEN_SOC_NARASI", "0").strip().lower() in (
        "1", "true", "ya")


def get_anthropic_api_key():
    """LLM API key. Empty means narration is never called. Read from `.env`, which is never
    committed (see `.gitignore`).
    """
    return (_baca().get("ANTHROPIC_API_KEY", "") or "").strip()


def get_agen_soc_interval():
    try:
        return max(30, int(_baca().get("AGEN_SOC_INTERVAL", 120)))
    except ValueError:
        return 120


def get_notif_per_insiden():
    """Send one email per INCIDENT instead of one per event. OFF by default.
    Enabling it changes who decides that an email goes out (correlated incidents instead of
    every `device_events` row) on the only path that reaches real inboxes. When ON,
    `notifikasi.proses_antrean()` still marks events done; events already covered by an
    incident are marked without an email, so the queue does not pile up and flood inboxes
    when the switch is turned off.
    """
    return _baca().get("NOTIF_PER_INSIDEN", "0").strip().lower() in (
        "1", "true", "ya")


def get_notif_insiden_pulih():
    """Also send ONE email when an incident closes. ON by default.
    The per-event path that per-incident mode replaces already sends recovery notices, so
    enabling per-incident mode without this would silently drop them.
    `NOTIF_INSIDEN_PULIH=0` disables it.
    """
    return _baca().get("NOTIF_INSIDEN_PULIH", "1").strip().lower() not in (
        "0", "false", "no")


def get_notif_interval():
    try:
        return max(10, int(_baca().get("NOTIF_INTERVAL", 30)))
    except ValueError:
        return 30


# Tiered notifications: no email until an outage is proven to persist, rather than on the
# first DOWN transition. A separate path from the `NOTIF_*` settings above, which
# `notifikasi.py` still uses as the older safety net; both run side by side. See
# docs/design/TIERED-NOTIFICATIONS.md.

def get_notif_putaran_menit():
    try:
        return max(1, int(_baca().get("NOTIF_PUTARAN_MENIT", 5)))
    except ValueError:
        return 5


def get_notif_putaran_butuh():
    try:
        return max(1, int(_baca().get("NOTIF_PUTARAN_BUTUH", 3)))
    except ValueError:
        return 3


def get_notif_sampel_min():
    """Minimum status_logs rows in a window for it to count as valid. Without it a dead poller
    would make every device look like '0 pings succeeded' and trigger an 'all devices down'
    email when only the monitor is down.
    """
    try:
        return max(1, int(_baca().get("NOTIF_SAMPEL_MIN", 30)))
    except ValueError:
        return 30


def get_notif_flap_ambang():
    """DOWN events within 1 hour before a device counts as 'unstable' (a device that flaps too
    fast to ever hit the 'down for 15 full minutes' rule). See
    docs/design/TIERED-NOTIFICATIONS.md for why the threshold is low.
    """
    try:
        return max(1, int(_baca().get("NOTIF_FLAP_AMBANG", 10)))
    except ValueError:
        return 10


def get_notif_flap_tenang_jam():
    try:
        return max(1, int(_baca().get("NOTIF_FLAP_TENANG_JAM", 6)))
    except ValueError:
        return 6



def get_auto_ban_enabled():
    """Kill switch for auto-ban. OFF by default, on purpose.
    `poll_auto_ban()` is the only poller job that changes the firewall without a human
    click, so enabling it (`AUTO_BAN_AKTIF=1`) must be a conscious operator decision, in the
    same spirit as `get_sadap_enabled()`.
    """
    return _baca().get("AUTO_BAN_AKTIF", "0").strip().lower() in ("1", "true", "ya")


def get_auto_ban_maks_per_putaran():
    """Mandatory rate limit: maximum IPs blocked automatically per round.
    Without it, one bad classification (e.g. mass false positives) could block dozens of
    addresses in a single round before a human can hit the kill switch. Candidates left over
    are retried next round, not lost.
    """
    try:
        return max(1, int(_baca().get("AUTO_BAN_MAKS_PER_PUTARAN", 5)))
    except ValueError:
        return 5


def get_auto_ban_interval():
    try:
        return max(30, int(_baca().get("AUTO_BAN_INTERVAL", 60)))
    except ValueError:
        return 60


def get_mysql_config():
    """Return (user, password, database_name, host, port) for backup."""
    env = _baca()
    props = baca_application_properties()

    user = env.get("MYSQL_USER") or props.get("spring.datasource.username", "root")
    password = env.get("MYSQL_PASS") or props.get("spring.datasource.password", "")

    # URL bentuknya: jdbc:mysql://localhost:3306/nsm_auth
    url = props.get("spring.datasource.url", "")
    nama, host, port = "nsm_auth", "localhost", "3306"
    if "//" in url:
        remaining = url.split("//", 1)[1]
        if "/" in remaining:
            alamat, name_db = remaining.split("/", 1)
            nama = name_db.split("?")[0] or nama
            if ":" in alamat:
                host, port = alamat.split(":", 1)
            else:
                host = alamat
    return user, password, env.get("MYSQL_DB", nama), host, port



def get_pagar_daftar_putih():
    """Intent keys/categories allowed to be fixed AUTOMATICALLY, from `PAGAR_DAFTAR_PUTIH` in
    `.env` (comma-separated, e.g. `ntp_server,dns_server`).
    EMPTY by default, on purpose, like `AUTO_BAN_AKTIF`. The `aman_otomatis` classification
    in `sot/katalog.py` says a key is low-risk in principle; this list says the operator has
    consciously enabled it for that key. Both are required.
    """
    mentah = _baca().get("PAGAR_DAFTAR_PUTIH", "")
    return {k.strip() for k in mentah.split(",") if k.strip()}


def get_pagar_batas_per_device_per_jam():
    """Maximum automatic actions for ONE device per hour.
    Without it, a bug that keeps drift from ever clearing (e.g. two systems overwriting the
    same value) would "fix" the same device forever and hide the real problem. See
    docs/design/CLOSED-LOOP-AUTOMATION.md.
    """
    try:
        return max(1, int(_baca().get("PAGAR_BATAS_DEVICE_PER_JAM", 3)))
    except ValueError:
        return 3


def get_pagar_batas_global_per_jam():
    try:
        return max(1, int(_baca().get("PAGAR_BATAS_GLOBAL_PER_JAM", 10)))
    except ValueError:
        return 10


def get_pagar_jam_kerja():
    """(start_hour, end_hour): automatic actions are allowed ONLY in this window. Default 08-17
    (working hours, when a human can check quickly).
    `mulai` is 0-23 and `selesai` is 0-24. `pagar_otomasi._dalam_jam_kerja()` tests
    `mulai <= jam < selesai`, so `selesai` is exclusive; allowing 24 is what makes "all day"
    (0-24) expressible.
    """
    env = _baca()
    try:
        start = int(env.get("PAGAR_JAM_MULAI", 8))
        finish = int(env.get("PAGAR_JAM_SELESAI", 17))
    except ValueError:
        return 8, 17
    if not (0 <= start <= 23 and 0 <= finish <= 24):
        return 8, 17
    return start, finish


def get_pagar_jendela_beku():
    """List of (start, end) ISO datetimes during which NO automatic action runs, regardless of
    hours or allowlist.
    `.env` format (`PAGAR_JENDELA_BEKU`): `start|end` pairs separated by semicolons, e.g.
    `2026-08-25T00:00:00|2026-08-26T00:00:00`. Empty by default. Entries that fail to parse
    are skipped with a printed warning rather than disabling the whole gate.
    """
    from datetime import datetime
    mentah = _baca().get("PAGAR_JENDELA_BEKU", "").strip()
    if not mentah:
        return []
    hasil = []
    for pair in mentah.split(";"):
        pair = pair.strip()
        if not pair:
            continue
        try:
            a, b = pair.split("|")
            hasil.append((datetime.fromisoformat(a.strip()),
                         datetime.fromisoformat(b.strip())))
        except ValueError:
            print("[pagar] PERINGATAN: jendela beku tidak sah, dilewati: %r"
                  % pair)
    return hasil


# Auto-recoverers: each has its own kill switch, OFF by default, same pattern as
# `AUTO_BAN_AKTIF`. Enabling one does not enable the others, since their risks differ (GNS3
# < service < interface < config). Even when enabled, `PAGAR_DAFTAR_PUTIH` must be filled
# explicitly: two layers for anything that touches devices.

def get_pemulih_gns3_aktif():
    return _baca().get("PEMULIH_GNS3_AKTIF", "0").strip().lower() in ("1", "true", "ya")


def get_pemulih_layanan_aktif():
    """Service down: restart over SSH+sudo.
    Requires a sudoers grant for `systemctl restart <service>` on the target server. The
    `nsmro` SSH account is deliberately limited to three firewall commands, so until a grant
    is installed this recoverer always fails at the execution step (harmless, but useless).
    """
    return _baca().get("PEMULIH_LAYANAN_AKTIF", "0").strip().lower() in ("1", "true", "ya")


def get_pemulih_interface_aktif():
    return _baca().get("PEMULIH_INTERFACE_AKTIF", "0").strip().lower() in ("1", "true", "ya")


def get_pemulih_konfig_aktif():
    return _baca().get("PEMULIH_KONFIG_AKTIF", "0").strip().lower() in ("1", "true", "ya")


def get_pemulih_interval():
    try:
        return max(60, int(_baca().get("PEMULIH_INTERVAL", 120)))
    except ValueError:
        return 120


def get_pagar_gagal_beruntun_maks():
    """Consecutive FAILURES before the circuit breaker opens for one (device, action type).
    After that, automatic actions of that type stop for that device until a human
    intervenes.
    Not the same as the rate limit (`PAGAR_BATAS_*_PER_JAM`): the rate limit caps how OFTEN
    a fix is tried but never stops one that always fails, which is the endless loop it
    exists to prevent (see docs/design/CLOSED-LOOP-AUTOMATION.md).
    Self-healing: the count is consecutive, so one success resets it to zero and a problem
    that really got fixed leaves no breaker hanging open.
    """
    try:
        return max(1, int(_baca().get("PAGAR_GAGAL_BERUNTUN_MAKS", 3)))
    except ValueError:
        return 3


# Conditional full automation.
# Three of the four recoverers are classified `wajib_manusia` in
# `pagar_otomasi.RISIKO_PEMULIH` for real reasons: `layanan_restart` can cut live sessions
# or loop without recovering, `interface_up` may target an interface someone shut down on
# purpose, and `konfig_kembalikan` pushes configuration to real devices.
# Instead of reclassifying them, each risk gets a provable condition (see
# `pagar_otomasi._bukti_cukup`). Full automation runs only if the operator enabled the
# switch below AND the evidence is gathered at that moment; otherwise the action falls to a
# human. The switches raise the ceiling, not lower the floor. Default "0": installing a new
# version never silently enables anything.


def _ya(nilai):
    return str(nilai).strip().lower() in ("1", "true", "ya")


def get_otomasi_penuh_layanan():
    """Allow `layanan_restart` automatically WHEN PROVEN: the service is confirmed down via
    `service_events` (not one missed check) and restart attempts for it are under the
    24-hour limit.
    """
    return _ya(_baca().get("OTOMASI_PENUH_LAYANAN", "0"))


def get_otomasi_penuh_interface():
    """Allow `interface_up` automatically WHEN PROVEN: the interface is not administratively
    `shutdown` in the latest config snapshot. A deliberate shutdown on Cisco leaves a
    `shutdown` line, so down without one is a fault, not a decision.
    """
    return _ya(_baca().get("OTOMASI_PENUH_INTERFACE", "0"))


def get_otomasi_penuh_konfig():
    """Allow `konfig_kembalikan` automatically WHEN PROVEN. Strictest condition, since it is
    the riskiest: the restore target must be a snapshot NSM recorded itself and verified,
    and the blast radius must be zero downstream devices.
    """
    return _ya(_baca().get("OTOMASI_PENUH_KONFIG", "0"))


def get_batas_restart_layanan_harian():
    try:
        return max(1, int(_baca().get("BATAS_RESTART_LAYANAN_HARIAN", "3")))
    except ValueError:
        return 3


def get_nsmapp_sandi():
    """SSH password for the nsm-app VM, read from `.env` so scripts never embed it in source."""
    return (_baca().get("NSMAPP_SANDI") or "").strip()


def get_ldap_admin_sandi():
    return (_baca().get("LDAP_ADMIN_SANDI") or "").strip()


def get_uji_105_sandi():
    """SSH password for the lab target host, read from `.env`.
    Intentionally has no fallback value: a script that disrupts a real service should stop
    with a clear message rather than try a guessed password.
    """
    return (_baca().get("UJI_105_PASS") or "").strip()


# =============================================================================
# PAKET A — penerima syslog (23 Agustus 2026)
# =============================================================================


def get_syslog_aktif():
    """Enable the syslog receiver. OFF by default: opening a port that ingests raw network data
    is an operator decision.
    """
    return _ya(_baca().get("SYSLOG_AKTIF", "0"))


def get_syslog_port():
    """UDP port for the syslog receiver. Default 1514, not 514: ports below 1024 need
    privileges on Linux, and running the receiver as root to bind 514 would give root to a
    process that consumes unauthenticated network data.
    Point Cisco devices at it with `logging host <nsm-ip> transport udp port 1514`.
    """
    try:
        p = int(_baca().get("SYSLOG_PORT", "1514"))
        return p if 1 <= p <= 65535 else 1514
    except ValueError:
        return 1514


def get_snmptrap_aktif():
    return _ya(_baca().get("SNMPTRAP_AKTIF", "0"))


def get_snmptrap_port():
    try:
        p = int(_baca().get("SNMPTRAP_PORT", "1162"))
        return p if 1 <= p <= 65535 else 1162
    except ValueError:
        return 1162


def get_snmptrap_community():
    """SNMP community accepted by the trap receiver. Not a password: SNMPv2c sends it in
    cleartext. It is a coarse filter, never authentication.
    """
    return (_baca().get("SNMPTRAP_COMMUNITY") or "public").strip()


def get_korelasi_aktif():
    """Enable incident correlation. ON by default, unlike the recoverers and the syslog
    receiver, because it only reads events that are already recorded and builds its own
    table: no device access, no open ports, nothing sent out. The worst case is wrong
    grouping, which is visible on the page.
    """
    return _ya(_baca().get("KORELASI_AKTIF", "1"))


def get_korelasi_interval():
    try:
        n = int(_baca().get("KORELASI_INTERVAL", "60"))
        return n if 10 <= n <= 3600 else 60
    except ValueError:
        return 60


# Addresses that must NEVER be blocked, and routers that have an ACL path.
# These used to be literal lab addresses in several modules (`report_service/_inti.py`,
# `ubah_firewall.py`, `ubah_acl_router.py`), which pointed at the wrong place on other
# installs. The duplicated checks stay on purpose: each module runs its own check before
# acting. Only the source of the values is shared.

def _daftar(kunci):
    return {b.strip() for b in _baca().get(kunci, "").split(",") if b.strip()}


def get_alamat_nsm():
    """Addresses of the machine running NSM; auto-detected by default. Used to recognize NSM's
    own traffic so it is not read as an attack.
    Detection is the default, not an empty list: an empty list would classify NSM's own
    service checks as login attempts, and once `AUTO_BAN_AKTIF` is on NSM could become a ban
    candidate itself. Set `ALAMAT_NSM` in `.env` (comma-separated) if NSM has several
    addresses or detection picks the wrong network card.
    """
    diminta = _daftar("ALAMAT_NSM")
    if diminta:
        return diminta | {"127.0.0.1"}
    alamat = {"127.0.0.1"}
    try:
        from connectors.lokal import ip_sekarang
        own = ip_sekarang()
        if own:
            alamat.add(own)
    except Exception:
        pass
    return alamat


def get_alamat_dilindungi():
    """Addresses that must never be blocked. Always includes `get_alamat_nsm()`. Add the
    gateway, directory, and any server whose loss would take the network down via
    `ALAMAT_DILINDUNGI` in `.env`.
    """
    return _daftar("ALAMAT_DILINDUNGI") | get_alamat_nsm()


def get_router_acl():
    """Routers that have an ACL block path, from `ROUTER_ACL` (JSON) in `.env`:
    `{"<device_id>": {"acl", "interface", "lokasi", "contoh_host_lokasi", "port_uji"}}`.
    EMPTY by default, like `AUTO_BAN_AKTIF`: ACL blocking is never offered, so a fresh
    install inherits no write access to routers nobody registered. `lokasi` must equal the
    `Device.location` of the devices the router guards; `report_service` uses it to offer
    ACL blocks only when a candidate targets that location.
    """
    mentah = _baca().get("ROUTER_ACL", "").strip()
    if not mentah:
        return {}
    import json
    try:
        data = json.loads(mentah)
    except ValueError:
        # A mistyped config must never silently become a permission.
        return {}
    hasil = {}
    for k, v in (data or {}).items():
        try:
            hasil[int(k)] = v
        except (TypeError, ValueError):
            continue
    return hasil

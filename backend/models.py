"""NSM table definitions.

WHY EVERY `String` HAS A LENGTH
-------------------------------
SQLite accepts `Column(String)` without a length; MySQL refuses:

    CompileError: VARCHAR requires a length on dialect mysql

Columns with free-length content use `Text`, not an oversized VARCHAR. For
example `konfig_snapshots.teks` holds a router's ENTIRE running-config
(thousands of characters); as `String(255)` MySQL would refuse to store the
config snapshot that serves as the safety net before config changes.

Sizes are NAMED, not bare numbers: `IP` explains itself where `String(45)`
does not, and widening one is a one-line change.
"""
from sqlalchemy import (Column, Integer, String, Boolean, Float, DateTime,
                        ForeignKey, Index, Text, UniqueConstraint)
from sqlalchemy.dialects import mysql
from datetime import datetime
from database import Base

# FRACTIONAL-SECOND TIMESTAMPS, FOR CORRECTNESS.
#
# MySQL `DATETIME` without `fsp` stores whole seconds and ROUNDS fractional
# values instead of truncating. So 10:59:59.700000 becomes 11:00:00 and the
# sample lands in a DIFFERENT `status_rollup_jam` bucket than the hour it was
# measured in. This silently breaks `uji_rollup.py`, which checks that the
# rollup matches the raw rows.
#
# `with_variant` applies DATETIME(6) to MySQL only; SQLite is unchanged, so the
# existing `nsm.db` and `penyangga.db` are unaffected.
WAKTU = DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")

# 45 chars: max length of an IPv6 address in text form, including mixed forms
# like ::ffff:192.168.20.101. The lab is IPv4 for now.
IP = String(45)

# Names of people, devices, services, accounts.
NAMA = String(100)

# Short keywords from a closed list in code: UP/DOWN, outage category,
# firewall direction, identity type. Not sentences.
KODE = String(30)

# Even shorter: values of a few letters (icmp/tcp/lokal, SHA/AES).
KODE_PENDEK = String(20)

# A sha256 hex digest is always exactly 64 characters.
SIDIK = String(64)

# File paths, URLs, user agents. Long but still indexable:
# 500 utf8mb4 chars = 2000 bytes, under the InnoDB index limit (3072 bytes).
JALUR = String(500)

# Human-readable text: reasons, notes, short details.
KALIMAT = String(500)

# Secrets and key paths. A bcrypt hash is 60 chars; Windows paths can be long.
RAHASIA = String(255)

# Interface names. NOT KODE(30) even though "FastEthernet0/1" is 15 chars:
# Windows adapter names are free-form ("VMware Network Adapter VMnet1" is 29)
# and SNMP `ifDescr` may be up to 255 octets (RFC 2863). A tight limit would
# silently reject bandwidth samples from the next device.
IFACE = String(255)


class Device(Base):
    __tablename__ = "devices"
    id = Column(Integer, primary_key=True)
    name = Column(NAMA)
    ip_address = Column(IP)
    device_type = Column(KODE)
    platform = Column(KODE, nullable=True)
    username = Column(NAMA)
    password = Column(RAHASIA)
    # Path to the SSH private key file. If set, it is used INSTEAD of the
    # password. Only the path is stored, not the secret, so the daily backup
    # that copies nsm.db to cloud storage carries no usable login credential.
    ssh_key_path = Column(RAHASIA, nullable=True)

    # Identity beyond IP (see `identitas.py`, docs/design/TRAFFIC-IDENTITY-FW.md).
    # One of: `sama`, `kemungkinan_sama`, `bertentangan`, `belum_diketahui`.
    # `belum_diketahui` (not asked yet) and `bertentangan` (asked, got a different
    # answer) are deliberately distinct.
    identitas_vonis = Column(KODE_PENDEK, nullable=True)
    identitas_diperiksa = Column(WAKTU, nullable=True)

    # Reason for pausing monitoring.
    #
    # Previously pausing only wrote `aktif = 0`, so an intentional pause looked
    # the same as a forgotten one in the data.
    #
    # NULL means "not recorded", NOT "no reason". Pauses that predate this column
    # are deliberately not backfilled with guesses.
    jeda_alasan = Column(KALIMAT, nullable=True)
    jeda_sejak = Column(WAKTU, nullable=True)
    jeda_oleh = Column(NAMA, nullable=True)
    location = Column(NAMA)
    # GNS3 node name (e.g. "R1", "SW-A"), set ONLY for devices that are Dynamips
    # emulated nodes in this lab. NULL means a regular physical device/VM, or not
    # Cisco at all (linux, etc.).
    #
    # Used by `kirim_perintah.py` because `reload` behaves DIFFERENTLY: on
    # physical gear, `reload` reboots and comes back. On GNS3/Dynamips, `reload`
    # shuts the emulated machine down PERMANENTLY (see docs/POSTMORTEM-R1.md).
    # When set, the safety net does NOT use `reload in N`; it recovers via the
    # GNS3 API (`gns3/hidupkan_ulang_node.py`) instead.
    gns3_node = Column(KODE_PENDEK, nullable=True)

    # Package D: owner tenant of this device. NULL means "unassigned", which is
    # VALID, not a leak: `tenancy.py` filters on `tenant_id == <id>`, so NULL
    # rows are never visible to any tenant, only to callers without a tenant
    # context (poller, CLI, platform admin).
    #
    # `devices` is deliberately the ONLY table with this column. Child tables
    # (status_logs, syslog_pesan, insiden, ...) join via `device_id` and are
    # filtered with a subquery. Copying `tenant_id` everywhere would be faster
    # but creates a second source of truth: moving a device to another tenant
    # would require rewriting millions of child rows, inconsistent until done.
    tenant_id = Column(Integer, ForeignKey("tenant.id"), nullable=True,
                       index=True)
    # Paused = skipped by the poller. For devices temporarily off this network
    # (e.g. a laptop taken elsewhere), so they are not logged as a continuous
    # outage. History is NOT deleted.
    aktif = Column(Integer, nullable=True, default=1)
    # Only devices flagged important send email on down/recovery.
    # Default OFF: notifications for everything quickly become noise and
    # get ignored.
    penting = Column(Integer, nullable=True, default=0)
    # --- SNMP v3. Empty = device is not monitored via SNMP. ---
    snmp_user = Column(NAMA, nullable=True)
    snmp_auth_pass = Column(RAHASIA, nullable=True)  # auth password
    snmp_priv_pass = Column(RAHASIA, nullable=True)  # privacy (encryption) key
    snmp_auth_proto = Column(KODE_PENDEK, nullable=True)  # SHA / SHA256 / MD5
    snmp_priv_proto = Column(KODE_PENDEK, nullable=True)  # AES / DES
    snmp_port = Column(Integer, nullable=True)  # default 161

    # --- Tiered notifications (see notifikasi_berjenjang.py) ---
    # When the last "DOWN" email was sent FOR THE ONGOING OUTAGE. NULL = no
    # email pending. Set when the DOWN email goes out, cleared when the device
    # recovers and the RECOVERED email goes out. NOT a counter, just a
    # "sent for this one" marker.
    notif_mati_dikirim = Column(WAKTU, nullable=True)
    # When the last "UNSTABLE" email (>=N DOWNs/hour) was sent.
    # Used for the NOTIF_FLAP_TENANG_JAM quiet period before warning again.
    notif_flap_dikirim = Column(WAKTU, nullable=True)

class StatusLog(Base):
    """RAW result of each device check, one row per ping round.

    `sumber` records HOW the device was proven reachable. A host can block
    ICMP while its TCP ports still answer; such a host is alive.

        "icmp"  ping answered (normal path)
        "tcp"   ping NOT answered, but a TCP port answered. The device counts
                as reachable, and the reason is stored so it is never confused
                with a clean ping result
        "lokal" read directly via psutil on this machine

    Without this column the only way to tell them apart is guessing from an
    empty `response_time_ms`.
    """
    __tablename__ = "status_logs"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    timestamp = Column(WAKTU, default=datetime.now)
    is_reachable = Column(Boolean)
    response_time_ms = Column(Float)
    sumber = Column(KODE_PENDEK, nullable=True)


class StatusRollupJam(Base):
    """Hourly rollup of `status_logs` per device. Never pruned.

    WHY: `status_logs` grows about 8 MB/day and is pruned at 35 days, so older
    history is lost for good. One hour holds about 720 raw rows (5 s polls);
    one row here replaces them, so a year for six devices is only about 52,000
    rows, small enough to keep forever.

    WHY SUM AND COUNT, NOT AVERAGE. An average of averages is WRONG when hours
    have different sample counts: an hour with 720 samples and one with 12
    (poller just started) would get equal weight.

    Storing SUM and COUNT, the average over any number of hours is
    `sum(latency_jumlah) / sum(latency_sampel)`, which matches recomputing from
    raw rows exactly. `uji_rollup.py` enforces that match.

    `jam` is always the start of the hour (minute, second, microsecond = 0).
    (device_id, jam) is unique so rebuilding never duplicates rows.
    """
    __tablename__ = "status_rollup_jam"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    jam = Column(WAKTU)

    # How many times the device was checked that hour and how many were
    # reachable. Sample-based availability = sampel_naik / sampel.
    sampel = Column(Integer)
    sampel_naik = Column(Integer)

    # Latency: sum and count, not average (see class docstring).
    # `latency_sampel` is NOT always equal to `sampel_naik`: a device proven
    # alive via TCP counts as reachable with empty latency.
    latency_jumlah = Column(Float)
    latency_sampel = Column(Integer)
    latency_min = Column(Float, nullable=True)
    latency_maks = Column(Float, nullable=True)

    # When this row was computed. If the rollup lags far behind,
    # `pangkas_data.py` refuses to prune raw rows not yet rolled up.
    dihitung = Column(WAKTU, default=datetime.now)


class DeviceEvent(Base):
    """Device status TRANSITIONS (not every poll).

    status_logs records EVERY ping result (every 5 s, never pruned). This table
    is written only when status CHANGES: UP -> DOWN or DOWN -> UP, so it stays
    small and reports read fast.

    event_type   : "UP" or "DOWN" (the NEW status)
    duration_sec : how long the PREVIOUS status lasted.
                   On an UP event this is the DOWN duration (outage length).
    category     : "dead"         -> ping failed & no TCP port answered
                   "ping_blocked" -> ping failed BUT a TCP port answered (alive)
                   "recovered"    -> device back UP
                   "baseline"     -> initial record when monitoring starts
    note         : manual admin note (e.g. "scheduled maintenance")
    """
    __tablename__ = "device_events"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    event_type = Column(KODE_PENDEK)
    timestamp = Column(WAKTU, default=datetime.now)
    duration_sec = Column(Float, nullable=True)
    category = Column(KODE, nullable=True)
    detail = Column(KALIMAT, nullable=True)
    last_rtt_ms = Column(Float, nullable=True)
    note = Column(KALIMAT, nullable=True)
    # When the email for this event was sent. Empty = never.
    # Marked on the event row itself so an event is never emailed twice, even
    # if the poller restarts.
    notif_terkirim = Column(WAKTU, nullable=True)


class Service(Base):
    """One monitored service on a device.

    Ping only proves the MACHINE is up. A service ON it can die without
    changing the ping result (Apache stops while Linux is fine).

    jenis : "tcp"   -> just prove something listens on the port
            "http"  -> request a page, check status code & content
            "mysql" -> connect and read the MySQL server greeting

    "tcp" and "http" are separate because an open port 80 does NOT mean the
    site is healthy: Apache can accept connections and return 500 for every
    request.
    """
    __tablename__ = "services"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    nama = Column(NAMA)
    jenis = Column(KODE_PENDEK)  # tcp / http / mysql
    port = Column(Integer)
    path = Column(JALUR, nullable=True)  # for http, e.g. /hello.php
    harap_status = Column(Integer, nullable=True)  # status code considered healthy
    harap_teks = Column(KALIMAT, nullable=True)  # text that must appear in the page body
    timeout_detik = Column(Integer, nullable=True, default=5)

    # systemd unit name for this service (used by `pemulih/layanan.py`).
    # NULL BY DEFAULT, meaning "not mapped, must NOT be auto-restarted", never
    # "guess from the name". Names like "E-Canteen" or "Login NSM" have no safe
    # textual mapping to a real unit (`apache2`, `mysql`, ...), so the operator
    # sets this ONCE per service that may be restarted, like
    # `PAGAR_DAFTAR_PUTIH`: two separate keys to enable anything that actually
    # touches a device.
    unit_systemd = Column(KODE, nullable=True)
    # Access log path OWNED BY THIS SERVICE, not by the device.
    #
    # A single global path (`ACCESS_LOG` in config) is wrong once a machine
    # serves more than one site: `.103` runs Apache on :80 AND E-Canteen on
    # :8080, and only the Apache log would be read.
    #
    # Empty means "use the default path from config", so existing services keep
    # their behavior.
    log_akses = Column(JALUR, nullable=True)
    # Like Device.aktif: paused means stop checking, not delete.
    # History stays intact.
    aktif = Column(Integer, nullable=True, default=1)


class ServiceCheck(Base):
    """RAW result of each service check, parallel to status_logs.

    All rows are kept so service charts and sparklines have data. Much smaller
    than status_logs because checks are less frequent: 3 services every 30 s is
    8,640 rows/day versus 86,400 for pinging 5 devices every 5 s.
    """
    __tablename__ = "service_checks"
    id = Column(Integer, primary_key=True)
    service_id = Column(Integer, ForeignKey("services.id"))
    timestamp = Column(WAKTU, default=datetime.now)
    ok = Column(Boolean)
    kode = Column(Integer, nullable=True)  # HTTP status code, if any
    waktu_ms = Column(Float, nullable=True)  # service response time
    kategori = Column(KODE, nullable=True)  # technical cause on failure


class ServiceEvent(Base):
    """UP/DOWN transition of a SERVICE, parallel to DeviceEvent.

    This is where "what caused the last incident" is stored. Categories are more
    specific than device_events because checks are layered and the failing layer
    is the diagnosis.

    kategori:
      koneksi_ditolak    port refused the connection. Host up, SERVICE down.
      timeout            no answer at all. Usually a firewall silently dropping
                         packets, or the device is overloaded.
      host_tak_terjangkau no route to host. Network problem, not the service.
      http_5xx           server answered but is broken internally.
      http_4xx           server answered but the monitored page is missing.
      isi_tak_cocok      status code is right but content is not as expected.
      mysql_bukan_mysql  something listens but it is not MySQL.
      pulih              service answers correctly again.

    The two diagnosis columns hold output of read-only commands NSM ran on the
    device at the time. Two snapshots, so before and after can be compared.
    """
    __tablename__ = "service_events"
    id = Column(Integer, primary_key=True)
    service_id = Column(Integer, ForeignKey("services.id"))
    device_id = Column(Integer, ForeignKey("devices.id"))
    event_type = Column(KODE_PENDEK)  # UP / DOWN
    timestamp = Column(WAKTU, default=datetime.now)
    duration_sec = Column(Float, nullable=True)
    kategori = Column(KODE, nullable=True)
    detail = Column(Text, nullable=True)  # human-readable cause
    kode = Column(Integer, nullable=True)
    # Evidence chain: ping & other port results at the time, so the incident card
    # can show which layer was healthy and which failed.
    bukti = Column(Text, nullable=True)
    saran = Column(Text, nullable=True)
    diagnosa_mulai = Column(Text, nullable=True)  # snapshot when the outage opened
    diagnosa_pulih = Column(Text, nullable=True)  # snapshot when the outage closed
    notif_terkirim = Column(WAKTU, nullable=True)


class AksesWeb(Base):
    """One HTTP request recorded in a web server access log.

    Interface counters cannot say who the peer is: `bandwidth_samples` knows
    "testUbuntu received 4 MB" but not from whom. To answer "which device
    downloaded what, and how much", the server's own log is the only reliable
    source, e.g. "192.168.1.43 downloaded /backup.zip, 40 MB, at 14:03, status
    200".

    byte_kirim = bytes SENT BY THE SERVER to the client (a download from the
    client's view). Apache combined log does not record request body size, so
    uploads are visible only with mod_logio enabled.
    """
    __tablename__ = "akses_web"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    # Which service handled this request.
    #
    # Needed once `.103` has two access logs (Apache :80 and E-Canteen :8080);
    # otherwise both sources share the same `device_id` and "how much E-Canteen
    # traffic" could only be guessed from the path (`/` is served by both).
    #
    # NULL means NSM does not know the owning service (the log came from the
    # shared default config path). Guessing would make per-service numbers look
    # certain when they are not. Older rows are NULL too.
    service_id = Column(Integer, ForeignKey("services.id"), nullable=True)
    waktu = Column(WAKTU)
    ip_klien = Column(IP)
    metode = Column(KODE_PENDEK)
    path = Column(JALUR)
    protokol = Column(KODE_PENDEK, nullable=True)
    status = Column(Integer, nullable=True)
    byte_kirim = Column(Float, nullable=True)  # server -> client (download)
    byte_terima = Column(Float, nullable=True)  # client -> server, needs mod_logio
    rujukan = Column(JALUR, nullable=True)
    user_agent = Column(JALUR, nullable=True)
    # Requests from NSM itself. Flagged, not dropped: a monitor that hides its own
    # traffic makes its numbers unaccountable. Pages may filter them out, but the
    # data stays.
    dari_nsm = Column(Integer, nullable=True, default=0)


class SadapanHttp(Base):
    """Files actually transferred over PLAIN HTTP, proven from real packet
    CONTENT, not guessed from the access log.

    WHY `akses_web` IS NOT ENOUGH FOR UPLOADS. The access log is written AFTER
    the request is processed and Apache combined log never stores the request
    body, only `byte_terima` (with `mod_logio`), without file name or content.
    Capturing packets (`dumpcap` + `tshark`) reads the request body, so file
    name and direction are known for certain.

    WHY PLAIN HTTP ONLY. This table deliberately never touches encrypted layers
    (SSH, LDAP StartTLS, MySQL TLS replication): reading them would require
    breaking TLS (a MITM certificate on every client), defeating the encryption
    built precisely so that content is NOT visible to anyone sniffing the
    network. Scope is deliberately narrow: one interface, one port, one
    unencrypted protocol. See `connectors/sadap_http.py`.

    `arah` is "unggah" if the body is in the CLIENT request (client sends a
    file), "unduh" if it is in the server response, and NULL if tshark cannot
    tell; NULL is honest, never a guess.
    """
    __tablename__ = "sadapan_http"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    waktu = Column(WAKTU)
    arah = Column(String(10), nullable=True)
    ip_klien = Column(IP)
    path = Column(JALUR, nullable=True)
    nama_berkas = Column(JALUR, nullable=True)
    content_type = Column(KODE_PENDEK, nullable=True)
    ukuran = Column(Float, nullable=True)
    # Content fingerprint (time+ip+path+size), same pattern as PenolakanAcl.
    # Capture may re-read the same window if the poller lags one round; without
    # this the same row would be stored twice.
    sidik = Column(SIDIK, unique=True)


class PosisiLog(Base):
    """How far into each log file NSM has read, as a byte offset plus the last file size.
    A file smaller than the stored position means the log was rotated, so reading restarts at zero.
    """
    __tablename__ = "posisi_log"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    jalur = Column(JALUR)
    posisi = Column(Float, default=0)
    ukuran_terakhir = Column(Float, default=0)
    diperbarui = Column(WAKTU, default=datetime.now)


class Flow(Base):
    """One active network conversation on a device, read from `ss -tin`.
    Any device and protocol, unlike `akses_web`. This is a periodic snapshot: connections that
    start and end between two reads are never seen.
    """
    __tablename__ = "flow_koneksi"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    waktu = Column(WAKTU, default=datetime.now)
    ip_lokal = Column(IP, nullable=True)
    port_lokal = Column(Integer, nullable=True)
    ip_lawan = Column(IP)
    port_lawan = Column(Integer, nullable=True)
    byte_masuk = Column(Float, nullable=True)
    byte_keluar = Column(Float, nullable=True)
    keadaan = Column(KODE, nullable=True)
    proses = Column(JALUR, nullable=True)


class IdentitasPerangkat(Base):
    """One identity marker of a device: hostname, serial, MAC, etc. See docs/design/TRAFFIC-IDENTITY-FW.md.
    Exists for safety: several lab devices use default addresses that could match devices on
    another network, and a wrong target would change someone else's configuration.

    One row per value, not per kind. When a hostname changes the old row is kept (its `terakhir`
    stops advancing) and a new row is added, so "since when did this change?" stays answerable.
    Nothing stored here is secret, and none of it may be used as a credential.
    """
    __tablename__ = "identitas_perangkat"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    jenis = Column(KODE)        # hostname / serial / mac / machine_id / sysname
    nilai = Column(RAHASIA)
    pertama = Column(WAKTU)
    terakhir = Column(WAKTU)
    sumber = Column(KODE_PENDEK)  # konfig / snmp / ssh / lokal / arp


class KonfigTemuan(Base):
    """Result of evaluating ONE compliance rule against ONE config snapshot.
    See docs/design/CONFIG-COMPLIANCE.md. The rules live in `connectors/kepatuhan.py` as data.

    `hasil` is one of PATUH (applies, met), TEMUAN (applies, not met) or TIDAK_BERLAKU (rule is
    not for this device's platform). The third value is required: without it a Linux device
    would look "100% compliant" against Cisco rules that were never checked on it.

    `baris_bukti` holds the triggering config line as stored (already masked by
    `konfig.samarkan()`). It is EMPTY for "must exist" rules that became a TEMUAN, since the
    evidence is the absence of a line.
    """
    __tablename__ = "konfig_temuan"
    id = Column(Integer, primary_key=True)
    snapshot_id = Column(Integer, ForeignKey("konfig_snapshots.id"))
    device_id = Column(Integer, ForeignKey("devices.id"))
    aturan_id = Column(KODE)
    hasil = Column(KODE_PENDEK)
    keparahan = Column(KODE_PENDEK)
    baris_bukti = Column(KALIMAT, nullable=True)
    nomor_baris = Column(Integer, nullable=True)
    dinilai = Column(WAKTU, default=datetime.now)


class KonfigSnapshot(Base):
    """One configuration snapshot of a device, stored ONLY when it changes.
    Read-only part of the config-push feature: the prior state must be recorded somewhere
    before anyone can change it. Storing every poll would pile up identical copies; this way
    the row count equals the number of real changes and doubles as history.

    `teks` is already masked and cleaned by `connectors/konfig.py` (passwords, SNMP communities
    and pre-shared keys replaced; self-changing lines such as `ntp clock-period` dropped).
    Without masking, device secrets would accumulate in `nsm.db`.
    """
    __tablename__ = "konfig_snapshots"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    waktu = Column(WAKTU, default=datetime.now)
    sidik = Column(SIDIK)                        # sha256 running-config terolah
    teks = Column(Text)                          # running-config siap simpan
    baris_tambah = Column(Integer, nullable=True)
    baris_hapus = Column(Integer, nullable=True)

    # Did the ACL change in this snapshot?
    # 1 = the changed lines (added or removed) touch an ACL definition
    # 0 = snapshot differs from the previous one, but not in the ACL
    # NULL = first snapshot of the device, or the platform is unknown to `konfig.deteksi_acl_berubah`
    #
    # Lets an ACL edit made outside NSM (no matching `firewall_perubahan` row) show up on the
    # Firewall page by itself.
    acl_berubah = Column(Integer, nullable=True)

    # --- Configuration that will apply AFTER the device restarts ---
    #
    # A running/startup difference means changes can be silently lost at power-off.
    # A snapshot is stored when EITHER fingerprint changes, not only the running one, because
    # `write memory` changes startup without touching running; otherwise the "unsaved" marker
    # would never clear.
    sidik_startup = Column(SIDIK, nullable=True)
    teks_startup = Column(Text, nullable=True)
    # Number of lines that differ between running and startup.
    # 0 = saved, >0 = changes would be lost on reboot, NULL = platform has no startup-config
    # concept (NOT the same as zero).
    belum_disimpan = Column(Integer, nullable=True)


# =============================================================================
# SOURCE OF TRUTH (stage 1) -- layer L1 of docs/design/CLOSED-LOOP-AUTOMATION.md.
# See `sot/__init__.py` for why the template is deliberately not a table here.
#
# FOUR TABLES, UNLIKE EVERY TABLE ABOVE
# All earlier tables store OBSERVATIONS (what a device answered). The four below store
# INTENT (what it SHOULD answer). The poller never writes them; only people do, via the web UI.
# =============================================================================

class IntentNilai(Base):
    """One intent key for one device. The value is stored as JSON.

    JSON rather than one column per value shape: the catalog (`sot/katalog.py`) has five shapes
    (text, number, bool, choice, list) and keeps growing. The value is strictly validated by
    `katalog.periksa()` before it reaches this table.

    One row per (device_id, kunci), no history; history lives in `IntentRiwayat`, so this table
    answers "what is the value NOW" with a single SELECT.
    """
    __tablename__ = "intent_nilai"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    kunci = Column(KODE, nullable=False)
    nilai_json = Column(Text, nullable=False)
    diubah_oleh = Column(NAMA, nullable=True)
    diubah_waktu = Column(WAKTU, default=datetime.now)


class IntentInterface(Base):
    """One intended interface for one device.
    Rows are saved as a whole from the web form, then reconciled against old rows: a row no
    longer submitted counts as deleted by a person. `sot/service.py` enforces this.
    """
    __tablename__ = "intent_interface"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    nama = Column(IFACE, nullable=False)
    deskripsi = Column(KALIMAT, nullable=True)
    ip_address = Column(IP, nullable=True)
    subnet_mask = Column(IP, nullable=True)
    vlan_id = Column(Integer, nullable=True)
    shutdown = Column(Boolean, default=False)
    diubah_oleh = Column(NAMA, nullable=True)
    diubah_waktu = Column(WAKTU, default=datetime.now)


class IntentVlan(Base):
    """One intended VLAN for one device. Same pattern as `IntentInterface`."""
    __tablename__ = "intent_vlan"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    vlan_id = Column(Integer, nullable=False)
    nama = Column(NAMA, nullable=True)
    diubah_oleh = Column(NAMA, nullable=True)
    diubah_waktu = Column(WAKTU, default=datetime.now)


class IntentRute(Base):
    """One intended static route for one device. Same pattern as `IntentInterface`."""
    __tablename__ = "intent_rute"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    tujuan = Column(IP, nullable=False)
    subnet_mask = Column(IP, nullable=False)
    next_hop = Column(IP, nullable=False)
    catatan = Column(KALIMAT, nullable=True)
    diubah_oleh = Column(NAMA, nullable=True)
    diubah_waktu = Column(WAKTU, default=datetime.now)


class IntentRiwayat(Base):
    """Audit trail of EVERY intent change (added, changed, deleted). Written by `sot/service.py`.
    `kategori` is 'nilai'/'interface'/'vlan'/'rute'; `kunci` is the row identifier (key name,
    interface name, VLAN number, or "destination/mask/next_hop" for routes).
    `lama_json`/`baru_json` NULL means the row did not exist yet / was deleted.
    """
    __tablename__ = "intent_riwayat"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    kategori = Column(KODE_PENDEK, nullable=False)
    # `KODE` (30 chars) is too short here: for routes `kunci` is the combined
    # destination/mask/next_hop, and `('0.0.0.0', '0.0.0.0', '10.10.10.2')` alone is 36 chars
    # (MySQL "Data too long for column 'kunci'"). Widened here only, not via the shared `KODE` alias.
    kunci = Column(String(150), nullable=True)
    aksi = Column(KODE_PENDEK, nullable=False)   # tambah / ubah / hapus
    lama_json = Column(Text, nullable=True)
    baru_json = Column(Text, nullable=True)
    oleh = Column(NAMA, nullable=True)
    waktu = Column(WAKTU, default=datetime.now)


Index("ux_intent_nilai", IntentNilai.device_id, IntentNilai.kunci,
     unique=True)
Index("ux_intent_iface", IntentInterface.device_id, IntentInterface.nama,
     unique=True)
Index("ux_intent_vlan", IntentVlan.device_id, IntentVlan.vlan_id,
     unique=True)
Index("ux_intent_rute", IntentRute.device_id, IntentRute.tujuan,
     IntentRute.subnet_mask, IntentRute.next_hop, unique=True)
Index("ix_intent_riwayat_device", IntentRiwayat.device_id, IntentRiwayat.waktu)


# =============================================================================
# AUTOMATION GUARD (stage 3) -- layer L3 of docs/design/CLOSED-LOOP-AUTOMATION.md.
# One table: a record of EVERY guard decision, allowed or denied. Logic in `pagar_otomasi.py`.
# =============================================================================

class PagarTindakan(Base):
    """One guard decision (allowed or denied) for one candidate automatic action.
    Both outcomes are recorded: "why did the system NOT fix this" needs an answer from data,
    and rate limits need rows to count from day one.

    `status_verifikasi` is separate from `keputusan`: allowed does not mean succeeded.
    Recoverers MUST call `pagar_otomasi.catat_verifikasi()` after acting; if never called the
    column stays NULL, which is distinct from `False` (tried and failed).
    """
    __tablename__ = "pagar_tindakan"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
    kategori = Column(KODE_PENDEK, nullable=False)
    kunci = Column(KODE, nullable=False)  # intent key, category name, or remediator type
    keputusan = Column(KODE_PENDEK, nullable=False)  # izin / tolak
    alasan = Column(KALIMAT, nullable=False)
    diminta_oleh = Column(NAMA, nullable=True)        # nama modul pemanggil, mis. 'drift_autofix'
    waktu = Column(WAKTU, default=datetime.now)
    status_verifikasi = Column(Boolean, nullable=True)
    verifikasi_bukti = Column(KALIMAT, nullable=True)
    verifikasi_waktu = Column(WAKTU, nullable=True)

    # --- Stage 8: real rollback ---
    #
    # Kept in the same table: one row already answers "which action, when, which device", and
    # rollback is about that same action.
    #
    # `state_sebelum` NULL means this recoverer stores no prior state (see `pemulih/rollback.py`),
    # not "tried to save but empty".
    state_sebelum = Column(Text, nullable=True)
    state_sesudah = Column(Text, nullable=True)
    # NULL = rollback not relevant/not attempted, True = restored, False = the rollback ITSELF
    # failed (the worst case: the fix and the way back both failed).
    rollback_dilakukan = Column(Boolean, nullable=True)


Index("ix_pagar_device_waktu", PagarTindakan.device_id, PagarTindakan.waktu)
Index("ix_pagar_keputusan_waktu", PagarTindakan.keputusan, PagarTindakan.waktu)


class NamaAlamat(Base):
    """Cached reverse-DNS name for an IP address.
    Stored rather than looked up on page load: a reverse lookup took 4.5 to 9 s (failed lookups
    the longest) and the Traffic page refreshes every 30 s with up to 25 addresses. The poller
    resolves in the background; the page only reads.

    Failures are stored too (`nama` NULL, `ditemukan` 0) so addresses without a PTR record are
    not retried every cycle. `diperiksa` allows an occasional re-check since names can go stale.
    """
    __tablename__ = "nama_alamat"
    ip = Column(IP, primary_key=True)
    nama = Column(RAHASIA, nullable=True)
    ditemukan = Column(Integer, nullable=True, default=0)
    diperiksa = Column(WAKTU, default=datetime.now)


class BandwidthSample(Base):
    """Per-interface traffic sample.
    Devices report byte counters, not speed: bps = (octets_now - octets_before) * 8 / seconds.
    The raw counters (`in_octets`/`out_octets`) are stored so the delta survives a poller restart.
    source: "ssh" (/proc/net/dev or show interfaces) or "snmp".
    """
    __tablename__ = "bandwidth_samples"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    iface = Column(IFACE)
    timestamp = Column(WAKTU, default=datetime.now)
    in_octets = Column(Float, nullable=True)
    out_octets = Column(Float, nullable=True)
    in_bps = Column(Float, nullable=True)
    out_bps = Column(Float, nullable=True)
    source = Column(KODE_PENDEK, nullable=True)


class TransferBerkas(Base):
    """One action on a file: who, what, when, from which machine.

    Covers two protocols in one table, told apart by `sumber` ("SFTP" / "SMB"), because both
    answer "who touched which file". Columns that differ may be empty:
      SFTP -> has `pid` and byte counts; no `mesin_klien`/`berbagi`
      SMB  -> has `mesin_klien`, `berbagi`, `hasil`; NO byte counts (`full_audit` logs
              operations, not volume; see `connectors/sambaaudit.py`)

    Separate from `akses_web` because the subject differs: `akses_web.ip_klien` is an ADDRESS,
    `pengguna` here is a PERSON (from LDAP, stable across machines and DHCP leases).
    `pengguna` may be None: the session was opened before NSM started reading. Recorded as is.
    """
    __tablename__ = "transfer_berkas"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    waktu = Column(WAKTU)
    # SFTP session process id; links rows that name the user to rows that name the file.
    pid = Column(Integer, nullable=True)
    pengguna = Column(NAMA, nullable=True)
    ip_klien = Column(IP, nullable=True)
    # Actions: `AMBIL` / `KIRIM` / `BUKA` / `HAPUS` / `GANTI_NAMA` / `BUAT_FOLDER` / `HAPUS_FOLDER`
    aksi = Column(KODE_PENDEK)
    jalur = Column(JALUR)
    jalur_baru = Column(JALUR, nullable=True)
    # From the SERVER's view: byte_baca > 0 means the server read the file to send it to the client.
    # Always 0 for SMB rows (operations are logged, not volume), meaning "unknown", NOT "no bytes moved".
    byte_baca = Column(Float, default=0)
    byte_tulis = Column(Float, default=0)

    # "SFTP" or "SMB". May be None on older rows; readers treat None as "SFTP".
    sumber = Column(KODE_PENDEK, nullable=True)
    # NetBIOS name of the client machine (Samba %m). Empty for SFTP.
    mesin_klien = Column(NAMA, nullable=True)
    # SMB share name. Empty for SFTP.
    berbagi = Column(NAMA, nullable=True)
    # "ok" or "gagal". Failures are kept on purpose (attempts at files the user has no right to).
    hasil = Column(KODE_PENDEK, nullable=True)


class PerintahPengguna(Base):
    """One shell command run over SSH: who, which command, when, from which address.

    Separate from `transfer_berkas`: that table is about FILES (path, bytes), this one about
    COMMANDS (program, arguments); merging would leave half the columns empty. It is shown as a
    separate table on the same /traffic page. Source is `auditd` (`execve` rule), not `tlog`,
    which records terminal screens that must be replayed to read.
    """
    __tablename__ = "perintah_pengguna"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    waktu = Column(WAKTU)
    pengguna = Column(NAMA, nullable=True)
    perintah = Column(NAMA, nullable=True)
    # Full command plus arguments. Longer than `perintah` since arguments can be much longer.
    argumen = Column(KALIMAT, nullable=True)
    berhasil = Column(Integer, nullable=True)   # 1/0 -- auditd success=yes/no
    ip_klien = Column(IP, nullable=True)
    # SSH session number from auditd (`ses=`); groups commands of one connection.
    sesi = Column(NAMA, nullable=True)


class SesiSftp(Base):
    """Map of process id -> person for running SFTP sessions.
    The user name appears only once in the log ("session opened"); later lines carry only the
    process id. Kept in the database, not in memory, so it survives poller restarts; otherwise
    later transfers would be recorded without an owner and without any error.
    """
    __tablename__ = "sesi_sftp"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    pid = Column(Integer)
    pengguna = Column(NAMA)
    ip_klien = Column(IP, nullable=True)
    mulai = Column(WAKTU, default=datetime.now)
    diperbarui = Column(WAKTU, default=datetime.now)


class OrangLdap(Base):
    """Local copy of the LDAP directory contents: who the people are, their roles.
    Copied rather than queried per page view: if `.101` is down, history pages would lose every
    name even though history is about past events. `diperbarui` is stored and shown when the copy
    is old, so readers know they see a copy.

    There is deliberately NO password column: a monitoring tool has no need for hashes, and an
    existing column tends to get filled.
    """
    __tablename__ = "orang_ldap"
    uid = Column(NAMA, primary_key=True)
    nama = Column(RAHASIA, nullable=True)
    jabatan = Column(RAHASIA, nullable=True)
    email = Column(RAHASIA, nullable=True)
    # Comma-separated group list. Plain text on purpose: the page only displays it.
    grup = Column(JALUR, nullable=True)
    diperbarui = Column(WAKTU, default=datetime.now)


class FirewallSnapshot(Base):
    """Firewall state of a device at one point in time.
    One row per CHANGE, not per read, so the rare real change is not buried (same pattern as
    `konfig_snapshots`). `teks` keeps the raw output as evidence: the parsed rules table can be
    wrong if the ufw output format changes, the raw output cannot.
    """
    __tablename__ = "firewall_snapshot"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    waktu = Column(WAKTU, default=datetime.now)
    # State fingerprint WITHOUT rule numbers (ufw renumbers the list after each deletion).
    sidik = Column(SIDIK)
    # 1 = ufw active, 0 = inactive. Never None in a stored row: an unreadable firewall yields an
    # error, not a snapshot ("unknown" must not be stored as "off").
    aktif = Column(Integer)
    kebijakan_masuk = Column(KODE, nullable=True)
    kebijakan_keluar = Column(KODE, nullable=True)
    kebijakan_rute = Column(KODE, nullable=True)
    logging = Column(KODE, nullable=True)
    jumlah_aturan = Column(Integer, default=0)
    teks = Column(Text, nullable=True)


class FirewallAturan(Base):
    """One firewall rule line parsed from a snapshot.
    Stored apart from the raw `teks` so it can be searched and counted. `nomor` is kept although
    it is not in the fingerprint: it is what `ufw delete <nomor>` uses, and is valid only for the
    snapshot it was read from.
    """
    __tablename__ = "firewall_aturan"
    id = Column(Integer, primary_key=True)
    snapshot_id = Column(Integer, ForeignKey("firewall_snapshot.id"))
    device_id = Column(Integer, ForeignKey("devices.id"))
    nomor = Column(Integer)
    ke = Column(NAMA)
    aksi = Column(KODE)
    arah = Column(KODE_PENDEK)
    dari = Column(NAMA)
    komentar = Column(RAHASIA, nullable=True)


class FirewallPerubahan(Base):
    """History of firewall changes made through NSM: who, what, and WHY.
    Separate from `firewall_snapshot`, which cannot say who ordered a change or on what grounds.
    A rule in a snapshot with no row here was changed outside NSM. `alasan` is required for real
    changes. REJECTED attempts are recorded too (e.g. trying to block NSM's own address).
    """
    __tablename__ = "firewall_perubahan"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    waktu = Column(WAKTU, default=datetime.now)
    # `BLOKIR`/`BUKA` (ufw) or `ACL_BLOKIR`/`ACL_BUKA` (router ACL)
    aksi = Column(KODE_PENDEK)
    ip_sasaran = Column(IP)
    menit = Column(Integer, nullable=True)
    alasan = Column(KALIMAT, nullable=True)
    oleh = Column(NAMA)
    # RENCANA / BERHASIL / DITOLAK_NSM / DITOLAK_SERVER / DIBATALKAN / GAGAL
    hasil = Column(KODE_PENDEK)
    # Raw server output or the rejection message, stored as is.
    bukti = Column(Text, nullable=True)


class LayananBergantung(Base):
    """Service A will not be healthy if service B is down.
    Without this, one dead machine raises several equal alarms (database, SSH, server, web app)
    where only one is the CAUSE. A separate table rather than a column on `services` because a
    service can depend on more than one thing (E-Canteen needs the database on `.104` and the
    LDAP directory on `.101`). `alasan` is shown on screen as the explanation.
    """
    __tablename__ = "layanan_bergantung"
    id = Column(Integer, primary_key=True)
    layanan_id = Column(Integer, ForeignKey("services.id"))
    # The service depended on. Empty means a DEVICE is depended on (e.g. an app needs its own host up).
    pada_layanan_id = Column(Integer, ForeignKey("services.id"), nullable=True)
    pada_device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
    alasan = Column(KALIMAT)


class SumberDaya(Base):
    """Saturation of a device: how full its disk, memory and CPU are.
    The only golden signal that warns BEFORE failure: a full disk stops services at once. On
    `.104` it holds both the NSM and E-Canteen databases.

    Sampled every 5 minutes, not every poll: disk space moves in hours, and each SSH session
    adds load to the machine being measured. `load` is stored already divided by core count so
    machines are comparable. An empty column means NOT MEASURED, not zero (Cisco has no `df` or
    `/proc/loadavg`).
    """
    __tablename__ = "sumber_daya"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    waktu = Column(WAKTU, default=datetime.now)
    disk_persen = Column(Float, nullable=True)
    mem_persen = Column(Float, nullable=True)
    load_per_inti = Column(Float, nullable=True)
    inti = Column(Integer, nullable=True)
    sumber = Column(KODE_PENDEK, nullable=True)   # ssh / lokal


class PenolakanAcl(Base):
    """One connection attempt DENIED by a router ACL, with source and destination.
    Separate from `firewall_aturan`: that is state (rules, rarely changing), this is events
    (hundreds per minute during a scan).

    Two timestamps, both needed: `cap_router` is what the router wrote (correct ordering within
    that router, but its clock can be years off without NTP), `waktu` is when NSM read it
    (comparable with other machines' logs). Overwriting one with the other loses information.
    """
    __tablename__ = "penolakan_acl"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    waktu = Column(WAKTU, default=datetime.now)      # kapan NSM membaca
    cap_router = Column(KODE, nullable=True)
    acl = Column(NAMA)
    aksi = Column(KODE_PENDEK)
    proto = Column(KODE_PENDEK)
    dari = Column(IP)
    port_dari = Column(Integer, nullable=True)
    ke = Column(IP)
    port_ke = Column(Integer, nullable=True)
    # "1 packet" in IOS means AT LEAST one: similar denials are merged within a time window.
    jumlah = Column(Integer, default=1)
    sidik = Column(RAHASIA)
    baris = Column(Text, nullable=True)  # raw output kept as evidence


class DeviceLink(Base):
    """Fixed path between two devices, physical (cable) or logical.
    Currently empty: the dashboard topology map is drawn entirely from `flow_koneksi`. NSM does
    not discover cables itself (no LLDP/CDP), so the schema exists so fixed links can be added
    later without another migration.

    `device_a_id`/`device_b_id` have no from/to order: a cable has no direction.
    """
    __tablename__ = "device_link"
    id = Column(Integer, primary_key=True)
    device_a_id = Column(Integer, ForeignKey("devices.id"))
    device_b_id = Column(Integer, ForeignKey("devices.id"))
    jenis = Column(KODE_PENDEK, nullable=True)     # mis. "kabel", "logis"
    keterangan = Column(NAMA, nullable=True)
    dibuat_oleh = Column(NAMA, nullable=True)
    waktu = Column(WAKTU, default=datetime.now)


# ======================================================================
# INDEXES
#
# Declared here so that `Base.metadata.create_all()` on a fresh database (MySQL,
# `penyangga.db`, new installs) creates them. They originally came from one-off
# `migrate_*.py` scripts, so a new database would otherwise have no indexes and every query
# would scan hundreds of thousands of rows, with no error, just slow pages.
#
# Index names are kept as they are (both `idx_` and `ix_` prefixes): renaming would make
# existing indexes in `nsm.db` look different and get duplicated.
# ======================================================================

Index("ix_status_device_ts", StatusLog.device_id, StatusLog.timestamp)

Index("ix_rollup_jam", StatusRollupJam.jam)
# One row per hour per device. The UNIQUE keeps `bangun_rollup.py` from duplicating rows on re-runs.
Index("ux_rollup_device_jam", StatusRollupJam.device_id, StatusRollupJam.jam,
      unique=True)

Index("ix_events_device_ts", DeviceEvent.device_id, DeviceEvent.timestamp)

Index("ix_services_device", Service.device_id)
Index("ix_svc_check_service_ts", ServiceCheck.service_id, ServiceCheck.timestamp)
Index("ix_svc_event_service_ts", ServiceEvent.service_id, ServiceEvent.timestamp)
Index("ix_svc_event_ts", ServiceEvent.timestamp)

Index("ix_akses_device_waktu", AksesWeb.device_id, AksesWeb.waktu)
Index("ix_akses_klien", AksesWeb.ip_klien, AksesWeb.waktu)

# UNIQUE rather than a plain index: "one row per device per file" was only an unenforced
# intention. `jalur` is truncated to 191 chars for MySQL utf8mb4 key length; this applies
# only to the index comparison, not the stored value.
Index("ix_posisi_device_jalur", PosisiLog.device_id, PosisiLog.jalur)
Index("uq_posisi_device_jalur", PosisiLog.device_id, PosisiLog.jalur,
      unique=True, mysql_length={"jalur": 191})

Index("ix_flow_device_waktu", Flow.device_id, Flow.waktu)
Index("ix_flow_lawan", Flow.ip_lawan, Flow.waktu)

Index("ix_identitas_device", IdentitasPerangkat.device_id)
Index("ux_identitas_nilai", IdentitasPerangkat.device_id,
      IdentitasPerangkat.jenis, IdentitasPerangkat.nilai, unique=True)

Index("ix_konfig_device_waktu", KonfigSnapshot.device_id, KonfigSnapshot.waktu)
Index("ix_temuan_device", KonfigTemuan.device_id, KonfigTemuan.dinilai)
Index("ux_temuan_snapshot_aturan", KonfigTemuan.snapshot_id,
      KonfigTemuan.aturan_id, unique=True)

Index("ix_nama_diperiksa", NamaAlamat.diperiksa)

Index("ix_bw_device_iface_ts", BandwidthSample.device_id,
      BandwidthSample.iface, BandwidthSample.timestamp)

Index("idx_transfer_waktu", TransferBerkas.waktu)
Index("idx_transfer_pengguna", TransferBerkas.pengguna, TransferBerkas.waktu)

Index("idx_sesi_pid", SesiSftp.device_id, SesiSftp.pid)

Index("idx_fw_snap_device", FirewallSnapshot.device_id, FirewallSnapshot.waktu)
Index("idx_fw_aturan_snap", FirewallAturan.snapshot_id)
Index("idx_fwubah_waktu", FirewallPerubahan.waktu)


Index("ux_bergantung", LayananBergantung.layanan_id,
      LayananBergantung.pada_layanan_id, LayananBergantung.pada_device_id,
      unique=True)
Index("ix_bergantung_layanan", LayananBergantung.layanan_id)

Index("ix_sumberdaya_device_waktu", SumberDaya.device_id, SumberDaya.waktu)

# Unique fingerprint: `show logging` returns the whole buffer on every read, so without this
# each cycle would duplicate everything already stored.
Index("ux_penolakan_sidik", PenolakanAcl.sidik, unique=True)
Index("ix_penolakan_waktu", PenolakanAcl.waktu)
Index("ix_penolakan_dari", PenolakanAcl.dari, PenolakanAcl.waktu)

Index("ix_devicelink_a", DeviceLink.device_a_id)
Index("ix_devicelink_b", DeviceLink.device_b_id)


class BanAktif(Base):
    """One IP currently or previously blocked by NSM on a device's firewall.
    Written ONLY by `penjaga_aksi.blokir()`, which first rejects allowlisted addresses.
    `waktu_kedaluwarsa` makes a ban temporary. `aktif` is kept apart from row deletion so
    "was once banned" stays available for audit.
    """
    __tablename__ = "ban_aktif"
    id = Column(Integer, primary_key=True)
    ip = Column(IP)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
    alasan = Column(JALUR, nullable=True)
    pola = Column(KODE, nullable=True)          # memindai/gigih/tembus/manual
    oleh = Column(NAMA, nullable=True)
    waktu_ban = Column(WAKTU, default=datetime.now)
    waktu_kedaluwarsa = Column(WAKTU, nullable=True)   # None = permanen
    waktu_buka = Column(WAKTU, nullable=True)
    aktif = Column(Integer, default=1)


Index("ix_ban_ip_aktif", BanAktif.ip, BanAktif.aktif)


class SyslogPesan(Base):
    """Syslog messages SENT by devices, as opposed to what NSM polls.
    Turns NSM from polling-only into also event-driven (link up/down, OSPF adjacency changes,
    who changed the config and from where).

    Syslog over UDP is UNAUTHENTICATED and easy to spoof, so `device_id` here is a GUESS from
    the sender address, and a syslog message must NEVER trigger an automatic action directly: it
    is evidence and a trigger for a check, and decisions go through `pagar_otomasi`.
    """
    __tablename__ = "syslog_pesan"
    id = Column(Integer, primary_key=True)
    waktu = Column(DateTime, nullable=False, index=True)

    # NULL when the sender matches no known device. Kept on purpose: unknown senders deserve a look.
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True,
                       index=True)
    alamat = Column(String(45), nullable=False)

    # From the PRI byte: facility = PRI // 8, severity = PRI % 8 (RFC 3164).
    # `severity` is 0..7; lower is more severe (0 emergency, 7 debug).
    facility = Column(Integer, nullable=True)
    severity = Column(Integer, nullable=True, index=True)

    tag = Column(String(64), nullable=True)       # mis. "%LINK-3-UPDOWN"
    pesan = Column(Text, nullable=False)

    # Template fingerprint: numbers/IPs/interface names normalized to <*> then hashed, so repeats
    # of the same event share a fingerprint. Makes "never-seen template" detectable.
    sidik_templat = Column(String(40), nullable=True, index=True)

    # Already turned into a device_event? NULL = not yet examined.
    jadi_event = Column(Boolean, nullable=True)


class Insiden(Base):
    """ONE incident, not one symptom.
    Without this, a dead LDAP server produced five separate rows (device down, LDAP down, login
    failures, SSH failure, replica unreachable) for one event. `akar_device_id` names the real
    culprit from the dependency graph (see docs/design/BLAST-RADIUS.md).
    """
    __tablename__ = "insiden"
    id = Column(Integer, primary_key=True)
    mulai = Column(DateTime, nullable=False, index=True)
    selesai = Column(DateTime, nullable=True)

    # 'terbuka' while any symptom is unrecovered, 'pulih' once all are back. Not derived from a
    # single device, because the incident ends only when all its symptoms do.
    status = Column(KODE_PENDEK, nullable=False, default="terbuka", index=True)

    # Root according to the dependency graph. NULL means undetermined, which is distinct from
    # "this device itself".
    akar_device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
    akar_pasti = Column(Boolean, nullable=True)

    # Highest severity among its symptoms, not the average.
    keparahan = Column(KODE_PENDEK, nullable=True)

    ringkas = Column(Text, nullable=True)
    jumlah_gejala = Column(Integer, nullable=False, default=0)
    mttr_detik = Column(Integer, nullable=True)

    # One email per INCIDENT, not per symptom.
    notif_terkirim = Column(Boolean, nullable=True, default=False)

    # Severity when the last email was sent. `notif_terkirim` alone cannot tell whether severity
    # ROSE (e.g. `perhatian` to `bahaya`), which is the only case where a follow-up email is due.
    notif_keparahan = Column(KODE_PENDEK, nullable=True)

    # "Recovered" email is sent ONCE. Separate flag from `notif_terkirim` because a recurring
    # incident would otherwise lose one of the two.
    notif_pulih_terkirim = Column(Boolean, nullable=True, default=False)


class InsidenGejala(Base):
    """One symptom belonging to an incident.
    A repeated symptom does not create a new row; it raises `jumlah` and updates `waktu_terakhir`.
    """
    __tablename__ = "insiden_gejala"
    id = Column(Integer, primary_key=True)
    insiden_id = Column(Integer, ForeignKey("insiden.id"), nullable=False,
                        index=True)

    # 'device' / 'layanan' / 'syslog': the table the symptom came from.
    jenis = Column(KODE_PENDEK, nullable=False)
    sumber_id = Column(Integer, nullable=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)

    waktu = Column(DateTime, nullable=False)

    # When the symptom was LAST SEEN still failing (not when it recovered; see `pulih_pada`).
    waktu_terakhir = Column(DateTime, nullable=True)

    jumlah = Column(Integer, nullable=False, default=1)
    pulih = Column(Boolean, nullable=False, default=False)

    # When the symptom recovered. Needed because `korelasi.tutup_yang_selesai()` used to derive
    # the end from `max(waktu_terakhir)` (last seen still broken), so a symptom that recovered
    # before the next 60 s correlation round gave `mttr_detik = 0`, which reads as "recovered
    # instantly" rather than "not measured".
    pulih_pada = Column(DateTime, nullable=True)

    detail = Column(Text, nullable=True)


# ===========================================================================
# PAKET C -- pembelajaran ringan (23 Agustus 2026)
# ===========================================================================

class BaselinePerilaku(Base):
    """Habit of a device at a given HOUR OF THE WEEK (168 slots per device).
    `anomali.py` uses fixed thresholds, which are wrong across devices (LDAP over the GNS3 WAN
    is normally hundreds of ms, a LAN web server under 1 ms) and across hours. This table
    supports relative anomalies: "usually 40 ms Saturday 20:00, now 260 ms".

    Slots are hour-of-week, not hour-of-day, because load has daily and weekly rhythms.
    Only four numbers per slot are kept (count, EWMA, moving mean deviation, last update);
    learning is ONLINE, because nsm-app has 3.9 GB of RAM shared with the poller, uvicorn and
    Spring Boot.
    """
    __tablename__ = "baseline_perilaku"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False,
                       index=True)

    # 'latency' | 'bandwidth_rx' | 'bandwidth_tx' | ...
    metrik = Column(KODE_PENDEK, nullable=False)

    # 0..167: hour of the week, Monday 00:00 = 0.
    slot = Column(Integer, nullable=False)

    # Samples seen so far. Used to REFUSE to judge while evidence is thin (same rule as `kapasitas.py`).
    n = Column(Integer, nullable=False, default=0)

    # Rata-rata bergerak eksponensial.
    ewma = Column(Float, nullable=True)

    # Moving average of |x - ewma|: mean deviation, not median. See `baseline.py` for the conversion
    # to standard deviations.
    ewmd = Column(Float, nullable=True)

    diperbarui = Column(WAKTU, default=datetime.now)

    __table_args__ = (
        # One row per (device, metric, slot). Without it, two concurrent rounds would create two rows
        # for one slot and the baseline would split in half.
        UniqueConstraint("device_id", "metrik", "slot",
                         name="uq_baseline_device_metrik_slot"),
    )


class BaselinePosisi(Base):
    """Last `status_logs` row already folded into the baseline.
    Without it each round would re-fold the same rows, the deviation would shrink toward zero,
    and every normal value would read as a large anomaly.
    """
    __tablename__ = "baseline_posisi"
    id = Column(Integer, primary_key=True)
    metrik = Column(KODE_PENDEK, nullable=False, unique=True)
    posisi_id = Column(Integer, nullable=False, default=0)
    diperbarui = Column(WAKTU, default=datetime.now)


class LogTemplat(Base):
    """One log-message PATTERN mined by Drain3.
    Drain3 turns a flood of syslog into dozens of templates; a template seen for the first time
    is the most valuable signal (the device said something it never said before).

    Kept alongside `syslog_pesan.sidik_templat`: that fingerprint is hand-written normalization,
    fast and used by the per-template flood suppressor on the intake path, but it only handles
    shapes its author anticipated. Drain3 discovers the variable parts by clustering.
    """
    __tablename__ = "log_templat"
    id = Column(Integer, primary_key=True)

    gugus_id = Column(Integer, nullable=False, index=True)

    templat = Column(Text, nullable=False)
    jumlah = Column(Integer, nullable=False, default=0)
    pertama = Column(WAKTU, nullable=True)
    terakhir = Column(WAKTU, nullable=True)

    # WORST syslog severity (lowest number) seen with this template, not the average.
    severity_min = Column(Integer, nullable=True)

    # Number of distinct devices that emitted this pattern. One device usually means a device
    # problem; many at once usually means the network.
    jumlah_device = Column(Integer, nullable=False, default=0)

    # Reviewed by a person or not.
    ditinjau = Column(Boolean, nullable=True, default=False)


class LogTemplatPosisi(Base):
    """Last `syslog_pesan` row already mined by Drain3. Same reason as `BaselinePosisi`: re-mining
    would double counts and swap "common" with "new".
    """
    __tablename__ = "log_templat_posisi"
    id = Column(Integer, primary_key=True)
    nama = Column(KODE_PENDEK, nullable=False, unique=True)
    posisi_id = Column(Integer, nullable=False, default=0)
    diperbarui = Column(WAKTU, default=datetime.now)


class UsulanAgen(Base):
    """One PROPOSAL from the SOC agent, and what became of it.

    The AI agent NEVER touches devices. It proposes, and proposals go through
    `pagar_otomasi.putuskan()`, the same guard as the automatic recoverers, so every existing
    safeguard applies. This table makes that auditable afterwards.
    `mode`: 'usul' = only recorded what it WOULD do, 'jalan' = actually passed to the guard.
    """
    __tablename__ = "usulan_agen"
    id = Column(Integer, primary_key=True)
    waktu = Column(WAKTU, default=datetime.now, index=True)
    insiden_id = Column(Integer, ForeignKey("insiden.id"), nullable=True,
                        index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)

    # 'triase' | 'bukti' | 'narasi' | 'tindakan'
    jenis = Column(KODE_PENDEK, nullable=False)

    # 'usul' | 'jalan'
    mode = Column(KODE_PENDEK, nullable=False, default="usul")

    # Proposed runbook (for kind 'tindakan'), e.g. 'gns3_start'.
    tindakan = Column(NAMA, nullable=True)

    # Guard decision: 'izin' | 'tolak' | 'tidak_diminta'
    vonis_pagar = Column(KODE_PENDEK, nullable=True)
    alasan_pagar = Column(Text, nullable=True)

    # Proposal content: narrative, evidence chain, or triage result, as JSON text.
    isi = Column(Text, nullable=True)

    # Agent confidence, kept so hesitant proposals can be told apart when judging its track record.
    keyakinan = Column(Float, nullable=True)


# ===========================================================================
# PAKET D -- multi-tenancy (23 Agustus 2026)
# ===========================================================================

class BackupLaporan(Base):
    r"""Backup status report, SENT by the machine that actually holds the files.
    Backups run on a Windows laptop to `C:\...` paths, which a Linux `nsm-app` cannot inspect.
    Chosen design: the laptop REPORTS its result into the shared database, with no new access
    path or credential (rejected: reading the laptop over SSH, or sharing the folder over SMB).

    `waktu_lapor` matters most: a stale report showing green is worse than none, so the report
    age is displayed and reports older than a day are flagged as a PROBLEM.
    """
    __tablename__ = "backup_laporan"
    id = Column(Integer, primary_key=True)

    # When the report was CREATED on the reporting machine, not when it was received.
    waktu_lapor = Column(WAKTU, nullable=False, index=True, default=datetime.now)

    # Reporting machine name, as is from `platform.node()`.
    mesin = Column(String(120), nullable=False)

    # Full `backup_status.ringkasan()` as JSON. Stored whole on purpose: its shape has changed
    # before and splitting it into columns would need a migration each time.
    isi = Column(Text, nullable=False)

    # Short text so it can be read without opening the JSON.
    sehat = Column(Boolean, nullable=True)
    jumlah_berkas = Column(Integer, nullable=True)
    total_mb = Column(Float, nullable=True)


class Tenant(Base):
    """One tenant: an organization whose network NSM monitors.
    Cross-tenant leaks fail silently (a query that forgets to filter returns another tenant's
    data on a normal-looking page), so filtering is applied in the ORM layer, not left to each
    caller. See `tenancy.py`. `kuota_device` caps how many devices a tenant may add.
    """
    __tablename__ = "tenant"
    id = Column(Integer, primary_key=True)
    nama = Column(NAMA, nullable=False, unique=True)
    kontak = Column(String(200), nullable=True)

    # Device limit. NULL = unlimited (used by the default tenant holding all existing lab devices).
    kuota_device = Column(Integer, nullable=True)

    aktif = Column(Boolean, nullable=False, default=True)
    dibuat = Column(WAKTU, default=datetime.now)

    # Dead tenants are deactivated, not deleted, to keep their monitoring history.
    catatan = Column(Text, nullable=True)


class PerangkatDitemukan(Base):
    """Addresses found by a scan, WAITING for a human decision.
    Deliberately NOT rows in `devices`: a tool that adds whatever it sees would let anyone who
    can plug in an IP address add polling load. Findings pile up here and only
    `penemuan.setujui()` (a person pressing a button) moves one into `devices`.

    `status`: baru (untouched), disetujui (became a device; `device_id` points to it),
    diabaikan (deliberately not a device, so the decision persists across scans).
    """
    __tablename__ = "perangkat_ditemukan"

    id = Column(Integer, primary_key=True)
    ip_address = Column(IP, nullable=False, index=True)

    # First AND last seen: the first answers "since when is this on the network", the last answers
    # "is it still there".
    pertama_terlihat = Column(WAKTU, default=datetime.now)
    terakhir_terlihat = Column(WAKTU, default=datetime.now)

    rtt_ms = Column(Float, nullable=True)
    port_terbuka = Column(KODE, nullable=True)      # mis. "22,80"
    sysobjectid = Column(NAMA, nullable=True)

    # Platform matched from sysObjectID to a definition file, or empty. Empty is NOT a failure:
    # unrecognized devices can still be monitored by ping, TCP and services.
    platform = Column(KODE, nullable=True)
    catatan = Column(KALIMAT, nullable=True)

    status = Column(KODE_PENDEK, nullable=False, default="baru", index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)

    # Direct, like `Device`, because a finding has no device to inherit from. See `tenancy.LEWAT_DEVICE`.
    tenant_id = Column(Integer, ForeignKey("tenant.id"), nullable=True, index=True)

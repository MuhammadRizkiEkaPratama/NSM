"""NSM poller: pings all devices periodically and records status and transitions.

Two things are written each round:
1. status_logs   : every ping result (raw data, never deleted).
2. device_events : only when status changes (UP <-> DOWN); the Report page reads
                   this for "when down, how long, which category".

Kept separate because computing 30-day availability from millions of
status_logs rows is slow. When ping fails, the poller tries TCP ports
(22/80/443) to tell a dead device from blocked ICMP; see connectors/tcp.py.
"""

# This file is now only the job list and their intervals (what runs, how often).
# The work lives in other modules; functions are re-imported here because tests
# and operational scripts call them as `poller.x()`. Run it with `py poller.py`.

from nsm.pemantau._inti import (  # noqa: F401
    status_terakhir, Sasaran, sasaran, PEKERJA_BACA, kerjakan_bersamaan, posisi_log)
from nsm.pemantau.bandwidth import (  # noqa: F401
    sampel_terakhir, satu_arah, pilih_pembaca, baca_bandwidth_device, simpan_bandwidth_device, bisa_dibaca_bandwidth, poll_bandwidth)
from nsm.pemantau.dasar import (  # noqa: F401
    gagal_beruntun, tcp_terjangkau_sampai, tcp_periksa_lagi_pada, JEDA_PROBE_TCP, beruntun_berikutnya, perlu_probe_tcp, tulis_event, segarkan_ip_lokal, periksa_device, poll_all)
from nsm.pemantau.firewall import (  # noqa: F401
    JALUR_UFW_LOG, baca_firewall_device, save_firewall, poll_kedaluwarsa_ban, poll_auto_ban, poll_penolakan_acl, poll_firewall_lokal, poll_firewall)
from nsm.pemantau.konfig import (  # noqa: F401
    poll_healer, poll_identity, _potret_linux, poll_config)
from nsm.pemantau.layanan import (  # noqa: F401
    gagal_layanan, event_layanan_terakhir, kumpulkan_bukti, check_service, poll_services)
from nsm.pemantau.sumberdaya import (  # noqa: F401
    poll_sumber_daya)
# The syslog state names `_syslog_penerima`, `_snmptrap_penerima`, `_syslog_peta`
# and `_syslog_peta_diperbarui` are deliberately not re-imported: their own
# functions rebind them (`global`), so an imported copy would go stale. Read them
# from `nsm.pemantau.syslog`.
from nsm.pemantau.syslog import (  # noqa: F401
    _syslog_simpan, mulai_snmptrap, start_syslog)
from nsm.pemantau.trafik import (  # noqa: F401
    jalur_log_web, jalur_log_sftp, jalur_log_smb, jalur_log_perintah, sesi_sftp_terbuka, baca_traffic_device, simpan_traffic_device, simpan_sesi_sftp, poll_traffic)
from nsm.pemantau.wawasan import (  # noqa: F401
    poll_person, poll_rollup, poll_nama_alamat, poll_notifikasi, poll_notifikasi_berjenjang, poll_correlation, poll_baseline, poll_pola_log, poll_agen_soc, poll_notifikasi_insiden)

from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import desc
import penyangga
from database import SessionLocal
from models import (Device, StatusLog, DeviceEvent, BandwidthSample,
                    Service, ServiceCheck, ServiceEvent,
                    AksesWeb, PosisiLog, Flow, NamaAlamat, KonfigSnapshot,
                    KonfigTemuan, TransferBerkas, SesiSftp, OrangLdap,
                    FirewallSnapshot, FirewallAturan, SumberDaya, PenolakanAcl,
                    IdentitasPerangkat, PerintahPengguna)
from config import (get_interval, get_down_threshold, get_probe_ports,
                    get_syslog_aktif, get_syslog_port,
                    get_snmptrap_aktif, get_snmptrap_port,
                    get_snmptrap_community,
                    get_korelasi_aktif, get_korelasi_interval,
                    get_bandwidth_interval, get_bandwidth_enabled,
                    get_notif_enabled, get_notif_interval,
                    get_service_interval, get_service_enabled,
                    get_service_down_threshold, get_diagnosa_enabled,
                    get_traffic_interval, get_traffic_enabled,
                    get_access_log_path,
                    get_ldap_url, get_ldap_basis, get_ldap_interval,
                    get_firewall_interval, get_firewall_enabled,
                    get_auto_ban_enabled, get_auto_ban_maks_per_putaran,
                    get_auto_ban_interval, get_notif_putaran_menit,
                    get_agen_soc_interval,
                    get_pemulih_gns3_aktif, get_pemulih_layanan_aktif,
                    get_pemulih_interface_aktif, get_pemulih_konfig_aktif,
                    get_pemulih_interval)
import notifikasi
import notifikasi_berjenjang
import diagnosa
import jeda
import identitas
import rollup
import report_service
from connectors.icmp import IcmpConnector, ping_banyak
from connectors.tcp import cek_port_terbuka, cek_port_banyak, TcpConnector
from connectors.ssh import SshConnector
from connectors.snmp import SnmpConnector
from connectors.lokal import LokalConnector, ip_sekarang
from connectors import (layanan, akseslog, flow, konfig, kepatuhan,
                        konfig_linux, sftplog, sambaaudit, perintahlog, ldapdir, ufwlog)
from connectors import firewall as fw
import tenancy

if __name__ == "__main__":
    poll_all()
    pesan_syslog = start_syslog()
    pesan_trap = mulai_snmptrap()
    sched = BlockingScheduler()
    sched.add_job(poll_all, "interval", seconds=get_interval(),
                  id="ping", max_instances=1)
    pesan_bw = "mati"
    if get_bandwidth_enabled():
        # max_instances=1: if the previous read (slow SSH) has not finished, do not pile up new runs.
        sched.add_job(poll_bandwidth, "interval", seconds=get_bandwidth_interval(),
                      id="bandwidth", max_instances=1)
        pesan_bw = f"tiap {get_bandwidth_interval()} dtk"

    pesan_svc = "mati"
    if get_service_enabled():
        sched.add_job(poll_services, "interval", seconds=get_service_interval(),
                      id="layanan", max_instances=1)
        pesan_svc = f"tiap {get_service_interval()} dtk"

    pesan_trf = "mati"
    if get_traffic_enabled():
        sched.add_job(poll_traffic, "interval", seconds=get_traffic_interval(),
                      id="traffic", max_instances=1)
        pesan_trf = f"tiap {get_traffic_interval()} dtk"

    # Firewall rules. A separate job rather than riding on poll_traffic(): the two
    # share an SSH session to Linux devices, but a missing sudo permission would then
    # read as an access-log failure and point to the wrong place.
    pesan_fw = "mati"
    if get_firewall_enabled():
        poll_firewall()
        sched.add_job(poll_firewall, "interval",
                      seconds=get_firewall_interval(),
                      id="firewall", max_instances=1)
        pesan_fw = f"tiap {get_firewall_interval()} dtk"

        # Laptop Windows Firewall, a separate job from poll_firewall() (see the docstring
        # of poll_firewall_lokal()). The interval matches Linux firewall/ACL so the three
        # layers on the Firewall page look in sync; that is a choice, not a requirement.
        poll_firewall_lokal()
        sched.add_job(poll_firewall_lokal, "interval",
                      seconds=get_firewall_interval(),
                      id="firewall_lokal", max_instances=1)

    # Router ACL denials, every 5 minutes like ufw. Not more often: the router log
    # buffer holds thousands of lines, so nothing is lost between reads, and a Cisco
    # SSH session is the expensive part.
    poll_penolakan_acl()
    sched.add_job(poll_penolakan_acl, "interval", seconds=300,
                  id="penolakan_acl", max_instances=1)

    # Auto-ban expiry: every 60 s, lifts temporary bans whose time has passed. Cheap,
    # does nothing without active bans, and is skipped if the `ban_aktif` table does
    # not exist yet.
    pesan_korelasi = "mati"
    if get_korelasi_aktif():
        sched.add_job(poll_correlation, "interval",
                      seconds=get_korelasi_interval(),
                      id="korelasi", max_instances=1)
        pesan_korelasi = "tiap %d dtk" % get_korelasi_interval()
    # Always registered (cheap to check); `poll_notifikasi_insiden()` returns
    # immediately when `NOTIF_PER_INSIDEN` is off (default). Same interval as
    # correlation: an incident is not worth notifying about faster than it is formed.
    sched.add_job(poll_notifikasi_insiden, "interval",
                  seconds=get_korelasi_interval(),
                  id="notifikasi_insiden", max_instances=1)

    # These three are always registered and each returns immediately when its feature
    # is off. Conditional registration would make `.env` changes require a restart.
    sched.add_job(poll_baseline, "interval", seconds=300,
                  id="baseline", max_instances=1)
    sched.add_job(poll_pola_log, "interval", seconds=300,
                  id="pola_log", max_instances=1)
    sched.add_job(poll_agen_soc, "interval",
                  seconds=get_agen_soc_interval(),
                  id="agen_soc", max_instances=1)

    sched.add_job(poll_kedaluwarsa_ban, "interval", seconds=60,
                  id="kedaluwarsa_ban", max_instances=1)

    # Auto-ban without a click. Always registered; `poll_auto_ban()` returns
    # immediately when the `AUTO_BAN_AKTIF` kill switch is off (default). The switch
    # is re-checked every round, so a `.env` change applies without restart. See
    # `poll_auto_ban()` and `config.get_auto_ban_enabled()`.
    pesan_auto_ban = ("tiap %d dtk" % get_auto_ban_interval()
                      if get_auto_ban_enabled() else "mati (kill-switch)")
    sched.add_job(poll_auto_ban, "interval",
                  seconds=get_auto_ban_interval(),
                  id="auto_ban", max_instances=1)

    # Auto-recovery. Always registered, same pattern as poll_auto_ban: the job itself
    # checks the four kill switches and returns quickly if all are off, so enabling
    # one in `.env` applies next round without a restart.
    sched.add_job(poll_healer, "interval",
                  seconds=get_pemulih_interval(),
                  id="pemulih", max_instances=1)

    # Saturation (disk, memory, load), every 5 minutes. Also run once at startup so
    # the page is not empty for five minutes after each poller restart.
    poll_sumber_daya()
    sched.add_job(poll_sumber_daya, "interval", seconds=300,
                  id="sumberdaya", max_instances=1)

    # Copy of names and titles from the LDAP directory. Not tied to the traffic
    # switch even though the Traffic page uses it: names appear wherever a uid does,
    # so disabling traffic must not change how people are written across the app.
    # Run once at startup so the page has names without waiting 30 minutes.
    pesan_ldap = "mati"
    if get_ldap_url():
        poll_person()
        sched.add_job(poll_person, "interval", seconds=get_ldap_interval(),
                      id="ldap", max_instances=1)
        pesan_ldap = f"tiap {get_ldap_interval()} dtk"

    # DNS name lookup. Follows the traffic switch since only the Traffic page uses
    # it. 180 s is deliberately infrequent: names rarely change and each failed
    # lookup waits for the resolver timeout.
    pesan_dns = "mati"
    if get_traffic_enabled():
        sched.add_job(poll_nama_alamat, "interval", seconds=180,
                      id="nama_alamat", max_instances=1)
        pesan_dns = "tiap 180 dtk"

    # Config backup, every 15 minutes (deliberately infrequent: router configs rarely
    # change on their own and each fetch opens a real CLI session).
    #
    # `next_run_time` is set to now so the first snapshot is taken immediately,
    # otherwise a device reconfigured just before a poller restart would have no
    # comparison snapshot for 15 minutes. Scheduled rather than called directly like
    # poll_all(), since a CLI session at startup would delay the first ping.
    sched.add_job(poll_config, "interval", seconds=900,
                  id="konfig", max_instances=1,
                  next_run_time=datetime.now())

    # Hourly rollup, every 600 s. Only completed hours are summarized, so running
    # more often adds almost no work, and it keeps the lag short after a poller
    # outage (a long lag makes `pangkas_data.py` refuse to delete anything).
    sched.add_job(poll_rollup, "interval", seconds=600,
                  id="rollup", max_instances=1,
                  next_run_time=datetime.now())

    # Device identity, every 1800 s; see poll_identitas() for why. Not run
    # immediately at startup: the first round opens SSH to every device and would
    # pile onto all the other jobs starting at once.
    sched.add_job(poll_identity, "interval", seconds=1800,
                  id="identitas", max_instances=1,
                  next_run_time=datetime.now() + timedelta(seconds=90))

    pesan_notif = "mati"
    if get_notif_enabled():
        sched.add_job(poll_notifikasi, "interval", seconds=get_notif_interval(),
                      id="notifikasi", max_instances=1)
        pesan_notif = f"tiap {get_notif_interval()} dtk"

        # Tiered notifications: a separate job alongside those above, switched on and off
        # by the same NOTIF_ENABLED, so disabling notifications stops both paths.
        sched.add_job(poll_notifikasi_berjenjang, "interval",
                      seconds=get_notif_putaran_menit() * 60,
                      id="notifikasi_berjenjang", max_instances=1)
        pesan_notif += f" (+ berjenjang tiap {get_notif_putaran_menit()} mnt)"

    print(
        f"Poller jalan (ping tiap {get_interval()} dtk, "
        f"ambang DOWN {get_down_threshold()}x gagal beruntun, "
        f"bandwidth {pesan_bw}, layanan {pesan_svc}, "
        f"traffic {pesan_trf}, nama DNS {pesan_dns}, direktori {pesan_ldap}, "
        f"firewall {pesan_fw}, auto-ban {pesan_auto_ban}, "
        f"konfigurasi tiap 900 dtk, notifikasi {pesan_notif}, "
        f"syslog {pesan_syslog}, trap {pesan_trap}, "
        f"korelasi {pesan_korelasi}). "
        f"Ctrl+C untuk berhenti."
    )
    sched.start()


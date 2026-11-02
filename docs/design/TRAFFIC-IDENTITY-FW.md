# Traffic, identity and firewall: from "what moved" to "who, and is it normal"

NSM started as an availability monitor: up or down, latency, configuration, compliance. This work moved it one step further, from **recording** to **judging**. Not "203 MB left this server", but "which file, who took it, is that normal compared with habit, and if not, why". Making that possible needed three things that touch real machines: traffic attributed to services and people, a central identity (LDAP), and the ability to read and change firewalls. Each of those in turn needed a guard against acting on the wrong machine, which is the device-identity fingerprint at the end.

Everything here ran in the personal lab ([TOPOLOGY.md](../TOPOLOGY.md)), with fictional LDAP users (arif, dewi, bagas, intan, siti, joko). UI labels are Indonesian; English glosses are used here. Blocking logic has its own document: [AUTO-BAN.md](AUTO-BAN.md).

## Status

| Part | Status |
|---|---|
| Per-service access logs, service attribution of web traffic | Implemented |
| Baseline and 7 anomaly detectors (`anomali.py`) | Implemented |
| LDAP directory, NSM login via LDAP, SSH via sssd, E-Canteen login via LDAP | Implemented (lab) |
| SFTP file server with LDAP identities, log reader, "who fetched which file" | Implemented (`sftp/`, `connectors/sftplog.py`) |
| Names and titles from the directory copied into NSM (`orang_ldap`) | Implemented |
| Firewall read, display, enable-with-safety-net, change with auto-revert | Implemented |
| Device identity fingerprint and write guard | Implemented; the "human confirms same device" step is **not** (see Open questions) |
| MySQL move and local SQLite buffer | Implemented, see [MYSQL.md](../MYSQL.md) |
| Merging application activity (E-Canteen `security_log`) with web traffic into "user X did Y from IP Z" | **Planned, not built** |
| A `LOGOUT` audit event in E-Canteen | Planned |

## Context and problem

1. **Addresses are weak identities.** A traffic record that says `192.168.56.1` cannot say whether a person was there. One disabled LDAP account should lose access everywhere at once, and every record should start naming people.
2. **Counting is not judging.** Totals per period cannot say whether 203 MB is a backup or a leak.
3. **Some services were invisible.** The most used web app (E-Canteen, a Spring Boot app used as a monitored workload) did not write an Apache access log, so the busiest service was the one NSM could not see.
4. **Wrong target is worse than wrong data.** Four of the six original lab devices sat on default addresses (`192.168.1.1`, `192.168.56.101`, `.103`, `.1`) that would match someone else's network. While NSM only read, a wrong target gave wrong data. Once NSM can write (config push, firewall), a wrong target means changing another party's device, and no "reload in N" safety net helps: it protects against a bad command, not a wrong device.

## Goals and non-goals

Goals: attribute traffic to a service and, where the protocol allows, to a person; compare against habit and always show the comparison number; centralise authentication without making NSM unreachable when the directory dies; make firewall state visible before anything can change it; refuse to write to a device whose identity is in doubt.

Non-goals: packet capture (NSM reads **server logs**; HTTP and FTP file names are visible, SSH and HTTPS payloads are not, and the report says so); replacing everything in the NSM database with LDAP; FTP in plain text; confirming identity with a hand-typed serial number.

## Design

### 1. Traffic attribution

- Each HTTP service names its own log (`services.log_akses`), read over one SSH connection per host. Before this there was one global access-log path.
- Each `akses_web` row carries the service it came from (`service_id`; NULL for old rows, honestly, because nobody knew then). Without it two websites on one machine are inseparable.
- Read positions are kept **per file**. One shared marker made progress in file A look like progress in file B and silently skipped unread lines.
- A failing log does not drop the others on the same host, and its position is not advanced.
- The read command used `stat -c %s <log> || echo 0`, which made a **missing** file indistinguishable from an empty one: zero new lines, no error. It now prints `-1`, so the four cases (missing, empty, has data, rotated) are distinct.
- The Tomcat access log of the lab web app uses `pattern=combined` (the same format as Apache, so the parser is unchanged) and an empty `file-date-format` so the file name stays `access.log` instead of changing daily.

### 2. Baseline and anomalies (`anomali.py`)

Findings must carry their comparison number: "203 MB in one hour, habit 0.3 MB/hour, 677 times". A label without a number gets ignored after the second time.

| Detector | Needs a baseline | Source |
|---|---|---|
| Volume spike (at least 5 times the hourly median) | yes | `akses_web`, hourly rollup |
| Client never seen before | yes | `akses_web.ip_klien` |
| Single large download (50 MB or more) | no | `akses_web.byte_kirim` |
| Error burst (20 or more per hour) | no | `akses_web.status` |
| Access outside working hours (before 07:00, after 18:00) | no | `akses_web.waktu` |
| Non-browser user agent (`curl`, `wget`, `sqlmap`, ...) | no | `akses_web.user_agent` |
| Sensitive file patterns (`.sql`, `.bak`, `.env`, `.pem`, `/wp-admin`, ...) | no | `akses_web.path` |

Design decisions, each from real data:

1. **The baseline refuses to compute under 24 hours of data** (`MIN_JAM_GARIS_DASAR`). The database then held only 6 hours of real user traffic; an average of 6 samples is coincidence, not habit. The page says "not yet, N hours short".
2. **Median, not mean.** A single 200 MB hour would raise the mean so far that the next 200 MB hour looks normal.
3. **Two groups of detectors.** The ones that need no baseline work from day one, otherwise the tool is silent in exactly the weeks it is looked at most.

Defects found by running on real data, kept as lessons:

- A plain `/admin` pattern was **removed**: 15 of 16 findings on an ordinary day were canteen staff using the app's legitimate admin pages. Only patterns tied to software that is not installed (`/wp-admin`, `/phpmyadmin`) remain. (An earlier plan had listed `/admin`.)
- The error-burst detector first skipped requests made by NSM and so reported nothing for the only real service failure in the data (229 HTTP 500s over three hours, all seen through NSM's own checks). A 5xx is a server failure no matter who asked.
- One outage spanning several hours was split into per-hour cards, and the quiet third hour vanished below the threshold. Consecutive hours are now merged (229 errors over 3 hours, matching the database).
- A raw hour key was shown as the finding time and browsers rendered "Invalid Date". A test now parses it like `new Date()`.
- One file fetched four times produced four identical findings; downloads are grouped per (address, file).

### 3. Central identity (LDAP)

LDAP replaces only **authentication**. `audit_logs`, the blocked-IP list and the emergency path stay in MySQL: a directory stores identity, not history, and not data that changes every minute.

The lab directory (`slapd`, base `dc=bsp,dc=id`; "bsp" is only a lab label) holds eight fictional people and five groups, generated by `ldap/buat_ldif.py`:

| Group | Meaning |
|---|---|
| `sysadmin` | SSH to servers and change configuration |
| `nsm-admin` / `nsm-viewer` | NSM role ADMIN / read-only USER |
| `ecanteen` | Users of the E-Canteen workload |
| `berkas` | May use the SFTP file server, no shell |

How consumers use it:

- **NSM login** (Spring Security LDAP). Roles come from groups; someone with no NSM group is refused even with the right password (siti and joko exist for E-Canteen, not for NSM). Login accepts uid **or** email through a search filter, `(|(uid={0})(mail={0}))`, and the identity used for groups and audit is taken from the **found directory entry**, not from what was typed. Otherwise a mail login found no groups (and was refused with a misleading message), and the audit log recorded one person as two actors.
- **SSH** through sssd, `access_provider = simple`, only group `sysadmin`. An auditor's LDAP bind succeeds but SSH is refused: being in the directory is not the right to enter a machine. Local accounts are kept as an emergency path, so `files` is consulted before `sss`, which means a local account wins over a same-named directory account. The NSM monitoring key must keep working after any PAM change, or pages silently stop updating rather than erroring.
- **E-Canteen** decides per user (`users.use_ldap`) where the password is checked. Role and stall come from the local table; LDAP answers only "is the password right". There is **no fallback to the old hash**: otherwise disabling someone in the directory would not close their access. Password change is refused for LDAP users instead of claiming "old password wrong". The directory address is in a server-owned config file, not in code; empty means LDAP is off.
- **Emergency path.** The directory VM is itself monitored by NSM, so if it dies nobody could log in to see why. A small number of accounts explicitly flagged for emergency use are validated locally, **only when LDAP is unreachable** (not when it answers "wrong password"), and every use is logged prominently. Telling "unreachable" from "refused" is done on the exception type (walking the cause chain), because Spring wraps connection failures.
- **Transport.** The first version sent bind passwords unencrypted inside the lab network. Once the directory moved behind the router, that crossed an extra hop, and StartTLS on port 389 with clients required to use it was added: see [LDAP-TLS.md](../LDAP-TLS.md). A replica design is in [LDAP-REPLICA.md](LDAP-REPLICA.md).

Traps tested explicitly:

- **Empty password.** A simple bind with a valid DN and empty password is an *unauthenticated bind* under RFC 4513 and many servers answer success. Code like `if (bind(dn, pw)) login()` would admit anyone. The `ldap3` client refuses to send it and `slapd` answers `unwillingToPerform (53)`; E-Canteen and NSM paths are tested too.
- **Provider fall-through.** Two providers tried in sequence let a wrong LDAP password fall through to an old MySQL hash. The login provider distinguishes "wrong password: refuse, MySQL untouched" from "unreachable: open the emergency path".
- **Lost event publisher.** Building the authentication manager by hand dropped Spring's event publisher, so no login was audited and the automatic account lock never counted failures: passwords could be guessed without limit while the login page still rejected them one by one. It was found because the audit log had no login rows while logins plainly occurred. It is restored and covered by tests, including "five failures produce five events".

### 4. SFTP file server and the person behind the transfer

SFTP, not FTP or FTPS: it rides on the SSH already running and monitored, opens no new service, needs no certificate or passive port range, and its log is readable. Plain FTP clients cannot connect, which is the point. `sftp/pasang-sftp.sh` (idempotent, six stages, stops on anything wrong) sets up a chroot at `/srv/berkas` with `ForceCommand internal-sftp`, folders `publik/` (read only), `unggah/` (writable) and `home/<uid>/`, and logging via `internal-sftp -f AUTH -l INFO`.

- Administrators are deliberately **not** in `berkas`: the forced command would take their shell away on their own server. The auditor **is**: allowed to fetch files, refused a shell. Verified: authenticated, but every command answers "This service allows sftp connections only".
- **Reader** (`connectors/sftplog.py`). The user name appears once, on the `session opened` line; the lines naming the file and bytes carry only a process id. So the pid-to-user map is stored in `sesi_sftp`, not in memory, because a session can outlive many poller cycles and restarts. A transfer from an unknown pid is stored with a NULL user and shown as "(unknown)": dropping it would hide exactly the long sessions that usually mean big files. Direction (`AMBIL`/`KIRIM`) follows bytes moved, not open flags. Delete and rename add no volume. `scp` is captured too (modern OpenSSH runs it over SFTP), and the page says so.
- **Names** (`connectors/ldapdir.py`). A raw uid reads as data; "Arif Rahman, Auditor, fetched 40 MB of CCTV footage" invites the right question. NSM reads the directory with an anonymous bind and a **closed attribute list** (`uid`, `cn`, `title`, `mail`; never "all", never passwords), copies it into `orang_ldap` (`poll_person`, every `LDAP_INTERVAL`, 1800 s by default, plus once at start; empty `LDAP_URL` disables it), and the page reads the copy. Querying live would make every name in the history vanish when the directory VM is down, and history that changes with another server's health cannot be trusted. The uid stays the primary line (it is what was logged) and name/title sit below it as a hint from a copy that may have changed. Accounts not in the directory, such as the monitoring account, are shown as they are, with no invented name.
- **Page.** On the Traffic page, "Who fetched which file" has three tables: per person, per file, latest events. It is the only part of the page that names people. The "by" column counts people, not events: one person fetching four times (habit) and four people fetching once (something is circulating) have the same total and opposite meanings.
- The simulation (`sftp/simulasi_transfer.py`) is lopsided on purpose (the auditor pulls 40 MB, others a few); with uniform data the page never demonstrates its use.

Four traps that cost most of the time share one shape: **it works and records nothing**.

1. chroot cuts `/dev/log`; rsyslog must open a second socket inside `/srv/berkas/dev/log`.
2. rsyslog drops root before opening it, so `dev/` inside the chroot must be writable by the `syslog` group.
3. AppArmor denies the write even though file permissions are correct, with a plain `Permission denied`; the profile needs one line in `/etc/apparmor.d/local/usr.sbin.rsyslogd`.
4. `Subsystem sftp` may be defined once; the default line must be commented out. The script runs `sshd -t` before restarting ssh.

### 5. Firewall: read first, then change

**Read** (`connectors/firewall.py`): `ufw status verbose` and `ufw status numbered` through `sudo` rights for exactly those two commands. A sudo rule that names the whole `ufw` binary would let a read-only account run `ufw disable` or `ufw reset`; the install script checks that `ufw disable` is still refused. The sudoers file is assembled in `/tmp`, validated with `visudo -c`, and only then moved into place, because one broken file in `/etc/sudoers.d` disables sudo for everyone. State is stored as a snapshot only when it changes (`firewall_snapshot`, `firewall_aturan`), read every `FIREWALL_INTERVAL` (300 s), shown on the Configuration page.

Three states produce the same empty table, so the page always states the situation first:

| State | Real meaning |
|---|---|
| enabled, zero rules | the default policy applies; with `deny incoming` the machine is closed tight |
| **disabled** | the machine is open |
| never read | NSM knows nothing |

The connector raises an error for the third case instead of returning an empty list. First finding: both lab servers had **no firewall** (`Status: inactive`), while `systemctl is-active ufw` said `active` (that only means the unit ran). A parsing test also caught `"active" in line`, which matches `inactive`; the status is now matched exactly.

**Enabling** (`firewall/nyalakan-firewall.sh`, run on a VM): ports are derived from measurement (`ss -tlnp` crossed with the services NSM monitors), localhost-only listeners get no rule. The script installs a systemd timer that turns ufw off again after N minutes (default 10), **proves** it is installed, adds allow rules before enabling, and does not remove the net itself: a net released by the party that placed it is only a pause. It really fired once in the lab (the proof finished but the release came late), then the second attempt stuck. The window became configurable because a tight window makes people hurry.

`backend/uji_terjangkau.py` is run before and after, and checks what the laptop would not notice: directory port from the web VM (sssd, tested with `id <user>` there), database port from the web VM (a real E-Canteen login), and the app port used from a phone through port forwarding.

**Change**: described in [AUTO-BAN.md](AUTO-BAN.md). The decisions from this work: every block has an expiry (an automatic system that blocks permanently eventually blocks something important, and months later nobody dares remove the rule); the policy lives in a root-owned wrapper that refuses even when the caller is not NSM; the proof uses a new SSH session. `firewall_perubahan` logs actions, reasons, actors and refusals; dry runs are not logged. The difference between `firewall_snapshot` (all changes, including by hand) and `firewall_perubahan` (changes through NSM) is itself a signal: a rule in the snapshot with no matching change row was made outside NSM. The first version had no web button for blocking, following the config-push precedent that real changes are only previewed over the web; it was added later behind the ADMIN role, CSRF and audit.

### 6. Device identity fingerprint (`identitas.py`, `identitas_sumber.py`)

NSM stores several markers per device and judges by how many match.

| Marker | Weakness alone |
|---|---|
| MAC | changes with the NIC; VMs often get random ones |
| `machine-id` | copied when a VM is cloned |
| hostname | legitimately changes |
| serial | absent on VMs |

| Match | Verdict |
|---|---|
| 2 or more match, none contradict | `sama` (same) |
| 1 matches, rest empty | `kemungkinan_sama`: monitored, not writable |
| any contradicts | `bertentangan`: stop |
| all empty | `belum_diketahui`: monitored, flagged |

"Contradicting" is different from "empty": empty means NSM never asked, contradicting means it asked and got another answer. Treating them alike makes a freshly registered device look foreign, and a guard that blocks normal work gets switched off.

Rules in code: only `sama` allows writes (`BOLEH_DITULISI`); monitoring continues on a mismatch, only writing stops; the check runs again **immediately before** each write (a verdict from 30 minutes ago says nothing about the device receiving the command now); markers come from the device itself, never typed by hand; a differing value does not overwrite the old one, it is stored beside it with `pertama`/`terakhir` times. The verdict is computed **before** the new values are stored: the first version stored first, so the first comparison matched itself.

Sources, cheapest first, first source wins per marker: stored config snapshot (hostname, zero connections), NSM's own ARP table and NIC list, SSH (`machine-id`, hostname, MAC of the interface that holds *this* address, Cisco `show version` serial), SNMP `sysName`. SSH is before SNMP because `sysName` is typed into the SNMP config and can go stale. Paused devices are not contacted. `poll_identity` runs every 1800 s.

Two defects that accused correct devices (a guard that does so teaches people to disable it):

1. The MAC was taken from the NIC holding the default route. The VMs have two NICs and NSM talks over the other, so ARP and SSH disagreed whenever an ARP entry expired. The question is now "the MAC of the interface holding this address". For Windows the MAC comes from `psutil` mapped by address, not SSH.
2. MAC notation differs (Windows dashes, Linux colons, Cisco dots, any case). All are normalised to `aa:bb:cc:dd:ee:ff` before comparing. Multicast, broadcast and all-zero MACs are never markers.

Wiring: `boleh_ditulisi()` is called by the config push (`kirim_perintah.py`, `report_service/konfig.py`) and the router ACL path (`ubah_acl_router.py`); `GET /identitas` shows verdict and markers, and the page refuses in Python rather than by hiding a button. The ufw path (`ubah_firewall.py`) checks credentials, pause state and the latest snapshot, but does **not** call the fingerprint check.

Schema: `identitas_perangkat(device_id, jenis, nilai, pertama, terakhir, sumber)` with `devices.identitas_vonis` and `devices.identitas_diperiksa`.

### 7. Database move and buffer (summary)

About 730,000 rows moved from SQLite to MySQL (details in [MYSQL.md](../MYSQL.md)). The rule that fell out: **the application and its database live at one site; the directory and the file server may span sites.** A page asks the database 10 to 50 times, LDAP once per login (sssd caches), the file server rarely and the user is waiting anyway. Measured across the emulated WAN: 152 ms per query and 0.11 Mbit/s. Wrong estimates beforehand: SQLite-specific code was in eight places, not four (availability math, chart grouping, data pruning among them; now in `dialek.py`); 82 unsized `String` columns that MySQL rejects; 26 indexes created only by `migrate_*.py` scripts, so `create_all()` on a new database produced tables without any index. The local buffer (`penyangga.db`, same schema, drained with the same copy function) also mirrors the device list: without it a dead database stops the poller entirely, not just its writes. `uji_penyangga.py` cuts port 3306 for real, so it is a dangerous test.

## Safety and failure modes

| Risk | Control |
|---|---|
| Directory VM dies, nobody can log in | Local emergency accounts, only when LDAP is unreachable, always audited |
| Disabling a user leaves a second door | No password fallback to old hashes anywhere |
| Wrong machine is written to | Fingerprint check right before writing (config push, router ACL) |
| Firewall change locks NSM out | Safety timer first, proven, then change; reachability proof by new session |
| Monitor stores state in what it monitors | Local buffer including a device-list mirror |
| Statistics stated with false confidence | Baseline refuses under 24 h |
| Sensitive data copied silently | Closed attribute list, no password column |

## Data model and interfaces

Tables: `akses_web` (+`service_id`), `services.log_akses`, `sesi_sftp`, `orang_ldap`, `firewall_snapshot`, `firewall_aturan`, `firewall_perubahan`, `ban_aktif`, `identitas_perangkat`. Endpoints: `GET /traffic/anomali`, `GET /ldap/direktori` (reads the copy, never the live directory), `GET /identitas`, `GET /firewall`. Settings: `LDAP_URL`, `LDAP_INTERVAL`, `FIREWALL_ENABLED`, `FIREWALL_INTERVAL`, `TRAFFIC_ENABLED`; the Java side uses `nsm.ldap.*` properties. Scripts: `ldap/buat_ldif.py`, `ldap/sssd.conf`, `sftp/pasang-sftp.sh`, `sftp/simulasi_transfer.py`, `firewall/*`.

## Testing in the lab

`uji_anomali.py`, `uji_baseline.py`, `uji_akseslog.py`, `uji_log_per_layanan.py`, `uji_sftplog.py`, `uji_berkas_tampil.py` (the volume math, including that delete/rename never add bytes), `uji_firewall.py` (every failure form must raise, never become an empty list), `uji_identitas.py`, `uji_identitas_sumber.py`, `uji_penjaga_identitas.py`, `uji_ldif_ldap.py` (files) and `uji_ldap_hidup.py`, `uji_ldap_ssh.py`, `uji_ldap_ecanteen.py` (live servers; they skip themselves if the directory is unreachable), `uji_terjangkau.py`. Redirects are not followed in the E-Canteen login test, otherwise success and failure both read as 200. Run with `python backend/jalankan_semua_uji.py`.

## Lessons learned

- "Succeeded without recording anything" is the most dangerous failure shape: the screen looks identical to "nobody used it".
- A guard must be tested from the opposite direction (what must be refused), repeatedly.
- Check whether data already exists before building it. File names were stored long before, but not on a page called Traffic; E-Canteen already logged about 20 action types, NSM just could not read them.
- A topology change can make an old, correct decision wrong without touching a line of code (the unencrypted directory login after the directory moved behind a router).
- A parser test that never parses the field the way the browser will lets "Invalid Date" through.
- Never suggest untested network changes: `New-NetIPAddress` on Windows turns DHCP off for that adapter.

## Open questions

- **Accepting a changed fingerprint.** The design says a human must confirm that a changed device is the same device. The code has no confirm or deny action. Because a conflicting value is stored next to the old one and comparison accepts any stored value of a kind, a persistent change appears to match again on a later collection round. An explicit confirm step, or marking old values superseded, would close this.
- Merge E-Canteen's own activity log with web access rows so one request reads "user X deleted menu item Y at 14:03 from this address".
- Allow `kemungkinan_sama` for monitoring but require `sama` for writing is the current choice; whether other devices should have stricter rules is undecided.
- Should the ufw write path also require a `sama` verdict?

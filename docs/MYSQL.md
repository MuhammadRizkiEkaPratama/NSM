# MySQL: migration, local buffer, and cross-site replication

NSM started on a single SQLite file (`backend/nsm.db`). This guide covers moving
its data to MySQL, the local SQLite buffer that keeps the poller recording when
MySQL is unreachable, and the read-only MySQL replica at the other lab site.

All hosts, row counts and timings are from the author's personal lab
(VirtualBox + GNS3). "Primary lab instance" means the nsm-app VM in that lab.
See the [README](../README.md) for the lab disclaimer and
[TOPOLOGY](TOPOLOGY.md) for the two-site layout.

## Contents

1. [Result](#1-result)
2. [Where the database should live](#2-where-the-database-should-live)
3. [Migration procedure](#3-migration-procedure)
4. [Porting problems](#4-porting-problems-nobody-listed-up-front)
5. [Failures that raised no error](#5-failures-that-raised-no-error)
6. [The local buffer](#6-the-local-buffer-penyanggadb)
7. [Security](#7-security)
8. [Cross-site replica](#8-cross-site-replica)
9. [Rollback](#9-rollback)
10. [Verification](#10-verification)
11. [Limits](#11-limits)

---

## 1. Result

| | Before | After |
|---|---|---|
| NSM data | `backend/nsm.db` (SQLite, 74.7 MB) | MySQL database `nsm` on the data server `192.168.56.104` (Site A) |
| E-Canteen data (lab demo app) | MySQL at `192.168.20.101` (Site B) | MySQL on the same data server |
| LDAP directory | `192.168.20.101` | unchanged (suited to cross-site use) |
| SFTP file server | `192.168.56.103` | unchanged |
| While MySQL is down | n/a | `backend/penyangga.db`, drained automatically on recovery |
| Copy of the data | none | read-only replica on `192.168.20.101` (Site B) |

731,878 rows were moved. All 21 tables (at that time) matched in row count
**and** time range.

`nsm.db` was not deleted. It is a snapshot of the history before the move and
the way back: leaving `NSM_DB_HOST` empty in `backend/.env` returns NSM to
SQLite without any code change.

Connection settings (read by `backend/database.py`; environment variables
override `.env`):

| Variable | Default | Meaning |
|---|---|---|
| `NSM_DB_HOST` | empty | MySQL host. Empty selects SQLite. |
| `NSM_DB_PORT` | `3306` | |
| `NSM_DB_NAME` | `nsm` | |
| `NSM_DB_USER` | `nsm_app` | |
| `NSM_DB_PASS` | empty | Use a placeholder in docs, a random value in `.env`. |

---

## 2. Where the database should live

The database was moved twice in one day, and both moves are instructive.

### 2.1 Distance: Site A, not Site B

The first plan put MySQL on `192.168.20.101`. Later that host moved to Site B,
behind three emulated routers. Measured path quality from the poller:

| Path | RTT | Throughput |
|---|---|---|
| to a Site A host (same LAN) | 2.2 ms | 118 Mbit/s |
| to `192.168.20.101` via R1, ISP, R2 | 152 ms | 0.11 Mbit/s |

Moving 1 MB across the WAN took 74 seconds, and the result was the same when the
path was idle. A `SELECT COUNT(*)` over 64,000 rows still took only 0.14 s,
because the server does the work and one number comes back. What collapses is
moving raw rows, which is exactly what every chart does.

Rule that decides placement:

> **An application and its database share a site. Directory and file services
> may cross sites.**

| Service | Asked how often | Cross-site OK? |
|---|---|---|
| Database | 10 to 50 times **per page** | no |
| LDAP directory | once per login, then cached by `sssd` | yes |
| File server | occasionally; users expect to wait | yes |

A page with 20 queries takes 0.02 s with a neighbouring database and 3.0 s
across the 152 ms link, purely in waiting. No query tuning or extra RAM fixes
that. GNS3 emulation only made an existing design error visible; on a real WAN
the symptom would be a vaguely slow page with no obvious cause.

A side effect worth noting: the `DARI-LOKASI-A` ACL on R2
([`gns3/acl_lokasi_b.py`](../gns3/acl_lokasi_b.py)) lost its two
`permit ... eq 3306` lines, because nothing in Site B needed MySQL any more.
Each `permit` must point to one real user; a cross-site allow list that
shrinks is a sign the design improved.

### 2.2 Isolation: a dedicated data server

Placing MySQL on the web server (`192.168.56.103`) fixed distance but traded one
mistake for another: the database shared a machine with the web tier. Judged on
two axes:

| Axis | DB at `.101` | DB at `.103` | DB at `.104` |
|---|---|---|---|
| own machine and segment | yes | no (shares web server) | yes |
| application query path | no (152 ms) | yes (2.2 ms) | yes (1.0 ms) |

`.104` was created by cloning `.103`, so both databases existed from the first
second; only the 2,995 rows written after the clone had to be caught up with
`pindah_data.copy_all()`, the same copy engine used by the initial migration
and by the buffer drain.

Cloning a VM duplicates identity, so three things must be regenerated:

| Item | Consequence if left identical |
|---|---|
| `/etc/machine-id` | NSM reads two machines as one device whose address keeps changing |
| SSH host keys | clients cannot tell the machines apart, the attack host-key checking prevents |
| hostname | every log and report becomes ambiguous |

Also give servers static addresses. The web server had been using a DHCP
lease inside the DHCP range; a moving lease makes the E-Canteen config, ACLs
and NSM's device table point at the wrong address at once, with no error naming
the cause. `.104` is static.

Resulting roles:

| Machine | Services |
|---|---|
| `192.168.56.103` web server | Apache :80, E-Canteen :8080, SFTP :22, SSH |
| `192.168.56.104` data server | MySQL :3306, SSH, SNMP agent |
| `192.168.20.101` directory | LDAP :389, SSH, MySQL replica |

The old MySQL on `.103` was stopped and disabled, with its data files kept for
a few days as a way back. `ufw` on `.104` allows 3306 only from NSM's host and
the web server, so the separation is enforced and not only drawn. This was
verified from `.104`: LDAP port 389 on `.101` answered and the directory was
readable, while port 22 on `.101` was refused.

---

## 3. Migration procedure

`[manual]` = you run it. `[script]` = a repo script does it. Run from
`backend/` with the project virtualenv.

1. `[manual]` Create the empty `nsm` database and an `nsm_app` account scoped as
   in [Security](#7-security). Put `NSM_DB_*` in `backend/.env`.
2. `[script]` Check that existing data fits the new column lengths, before any
   row moves:
   ```bash
   python uji_panjang_kolom.py
   ```
   It reads the live database through the same engine NSM uses and reports
   columns whose longest value exceeds the declared `VARCHAR` length. It
   changes nothing.
3. `[script]` Dry run, then migrate:
   ```bash
   python pindah_ke_mysql.py          # plan only, changes nothing
   python pindah_ke_mysql.py --jalan  # do it
   ```
   The script creates tables and indexes, copies all tables in a foreign-key-safe
   order, then proves arrival by comparing **row counts and the first/last
   timestamp of each table** (row counts alone cannot detect a lost month
   replaced by rows from elsewhere). It is resumable: for integer-keyed tables
   only rows with `id` above the destination's maximum are copied, so an
   interrupted run is simply re-run. Tables keyed by a natural key
   (`nama_alamat.ip`, `orang_ldap.uid`, `posisi_log` on `(device_id, jalur)`)
   are overwritten instead. The source is only read.
4. `[manual]` Keep `nsm.db`. Do not delete the source until the new database
   has proven itself for several days.
5. `[manual]` Restart NSM, then check the Health page and run the follow-up
   items in [section 5](#5-failures-that-raised-no-error).

Foreign-key checks are deliberately left on during the load. `SET
FOREIGN_KEY_CHECKS=0` applies per connection while each batch takes a new
pooled connection, so it would give false assurance; all 22 foreign-key pairs
were checked beforehand and had zero orphan rows.

---

## 4. Porting problems nobody listed up front

The plan had said only four `PRAGMA` statements were SQLite-specific.

### 4.1 82 `String` columns without a length

MySQL refuses `VARCHAR` without a length (`CompileError: VARCHAR requires a
length on dialect mysql`), so the tables cannot even be created. Choosing a
length forces a decision about each column's content. One decision protected
data: `konfig_snapshots.teks` holds an entire router running-config, so it is
`Text`. As `String(255)` MySQL would have refused to store the device config
snapshot that serves as the safety net before config changes.

Sizes are named in `backend/models.py` (`IP`, `NAMA`, `KODE`, `SIDIK`, `JALUR`,
`IFACE`) instead of bare numbers. `uji_panjang_kolom.py` found 80 columns safe
and flagged `bandwidth_samples.iface` (Windows adapter names are free-form), now
255 characters, the SNMP `ifDescr` limit in RFC 2863.

### 4.2 26 indexes that existed only in the live database

They had been created by one-off `migrate_*.py` scripts, so `create_all()` on a
fresh database produced tables with no indexes. Nothing errors; every query
simply scans 500,000 rows, now over the network. They are declared in
`models.py` and were compared in both directions against the live `nsm.db`
with zero differences.

### 4.3 MySQL `DATETIME` rounds fractional seconds

Without a fractional-seconds precision, `DATETIME` rounds: `10:59:59.700000`
is stored as `11:00:00`, moving the sample into a different
`status_rollup_jam` bucket. `models.py` uses `DATETIME(6)` through
`with_variant`, so only MySQL changes. A value such as
`2026-07-22 09:36:50.157997` survives intact.

### 4.4 SQLite-specific SQL in eight places

| Place | SQLite feature | Role |
|---|---|---|
| `jeda.py` | `julianday()` | availability calculation |
| `report_service` | `strftime()` | chart grouping |
| `report_service` | `julianday()` | sparklines |
| `pangkas_data.py` | `sqlite_master` | data pruning |
| `kesehatan.py` | all three | Health page |

None showed up during the migration; they appeared when pages were opened.
MySQL raises on an unknown function. Had `julianday()` silently returned
`NULL`, availability would have been wrong with no sign, and a wrong
availability still looks like a number. MySQL also rejects derived tables
without an alias. All dialect differences now live in `backend/dialek.py`.

### 4.5 The dialect must be decided per connection

The first `dialek.py` set `MYSQL = database.PAKAI_MYSQL` once at import. Nine
test files build their own SQLite databases, so MySQL SQL reached SQLite
(`no such column: MICROSECOND`). It is also wrong in production: with the local
buffer, one process writes to MySQL in one round and SQLite in the next. The
rule: use `dialek._mysql(db)` inside any function that receives a session; use
`database.PAKAI_MYSQL` only for process-level questions ("where is NSM
configured to write?").

---

## 5. Failures that raised no error

These are the most expensive failure type: succeeding without doing anything.

1. **Backup copied a frozen file.** `backup_nsm.py` kept copying `nsm.db`. The
   copy succeeded, passed `integrity_check`, and held data frozen at the move
   date. Backups would have reported success every night while storing nothing
   new. It now dumps the database NSM actually uses (`nsm.sql`) and no longer
   includes `nsm.db`.
2. **Poller freshness check said "stale" forever.** `scripts/restart_nsm.ps1` opened
   `nsm.db` directly. It now calls `backend/cek_segar.py`, which follows
   wherever NSM writes, prints seconds since the last row (`-1` if none), and
   exits with status 2 when the database is unreachable, so "poller idle" and
   "database unreachable" are distinguishable.
3. **Backup manifest always yellow.** `backup_status.py` required `nsm.db` in
   every zip, so each backup would be marked partial. The required list now
   follows the database in use (`nsm.sql`).

`mysqldump` privileges: `backup_nsm.py` runs it with `--single-transaction`,
`--set-gtid-purged=OFF` (otherwise restoring the dump onto the same server
fails with `ERROR 3546`, and restoring onto the same server is the likeliest
scenario), `--skip-masking-policies`, `--no-tablespaces`, and with
`--skip-events` and `--skip-routines` for the restricted account. Each of those
flags exists to avoid asking for a privilege the schema does not need
(`mysql` schema access, `PROCESS`, `EVENT`). The wrong fix would be to widen
`nsm_app`; asking for rights to copy things that do not exist is the quietest way
access grows. Credentials reach `mysqldump` through a temporary
`--defaults-extra-file`, never the command line.

---

## 6. The local buffer (`penyangga.db`)

Once data lives across a network, "database unreachable" becomes possible, and a
monitor hits it exactly when it is most needed: network trouble often cuts the
database connection too. A monitor that stops recording during an outage is
useless, so the move and the buffer ship together
(`backend/penyangga.py`, `backend/database.py`).

### 6.1 Design

- `penyangga.db` is a local SQLite file with the **same schema** as MySQL.
  Writers do not need to know where they write.
- The poller asks `penyangga.sesi()` for a session each round. While MySQL is
  healthy this is `SessionLocal()` at no extra cost. After a failure it returns a
  buffer session and retries MySQL only every `JEDA_COBA_LAGI` = 30 s, so rounds
  do not each pay the full connection timeout.
- **The easy-to-miss part is reading, not writing.** With MySQL down the poller
  also loses its list of devices and services. `cermin_acuan()` therefore mirrors
  `devices`, `services` and **each device's last `status_logs` row** into the buffer
  every `JEDA_CERMIN` = 300 s while healthy (the last status gives the first
  buffered round a comparison point, so it does not log false transitions).
  Trade-off: a device added within 5 minutes before an outage is not monitored
  during it.
- Draining uses the **same** `pindah_data.copy_all()` as the migration. Code that
  only runs in outages is the least tested; sharing the everyday path makes it
  trustworthy.
- **Order: write to MySQL first, then delete from the buffer**, per batch. Reversed,
  a dropped connection loses rows from both places; this way the worst case is
  duplicates, which are easier to clean than losses.
- Reference tables (`devices`, `services`) are copied *into* the buffer and never
  sent back, or a device paused in the UI during the outage would resume.
  Mirrored status rows are removed before the drain; otherwise every outage would
  leave one duplicate per device, and duplicates in `status_logs` skew
  availability (the denominator grows without a new measurement). A small
  `cermin_batas` table in the buffer records the boundary.
- Buffer IDs are unrelated to MySQL IDs, so ordinary tables drop `id` on drain
  (`abaikan_id`). Filtering by "`id` greater than the destination maximum", right for
  a resumable migration, would filter out the *entire* backlog because buffer
  numbering is lower; the drain would report "done" with nothing moved.
- Parent/child pairs (`konfig_snapshots`→`konfig_temuan`,
  `firewall_snapshot`→`firewall_aturan`) keep IDs: parent IDs are shifted
  beyond MySQL's range (`shift_parent`) and the children's pointer column is shifted
  by the same amount. Without this, compliance findings attached to the wrong
  device's snapshot.
- `siapkan()` adds columns that models gained since `penyangga.db` was created
  (as nullable, without a default), since `create_all` never alters existing
  tables; otherwise the drain's `SELECT` fails and blocks the backlog.
- The Health page shows a "Local buffer" row: empty, or the rows waiting.
- Files are git-ignored (`penyangga.db`, `-shm`, `-wal`).

### 6.2 Proving it: `uji_penyangga.py`

The test cuts port 3306 for real by deleting the `ufw` allow rule on the data
server, not by stopping `mysqld`. A stopped server refuses connections
quickly; a real outage drops packets and clients hang, the failure that could
freeze the poller. SSH is never cut, because the way in to repair must not
pass through the thing being broken. Use `ufw delete allow`, not `ufw deny`:
`ufw` identifies a rule by its match criteria, so a `deny` with identical
criteria *replaces* the `allow`, and deleting it later leaves zero rules.

It writes real rows (a dozen), checks that the poller can still read its device
list during the outage, restores the rule in a `finally` block, drains, and
verifies that child rows landed under the right parent. The migration notes
recorded 9/9; the current script has 13 checks including the parent/child ones.
It is listed under the `dikecualikan` (excluded) key of
`backend/ci_manifest.json` and never runs in CI.

Setup notes: it needs `UJI_103_PASS` (an admin password for the data server;
the name is historical, the script connects to the host in `NSM_DB_HOST`) in
`backend/.env`, and its `ufw` commands are written for NSM connecting from
`192.168.56.1`; edit them if your NSM host has another address.

---

## 7. Security

- `nsm_app` is restricted to NSM's host address (not `%`), to the `nsm`
  database only, with no `GRANT OPTION`, no `PROCESS`, and no access to the
  `mysql` schema.
- `ufw` on the data server opens 3306 per source host, not to the subnet.
- The password is random, kept in `backend/.env` (git-ignored), never in code.
  MySQL passwords never travel on a command line.
- The E-Canteen database account was re-created with fresh credentials instead of
  copying the old ones.

---

## 8. Cross-site replica

`.104` holds both the NSM and E-Canteen databases; if it fails, monitoring and
the app stop together, and a monitor that stops will not record why. A copy at
Site B follows it continuously:

```
   SITE A                                SITE B
   .104  MySQL source   ──── WAN ────>   .101  MySQL replica
         server-id 104   verified TLS          server-id 101
         binlog + GTID                          read_only + super_read_only
```

A copy in the same rack dies from the same causes; a copy at another site
survives site-wide events. It also gives the WAN work it suits: app queries
across the WAN are unusable (152 ms per round trip), while asynchronous
replication is not, because the source never waits for the replica. The
difference is who waits for whom.

### 8.1 What is replicated

```
replicate-do-db = nsm
replicate-do-db = ecanteen
```

A first attempt used `mysqldump --all-databases`, which is wrong for a replica.
The `mysql` schema holds the source's system accounts, including a
maintenance account whose password differs per machine; loading it would have
overwritten the replica's own and broken its init and logrotate scripts, far from
anywhere replication is mentioned. This was caught by inspecting the dump
(`CREATE DATABASE mysql` appeared) before loading it. Dump `--databases nsm
ecanteen` instead. The dump's `GTID_PURGED` still covers all of the server's
transactions, which is wanted: the replica treats the rest as done. `replicate-do-db`
filtering is dependable with row-based binary logging (the MySQL 8.0 default).

### 8.2 GTID, not file positions

Position-based replication needs a binlog file name and byte offset that change
on every rotation, and recovering a lagging replica means reading numbers
correctly under pressure. With GTID, `SOURCE_AUTO_POSITION=1` makes the
replica say what it has and the source send the rest.

### 8.3 Settings (reference)

These are the lab's choices expressed as standard MySQL 8.0 settings; adapt
addresses and paths. On the source, drop-ins under `/etc/mysql/mysql.conf.d/`
(the lab used `nsm-replikasi.cnf` and `nsm-tls.cnf`):

```ini
# source (.104)
server-id = 104
gtid_mode = ON
enforce_gtid_consistency = ON
binlog_expire_logs_seconds = 259200   # 3 days
ssl_ca   = <path to lab CA certificate>
ssl_cert = <path to server certificate>
ssl_key  = <path to server key>

# replica (.101)
server-id = 101
gtid_mode = ON
enforce_gtid_consistency = ON
read_only = ON
super_read_only = ON
replicate-do-db = nsm
replicate-do-db = ecanteen
```

```sql
-- source: replication account, TLS required, from the replica only
CREATE USER 'repl'@'192.168.20.101' IDENTIFIED BY '<REPL_PASSWORD>' REQUIRE SSL;
GRANT REPLICATION SLAVE ON *.* TO 'repl'@'192.168.20.101';

-- replica: after loading the dump (its executed-GTID set must be empty first)
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST='192.168.56.104', SOURCE_USER='repl',
  SOURCE_PASSWORD='<REPL_PASSWORD>', SOURCE_AUTO_POSITION=1,
  SOURCE_SSL=1, SOURCE_SSL_CA='/etc/mysql/tls/ca.crt',
  SOURCE_SSL_VERIFY_SERVER_CERT=1;
START REPLICA;
```

Also allow the replica on the source's firewall:
`ufw allow from 192.168.20.101 to any port 3306 proto tcp`.

### 8.4 Seeding across a 0.11 Mbit/s link

| | |
|---|---|
| raw dump | 55.2 MB, about 69 minutes at line rate |
| `gzip -9` (8 s) | 9.6 MB |
| actually sent | 52 minutes, about 3 KB/s effective |

Throughput was far below the nominal ~13 KB/s: the SFTP window (paramiko) waits
for acknowledgements at 152 ms RTT. For a much larger seed use `rsync` or `scp`.
Integrity was checked with **SHA-256, not size**, since a truncated file still
has a plausible size. The file went via the operator's laptop rather than
`.104`→`.101`, because direct copy would need SSH from Site B to Site A and the
R2 ACL deliberately does not allow it; opening a line for a one-off copy is how
permanent holes form.

### 8.5 No new ACL rule

The R2 ACL filters traffic *entering* Site B on the WAN side. The replica
connects *outbound* to `.104:3306`, and all return data comes back inside that
TCP connection, matched by the existing `permit tcp any any established`.
This follows from the shape of MySQL replication: the follower always makes the
connection. Designs that pull are almost always friendlier to firewalls than
designs that push.

### 8.6 TLS with the lab CA, verified

MySQL refuses plaintext authentication by default (`caching_sha2_password ...
Authentication requires secure connection`). `GET_SOURCE_PUBLIC_KEY=1` would
protect only the password while leaving the whole data stream in clear. What
crosses here is every row of `nsm` and `ecanteen` over a link the story treats
as someone else's ISP, so it is not used.

MySQL's auto-generated certificate encrypts but names no machine, so the replica
cannot prove it reached `.104`. Instead the server certificate comes from the
existing lab CA (the one used for LDAP; see [LDAP-TLS](LDAP-TLS.md)):

```
subject = C=ID, O=BSP Lab, CN=nsm-data
issuer  = C=ID, O=BSP Lab, CN=BSP Lab Internal CA
SAN     = IP Address:192.168.56.104, DNS:nsm-data
```

The CA key lives on `.101`, which needs a certificate for `.104`, so the **CSR
crosses, never the key**. Because the SAN contains the IP,
`SOURCE_SSL_VERIFY_SERVER_CERT=1` works; with the stock certificate that line
fails and the temptation to disable it is strong. TLS is offered to everyone but
required only for the replication account (`REQUIRE SSL`), leaving Site A LAN
clients untouched.

### 8.7 The replica really is read-only

`read_only` alone still lets users with `SUPER` write, and `root` has it. One wrong
command in the wrong terminal makes the replica drift silently until it hits a
row it did not expect. With `super_read_only` the attempt fails:

```
ERROR 1290: The MySQL server is running with the --super-read-only option
```

The replication threads are exempt, which is what makes the setting usable.

### 8.8 Evidence: row counts, not `Seconds_Behind_Source`

`Seconds_Behind_Source: 0` showed from minute one while the replica was still
6,230 rows behind. Evidence used instead: `status_logs` row counts on both sides
while the real poller was writing.

```
source 564400  replica 558170  diff 6230
source 564880  replica 561590  diff 3290
source 565330  replica 564420  diff  910
source 565520  replica 565520  diff    0
```

`ecanteen.users` also filled (11 rows), so both databases replicate.

### 8.9 The replica is monitored

An unmonitored replica is worse than none: it gives unfounded confidence and its
absence is found on the day it is needed. NSM checks it on the Health page
("Database replica", `backend/connectors/replikasi.py`, `kesehatan._replikasi()`):

- It asks over **SSH** to the replica host and runs `SHOW REPLICA STATUS\G`,
  reusing an existing, already-justified path instead of re-opening 3306 across
  sites. The MySQL account used there authenticates by OS user over the Unix
  socket (no stored password) and holds only `REPLICATION CLIENT`.
- The verdict is driven by whether **both threads run**. A stopped replica
  reports lag NULL or 0, the worst state looking healthiest. Lag is shown as a
  rough number only: it measures the age of the event being processed, not the
  queue, and can rise while catching up.
- Lag thresholds: attention at 1 day, danger at 3 days (`AMBANG_LAG_*`), the
  source's binlog retention, beyond which the replica must be re-seeded. A
  measurement recorded in the code showed that at the lab's full write rate the
  replica can trail steadily over the 152 ms path (about 90 rows per 45 s) and
  `binlog_transaction_compression` did not help, so tighter thresholds would sit
  yellow permanently; an alarm that is always on is not an alarm.
- "Unreachable" is reported as attention, not failure: it means NSM cannot ask.

Settings in `backend/.env`:

| Variable | Default | Meaning |
|---|---|---|
| `REPLIKASI_HOST` | empty | Replica host. Empty means nothing is probed. |
| `REPLIKASI_ENABLED` | `1` | Set `0` to disable the check. |

---

## 9. Rollback

| Item | Step |
|---|---|
| back to SQLite | empty `NSM_DB_HOST` in `backend/.env` (`nsm.db` is complete up to the move) |
| replication | `STOP REPLICA; RESET REPLICA ALL;` on the replica |
| replica MySQL | `systemctl disable --now mysql` |
| source binlog / TLS | remove the drop-in `.cnf` files, restart |
| replication account | `DROP USER 'repl'@'192.168.20.101';` |
| firewall | `ufw delete allow from 192.168.20.101 to any port 3306` |

Binlogs are kept 3 days. A replica down longer must be re-seeded, a better trade
than filling the source disk with logs nobody reads.

---

## 10. Verification

| Check | Result |
|---|---|
| `pindah_ke_mysql.py`, count and time range per table | 21/21 match |
| `uji_panjang_kolom.py` | 80 columns, none over limit |
| `uji_penyangga.py` (port 3306 really cut) | 9/9 when recorded |
| `uji_percakapan.py` | 53/53 |
| `uji_jalur_db.py` | 14/14 |
| `uji_ldap_ecanteen.py` (real login against new DB) | 10/10 |
| 21 API endpoints | all 200 |
| `backup_nsm.py` | success, `nsm.sql` 47.65 MB |
| `pindah_data.bandingkan`, `.103`→`.104` | 21/21 match |
| `uji_terjangkau.py` | 13/13 |
| RTT NSM to database | 1.0 ms |

---

## 11. Limits

- The replica is a recoverable copy, not a hot standby. No failover or promotion
  procedure has been written or tested.
- `.104` remains a single point of failure for the live path until a failover
  exists.
- The seeding path (SFTP over a 152 ms link) is slow by design of the lab.

## Operational pitfalls

- `sudo` elevates only the **first** command in an `&&` chain. A copy of the CA
  file never arrived, and MySQL reported `SSL_CTX_set_default_verify_paths
  failed`, which does not mention a missing file. The clue was a certificate
  with mode 664 where 644 was commanded: a permission that differs from the
  command shows the command never ran. Use `sudo bash -c '<whole chain>'`.
- Restarting MySQL to enable TLS made the poller's reconnect attempts fail
  repeatedly, and MySQL blocked the host (`is blocked because of many connection
  errors`; Ubuntu's `max_connect_errors` is 100). Recover with `mysqladmin
  flush-hosts`. Restarting a database can lock out its own clients, and the
  symptom is "access denied", not "server restarting".

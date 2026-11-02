# NSM: Network Status Monitor

Network monitoring, configuration compliance, and **guarded automation** for
small to medium networks.

NSM watches devices over ICMP, TCP, SNMP, and SSH, stores their history,
snapshots device configuration and scores it against rules, listens for syslog
and SNMP traps, groups related symptoms into a single incident, and then, **if
and only if six gates allow it**, repairs some failures on its own.

> **Lab project.** NSM was built during my internship in the Network Security
> division of PT Bumi Siak Pusako (BSP). It runs entirely in a personal lab
> (VirtualBox + GNS3 on my own laptop) and has no connection to any BSP system,
> network, or data. Names like "BSP" in the lab artifacts (LDAP domain, report
> header, CA name) are lab labels only. "Primary instance" in these docs means
> the nsm-app VM in that lab, not a company production system.

License: [MIT](LICENSE). Author: Muhammad Rizki Eka Pratama.

---

## What makes it different

Most monitoring tools stop at "notify". Tools that can *act* usually add their
safety rails after the first incident. NSM was built the other way round:
**the guard rails first, the ability to act second.**

| | |
|---|---|
| **Six gates** | Every automatic action passes, in this order: risk classification, operator allow-list, freeze window, working hours, circuit breaker, and rate limit. The first gate that says no ends the check |
| **Audit of allow *and* deny** | One row is written for every decision, including refusals. An unrecorded refusal is indistinguishable from a question nobody asked |
| **Blast radius first** | "If this device goes down, 8 other devices go dark with it" is shown **before** anyone presses the button |
| **Kill-switches default to off** | Every capability that touches a device needs a conscious setting in `.env`, not just an installation |
| **"Unknown" is not "zero"** | A blast radius of 0 on an incomplete dependency graph is reported as *cannot be determined*, never as safe |

The SOC agent has no path to devices of its own. It proposes; the same gates
decide, with `simulasi=True` so that asking "what if" does not use up the quota
of the real remediators. Its optional LLM narration is off by default.

---

## Architecture

```
Browser --> Java (Spring Boot, "blind viewer") --> Python (FastAPI, "the brain") --> MySQL
                                                        ^                              ^
                                                        |                              |
                                          Syslog/Trap --+            Poller --> Connectors --> Devices
```

Data flows one way, and the rule is strict:

* **Python** is the only brain: all business logic, the only component that
  touches the database or opens SSH/SNMP sessions to devices.
* **Java** is a blind viewer: no database access for monitoring data, no SSH,
  no calculations. It forwards JSON through a single integration point,
  `NetmonApiClient`. (It keeps its own small account database for logins.)
* **Local buffer**: if MySQL is unreachable, the poller writes to a SQLite
  database with the same schema and catches up later. A monitor that stops
  recording exactly when the network breaks is useless.

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Features

**Monitor**
- ICMP ping plus TCP probe (tells *ping blocked* apart from *down*)
- TCP, HTTP, and MySQL service checks
- Per-interface bandwidth (SSH or SNMPv3 authPriv)
- Disk, memory, and CPU saturation
- Cross-site MySQL replication check
- SFTP and SMB file-transfer audit

**Analyze**
- Availability with unmonitored time **removed** from the denominator
- Per hour-of-week baseline (168 slots, EWMA)
- Log pattern mining (Drain3)
- Symptom correlation into one incident through a dependency graph
- Forecasts for disk full and bandwidth saturation (regression with R squared)
- SLOs and error budgets

**Configuration**
- Snapshots only when something changed, secrets masked
- Compliance: 23 rules expressed as data
- Source of Truth and drift detection
- Command push with preview, safety net, and proof of life afterwards

**Act (opt-in)**
- Three firewall layers: ufw, Cisco router ACL, Windows Firewall
- Auto-ban with a double-checked allow-list
- Four remediators: GNS3 node, service, interface, configuration
- Rollback and circuit breaker

---

## Quick start

Requirements: Python 3.12+, JDK 25 (the frontend targets Spring Boot 4.1; see
`frontend/pom.xml`), and MySQL 8 for the web frontend. The Python backend alone
can run on SQLite.

```bash
git clone <repo-url> nsm && cd nsm
python -m venv backend/venv
source backend/venv/bin/activate          # Windows: backend\venv\Scripts\activate
pip install -r backend/requirements.txt
cp backend/.env.contoh backend/.env       # then edit it
cp frontend/src/main/resources/application.properties.contoh \
   frontend/src/main/resources/application.properties
```

Edit `backend/.env`:

* To run without MySQL, leave `NSM_DB_HOST` empty (the backend then uses a
  local SQLite file; no code change needed).
* Review the switches. The code default for every device-touching switch is
  off, and the example file keeps them off (`AUTO_BAN_AKTIF=0`); turn auto-ban on
  only deliberately.
* Syslog and SNMP-trap receivers are off by default (`SYSLOG_AKTIF`,
  `SNMPTRAP_AKTIF`; UDP ports 1514 and 1162).

Create the tables and start the backend. Run these from `backend/`, each in its
own terminal (the venv active):

```bash
cd backend
python init_db.py                                       # creates tables, seeds 3 sample devices
python -m uvicorn main:app --host 127.0.0.1 --port 8000
python -u poller.py
```

Check the API: `curl http://127.0.0.1:8000/devices`. On Linux the poller needs
permission to use unprivileged ICMP sockets (or run as root), otherwise pings
report an error.

The web UI needs MySQL for its login database. Create the databases `nsm_auth`
(frontend) and, if you use MySQL for the backend, `nsm` (see
[docs/MYSQL.md](docs/MYSQL.md)), set the credentials in both config files, then:

```bash
cd frontend && ./mvnw spring-boot:run
```

Open `http://localhost:8080`. The first admin password is **generated randomly**
and printed once to the console when Spring Boot first starts; copy it then. The
example properties enable LDAP login; clear `nsm.ldap.url` to use local
accounts only (see [docs/LDAP-TLS.md](docs/LDAP-TLS.md)).

The full lab (GNS3 topology, VMs, LDAP) is described in
[docs/LAB-SETUP.md](docs/LAB-SETUP.md).

---

## Tests and CI

```bash
python -m pytest                          # lab-dependent tests are skipped
python backend/jalankan_ci.py --mode semua
python -m ruff check .
```

There are 105 legacy `uji_*.py` test scripts (run as subprocesses; 12 already
converted to native pytest) plus a native pytest suite in `backend/tests`. Some
need the live lab and are skipped when it is off; three **change real (lab)
devices** and run only on request. See [backend/tests/README.md](backend/tests/README.md).

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs only what works
without the lab, and says so. CI baseline, as honestly as I can state it:

* `ruff check` currently reports legacy findings in older files (about 290 with
  ruff 0.16.9 when this was written), so the lint job is not clean.
* Two legacy tests fail in a clean checkout: `uji_jeda` (part of it expects
  real data from a lab database) and `uji_permukaan_paket` (a snapshot check
  tripped by a SQLAlchemy signature change).
* mypy covers only `backend/nsm`, and the Java test step does not fail the
  workflow (some tests need MySQL).

---

## Deliberately not included

- **Automatic device discovery**: the inventory is filled in by hand
- **Pre-change verification** (Batfish and similar): dropped for lack of
  resources on the VM, not because it is unimportant
- **Broad multi-vendor support**: only Cisco IOS and Linux are lab-tested; other
  vendors are definitions marked as documentation-level (see
  [backend/perangkat/README.md](backend/perangkat/README.md))
- **Service-to-service authentication**: the Python API binds to `127.0.0.1`
  and relies on that boundary, not on tokens (see [SECURITY.md](SECURITY.md))
- **High availability**: one poller, one API

## Honest limits

| Topic | State |
|---|---|
| Scale tested | **11 monitored devices** in a two-site lab (lab numbers) |
| Devices | Emulated Cisco routers/switches (GNS3/Dynamips), Ubuntu VMs, the host laptop, and a home ISP router; not real production gear |
| Cisco images | Bring your own licensed images; none are included |
| Real-world use | Never used on a real or company network |
| Device credentials | Stored as-is in the database, as in most comparable tools |
| Syslog and SNMP traps | Unauthenticated UDP: used as **evidence and a trigger for checks**, never as a trigger for action |
| CSP | `style-src 'unsafe-inline'` is still permissive |
| Some UI pages | Not every new API has a page yet |

---

## Documentation

| Document | Covers |
|---|---|
| [docs/PROJECT-SUMMARY.md](docs/PROJECT-SUMMARY.md) | Internship project summary |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Code architecture |
| [docs/LAB-SETUP.md](docs/LAB-SETUP.md) | Building the lab |
| [docs/TOPOLOGY.md](docs/TOPOLOGY.md) | Two-site topology |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Starting, restarting, deploying |
| [docs/BACKUP.md](docs/BACKUP.md) | Backups and restore checks |
| [docs/SNMP.md](docs/SNMP.md) | SNMPv3 setup |
| [docs/SSH-WINDOWS.md](docs/SSH-WINDOWS.md) | SSH to Windows with a limited account |
| [docs/LAB-WEBSERVER.md](docs/LAB-WEBSERVER.md) | Lab web server |
| [docs/MYSQL.md](docs/MYSQL.md) | MySQL setup and replication |
| [docs/LDAP-TLS.md](docs/LDAP-TLS.md) | LDAP with StartTLS |
| [docs/FAULT-INJECTION.md](docs/FAULT-INJECTION.md) | Deliberate fault tests |
| [docs/POSTMORTEM-R1.md](docs/POSTMORTEM-R1.md) | The R1 outage |
| [docs/design/](docs/design/CLOSED-LOOP-AUTOMATION.md) | Design notes: [closed-loop automation](docs/design/CLOSED-LOOP-AUTOMATION.md), [auto-ban](docs/design/AUTO-BAN.md), [tiered notifications](docs/design/TIERED-NOTIFICATIONS.md), [traffic identity firewall](docs/design/TRAFFIC-IDENTITY-FW.md), [config compliance](docs/design/CONFIG-COMPLIANCE.md), [blast radius](docs/design/BLAST-RADIUS.md), [incremental backup](docs/design/INCREMENTAL-BACKUP.md), [device-agnostic](docs/design/DEVICE-AGNOSTIC.md), [clean architecture](docs/design/CLEAN-ARCHITECTURE.md), [network status](docs/design/NETWORK-STATUS.md), [LDAP replica](docs/design/LDAP-REPLICA.md) |
| [docs/project-report/](docs/project-report/) | Internship report (Indonesian) |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contributing |
| [SECURITY.md](SECURITY.md) | Reporting vulnerabilities, threat model |

## License

[MIT](LICENSE).

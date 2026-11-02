# NSM: Internship Project Summary

> **Lab project.** NSM was built during my internship in the Network Security
> division of PT Bumi Siak Pusako (BSP), July to August 2026. It runs entirely in
> a personal lab (VirtualBox + GNS3 on my own laptop) and has no connection to
> any BSP system, network, or data. All numbers below are **lab numbers**.

---

## 1. Problem

The internship brief was a network automation application: real-time device
monitoring, remote configuration of routers, switches, and servers, and
connectivity tests. Together with the field supervisor the scope was narrowed
to up/down monitoring plus remote access, using **GNS3** as a simulated network.

Existing monitors mostly stop at "notify". Tools that act tend to add safety
rails only after something has gone wrong. The question that shaped NSM was:
*how do you let a monitor fix things without letting it make things worse?*

## 2. Solution

NSM is a Network Status Monitor with a deliberately strict architecture:

* **Python (FastAPI)** is the brain: all logic, the only component touching the
  database and devices.
* **Java (Spring Boot + Thymeleaf)** is a blind viewer that forwards JSON.
* **MySQL** stores history, with a local SQLite buffer so recording never stops
  when the database is unreachable.

Data flows `Browser -> Java -> Python -> database <- poller <- connectors <-
devices`. Automation was built **guard rails first**: every automatic action
passes six ordered gates (risk classification, allow-list, freeze window,
working hours, circuit breaker, rate limit), and every decision, allowed or
denied, writes an audit row. See [ARCHITECTURE.md](ARCHITECTURE.md).

## 3. What was built

| Area | Delivered |
|---|---|
| Foundation | Lab, ping, SQLite then MySQL with buffer, FastAPI, Java dashboard, GNS3 plus Cisco via Netmiko |
| Web security | Login and roles, password policy, CAPTCHA, tiered lockout, SMTP password reset, audit log, LDAP login with StartTLS |
| Reporting | Availability, incidents, MTTR, SSH and SNMPv3 bandwidth, live charts, scheduled backups, Excel/Word/PDF export, email notifications |
| Monitoring | Layered service checks, traffic log, SSH to Windows with a limited account, health and backup pages, MySQL replication check, SFTP/SMB file audit |
| Configuration | Config snapshots, 23 compliance rules, Source of Truth with drift detection, device identity verification, command push with preview and safety net |
| Firewall | Three layers (ufw, Cisco ACL on a router, Windows Firewall); one-click blocking; auto-ban without a click |
| Closed-loop automation | Four remediators (GNS3 node, service, interface, configuration), six gates, rollback, circuit breaker, blast-radius calculation |
| Insight | Incident timeline and correlation, one notification per incident, hour-of-week baselines, log pattern mining (Drain3), forecasts, SLOs and error budgets, a SOC agent that only proposes, multi-tenant data separation |
| Lab topology | Two sites (A and B) with a simulated ISP router between them, MySQL replication across sites, LDAP at one site |

The primary lab instance is the `nsm-app` VM, running three systemd services:
poller, API, and frontend. Deployment uses a script that also verifies the
deployed source matches the development machine.

## 4. Results measured in the lab

These come from the lab, not from a real network.

* **Automatic recovery, end to end.** A deliberate power-off of an emulated
  router was detected by the poller, the gates allowed the GNS3 remediator, and
  the router was running again **78 seconds** after it was shut down, with no
  command typed by a person.
* **Incident grouping.** 4 alarms became 1 incident and 1 email (previously 4
  emails, 3 of which blamed devices that were not broken).
* **Log mining.** 321 real syslog messages from the lab folded into 10 patterns.
* **Baseline build.** 300,000 status rows were folded into baselines in about 50
  seconds (459 slots filled for 6 devices).
* **Tenant separation.** Through real HTTP, a wrong tenant saw 0 devices while a
  request with no tenant header saw 11.
* **Cross-site cost.** Within site A: 2.2 ms and 118 Mbit/s; across sites
  (emulated routers): 152 ms and 0.11 Mbit/s. This is why the application and
  its database share a site.
* **Alert noise.** Raising the DOWN threshold from 2 to 5 poll intervals cut
  false "incidents" on emulated routers from 267-277 per day to 5-16.
* **Tests.** 105 legacy test scripts plus a native pytest suite (see
  [../backend/tests/README.md](../backend/tests/README.md)).

## 5. Lessons and notable defects

* **Real faults find what mocks cannot.** Hundreds of tests with mocks passed;
  switching off a real emulated router exposed four defects, and a second run
  found two more (a GNS3 controller address pointing at the wrong machine, and
  credentials read from a Windows-only path). Mocks prove the logic; only a real
  fault proves the chain is connected. See
  [FAULT-INJECTION.md](FAULT-INJECTION.md).
* **The R1 outage.** The safety net for pushing configuration used `reload in N`.
  On an emulated Dynamips router, `reload` powers the virtual machine off
  permanently instead of rebooting. The router, its neighbor, and the LDAP
  directory behind it went dark, and nobody could log in. The root cause was
  fixed with a guard in the command-sending code. See
  [POSTMORTEM-R1.md](POSTMORTEM-R1.md).
* **Silent failures are the dangerous ones.** Examples: login auditing and
  auto-lock were silently disabled for two days; one corrupt log line (NUL
  bytes) cancelled a whole combined transaction and traffic storage failed for
  days; MTTR read 0 seconds for every incident because it was computed from the
  wrong timestamp; a backup of the accounts database was silently missing.
* **Measure dependencies again.** A planned online-learning library was
  measured at about 103 MB of extra memory against 7 MB for the pattern-mining
  library, so the baseline formula (about sixty lines) was written directly and
  the library is used only as a test oracle.
* **Looking finds what tests miss.** A Backup page that nagged constantly
  because NSM on Linux looked for a Windows-style folder, and tables that never
  filled the page because of one CSS rule, passed every automated test.
* **Early weakness, later fixed.** In one early period the poller ran on a laptop
  that was not always on, and only 25.5% of the time was actually monitored. That
  motivated the dedicated VM and excluding unmonitored time from availability.

## 6. Skills demonstrated

Python (FastAPI, SQLAlchemy, APScheduler), Java (Spring Boot, Spring Security,
Thymeleaf), MySQL including replication and TLS, SNMPv3, SSH automation
(Netmiko, Paramiko), LDAP, Linux administration (systemd, ufw, fail2ban,
Samba), Cisco IOS and ACLs, GNS3/VirtualBox lab building, clean architecture
and dependency inversion, safety-focused automation design, testing strategy
(including testing the tests), incident analysis, and technical writing.

## 7. Honest limitations

* A lab project: 11 monitored devices, mostly emulated or virtual, in one
  two-site lab. It has never run on a real network.
* Several new switches ship off by default and have not run on real incidents;
  the SOC agent has been exercised by tests, not by real production incidents.
* Web pages for some newer APIs do not exist yet, and the incident page has not
  been visually verified in a browser with a real account.
* One poller, one API, no high availability; no authentication between Java and
  Python beyond the localhost boundary.
* Batfish-style pre-change verification was cancelled for lack of VM memory.
* Backups have no second disk for an off-machine copy; the risk is shown in the
  UI rather than hidden.
* Only Cisco IOS and Linux are lab-tested; other vendors are definitions marked
  as documentation-level.

# Blast radius and root-cause attribution: one event, one diagnosis

**Status:** implemented, with a different mechanism from the first proposal (see "Proposed but not built"). The topology-graph attribution, the service dependency table, the cause/effect/warning diagnosis panel, incident correlation and the blast-radius guards are in the code. **Not built:** a third "unreachable" state excluded from availability, an out-of-band management network, and dependency suggestions mined from flow data.

Numbers come from the author's lab. Code identifiers are Indonesian: `ketergantungan` = dependency, `hulu` = upstream, `hilir` = downstream, `sebab` = cause, `akibat` = effect, `layanan` = service.

## Context and problem

When one machine dies, several things go red at once. Early in the lab, losing the data server lit four equal alarms (MySQL, SSH, the server, and the web app that depends on it); only one is a cause. Losing the first router (R1) took R2, SW-B and the LDAP directory behind it: four devices, one cause, four DOWN incidents, four emails and, once automatic recovery existed, four fix attempts of which three were certain to fail because the path was cut.

That distorts three things: availability (a healthy device is charged for a broken path), trust in alerts (four emails for one event teach people to skip them), and the cause itself (one useful line buried under three derived ones). Telling cause from effect should be the monitor's job, not the reader's.

## Goals and non-goals

Goals: classify each failing device or service as cause or effect; show effects under their cause instead of hiding them; collapse symptoms with the same root into one incident and one message; give automation and operators a number for "who else goes dark if this breaks".

Non-goals: guessing routing NSM cannot see; hiding alarms for tidiness (the service dependency list is hand-written, so a wrong guess must stay visible).

## Design

**1. Devices: derive dependency from the cabling.** `ketergantungan.py` reads `device_link` (physical paths, filled by `isi_device_link.py` from the GNS3 cables), not a hand-kept "A depends on B" list. Links are undirected; direction comes from the vantage point: the device with platform `lokal` (where NSM runs). The "upstream" of a device is every device on the shortest path (BFS) from NSM to it. The vantage point is found by role, not by IP, because NSM's address moved once and hardcoded IPs were left behind in four places.

- `penyebab_hulu(db, device_id, mati=...)`: is this device's outage explained by a dead upstream device? Answers `ada_penyebab` (effect), `tidak_ada` (cause) or `tidak_bisa_dipastikan` (the graph cannot answer).
- `hilir(db, device_id)`: the blast radius, every device whose path from NSM passes through this one.
- `graf_lengkap()`: whether every active device has a path; separates "nothing depends on it" from "NSM does not know".

**2. Services: a small evidence-based table.** `layanan_bergantung` has four rows, each traceable to a real config (for example the web app's `application.properties` names the MySQL URL and the LDAP URL; `sssd.conf` makes SSH logins depend on the directory). `akar.nilai()` is a pure function with three ordered rules: the host is down (explains most, checked first), a required service is down, a required device is down. It iterates to a fixed point with a cap of 8 rounds so an accidental cycle stops instead of hanging.

**3. One panel, three verdicts.** `report_service.diagnosis()` returns one ordered list: causes first, each effect right below its cause, then warnings. Steps ("first step", with raw evidence last) are shown only for causes; telling people to inspect a merely affected service sends them to the wrong place. A single layout deepens downward instead of a beginner/expert mode switch: two modes means two views to maintain, and beginners never see the technical form next to its meaning.

**4. One definition of "down".** The panel decides "down" from `device_events` (after the poller's consecutive-failure rule) and passes that set as `mati=` into `penyebab_hulu`. The module's own fallback uses the latest raw `status_logs` row. Mixing both on one screen makes the same device alive in one row and dead in the next. The "because" sentence names the most upstream dead device (what must be fixed), not the nearest neighbour.

**5. Saturation in the same panel.** A third tier, `peringatan` (warning), covers resources that will break soon: disk, memory, CPU load per core, sampled every 5 minutes over SSH. Two thresholds per metric (disk 80/90 %, memory 85/95 %, load per core 1.5/3.0); value and threshold are printed together. Memory uses `available`, not `used` (Linux counts cache as used); load is divided by core count; an unmeasurable value (a router has no `df`) gets no verdict rather than 0 %. A capacity forecast warns before a threshold is crossed. It sits in the incident panel because disks fill fastest during incidents.

**6. Consumers of the graph.**

| Consumer | Use |
|---|---|
| `korelasi.py` | symptoms with the same root device merge into one incident; time only filters, the root unifies |
| `notifikasi_insiden.py` | one message per incident, listing every symptom and marking the root |
| `kirim_perintah.py` | the pre-change plan prints "if this command is wrong, N other devices lose their path". It informs, never blocks: transit devices are sometimes exactly what must change |
| `pagar_otomasi.py`, `pemulih/konfig.py` | automatic config rollback requires zero downstream devices and a certain graph |
| `pemulih/orkestrasi.py` | recovery candidates whose outage is an effect are withheld, and the withholding is printed |
| `GET /devices/{id}/history` | returns `dampak_hilir {jumlah, daftar, pasti, tak_terjangkau}` |

## Safety and failure modes

- **Unknown is not "none".** An incomplete graph yields `tidak_bisa_dipastikan`, never `tidak_ada`. The two callers treat doubt differently on purpose: the recoverer does not act, the notifier still alerts (silence is never a safe default for news).
- **Dependencies need evidence.** A row exists only if it points at a real consumer. A dependency invented by hand makes NSM call a cause an effect, and a wrongly demoted alarm is worse than a noisy one.
- **Failure of the helper must not look like safety.** If blast radius cannot be computed, plan and gate record "unknown" (certainty false), never zero downstream, which would unlock the riskiest action. The same failure must not stop a legitimate command or the diagnosis panel.
- **Effects stay visible**, only demoted.

## Data model

`device_link(device_a_id, device_b_id, jenis, keterangan, ...)` undirected. `layanan_bergantung(layanan_id, pada_layanan_id | pada_device_id, alasan)`; `alasan` is the sentence shown on screen. Seed with [script] `python migrate_ketergantungan.py` (plan only) then `--jalan`; fill links with `python isi_device_link.py`.

## Proposed but not built

The first proposal added a per-device parent (`devices.induk_id`), a non-pinged `penanda` device kind, a third state UNREACHABLE excluded from the availability denominator via `jeda.py`, and `terhalang_oleh` columns on `status_logs`/`device_events`, plus cycle rejection on write. The shipped design reaches the same attribution from the existing link graph with no per-device manual parent. Consequences: availability (`jeda.py`) still excludes only unmonitored gaps (poller off, device paused), so time spent behind a dead parent still counts as downtime; the unregistered intermediates (GNS3 VM, host-only adapter) have no node.

## Testing in the lab

`uji_ketergantungan.py` replays the real R1 outage on the lab's exact topology (R1 down: R2, SW-B, LDAP are effects; R1 up and LDAP down alone: LDAP is a cause; incomplete graph: undetermined; recoverer and notifier treat doubt differently; the candidate filter returns reasons). Also `uji_akar.py` (pure verdicts, including a cycle), `uji_dampak_hilir.py`, `uji_korelasi.py`, `uji_report_service.py`, `uji_sumberdaya.py`. Real injected outages are in [FAULT-INJECTION.md](../FAULT-INJECTION.md).

## Lessons learned

- **The page contradicted itself.** The summary ("all healthy") was computed from services while dead devices were appended afterwards. Summaries are now computed from the final list.
- **Two panels disagreed.** One used a raw ping row, the rest used `device_events`; one lost ping on the 152 ms inter-site path raised a false cause card. Now there is one source.
- **A hardcoded verdict hid for months.** Down devices with no registered service were all marked cause, so the first router outage showed "4 causes, 2 affected" and sent people to two healthy remote devices. `penyebab_hulu()` already answered correctly and had its own tests; the panel never called it. After wiring it: 2 causes (a genuine separate gateway fault and R1), 4 affected.
- **Security evidence nobody can read is no evidence.** The router's ACL `deny ... log` had found a missed SNMP permit within seconds, but console-only logging stored nothing. `gns3/nyalakan_log_router.py` enables `logging buffered` with `logging rate-limit` (without it a flood of denied packets makes the router busy writing logs). Filtering runs on the router (`show logging | include IPACCESSLOG`) to spare the narrow inter-site link, and repeats are filtered by per-line fingerprint because the buffer is returned whole each time. Router clocks started from zero, so `penolakan_acl` stores both the router stamp and NSM's read time; `gns3/pasang_ntp_router.py` syncs the routers.
- **A test runner died silently.** A 900 s timeout killed the runner and 17 later tests never ran, with no message. `jalankan_semua_uji.py` now allows 1800 s and reports a timeout as `MACET` (stuck) and continues. A list that looks complete but is half is the costliest failure here.

## Open questions

- A separate out-of-band management network (a second host-only adapter exists, idle) so one bad firewall rule cannot cut the only way into a host.
- Suggesting dependencies from `flow_koneksi` for a human to approve.
- Whether availability should exclude time behind a dead upstream, and how to mark the discontinuity in old figures.
- Showing ACL denials on the firewall page (data reaches `/firewall`, no view yet).

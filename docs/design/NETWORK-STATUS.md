# Design: network status, stability and link quality

How NSM stopped reporting hundreds of false "incidents" per day, and how it now
separates **alive or dead** (availability) from **good or bad link** (quality).
All numbers are from the author's personal lab (VirtualBox + GNS3), measured on
19 August 2026 against the MySQL database; see the [README](../../README.md).

## Context and problem

The Report page marked five devices "unstable" with 167 to 179 outages each and
availability of 95 to 96% shown red. The questions were how long they were
unstable and why 96% was red.

### Most "outages" were false

NSM pings every **10 seconds** (`POLL_INTERVAL=10` in the lab `.env`; the code
default if unset is 30). Confirmed from 30 consecutive raw timestamps: median
9.99 s. The old rule declared DOWN after 2 consecutive failures, so the minimum
recordable outage was one interval.

Failure episodes from raw `status_logs` (6,481 episodes, 5 devices, 24 h):

| Consecutive failures | Duration | Count | Share | Cumulative |
|---|---|---|---|---|
| 1 | 10 s | 5,124 | 79.1% | 79.1% |
| 2 | 20 s | 781 | 12.1% | 91.1% |
| 3 | 30 s | 400 | 6.2% | 97.3% |
| 4 | 40 s | 128 | 2.0% | 99.3% |
| 5 | 50 s | 20 | 0.3% | 99.6% |
| 7 to 37 | 70 to 370 s | 26 | 0.4% | 100% |

**99.3% of episodes ended within 40 s.** Only 9 were long (130 to 370 s) in 24 h
across five devices.

### One shared cause

Per-hour failed-ping rates moved together on all five GNS3 devices (for example
10% at 03:00, 25 to 30% at 09:00, 36 to 42% at 13:00) while the data server,
which does not pass through GNS3, stayed at **0.0% every hour**. Likely cause
(not proven): Dynamips routers are emulated in software and delay ICMP replies
when the host CPU is busy, with peak latencies of 984 to 998 ms against a 1 s ping
timeout (`connectors/icmp.py`: `COUNT=1`, `TIMEOUT=1`). A direct test of four
settings ran only 3 minutes in a quiet hour (0% everywhere) and proves nothing.

### Why 96% was red

The old colour scale (green at 99.9% or more, yellow at 99% or more, red below)
was datacenter-SLA shaped, with no middle colour.

### How availability is computed

`availability = (window - total incident duration) / window * 100`, from incidents,
not ping counts. Fewer false incidents therefore improves availability, but real
packet loss would **vanish from the report**: a device dropping 40% of packets
could show a perfect green. Hence a separate quality measure.

### What the Health page is

"System health" checks NSM itself (poller heartbeats, backup age, replica,
database size, disk, skipped ping rounds), not network health. Verdict is the
worst of the parts.

## Goals and non-goals

Goals: cut false incidents without hiding real outages; say how long a device has
been unstable; show link quality separately from availability; use a colour scale
that fits an emulated lab.

Non-goals: multi-packet probes (tested idea skipped); per-device thresholds
(single threshold chosen); alerting on state change (needs stored state, future);
changing the service-check threshold (`SERVICE_DOWN_THRESHOLD`, default 2 at 30 s;
TCP is far more reliable than ICMP and no data shows a problem).

## Design

### Decisions

| # | Decision |
|---|---|
| 1 | DOWN after **5** consecutive failures (50 s of silence at 10 s polling) |
| 2 | Multi-packet probes skipped |
| 3 | Link quality as a column separate from availability |
| 4 | Colour scale: 100% dark green, 99% or more green, 95% or more yellow, 90% or more orange, below 90% red |
| 5 | Stable/unstable decided by time, not ping count |
| 6 | Old history recomputed with the new rule rather than deleted |

Effect on the same 24 h of data (simulation counting failed pings times 10 s; the
Report page also removes unmonitored time, so judge the change, not the absolute):

| Device | At 2x | At 5x |
|---|---|---|
| Router A | 277 outages / 92.7% | 5 / 99.7% |
| LDAP (B) | 274 / 92.7% | 6 / 99.5% |
| Router B | 272 / 92.7% | 12 / 99.2% |
| Switch B | 267 / 92.9% | 9 / 99.3% |
| Switch A | 268 / 91.5% | 16 / 97.9% |
| Data server | 0 / 100% | 0 / 100% |

### A. DOWN threshold

`DOWN_THRESHOLD` in `backend/.env` (read by `config.get_down_threshold()`,
default 5). Recovery to UP needs a single success. Accepted risk: a real outage
shorter than 50 s is no longer recorded, partly offset by the quality column.

### B. Recomputing history

`backend/hitung_ulang_insiden.py` rebuilds `device_events` from raw
`status_logs`, interactively. It requires a backup under one hour old,
copies the old table once to `device_events_sebelum_ambang5` (the first copy stays the
reference), prints before/after per device, and asks for explicit confirmation
before swapping. It is idempotent. Four traps are handled:

| # | Trap | Handling |
|---|---|---|
| B1 | A gap while the poller was off could read as consecutive failures | break the streak when rows are more than 3 intervals apart |
| B2 | `ping_blocked` (ICMP fails, TCP alive) is not an outage | read `status_logs.sumber`; `tcp` means alive |
| B3 | `baseline` marker rows are not outages | copied unchanged |
| B4 | `status_logs` starts before events do | recompute only from each device's first event |

Until it is run, history before the change keeps the old threshold. Deadline:
`pangkas_data.py` prunes `status_logs` after **35 days**, so older history can no
longer be recomputed.

### C. Time-based stability (hysteresis)

`report_service.hitung_kestabilan(db, device_id, sekarang)` replays the device's
DOWN events through a state machine (baseline rows excluded):

| Transition | Rule | Setting |
|---|---|---|
| Stable to **unstable** | at least 3 DOWNs within 15 minutes | `STABIL_MIN_SIKLUS=3`, `STABIL_JENDELA_MENIT=15` |
| Unstable to **stable** | no DOWN for 10 full minutes | `STABIL_PULIH_MENIT=10` |

It returns whether the device is stable, since when, for how long, and the count in
the window, so the badge can read "unstable, 40 min". It is intentionally not
cached, so cards and tables cannot show two different states.

### D. Availability colours

`warnaAvail()` in `frontend/.../static/report.js` returns `hijau-gelap`, `hijau`,
`kuning`, `oranye` or `merah` at 100, 99, 95 and 90; the matching CSS classes are in
`css/nsm.css`. The bar colour and the explanatory sentence must follow the same
scale, or the bar and number disagree.

### E. Link quality column

`report_service.hitung_kualitas_sambungan()` counts every ping attempt in the
period (via `rollup.sampel_periode`), with no threshold:

| Packet loss | Verdict |
|---|---|
| under 1% | good |
| 1 to under 5% | fair |
| 5 to under 15% | poor |
| 15% or more | very poor |

(`KEHILANGAN_BAGUS/CUKUP/BURUK` = 1, 5, 15.) It also reports peak latency and
returns `None`, not 0%, for a period with no samples. The cut-offs sit far below
the GNS3 range (5.7 to 40.7%) while non-GNS devices measured 0.00 to 0.01%.
Results are cached 30 s. The page should say that this loss reflects emulation
on a laptop, not broken devices, otherwise a reader may think the lab network is
genuinely bad.

### F. Health page subtitle

A one-line subtitle stating that the page reports the monitoring tool's condition.

## Safety and failure modes

- The threshold change is a deliberate trade: shorter real outages go unrecorded.
- Recomputing history is destructive, so it is gated by backup, a preserved copy
  and explicit confirmation.
- The GNS3 recoverer must not use the loosened signal: it reads the official
  `device_events` verdict, not raw pings (see
  [POSTMORTEM-R1](../POSTMORTEM-R1.md)).

## Data model and interfaces

Tables: `status_logs` (raw pings, `sumber` icmp/tcp/lokal), `device_events`
(DOWN/UP with category `dead`, `recovered`, `ping_blocked`, `baseline`),
`status_rollup_jam`. No new table for C and E. Config keys: `DOWN_THRESHOLD`,
`STABIL_*`, `POLL_INTERVAL`.

Reference data (19 August): `status_logs` 901,863 rows (22 Jul to 19 Aug);
`device_events` 3,745 rows (25 Jul to 19 Aug); failed pings in 24 h ranged from
5.7% to 18.4% on GNS3-path devices and 0.00 to 0.01% elsewhere; mean/max latency
for GNS3 devices ranged 51 to 194 ms mean and 981 to 998 ms max.

## Testing in the lab

Standalone scripts and pytest equivalents: `uji_kestabilan.py` /
`tests/test_kestabilan.py` (entry on the 3rd cycle not the 2nd, exit exactly after
10 quiet minutes not 9), `uji_kualitas_sambungan.py` /
`tests/test_kualitas_sambungan.py` (edge values such as 0.9, 1.1, 5.1, 15.1%; no
data gives `None`), `uji_hitung_ulang_insiden.py` (traps B1 to B4, idempotence, raw
data untouched). `uji_rollup.py`, `uji_ping_diblokir.py`, `uji_paralel_baca.py`
and `uji_jeda.py` were re-run because they touch the threshold; six tests that
hard-coded "two rounds" were changed to use the configured threshold.

Live check after restarting the poller: the startup log showed the new threshold
and **no new DOWN event in the first 4 minutes**, in a period that historically
loses 10 to 40% of packets. In the browser, 90.20% rendered orange, 97 to 98%
yellow, 100% dark green; one LDAP device showed 97.98% availability (yellow) but
quality "poor, 13.9% loss". Two facts, both kept.

## Lessons learned

- Measure before assuming: the first draft assumed a 5 s interval, which was wrong
  (10 s). Incident counts per threshold were unaffected, but every seconds label
  was off by 2x.
- An aggregate over a whole period cannot say "since when". Replaying events
  through a state machine can.
- Fixing one metric can hide a real problem; give the hidden quantity its own
  column.
- Comments and docstrings that quote a number go stale: `config.get_down_threshold()`
  still describes "5 x 5 s = 25 s" while the lab runs 10 s polling (50 s).

## Open questions

1. Should `SERVICE_DOWN_THRESHOLD` rise too? Measure the `service_checks` failure
   distribution first; do not assume TCP behaves like ICMP.
2. Retest 3-packet probes during 09:00 to 16:00 for at least 30 minutes.
3. Per-device thresholds would suit physical devices that lack emulation delay.
4. Alerting when a device turns unstable needs stored state.
5. Some front-end files still hard-code "5 seconds" for refresh cadence; the
   per-device chart interval claims to match the poller and now does not.

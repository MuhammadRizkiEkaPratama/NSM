# Tiered notifications: fewer emails, fewer false alarms

NSM's original notifier emailed on every DOWN transition. The tiered notifier holds back until an outage has proven itself, groups devices into one email, and warns once about devices that flap. This document records the request, the design, what was measured, and which further ideas (maintenance windows, extra channels) are still only plans.

Numbers are lab numbers from the personal lab described in [TOPOLOGY.md](../TOPOLOGY.md).

## Status

| Part | Status |
|---|---|
| Legacy per-event notifier (`notifikasi.py`) | Implemented, still scheduled |
| Tiered evaluator: "down" after a continuous window, "recovered" only for devices that were notified, "unstable" flap warning | Implemented (`notifikasi_berjenjang.py`, job `poll_notifikasi_berjenjang`) |
| One combined email per kind per round, subscribers de-duplicated | Implemented (`/internal/notifikasi-gabungan` in the Java frontend) |
| Immediate extra email when an automatic recovery fails | Implemented (`eskalasi_segera`, called by the recovery modules); not part of the original request |
| One email per incident instead of per event | Implemented in a separate module (`notifikasi_insiden.py`), off by default (`NOTIF_PER_INSIDEN=0`) |
| Scheduled maintenance windows, send delay, quiet hours, Telegram/webhook channels, escalation by duration | **Planned only. No code exists** |

## Context and problem

The legacy path (`notifikasi.py`) reads `device_events` and emails immediately on every DOWN row, and also on recovery. Its only brake is `NOTIF_JEDA_MENIT` (default 5): if the same device just triggered an email, the next event is dropped. It checks the queue every `NOTIF_INTERVAL` seconds (default 30), and when the mail server is unreachable it retries along a ladder of 30, 60, 300, 900, 1800, 3600 seconds. A device that dies for 40 seconds still produces an email, and by the time the reader opens NSM everything is green.

The field supervisor's request, paraphrased: do not send an email on the first failed check. Evaluate in 5-minute rounds and send only if a device is still down after the third round, so there is no spam and no "alarm that is already gone when I open the dashboard". Several servers should share one queue and one email. Recovery emails were originally not wanted.

This is a standard pattern: Nagios SOFT/HARD states with `max_check_attempts`, the Prometheus `for:` clause (pending then firing, timer resets if the condition breaks), Alertmanager grouping, and the "down after N consecutive failures" setting of hosted uptime monitors.

## Goals and non-goals

Goals: no email for outages that heal on their own; each device counted on its own clock; one email for several devices; no silent gap for devices that flap; state that survives a poller restart.

Non-goals: slowing the ping. Pings keep running at the poll interval (10 s in the lab), because graphs, availability and link quality depend on them. Only the notification **evaluator** runs every 5 minutes. Recording is never delayed either; only sending is.

## Design

### Three rules, one evaluator

The job runs every `NOTIF_PUTARAN_MENIT` (default 5), evaluates every active device and sends at most one email per kind:

```
every 5 minutes, for each active device:
  A. count successful pings in the last NOTIF_PUTARAN_BUTUH x NOTIF_PUTARAN_MENIT minutes (default 15)
       zero (and enough samples)  -> candidate "down"
       any success                -> the count restarts from zero
  B. was a "down" email sent and a ping now succeeds -> candidate "recovered"
  C. DOWN events in the last hour >= NOTIF_FLAP_AMBANG and not warned recently -> candidate "unstable"
merge candidates of the same kind -> one email per kind
```

**Continuous, not three samples.** One successful ping anywhere in the window resets the clock, like Prometheus `for:`. Sampling three times at 5-minute spacing would be fooled by a device that blips: dead at the sample instant, alive in between, and the resulting email would still feel like a false alarm. The data is free: pings are in `status_logs.is_reachable`.

**Consequence worked out in the tests.** A device that starts failing exactly at minute 5 gets its email at round 5 (minute 20), not round 4, because the window seen at minute 15 still touches healthy time. In the test scenario a second server that recovers at minute 10 never gets any email at all.

| Round | Minute | File server | Data server | Email |
|---|---|---|---|---|
| 1 | 0 | down | up | no |
| 2 | 5 | down | down (starts) | no |
| 3 | 10 | up (window will never be fully down) | down | no |
| 4 | 15 | up | down for 10 min only | no |
| 5 | 20 | up | down for the full 15 min | yes, data server only |

**Recovery email only for devices that received the down email.** A device that never triggered "down" gets no "recovered" either, so there is no extra noise. The reverse case matters too: an email saying "X is down" followed by silence leaves the reader staring at a green dashboard. This matches Nagios (recovery goes to whoever got the problem) and Alertmanager's `send_resolved`.

**Unstable warning.** Flapping devices never stay down for 15 minutes, so they would never be reported. At 10 or more DOWN events in one hour a single "unstable" email is sent, then silence until the device has been below the threshold for `NOTIF_FLAP_TENANG_JAM` (default 6 h). Without that last clause a device could be warned once in its lifetime. It maps to Nagios flap detection.

**Why 10 and not 30.** The first proposal was 30 per hour. Tested against the lab data it could never fire: the worst hour was 48 DOWN events per hour before the DOWN threshold was raised from 2 to 5 consecutive failures, and 3 per hour over the following week. The same real outage hour counted 45 events in the old data and 3 in the corrected data, so the detection layer already absorbs most flapping. Ten is over three times the worst normal hour but reachable when the network is really broken. A number that sounds sensible still has to be tested against your own data.

**One email for several devices.** Matching devices are merged into one message. The Java endpoint `/internal/notifikasi-gabungan` takes a list of `device_ids`, takes the **union** of subscribers across them and de-duplicates per user, so someone subscribed to three failing devices gets one email. Counting stays per device; only the queue and the message are shared.

### State and the "poller died" trap

Only two timestamps are stored, on `devices`: `notif_mati_dikirim` and `notif_flap_dikirim`. They answer "have we already sent for this condition?" and nothing else. "How long has it been down" is recomputed every round from `status_logs`, so no counter can drift from its source, and a poller restart loses nothing (a counter kept in process memory would reset a device that had been down 14 minutes, and its email would never go out).

If the poller itself was dead for 15 minutes, every device would show zero successful pings and the system would email "everything is down". The guard is a minimum sample count, `NOTIF_SAMPEL_MIN` (default 30); with too few rows the evaluation returns "not enough data" and the device is skipped this round.

A failed send is deliberately not marked, so the next round re-evaluates and retries without a separate failure marker.

### Settings (`backend/.env`)

| Setting | Default | Meaning |
|---|---|---|
| `NOTIF_ENABLED` | `1` | Master switch; turns off both notifier jobs |
| `NOTIF_PUTARAN_MENIT` | `5` | Minutes between evaluation rounds |
| `NOTIF_PUTARAN_BUTUH` | `3` | Rounds of continuous failure before "down" |
| `NOTIF_SAMPEL_MIN` | `30` | Minimum ping rows for a window to count |
| `NOTIF_FLAP_AMBANG` | `10` | DOWN events per hour for "unstable" |
| `NOTIF_FLAP_TENANG_JAM` | `6` | Calm hours before another "unstable" warning |
| `NOTIF_JEDA_MENIT`, `NOTIF_INTERVAL` | `5`, `30` | Legacy notifier |

## Safety and failure modes

| Failure | Behaviour |
|---|---|
| Mail or Java unreachable | Nothing marked, retried next round; legacy path has its own backoff ladder |
| Poller down | Sample guard skips devices instead of declaring them dead |
| Process restart mid-outage | Window recomputed from the database; markers persist |
| Recovery attempt failed | `eskalasi_segera` sends one extra email immediately instead of waiting for the window |
| Subscribers overlap | Union de-duplicated per user |
| Device with zero subscribers | Audit entry is recorded as skipped, not as "sent" |

## Testing in the lab

`backend/uji_notifikasi_berjenjang.py` runs against an in-memory SQLite database with real ping and event rows (not mocks), covering: too few samples is not "all dead"; continuous-down versus any-success; the round 4 versus round 5 table above; flap rules; one combined message for many devices. It was self-verified by deliberately breaking `_down_terus_penuh()` and confirming the relevant tests failed before restoring it. `uji_notifikasi_tangga.py` covers the legacy retry ladder.

```
python backend/uji_notifikasi_berjenjang.py
```

## Lessons learned

- A schema migration (`migrate_notif_berjenjang.py`, adding the two columns) hung eight times with `Lock wait timeout`. The cause was five idle MySQL connections holding metadata locks for about 70 minutes after a network hiccup. Killing them fixed it. Not a notifier bug, but a routine `ALTER TABLE` can stall live monitoring.
- Measure thresholds against your own data before adopting them.
- Markers that live in memory disappear exactly when they are needed.

## Open questions

- **Both notifiers run together.** `poll_notifikasi` and `poll_notifikasi_berjenjang` are registered under the same `NOTIF_ENABLED`, and there is no switch to disable only the legacy path. With defaults, a long outage produces the immediate legacy email and later the tiered one. The plan was to run both for a few days against real outages, then retire the old path; that retirement has not happened and the tiered path has been verified with synthetic data, not a long soak.
- `NOTIF_SAMPEL_MIN=30` assumes the lab's 10 s poll interval (about 90 rows per window). At the code default `POLL_INTERVAL=30` a 15-minute window holds about 30 rows, leaving no slack.

## Planned, not built: alert rules and other channels

This part was written as a design only. No tables or code exist for it.

- **Maintenance windows**: scheduled time ranges (per device or global) in which the device is still pinged and data is still collected, but no alerts are sent and availability is not affected, ending automatically. This differs from the existing pause (which stops monitoring and must be remembered and released; in the lab a paused device stayed paused for over eight days unnoticed). A `jendela_perawatan` table (device, start, end, reason, creator) was sketched.
- **Send delay**: a per-device `tunda_detik`. Record immediately, send only if still down; outages that heal first stay visible in the history with a "recovered before notification" marker. Per device because a 30-second Wi-Fi gateway blip is normal, while a 30-second database loss is an incident.
- **Quiet hours** that defer, never drop (the message is sent at the end with the original time).
- **Escalation by outage duration, not by send attempts**, so a failing mail server does not look like a device that is still down: for example email at 5 minutes, email plus a chat message at 30, a "prolonged" marker at 120.
- **Channels as a list of senders** (email, Telegram bot, webhook), where one failing channel never blocks another. A bot token would be a new secret and would live in the Java frontend's configuration, never in the Python side or the database.
- **Grouping by cause** rather than by time, using the dependency graph (see [BLAST-RADIUS.md](BLAST-RADIUS.md)). The per-incident email module already provides one email per outage and a follow-up only when severity rises.

Rules the plan held to: recording is never delayed or skipped; suppressed alerts are logged as skipped with the reason; maintenance windows always have an end; defaults reproduce today's behaviour.

## References

- Nagios Core, state types (SOFT and HARD, `max_check_attempts`)
- Prometheus alerting rules (`for:`) and Alertmanager grouping
- Zabbix trigger best practices

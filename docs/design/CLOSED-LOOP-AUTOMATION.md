# Guarded Closed-Loop Automation

NSM can detect a fault, decide whether it may act, fix it, check that the fix worked, and undo or escalate if it did not. This document describes how that loop is built so that "automatic" never means "unchecked", and it separates what exists in code from what is only planned.

> **Lab scope.** Everything here ran in the personal VirtualBox + GNS3 lab described in [LAB-SETUP](../LAB-SETUP.md). Device counts, timings and incident numbers are lab numbers. "Primary lab instance" means the `nsm-app` VM in that lab.

Contents: [Status](#1-status-what-is-in-code-and-what-is-not) | [Problem](#2-context-and-problem) | [Goals](#3-goals-and-non-goals) | [Design](#4-design) | [Gates](#5-the-gate) | [Remediators](#6-the-four-remediators) | [Blast radius](#7-blast-radius-and-dependency-awareness) | [SOC agent](#8-the-soc-agent-proposes-never-executes) | [Manual path](#9-the-manual-change-path-and-its-safety-net) | [Linux stage](#10-the-linux-host-stage) | [Safety](#11-safety-and-failure-modes) | [Data model](#12-data-model-and-interfaces) | [Testing](#13-testing-in-the-lab) | [Lessons](#14-lessons-learned) | [Open questions](#15-open-questions)

---

## 1. Status: what is in code and what is not

Where the original plan and the code disagree, this document follows the code.

| Area | Status | Notes |
|---|---|---|
| Source of truth (intended state) | Implemented | `backend/sot/`: catalog, renderer, service |
| Drift detection | Implemented, Cisco IOS only | `backend/drift/`; the Linux snapshot collects security posture, not hostname/NTP |
| Automation gate | Implemented | `backend/pagar_otomasi.py` |
| Remediator: restart GNS3 node | Implemented | `backend/pemulih/gns3.py` |
| Remediator: restart a systemd service | Implemented | `backend/pemulih/layanan.py` |
| Remediator: bring an interface up | Implemented | `backend/pemulih/interface.py` |
| Remediator: fix config drift | Implemented for 9 keys | `backend/pemulih/konfig.py` |
| Dependency filter and blast radius | Implemented | `backend/ketergantungan.py` |
| Verification, rollback, escalation | Implemented | `pemulih/rollback.py`, `notifikasi_berjenjang.eskalasi_segera` |
| SOC agent (propose only) | Implemented | `backend/agen_soc.py`; `usul` mode is the default |
| SOC agent executing runbooks | Partial | Only the GNS3 restart runbook has an executor in `jalan` mode |
| Linux host write path | **Not implemented** | `perangkat/linux.yaml` has `tulis.didukung: false`; only two narrow wrappers exist (section 10) |
| Revert scheduler for Linux config | **Planned only** | Design in section 10 |
| Per-key risk scoring at the config remediator | **Not enforced** | Risk is a coarse per-remediator class (section 5) |
| Operator endpoint to reset the circuit breaker | **Not implemented** | Function exists, no API route |

The build order differed from the stage numbering: GNS3 restart (4), then interface up (6), rollback (8), config drift fix (7), service restart (5), escalation (9). Stages 0 to 3 (always-on VM, source of truth, drift, gate) came first.

## 2. Context and problem

NSM began as a monitor: it polls devices, receives syslog and SNMP traps, and shows status. The next question was what to do about what it sees. Three observations shaped the design.

**Observed state is not intended state.** A monitor knows what a device looks like now. To act safely it also needs to know what the device is meant to look like. That is the source of truth (SoT): a small database of declared intent (hostname, NTP servers, which interfaces should be up) that drift detection compares against the latest config snapshot.

**One root fault looks like many.** When router R1 in the lab goes down, everything behind it stops answering. Without dependency awareness, NSM would see five devices down, attempt four automatic fixes and send four emails for one cause. That is an automation storm, and it is the failure the dependency filter exists to prevent.

**Automation that cannot be trusted will not be switched on.** The first automatic action NSM ever took, blocking attacker IPs ([AUTO-BAN](AUTO-BAN.md)), was able to block NSM's own host. The rule that came out of it: every automatic action passes one gate, and the gate is checked at the point of execution, not only where the action is proposed.

### Anatomy of a closed loop

| Part | What it answers | Where |
|---|---|---|
| Detect | Is something wrong, and is it real (debounced, not a single lost ping)? | `device_events`, `service_events`, drift, `insiden` |
| Explain | Is it a cause or an effect of another outage? | `ketergantungan.py` |
| Decide | May automation act here, now? | `pagar_otomasi.putuskan()` |
| Act | Do the narrowest possible thing | `pemulih/*`, `connectors/perintah.py` |
| Verify | Did the world actually change? | per-remediator, recorded as tri-state |
| Undo | If not, go back | `pemulih/rollback.py`, `kirim_perintah.py` |
| Escalate | Tell a human, louder if undo also failed | `notifikasi_berjenjang.eskalasi_segera` |
| Audit | Who asked, what was decided, what happened | `pagar_tindakan` table |

## 3. Goals and non-goals

**Goals**

- Fix a small set of well-understood faults without a human, in the lab, safely.
- Make "safe" mechanical: each rule is a check that can refuse, not a convention.
- Record every decision, including refusals, so the system can be audited and tuned.
- Fail closed: an unknown, unreachable or ambiguous situation means "do not act, tell a human".

**Non-goals**

- General-purpose remediation or arbitrary command execution. The catalog is short and fixed.
- Replacing a change-management process on a real network. This is a lab design.
- Letting a language model act. The SOC agent proposes; the gate and remediators act.
- Auto-saving configuration. `write memory` is always a separate human action.

## 4. Design

### Layers

| Layer | Responsibility |
|---|---|
| L1 Source of truth | Declared intent: values, interfaces, VLANs, routes, with history |
| L2 Drift detection | Compares intent with the latest snapshot, per key |
| L3 Automation gate | One function that every automatic action must pass |
| L4 Remediators | Four narrow fixers, ordered by rising risk |
| L5 Verify and rollback | Proof that the fix worked; a way back when it did not |
| L6 Reliability | Always-on VM, systemd units, debounced events, tunnel supervision |

### The loop

```
detect ──> dependency filter ──> gate ──> act ──> verify ──┬─> ok: record, done
(debounced   (effect of an        (6 checks,   (one narrow    │
 events,      upstream outage?     every        action)       └─> failed: rollback if one exists,
 drift)       hold back)           decision                       escalate, count toward breaker
                                   recorded)
```

Detection uses the debounced `device_events` and `service_events` tables, not raw pings: a device is DOWN only after `DOWN_THRESHOLD` consecutive failures (default 5 poll intervals). An early version of the GNS3 remediator acted on raw pings and restarted devices that were merely slow; it was fixed to read the debounced events.

### Switches are re-read every round

Settings are read on each remediator round, not at startup, so a switch takes effect without restarting a service. Intervals: `PEMULIH_INTERVAL` (default 120 s, minimum 60), `AGEN_SOC_INTERVAL` (default 120 s, minimum 30). One remediator stage failing does not stop the others (`pemulih/orkestrasi.py` runs the four in order of rising risk).

## 5. The gate

`pagar_otomasi.putuskan(db, device_id, kategori, kunci, oleh=None, sekarang=None, bukti=None, simulasi=False)` returns allow or refuse with a reason. Gates run in this order and the first refusal wins.

| # | Check | Setting | Default |
|---|---|---|---|
| 1 | Risk class | built in (`RISIKO_PEMULIH`) | `gns3_restart` safe; other three need a human unless gate 1b passes |
| 1b | Evidence for human-class actions | `OTOMASI_PENUH_*` switches plus live evidence | all off |
| 2 | Allowlist | `PAGAR_DAFTAR_PUTIH` | empty (nothing allowed) |
| 3 | Freeze window | `PAGAR_JENDELA_BEKU` | none |
| 4 | Working hours | `PAGAR_JAM_MULAI` / `PAGAR_JAM_SELESAI` | 8 to 17, end exclusive, end may be up to 24 |
| 5 | Circuit breaker | `PAGAR_GAGAL_BERUNTUN_MAKS` | 3 consecutive failures |
| 6 | Rate limit | `PAGAR_BATAS_DEVICE_PER_JAM`, `PAGAR_BATAS_GLOBAL_PER_JAM` | 3 per device per hour, 10 globally per hour |

Details that are easy to get wrong:

**Risk is binary, not a number.** Each remediator kind is `aman_otomatis` (safe to automate) or `wajib_manusia` (needs a human). Only `gns3_restart` is the first; service restart, interface up and config fix are the second. An unknown remediator kind defaults to `wajib_manusia`. There is no numeric risk score in code.

**Gate 1b turns "needs a human" into "needs evidence".** A `wajib_manusia` action is evaluated only if its `OTOMASI_PENUH_*` switch is on *and* live evidence holds:

| Action | Evidence required |
|---|---|
| Service restart | fewer than `BATAS_RESTART_LAYANAN_HARIAN` (default 3) allowed restarts in 24 h for that device and service |
| Interface up | the latest config snapshot shows no `shutdown` line under that interface; no snapshot means refuse |
| Config fix | zero downstream devices and a complete dependency graph (section 7) |
| anything else | refuse |

**Allowlist.** Empty by default, so a fresh install may do nothing. For the `nilai` and `pemulih` categories the allowlist matches on the key name.

**Freeze window.** `start|end` ISO timestamp pairs separated by `;`.

**Circuit breaker.** After N consecutive failed actions for the same (device, category, key) the gate refuses further attempts. One success closes it again. Rows whose verification is still NULL are skipped when counting, and a human-written `reset_pemutus:` row stops the count. It is checked before the rate limit, so a failing action reports "breaker open" rather than "rate limited".

**Rate limit.** Recomputed from `pagar_tindakan` rows on every call, not kept in memory, so a restart cannot reset it. The global limit is per tenant when the device has a `tenant_id`.

**Every decision is recorded**, allow or refuse. With `simulasi=True` all checks run but no row is written, so asking "would this be allowed?" does not spend the rate-limit budget. The SOC agent in `usul` mode relies on this.

**Verification is tri-state.** `record_verification()` sets `status_verifikasi` to NULL (not yet known), True or False. NULL is never treated as success.

**Two keys per remediator.** To act, a remediator needs its own switch (`PEMULIH_GNS3_AKTIF`, `PEMULIH_LAYANAN_AKTIF`, `PEMULIH_INTERFACE_AKTIF`, `PEMULIH_KONFIG_AKTIF`) *and* an allowlist entry. Either missing means nothing happens.

### Kill switches

All default to off. A typo in a value must never become permission.

| Switch | Meaning |
|---|---|
| `PEMULIH_GNS3_AKTIF`, `PEMULIH_LAYANAN_AKTIF`, `PEMULIH_INTERFACE_AKTIF`, `PEMULIH_KONFIG_AKTIF` | each remediator |
| `OTOMASI_PENUH_LAYANAN`, `OTOMASI_PENUH_INTERFACE`, `OTOMASI_PENUH_KONFIG` | allow gate 1b to evaluate a human-class action |
| `AGEN_SOC_AKTIF` | SOC agent runs at all |
| `AGEN_SOC_MODE` | `usul` (default; unknown values fall back to it) or `jalan` |
| `AGEN_SOC_NARASI` | agent may call an external LLM API |
| `AUTO_BAN_AKTIF` | automatic attacker blocking (code default off) |
| `INJEKSI_TERJADWAL_AKTIF` | scheduled fault injection |

`backend/.env.contoh` ships these as off, with one exception: it sets `AUTO_BAN_AKTIF=1` (the code default is off), so check that line before copying the file. `nyalakan_otomasi.py` is the helper that turns a chosen set on for the primary lab instance.

## 6. The four remediators

All live in `backend/pemulih/`. All go through the gate with `oleh` set to a recognisable origin (`poller_pemulih_gns3`, `poller_pemulih_layanan`, `poller_pemulih_interface`, `poller_pemulih_konfig`, `agen_soc`, `reset_pemutus:<who>`).

| Remediator | Candidate | Action | Verification | Rollback |
|---|---|---|---|---|
| `gns3.py` | active device with a `gns3_node` whose latest event is DOWN | controller API stop then start (`connectors/gns3_pemulihan.pulihkan`); URL from `GNS3_URL` | two-phase, 180 s timeout | none (previous state is the fault) |
| `layanan.py` | service with `unit_systemd` set and latest event DOWN | `sudo /usr/local/sbin/nsm-restart-layanan restart <unit>` as a restricted account | 90 s | none |
| `interface.py` | drift: intent says up, snapshot says `shutdown` | catalog command `iface_hidup` via `kirim_perintah.kirim(..., sungguhan=True)` | synchronous | `batalkan()` exists, not triggered automatically |
| `konfig.py` | drift status `beda` on a supported key | catalog command that rewrites the key | fresh snapshot, 1200 s | automatic via `kirim_perintah.putuskan(..., 'batalkan_sekarang')` |

Notes per remediator:

- **GNS3 restart.** The controller stays bound to `127.0.0.1`; `terowongan_gns3.py` keeps a reverse SSH tunnel to it and turns `PEMULIH_GNS3_AKTIF` off if the tunnel cannot be restored, so the remediator never acts blind. Hard-coding the controller URL was a real bug (the first unattended run failed on it).
- **Service restart.** Defence in depth: the database column `services.unit_systemd` is the first allowlist, and the server-side wrapper `firewall/nsm-restart-layanan` is the second, accepting only `restart` and `status` (never `stop`) for named units. `isi_unit_systemd.py` maps four units on two lab servers (apache2, ecanteen, smbd, auditd). SSH, LDAP and MySQL are deliberately never mapped: SSH is NSM's own path in, LDAP breaks logins, MySQL holds NSM's own data. NULL means "never auto-restart"; unit names are never guessed from service names.
- **Interface up.** Candidates come from drift, not from "interface is down": the trigger is "intent says up and the snapshot says shutdown". The remediator refuses when the snapshot shows no `shutdown` line (someone else may have changed it since).
- **Config fix.** Supported keys: single-valued `hostname`, `banner_masuk`, `zona_waktu`, `snmp_lokasi`, `snmp_kontak`; list-valued `ntp_server`, `dns_server`, `logging_server`; and the one-way boolean `layanan_http_mati`. Four keys are deliberately unsupported, with reasons recorded in `ALASAN_TIDAK_DIDUKUNG`: `domain`, `exec_timeout_menit`, `vty_izin`, `ssh_saja`. When a fix fails verification the remediator rolls back automatically; if the rollback also fails, the escalation is louder, because "fix failed and undo failed" is the worst state the system can be in.

`rollback.py` provides the bookkeeping shared by remediators with a meaningful way back: `simpan_state_sebelum`, `simpan_state_sesudah`, `ambil_state_sebelum`, `kembalikan`. A rollback exception is recorded as `rollback_dilakukan = False` rather than propagating, so the failure is visible in the audit table.

## 7. Blast radius and dependency awareness

Two related questions use the same graph, built from the `device_link` table (the real cabling, copied from GNS3).

**Is this outage a cause or an effect?** `ketergantungan.penyebab_hulu()` walks the shortest path from the vantage point (the device whose platform is `lokal`, i.e. where NSM runs) to the target. Its answer has three values, not two:

| Answer | Meaning | Remediator | Notifications |
|---|---|---|---|
| `ada_penyebab` | an upstream device is down; this is an effect | hold back | suppress separate alert |
| `tidak_ada` | path intact, all upstream alive; this is a cause | proceed to gate | alert |
| `tidak_bisa_dipastikan` | graph cannot answer (missing link, no anchor) | hold back | alert anyway |

"Unsure" is deliberately not "none". An incomplete graph must never read as a proven healthy path. The remediator treats unsure as "do not act"; notifications treat it as "alert", because a skipped alarm is worse than an extra one. `orkestrasi._saring_hulu` applies `filter_candidate` to every remediator's candidates and returns the held-back ones with reasons so they are logged, not lost.

**How many devices go dark if this one fails?** `ketergantungan.hilir()` returns the devices whose path from NSM passes *through* the target. That is its blast radius. `graf_lengkap()` distinguishes "radius 0" from "the graph does not know": an empty list means nothing depends on it only when the graph is complete.

Lab radii (devices behind each one): Site A switch 8, Site A router 3, Site B router 2, Site B switch 1, web server 0.

Where radius is used:

- **Command preview.** The manual-change preview shows `dampak_hilir*` so an operator sees "this shutdown cuts off N devices" before sending. It informs; it does not block.
- **Device page.** Shows the same count.
- **Gate 1b evidence** for the config remediator: automatic config fixes are only considered on devices with no downstream and a complete graph.

This closed a gap in the earlier pre-change check, which only rejected commands on the interface NSM itself used to reach the target. Shutting `Fa1/0` on R1 left R1 reachable through `Fa0/0` while everything behind it went dark. See also [BLAST-RADIUS](BLAST-RADIUS.md).

## 8. The SOC agent proposes, never executes

`backend/agen_soc.py` reads incidents, gathers evidence and writes a triage, an optional narrative and a proposed action. It cannot touch a device. This is enforced rather than promised: a test (`uji_agen_soc.py`) asserts that the file contains none of `netmiko`, `ConnectHandler`, `paramiko`, `subprocess`, `urllib.request` or `socket.`, and that it does not import `connectors`.

### What it does

1. **Triage.** Finds similar incidents over the previous 30 days.
2. **Evidence.** Collects recent syslog (5 min), config snapshots, the upstream graph, error budget, baseline and new log patterns. Collections that fail are listed in the output instead of silently omitted.
3. **Narrative.** A template always produces a plain account in which every sentence traces to an evidence field. Optionally an external LLM rewrites it. The prompt allows only facts present in the supplied JSON and forbids suggesting actions; any failure falls back to the template.
4. **Runbook mapping.** Maps the incident to one of `gns3_restart`, `layanan_restart`, `interface_up`.
5. **Proposal.** Passes the proposed action through `pagar_otomasi.putuskan()` with `oleh="agen_soc"`.

### Three independent switches

| Switch | Question it answers |
|---|---|
| `AGEN_SOC_AKTIF` | may the agent analyse at all? |
| `AGEN_SOC_MODE` | `usul`: log what it *would* do (gate called with `simulasi=True`). `jalan`: the gate decides and, if it allows, the proposal is delegated to the remediator. |
| `AGEN_SOC_NARASI` | may device names, IP addresses and event sequences leave the lab network for an external LLM API? |

The narrative switch is separate on purpose: it is a data-egress decision, not an analysis decision. With it off, narratives still work from templates.

In code, `jalan` mode currently delegates only the GNS3 restart runbook; the service and interface runbooks have no executor in the agent and rely on the regular remediators. The recommended path is to run `usul` for several weeks and compare proposals with human decisions on the `/agen-soc` page before considering `jalan`. `agen_soc.ringkas` reports how often the agent's proposal and the gate's verdict agree. The agent's `proses` is idempotent: an incident that already has a triage row is skipped.

## 9. The manual change path and its safety net

Operators can also send catalog commands by hand through the same machinery (`backend/kirim_perintah.py`). The automatic config and interface remediators reuse it, so manual and automatic changes share one safety path.

Flow: guards (device identity matches, device not paused, command in catalog) then snapshot before, arm a safety net, send, prove the device still answers, snapshot after, decide keep or revert.

- **Dry run by default.** `sungguhan=False` sends nothing.
- **Closed catalog.** 15 commands in `connectors/perintah.py`. Parameters are validated: allowlisted values only, newlines rejected, interface names checked against the snapshot.
- **Per-device definition.** `perangkat/*.yaml` marks each command `teruji` as `lab`, `rekaman` or `dokumentasi`; only `lab` may write. Each platform declares its `jaring_pengaman`.
- **Save is a separate step.** `write memory` is a distinct button (`simpan_permanen`), never automatic. The "Save?" prompt is answered no.
- **Safety net is a timed reload, and not for emulated routers.** For physical-style devices a `reload in N` is armed before the change and disarmed (`lepas_setelah_terbukti`) only after proof the device still answers. For GNS3 (Dynamips) nodes `reload` is not used, because in Dynamips it destroys the emulation permanently, which is what happened to R1 during an early test ([POSTMORTEM-R1](../POSTMORTEM-R1.md)). GNS3 nodes revert through the controller instead.
- **Rollback is not a list of inverse commands.** It lets the net expire, or restores via the controller, so the device returns to its saved startup state.

## 10. The Linux host stage

The Linux stage extends the same loop to Ubuntu hosts: read-only snapshot, drift, and, eventually, tightly bounded writes.

### In code today

- **Read.** A Linux snapshot collects security posture (SSH settings, firewall state and similar). It does not collect hostname or NTP, so config drift does not apply to Linux hosts.
- **`firewall/nsm-restart-layanan`.** The service-restart wrapper described in section 6.
- **`firewall/nsm-ubah-firewall`.** A ufw wrapper with a server-side forbidden-address list, no ability to disable the firewall, and automatic expiry of a rule through `systemd-run`. Used for the block path in [AUTO-BAN](AUTO-BAN.md).
- **`perangkat/linux.yaml`** declares `tulis.didukung: false` and `jaring_pengaman: tidak_ada`. The generic write path refuses Linux hosts.

### Planned, not implemented: revert scheduler for config changes

The reason a Linux write path is harder than a Cisco one: there is no `reload in N`. A bad `sshd_config` change can lock NSM out of the machine it just edited. The proposed design:

1. Copy the target file to `/var/backups/nsm/`.
2. Install a revert timer: `systemd-run --on-active=5min --unit=nsm-pulih-<id>` that restores the copy.
3. Write the change and restart or reload the service.
4. Open a **new** SSH connection to prove access still works (the existing session proves nothing).
5. If it works, cancel the timer and keep the change. If not, do nothing: the timer restores the file.

The proposed catalog is six changes across sshd, ufw and NTP. `at` and `cron` were considered and rejected as the timer: `systemd-run` units are named, inspectable and cancellable. Open design question: privilege model (section 15).

## 11. Safety and failure modes

| Failure | What happens |
|---|---|
| Default install | Everything off; empty allowlist. Nothing acts. |
| Setting typo | Unknown mode values fall back to the safe value (`usul`); switches parse as off unless clearly on. |
| Upstream outage | Dependent devices are held back, not "fixed". |
| Graph incomplete | Remediator holds back; notifications still alert. |
| Repeated failure | Circuit breaker opens after 3; it does not close itself on time, only on a success or a human reset. |
| Verification not finished | Status stays NULL, never counted as success; the breaker skips NULL rows. |
| Fix fails | Rollback where one exists; escalation via `eskalasi_segera`, louder if rollback also failed. |
| Fix would cut management | Those keys are unsupported (`vty_izin`, `ssh_saja`). |
| GNS3 tunnel lost | Tunnel supervisor retries; if it cannot restore, it disables `PEMULIH_GNS3_AKTIF`. |
| Wrong host | Device identity is checked (`sama`) before any write; paused devices are refused. |
| Compromised or confused agent | It has no device code path; its proposals face the same gate. |
| Server-side bypass | Wrapper scripts enforce the unit and address allowlists on the managed host itself. |
| Wasted budget | `simulasi=True` avoids spending the rate limit on dry questions. |

Two properties are worth stating plainly. **Fail closed:** every unknown resolves to "do not act". **Honest values:** `status_verifikasi` and `rollback_dilakukan` can be NULL, and a NULL is displayed as "unknown", not rounded to success.

## 12. Data model and interfaces

Verified against `backend/models.py` and the route modules.

### Tables

**`pagar_tindakan`** (`PagarTindakan`): one row per gate decision, allow or refuse.

| Column | Meaning |
|---|---|
| `id`, `device_id`, `kategori`, `kunci` | what was asked, on which device |
| `keputusan`, `alasan` | `izin` or `tolak`, with the reason |
| `diminta_oleh`, `waktu` | who asked (see section 6), when |
| `status_verifikasi`, `verifikasi_bukti`, `verifikasi_waktu` | tri-state result and proof |
| `state_sebelum`, `state_sesudah` | JSON state around the action |
| `rollback_dilakukan` | tri-state |

Indexed on (`device_id`, `waktu`) and (`keputusan`, `waktu`).

**`usulan_agen`** (`UsulanAgen`): the agent's output. Fields: `waktu`, `insiden_id`, `device_id`, `jenis` (`triase`, `bukti`, `narasi`, `tindakan`), `mode`, `tindakan`, `vonis_pagar` (`izin`, `tolak`, `tidak_diminta`), `alasan_pagar`, `isi` (JSON), `keyakinan`.

**Source of truth:** `intent_nilai`, `intent_interface`, `intent_vlan`, `intent_rute`, `intent_riwayat`. Jinja2 templates live on disk (`sot/templates/cisco_ios.j2`, `linux.j2`), never in the database, which removes template injection as a class of bug; the renderer also uses a sandboxed environment with strict undefined variables. The catalog holds no secrets.

**Other:** `insiden`, `insiden_gejala`, `device_link`, `konfig_snapshot`, `services.unit_systemd`.

**Drift statuses:** `cocok`, `beda`, `tidak_terbaca`, `hilang`, plus `tidak_didukung`. Comparison is scoped per key, not a raw text diff.

### Python API (read-only unless noted)

| Endpoint | Purpose |
|---|---|
| `GET /pagar/status`, `GET /pagar/riwayat` | gate state and decision history |
| `GET /agen-soc` | agent proposals and agreement summary |
| `GET/POST /sot/...` | read and edit intent |
| `GET /drift`, `GET /drift/{id}` | drift results |
| `/devices/{id}/perintah`, `/pratinjau`, `/kirim`, `/putuskan`, `/simpan` | manual change flow (write endpoints guarded as in section 9) |

There is no endpoint that resets the circuit breaker; `pagar_otomasi.reset_pemutus(db, device_id, kategori, kunci, oleh, alasan)` exists, requires a non-empty reason, and is currently run by hand.

### Viewer pages (Java frontend)

`/admin/konfig/sot`, `/admin/konfig/drift`, `/admin/konfig/pagar`, `/agen`, plus `/api/pagar/*`, `/api/sot/*`, `/api/drift/*`, `/api/agen-soc`. The health page has an "Pagar otomasi" section. The frontend holds no logic: it calls the Python API only.

### Poller jobs

`poll_healer` in `nsm/pemantau/konfig.py` runs the remediators; `poll_agen_soc` in `nsm/pemantau/wawasan.py` runs the agent.

## 13. Testing in the lab

Mocked tests are necessary and not sufficient. The approach has three levels; procedures live in [FAULT-INJECTION](../FAULT-INJECTION.md).

**Unit level.** `uji_pagar_otomasi.py` tests each gate in both directions: one case that must refuse and one that must allow, so a gate that always allows (or always refuses) cannot pass. `uji_agen_soc.py` includes the "no device code" assertion. `tests/test_setelan_terbaca.py` fails when a setting is documented or written but never read by code. A CI helper, `ci_klasifikasi.py`, sorts tests into tiers by running each twice with the network blocked.

**Real fault injection.** One script per remediator breaks something real and watches the loop repair it:

| Script | Fault | Why this target |
|---|---|---|
| `injeksi_r1.py` / `injeksi_r1_otomatis.py` | stop router R1 through the controller; the second variant is hands-off and checks the evidence row `diminta_oleh='poller_pemulih_gns3'` | exercises the GNS3 remediator |
| `injeksi_layanan.py` | stop `smbd` on the file server using a separate admin account (the restricted remediator account cannot stop services, by design) | server chosen so no notification subscriber receives mail; `auditd` was avoided because stopping it loses audit records |
| `injeksi_interface.py` | declare `FastEthernet1/1` on R1 should be up | verified before use to have no cable and zero impact; the fault is a *declared intent*, which is how real drift appears |
| `injeksi_terjadwal.py` | scheduled chaos, GNS3 nodes only | off by default; refuses to run when the error budget is exhausted |

**Reported results (from the lab notes; the test suite was not re-run when writing this document):**

- R1 stopped with automation live: DOWN event at 00:12:34, gate allow at 00:13:36 with verification true, UP at 00:13:52. About 78 s end to end: 62 s to detect and decide, 16 s to act and verify.
- The first hands-off run failed (wrong controller URL and credentials in the remediator). The circuit breaker opened after 3 failures, as designed. After the fix the run passed.
- Changing the verification ping to `COUNT=3, TIMEOUT=2` cut false "still down" verdicts from about 20% to 0 of 25 trials.
- Real injection found four defects that mocked tests had passed.

## 14. Lessons learned

1. **Act on debounced state, not raw probes.** Raw pings made a slow emulated router look dead; the remediator must read the same debounced events a human would trust.
2. **Mocked tests miss integration.** The defects real injection found (the controller URL and credentials among them) lived in the seams between components.
3. **A migration must also sweep paths stored in the database.** Moving files left rows pointing at old locations.
4. **Compiled jar versus source on the VM.** The running Java artifact can lag the source. `cek_sinkron_nsmapp.py` compares them before a test counts as evidence.
5. **UTC versus local clock.** Working-hours and freeze-window comparisons need one explicit clock.
6. **Automation can attack its own host.** Auto-ban once could block NSM. The cure is a protected-address list *and* a gate at the point of execution.
7. **Untested safety nets are not safety nets.** The tunnel's recovery path needed its own test before it deserved trust.
8. **A setting nobody reads is a trap.** `PAGAR_JAM_KERJA` is documented but unread (the real keys are `PAGAR_JAM_MULAI` / `PAGAR_JAM_SELESAI`); `tests/test_setelan_terbaca.py` now guards the class.
9. **Test refusal and allowance in pairs.** A gate with only an "allows" test can be silently open.
10. **Let dry-run questions be free.** The `simulasi` parameter keeps "what would happen?" from consuming the rate limit.
11. **A breaker that locks itself needs a human way to reopen.** That is why `reset_pemutus` requires a reason.
12. **Enforce policy on the managed host too.** Wrapper scripts reject what the application layer should already have refused.
13. **NULL is not success.** Tri-state verification stops "no evidence yet" from being read as "worked".
14. **An exit code is not proof.** Verification checks the observable outcome (service answering, config in a fresh snapshot), not the return value of the command that was sent.
15. **Keep `.env` and `config.py` in agreement.** Defaults that differ between the two produced a surprise when a switch appeared "on" in one and "off" in the other.

## 15. Open questions

- **Per-key risk at the config remediator.** `sot/katalog.py` carries a per-key risk table (`RISIKO_KUNCI`), but the config remediator's gate uses the coarse remediator class. Should risky keys (for example `hostname`, which is classified human-only yet supported) need stricter evidence?
- **Linux write path.** Privilege model for the revert scheduler: a narrow sudoers rule for one wrapper, or a separate write account with its own key? Neither is built.
- **Agent trust.** How long should the agent stay in `usul` mode, and what agreement rate against human decisions would justify `jalan`? No threshold is set.
- **Agent runbooks.** Service and interface runbooks have no executor in the agent; add them, or keep the agent propose-only for those?
- **Breaker reset endpoint.** Should resetting the circuit breaker become an authenticated API call, or stay a deliberate console-only act?
- **Dead setting.** Remove `PAGAR_JAM_KERJA` or wire it up.
- **GNS3 tunnel fragility.** The remediator depends on a reverse SSH tunnel that the lab host can drop; a controller reachable by a safer path would simplify this.
- **Unsupported keys.** `domain`, `exec_timeout_menit`, `vty_izin` and `ssh_saja` stay manual. Is there a safe verification story for any of them?
- **Cisco-only drift.** Drift and the config remediator are Cisco IOS only; extending to Linux needs the snapshot to collect the relevant keys first. An earlier plan to add offline config analysis (Batfish) was dropped for resource reasons.

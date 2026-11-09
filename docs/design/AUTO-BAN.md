# Auto-ban: temporary, self-expiring blocks

NSM can turn "this address is scanning or breaking in" into a firewall rule, but only in a way that cannot lock NSM out of its own lab, cannot outlive its reason, and still cleans up if NSM itself dies. This document describes the decision logic, the execution chain for Linux hosts (ufw) and for the emulated Cisco router (ACL), the optional unattended mode, and what was proven in the lab.

All numbers and hosts are from the personal lab (see [TOPOLOGY.md](../TOPOLOGY.md)). UI labels are in Indonesian; English glosses are used here.

## Status

| Part | Status |
|---|---|
| Classification of denied attempts, breach detection, MAC/ARP spoofing detection | Implemented (`backend/report_service/firewall.py`) |
| Decision layer: allowlist, "automatic" vs "review" candidates | Implemented (`rencana_penjagaan`) |
| One-click ufw block, always temporary, expires on the server | Implemented (`penjaga_aksi.py`, `ubah_firewall.py`, `firewall/nsm-ubah-firewall`) |
| One-click router ACL block with self-removing EEM applet | Implemented, manual only (`ubah_acl_router.py`) |
| Unattended ufw blocking (`poll_auto_ban`) | Implemented, **off by default** (`AUTO_BAN_AKTIF`) |
| Expiry sweep and bookkeeping (`ban_aktif`, `poll_kedaluwarsa_ban`) | Implemented |
| Email to subscribers on every block | Implemented, best-effort |
| fail2ban for SSH brute force on each Linux VM | Configured by hand in the lab, **not in this repo**, independent of NSM |
| Unattended router ACL blocking | Deliberately not built |

## Context and problem

The Firewall page already reads three layers: ufw on the Linux VMs, an ACL on the emulated router that guards site B, and Windows Firewall on the NSM host. Reading is not protection. The obvious next step, "block whoever is attacking", has three classic failure modes for a security tool:

1. It blocks something it must never block: its own server, the directory, the database, the monitoring path.
2. It blocks permanently. Months later nobody knows why the rule exists and nobody dares remove it.
3. The block depends on the blocker staying alive.

A detection subtlety also shapes the design. Deny logs only contain what was blocked, so a successful break-in never appears there. The evidence of "got in" is an established connection to a sensitive port.

## Goals and non-goals

Goals: block only clear patterns automatically and send everything doubtful to a human; make every block temporary with the expiry living on the target (server timer, router applet), not in NSM; check the allowlist at the point of execution, not only in the UI; audit every attempt including refusals; make unattended blocking an explicit opt-in.

Non-goals: permanent bans (a person adds those by hand), reputation feeds, blocking by MAC (MAC is evidence, not a control), IPv6, packet capture, automatic router ACL writes.

## Design

### Detection and decision (no side effects)

| Function | What it decides |
|---|---|
| `penolakan_acl` | Groups denied attempts per source into `pengecekan` (NSM's own probes, ICMP, service replies), `diblokir` (real attempts the firewall refused) and `tembus` (the source holds a live connection) |
| `deteksi_pembobolan` | An ESTAB connection (from `ss -tin`, only the last 3 minutes) to a sensitive service port from an address that is not a registered device is a breach. Public ports 80/443/8080/8443 are excluded |
| `deteksi_spoofing` | Compares each registered device's baseline MAC (see [TRAFFIC-IDENTITY-FW.md](TRAFFIC-IDENTITY-FW.md)) with the local ARP table. Only IPs on NSM's own L2 segment are compared, to avoid false positives across routers |
| `daftar_dilindungi` | The never-ban allowlist: every registered device plus NSM's own addresses |
| `rencana_penjagaan` | Turns the above into candidates. It executes nothing |

Classification: a live connection (`tembus`), at least 5 distinct destinations (`memindai`, `AMBANG_PINDAI`) or at least 50 attempts (`gigih`, `AMBANG_GIGIH`) is `blokir-otomatis`. Anything else, such as an unknown host making a few normal connections (maybe a new server nobody registered), is `tinjau` (review) and only offers a button.

The freshness window matters: `flow_koneksi` accumulates snapshots, so without the 3-minute window a breach alarm never clears after the block. Limits stated on the page: `flow_koneksi` is a 60-second snapshot (it proves a connection existed, not that none did), and MACs only mean something inside one L2 segment and can be forged, so they raise the bar rather than build a wall.

### Execution chain (ufw)

```
UI "Block" button
  -> Spring POST /api/firewall/blokir        ADMIN role, CSRF, audit FIREWALL_BLOKIR
  -> FastAPI POST /firewall/blokir
  -> penjaga_aksi.blokir                     wide allowlist (all registered devices), checked HERE
  -> ubah_firewall.blokir                    forbidden list, permission checks, change log
  -> SSH: sudo /usr/local/sbin/nsm-ubah-firewall blokir <ip> <minutes>
  -> server wrapper                          its own forbidden list and limits, self-expiry timer
  -> ufw insert 1 deny from <ip>
```

`penjaga_aksi` does not write raw `ufw` rules (the monitoring account `nsmro` is not allowed to). It delegates to `ubah_firewall`, which gives temporary blocks, a reachability proof and an audit trail for free.

The order inside `ubah_firewall.blokir` must not be swapped:

1. Check permissions before any connection exists: device exists, is not paused, has credentials, platform's capability is `ufw`, the latest firewall snapshot shows ufw **active** (a rule written to a disabled firewall "succeeds" and blocks nothing), the address is valid IPv4, not forbidden, not the device itself, and the duration is 1 to 1440 minutes. A reason string is mandatory.
2. Send the command. The server installs its own expiry timer.
3. Prove the device still serves NSM, over a **new** SSH session. An already-open TCP session survives a rule that forbids new ones, so reusing it would always answer "still reachable", including right after NSM locked itself out.
4. If the proof fails, unblock immediately instead of waiting for the timer.

Outcomes recorded: `BERHASIL`, `DIBATALKAN` (proof failed, revert succeeded), `BERHASIL_TANPA_BUKTI` (rule is on the device but both the proof and the revert failed, usually a flaky SSH session; the server timer is the last net), `DITOLAK_NSM`, `DITOLAK_SERVER`. `penjaga_aksi` records `BERHASIL_TANPA_BUKTI` as an active ban, otherwise NSM would lose track of a rule that really exists.

The server wrapper (`firewall/nsm-ubah-firewall`, installed by `firewall/pasang-ubah-firewall.sh`) holds the policy because sudoers cannot express it ("not NSM's own address", "must expire", "never touch SSH rules", and one stray `*` in an argument pattern turns "may block one address" into "may write any rule"). It has no command to disable ufw, change defaults or delete allow rules. For `blokir` it validates the address against its own forbidden list, caps the duration at 24 h, stops any older timer for the same address (otherwise the first, shorter timer would silently end a longer block), inserts the rule at position 1 (ufw uses the first match, so a deny below an allow is never read), then installs a `systemd-run --on-active` timer **after** the rule exists and verifies it; if the timer is missing it deletes the rule and exits with an error. `buka` deletes matching rules in a loop, since repeated writes can leave several.

### Router ACL layer

`kirim_perintah.py` (the generic config push) was not reusable: its `reload in N` safety net cannot stack, so a second block would reset the first timer, and if it ever fires the whole router reboots and site B goes dark.

`ubah_acl_router.py` instead:

- inserts `deny ip host <ip> any log` at a free sequence number between 1 and 9, re-reading `show access-list` every time. The first real rule is at 10, `permit tcp any any established`, which a packet with a forged ACK flag can slip past. The block sits above it, closing that gap;
- installs an **EEM applet** (`event timer countdown`) on the router that removes that one ACL line and then deletes itself. It is the router-side equivalent of the server timer, so the block expires even if NSM is down;
- proves success twice: a new SSH session to the router, and a TCP connect from NSM to a legitimate host at the protected site (so the new rule did not close legitimate traffic). Failure triggers an immediate rollback of line and applet; the applet remains the last net;
- is limited to routers listed in `ROUTER_ACL` in `.env` (JSON, empty by default). A fresh install inherits no permission to write to any router;
- is offered in the UI only when a candidate's target sits at a location the router guards, as a second, outlined button.

The same IP can be banned on both layers at once, so `ban_aktif` rows are keyed on `(ip, device_id)`. Keyed on `ip` alone, the second layer would be treated as "already banned" and never installed. Which mechanism a device uses comes from its definition file (`kemampuan.firewall: ufw` or `acl`), not from a vendor name in code.

### Unattended mode (`poll_auto_ban`)

Runs every `AUTO_BAN_INTERVAL` seconds (default 60, minimum 30) and returns at once unless `AUTO_BAN_AKTIF` is `1`. The switch is re-read each round, so editing `.env` takes effect without a restart. It takes candidates classed `blokir-otomatis` with a known target device and calls `penjaga_aksi.blokir(..., oleh="auto")`:

- ufw only, never ACL. An ACL block closes the path for a whole location, not one device, so it stays a per-candidate human click. The "Block all (N)" button obeys the same rule;
- at most `AUTO_BAN_MAKS_PER_PUTARAN` blocks per round (default 5). A classification bug that flagged dozens of addresses would otherwise block them all before a human could react. Candidates not reached are retried next round;
- allowlist checked again at execution, idempotent per `(ip, device_id)`, one failing or refused candidate never aborts the round, and each block emails subscribers.

### Expiry and bookkeeping

`BAN_MENIT = 60` is the single source for both what is sent to the server and the `waktu_kedaluwarsa` NSM records. `poll_kedaluwarsa_ban` (every 60 s) lifts expired bans as an extra net and syncs `ban_aktif` with reality; it chooses ufw or ACL from the device platform. One unreachable device must not abort the loop for the others, so `unblock` catches every exception and returns a structured answer.

### Host-level layer (fail2ban, outside NSM)

NSM watches application and ACL logs. fail2ban on each Linux VM watches `sshd` logs and responds locally, so it keeps working if NSM is dead. It was installed by hand, because the monitoring account may only run the wrapper. All three VMs use the same jail, with `ignoreip` copied from the same allowlist:

```ini
[DEFAULT]
ignoreip = 127.0.0.1/8 ::1 <PROTECTED_ADDRESSES>
bantime  = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
```

## Safety and failure modes

| Risk | Control |
|---|---|
| Blocking own infrastructure | Allowlist in the decision layer and again at execution; `ubah_firewall` forbidden list from `.env` (`ALAMAT_NSM`, `ALAMAT_DILINDUNGI`); the wrapper keeps its own list on the server |
| Block cuts NSM off | Reachability proof over a new session, immediate revert |
| NSM dies | Timer on the server, applet on the router |
| Mass false positives | Kill-switch, per-round cap, doubtful cases only "review" |
| Spoofing a trusted host by IP | Allowlist binds IP and MAC; mismatch raises an impersonation warning |
| NSM reporting wrong state | `BERHASIL_TANPA_BUKTI` instead of a false "cancelled" |
| Writing to the wrong device | `ubah_acl_router` also asks `identitas.boleh_ditulisi` ([TRAFFIC-IDENTITY-FW.md](TRAFFIC-IDENTITY-FW.md)) |
| Unaudited changes | `firewall_perubahan` records every real attempt, refusals included (dry-run plans are not logged); Spring audit entries `FIREWALL_BLOKIR`, `FIREWALL_ACL_BLOKIR`, `FIREWALL_BUKA_BLOKIR`; the actor comes from the session, never from the request body |
| Forbidden lists drifting apart | They are duplicated on purpose (different machines), but the Python side now reads `.env`; a test compares them. At one point the lists had silently diverged while a comment claimed "identical" |

## Data model and interfaces

`ban_aktif`: `ip`, `device_id`, `alasan`, `pola` (`memindai`/`gigih`/`tembus`/`manual`), `oleh` (`auto` or an analyst), `waktu_ban`, `waktu_kedaluwarsa`, `waktu_buka`, `aktif`. Rows are deactivated rather than deleted, to keep "was banned" history. `firewall_perubahan` holds action, target, minutes, reason, actor, result and raw evidence.

| Endpoint | Purpose |
|---|---|
| `GET /firewall` | Three-layer state, `penjagaan`, `pembobolan`, `penolakan`, `ban_aktif` |
| `POST /firewall/blokir`, `/firewall/blokir-acl`, `/firewall/buka-blokir` | Block (ufw / ACL) and unblock; the Spring counterparts are `/api/firewall/*` |

Settings (`backend/.env`): `AUTO_BAN_AKTIF`, `AUTO_BAN_MAKS_PER_PUTARAN`, `AUTO_BAN_INTERVAL`, `ALAMAT_NSM`, `ALAMAT_DILINDUNGI`, `ROUTER_ACL`, `FIREWALL_ENABLED`, `FIREWALL_INTERVAL`.

## Testing in the lab

Unit tests never touch a device: they use a temporary SQLite DB, a fake executor (`_exec`) and fake ARP/log data. Relevant files in `backend/`: `uji_penjaga_aksi.py`, `uji_pembobolan.py`, `uji_spoofing.py`, `uji_penjagaan.py`, `uji_winfw_rotasi.py`, `uji_poll_auto_ban.py` (including a regression that a candidate with an ACL router is never auto-blocked on the ACL layer), `uji_ubah_acl_router.py` (against real `show access-list` output) and the Java `KonfigControllerFirewallTest`. `uji_ubah_firewall.py` is mostly about what must be **refused**; it touches devices, so `jalankan_semua_uji.py` skips it unless `--semua` is given.

```
python backend/jalankan_semua_uji.py          # safe tests only
python backend/jalankan_semua_uji.py --semua  # includes device-touching tests
```

A dry run is always available: `ubah_firewall.blokir(db, device_id, ip, 60, "test", "test", sungguhan=False)` returns the plan without connecting. `scripts/simulasi_serangan.py` generates controlled, rate-limited refused connection attempts from other lab machines (`--menit`, `--sekaligus`, `--hanya-a`, `--hanya-b`). An attacker Kali VM scanning the lab was used for the live proofs below.

Live proofs in the lab, each verified independently over SSH rather than trusting NSM's own record:

- ufw: block via the UI, rule at position 1, `nsm-buka-<ip>.timer` present; unblock via the UI removes both. Repeated several cycles, plus a self-expiry run where `ubah_firewall.blokir()` was called directly so NSM never called unblock and the server timer lifted it.
- ACL: block via the UI inserted line 1 above sequence 10, applet registered with the right countdown, a legitimate TCP connect to the protected site still worked; unblock removed line and applet. Also repeated, plus a direct self-expiry run.
- Unattended: with `AUTO_BAN_AKTIF=1` the first round blocked an existing scanner candidate (14 destinations) with no click, recorded as `oleh=auto`.

## Lessons learned

- Repeating live proofs found what one success could not. Three real bugs surfaced on the ACL path: a catch-all exception missing in `block_acl`; a "cancelled" status that lied when the rule was in fact still on the router (hence `BERHASIL_TANPA_BUKTI`); and an applet that deleted its ACL line but not itself, because action 5 used `end` (leaves config mode entirely) and the following config-mode command failed silently, since EEM does not check CLI exit codes. The fix is `exit` then a final `end`.
- Do not reuse a safety net built for another purpose. `reload in N` suited rare supervised changes, not frequent temporary blocks.
- Prove a mechanism in isolation first. The EEM countdown was tested with a throwaway applet (10 seconds, syslog only) before any feature code existed.
- Treat `None` as "given and wrong", not "not given". An early `blokir(ip=None)` skipped every permission gate and opened an SSH connection. A sentinel (`TIDAK_DIBERI`) fixed it, and `menit=True` is rejected because `isinstance(True, int)` is true.
- One failing device must not abort a loop over many (the original unblock bug cancelled all other expirations in the same round).
- The running poller may be older than the code on disk. Restart before live tests; blocks survive a restart because the rule lives on the target and the row in MySQL.
- Dynamips routers sometimes refuse new SSH sessions under back-to-back tests. Retry with pauses rather than one long session.

## Open questions

- Should unattended ACL blocking ever exist, perhaps for a narrow pattern with a shorter duration?
- Server-side forbidden lists must be edited per server when NSM is installed on another network; a push-based sync would remove that chore.
- fail2ban setup is manual. A script in the repo would make it reproducible.

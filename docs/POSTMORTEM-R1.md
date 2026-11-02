# Post-mortem: R1 halted, Site B lost, LDAP logins refused

Incident date: 14 August 2026 (lab time). Scope: the author's personal lab
(VirtualBox + GNS3); nothing here involves any production network. See the
[README](../README.md).

**Status: resolved.** R1 was restarted at 08:35 and every path was verified.
The root cause (a safety mechanism unsuitable for emulated routers) was fixed on
19 August and re-verified on 21 August. This document is blameless: it records
what the system did and what was learned.

## Summary

An operator could not log in to NSM. The password was correct. The chain of
causes:

```
login refused
  - LDAP 192.168.20.101 unreachable
      - all of Site B unreachable (R2, SW-B, .101)
          - R1 (192.168.56.60) HALTED          <- root cause
              - `reload in N` armed by NSM's own command-sending path
```

NSM's configuration-send path installs `reload in N` as a dead-man's switch
before sending a command. On a physical router `reload` means reboot and return
with the saved configuration. On GNS3/Dynamips it means **the emulated machine
stops and stays stopped** until someone presses Start. A failed send left the
reload armed, and R1 halted. Its absence took out R2, SW-B and the LDAP host
behind it, and because NSM logs in through LDAP, nobody could sign in.

## Impact

- All of Site B unreachable for the duration (about an hour that morning).
- No directory user could log in to NSM or the lab E-Canteen app.
- NSM has a separate break-glass login path that opens only for accounts
  explicitly flagged for it and only when LDAP is unreachable. The operator used
  an ordinary directory account, so the refusal was correct behavior
  (*"Identity server (LDAP) cannot be reached, and this account is not an
  emergency account"*). Widening that bypass was considered and rejected: it would
  add a hole without adding capability.

## Timeline and evidence

### NSM monitors every hop, so the break could be located

```
SW-A (192.168.56.61)   UP    17 ms    <- GNS3 VM alive
R1   (192.168.56.60)   DOWN           <- only door to the WAN
R2   (192.168.20.1)    DOWN
SW-B (192.168.20.2)    DOWN
LDAP (192.168.20.101)  DOWN
```

The workstation's route (`192.168.20.0/24 via 192.168.56.60`) was correct; it
simply pointed at a dead next hop.

### Failures fell on the same second

| Time | R1 | R2 | LDAP | SW-A |
|---|---|---|---|---|
| 07:09:36 | DOWN | DOWN | DOWN | DOWN |
| 07:10:29 | UP | UP | UP | UP |
| 07:15:31 | DOWN | DOWN | DOWN | DOWN |
| **07:39:51** | **DOWN** | **DOWN** | **DOWN** | still UP |

Devices do not fail on the same second by coincidence: this is one failure with
several symptoms. SW-A staying UP at 07:39:51 showed the GNS3 VM itself was
healthy.

### R1's console kept its last seconds

```
%SYS-5-CONFIG_I: Configured from console by nsm on vty0 (192.168.56.1)
*** --- SHUTDOWN in 0:01:00 ---
*** --- SHUTDOWN NOW ---
%SYS-5-RELOAD: Reload requested by nsm on vty0 (192.168.56.1). Reason: Reload Command.
ROM: reload requested...
!!! WARNING - VM is not running, will be unresponsive (status=1) !!!
```

User `nsm` from `192.168.56.1` is NSM's own write path.

### GNS3 misreports node state

```
R1    gns3=started  -> console: HALTED (VM is not running)
ISP   gns3=started  -> console: ISP#    alive
R2    gns3=started  -> console: R2#      alive
SW-B  gns3=started  -> console: SW-B#    alive
```

`status: started` in the GNS3 API only means the Dynamips process runs, not that
the router inside is alive. The console is the honest source.

### Audit log: what was actually sent

Targets: 5 = R1, 8 = SW-A.

```
13 Aug 14:32     R1    iface_keterangan  OK + write memory
13 Aug 17:04     SW-A  iface_mati        (not delivered)
14 Aug 07:38     SW-A  iface_hidup       (not delivered)
14 Aug 07:39     SW-A  iface_mati        (not delivered)
14 Aug 07:39:51  R1/R2/SW-B/LDAP go down
14 Aug 07:40     R1    iface_mati        (not delivered)
```

(`iface_mati` is flagged `memutus`, meaning it can cut access, so it takes a
different path through the sender.)

### Recovery, 08:35

R1 answered **10 seconds** after start (not the expected 1 to 2 minutes). Proven
in layers: ping to `.61`, `.60`, `192.168.20.1`, `.2`, `.101` all replied; LDAP
`:389` and SSH `:22` open; NSM showed R1, R2, SW-B and LDAP `UP`.

### A second, unrelated problem: login still refused after recovery

The operator still could not sign in at 08:53. Layer by layer the login path was
healthy: LDAP reachable, the user's entry found, bind accepted, group membership
mapped to the admin role, a real `POST /login` answered `302 -> /`, and login by
email also worked. The audit log settled it: the last failed attempt was 08:21,
and after that **no `LOGIN_FAILED` rows at all**, even though the operator
reported failures. The failure never reached the password checker.

Cause: the Spring application was restarted at 08:18. A login tab opened before
that carried a CSRF token from the old instance, so every submit was rejected at
the CSRF layer and redirected back to the login page before the password was
examined (`/login?kedaluwarsa`, with no audit trail). A stale token gave that
redirect; a fresh token gave `302 /`. **Fix: hard-refresh the login page.**

## Root cause

`backend/kirim_perintah.py` arms `reload in N` as a safety net **before**
sending. If sending fails midway it deliberately leaves the reload armed:

```python
except Exception as e:
    # Connection closed, BUT `reload in` is deliberately left armed.
    # If failure happens after the safety net is installed, the only safe state
    # is to let the device bring itself back.
```

That reasoning is right for physical routers and wrong for GNS3. The lesson about
Dynamips `reload` had been written down on 8 August, but the code was not
changed, so it struck again. A lesson recorded but not implemented is only a note.

Why sends kept failing for `iface_mati`/`iface_hidup` (while `iface_keterangan`
succeeded) was left as an open investigation at the time; the audit log stored
only "not delivered", not the reason.

## Fix

For any device with `gns3_node` set, `kirim_perintah.py` **never** installs
`reload in N`. The safety net is instead recovery through the GNS3 controller
API (`connectors/gns3_pemulihan.pulihkan()`: `stop`, then `start`), triggered only
when the device is proven unresponsive after a command that can cut access, and
called directly rather than over the network that just failed. The cancel
("revert") action for GNS3 nodes also never sends a CLI `reload`.

Accepted trade-off: if NSM itself dies exactly between sending the command and
triggering the recovery, nothing on the device brings it back, unlike a physical
router. The worst case is now "no automatic recovery", not "node dead forever".

Further hardening that came out of this incident: dependency attribution
(effects are not alarmed as causes), automated GNS3 node recovery behind six
safety gates, and the deliberate re-test in
[FAULT-INJECTION](FAULT-INJECTION.md). The improved diagnosis is described in
[BLAST-RADIUS](design/BLAST-RADIUS.md), and an LDAP replica at Site A
(so one router cannot lock everyone out) is proposed in
[LDAP-REPLICA](design/LDAP-REPLICA.md).

## Manual recovery if it recurs

A halted GNS3 node can be restarted through the API with no GUI. The repo has a
script that checks each node's console and restarts those that are dead despite
`started` (switches first, then routers; `--paksa` restarts all):

```bash
cd C:\Users\<user>\NSM\gns3
python hidupkan_ulang_node.py
```

Check liveness through the **console**, not the GNS3 status. Connect to the node's
console port on the GNS3 VM, send `\r\n` and read: `R1#` means alive, `VM is not
running` means halted. Read the port numbers from the API rather than memorizing
them.

## Follow-up: R1 stopped again, on purpose (22 August)

Ten days later R1 was stopped again, deliberately and with the operator's
permission, to prove automatic recovery: it was detected, recovered and the
recovery verified. The difference from the incident is the code path, not
caution:

| | 13 Aug (incident) | 22 Aug (deliberate) |
|---|---|---|
| Method | `reload in N` typed at the CLI | `POST /nodes/{id}/stop` to the GNS3 API |
| Touches configuration | yes | no |
| Equivalent to | scheduling the router's suicide | pulling the power |
| Reversible | no | yes, `POST .../start` |
| Result | R1 dead permanently | R1 back in about 40 s |

It also proved with numbers that one router failing takes R2, SW-B and LDAP with
it, and that two safeguards built for it work: `orkestrasi._saring_hulu()` held
back R2 and SW-B (of 3 raw candidates only R1 went forward; without it one root
cause would trigger three repair attempts guaranteed to fail, three escalation
emails and three open circuit breakers for healthy devices), and the diagnosis
panel named R1 as the single cause at Site A (it had not done so before a fix
made that same night).

One dangerous defect surfaced only because R1 was really stopped. After recovery
R1 answered with 300 to 700 ms latency (Dynamips is heavy after boot) and one
ping in a run of successes failed. The old recoverer judged up/down from the
latest `status_logs` row, so **one lost packet was enough for it to restart a
router that had just become healthy**, while NSM itself needs 5 consecutive
failures before calling a device down. The recoverer now reads the official
`device_events` verdict (service recoverer likewise).

## Lessons learned

1. **Implement the lesson, not just the note.** The Dynamips `reload` behavior was
   documented six days before it struck again.
2. **Do not trust a status list; ask the thing itself.** GNS3's `started` and the
   GNS3 panel were both wrong; only the console told the truth. The same applies to
   judging any process from a status field.
3. **A symptom is not a diagnosis.** "Password rejected" did not mean the password
   was checked. The discriminator is whether a `LOGIN_FAILED` row exists in the
   audit log; if not, the break is in front of the password checker (CSRF, session,
   IP filter).
4. **Read the record that holds the answer.** On 13 August the wrong device was
   suspected from a screenshot that happened to show SW-A, when the audit log, one
   query away, showed R1 had been hit. If a log stores the answer, read the log.
5. **Dependencies cluster.** Several devices failing within the same second is one
   failure. The dashboard showed four red devices and did not say three were red
   because of the fourth; that gap led to the dependency work.
6. **Safeguards must match the platform.** A dead-man's switch that is safe on
   hardware can be the failure on an emulator.
7. **Rehearse the failure.** Exercising the recovery for real, safely and on
   purpose, is the only way the lesson stays learned.

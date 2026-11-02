# Deliberate fault injection in the lab

How to switch off a real (emulated) device on purpose to prove NSM's automation
works end to end, what to check before doing it, and what must be restored
afterwards. Everything here runs in the author's personal lab (VirtualBox +
GNS3); see the [README](../README.md).

The script is `backend/injeksi_r1.py`. The incident that motivated it is in
[POSTMORTEM-R1](POSTMORTEM-R1.md).

## 1. Why this exists when hundreds of tests already do

The Stage 4 recoverer (GNS3 node restart) tests all use a fake `_panggil`;
none ever touches a GNS3 server, deliberately, since tests that touch real
devices must not run automatically. So one thing no test can prove is whether the
chain is connected end to end:

```
tests prove          : the LOGIC of each piece is right
injection proves     : the PIECES are actually connected
```

The difference is not theoretical. The first injection found four real defects
that 316 green tests had missed, two of them automation that would have
restarted a healthy device.

## 2. How to switch a node off, and what never to use

Stop the node through the GNS3 controller API:

```
POST /v2/projects/{project_id}/nodes/{node_id}/stop
```

This is equivalent to pulling the power. It does not touch configuration and is
fully reversible with `/start`.

> **Never use a configuration command to stop a test node.** In the 13 August
> incident, `reload in N` typed at a router CLI halted R1 permanently under
> GNS3/Dynamips. That is a different code path and must not be used here.

`connectors/gns3_pemulihan.pulihkan()` itself does `stop` and then `start`,
because `POST .../start` on a node the controller still believes is running does
nothing.

## 3. Check before switching anything off

### 3.1 Who will be emailed

Switching a device off triggers **real notifications by SMTP**, opt-in per device
in table `nsm_auth.notif_langganan` (`id`, `device_id`, `username`).

```sql
select l.id, l.device_id, l.username, u.email
from nsm_auth.notif_langganan l
join nsm_auth.users u on u.username = l.username;
```

A "Router A DOWN" email at 23:15 for an outage you caused yourself is a **false
alarm**, the thing this project tries to eliminate, and false alarms train people
to ignore the next real one. The script removes the affected subscriptions
(devices 4 and 5 in `injeksi_r1.py`) and re-inserts them with the same ids in a
`finally` block.

### 3.2 What else goes down

Read `device_link`; do not guess.

```sql
select * from device_link;
```

Lab topology at the time:

```
NSM (2) -> SW-A (8) -> R1 (5) -> ISP -> R2 (9) -> SW-B (10) -> LDAP (4)
                   \-> web server (6), SMB (11), MySQL (12)
```

Stopping **R1** also cuts R2, SW-B and LDAP: four devices from one action. The
SW-A branch (web, SMB, MySQL) stays up.

### 3.3 Start from a clean state

The node must be `started` in GNS3 **and** `UP` in NSM. Otherwise you cannot tell
whether the injection or an earlier fault caused what you see.

## 4. What is changed temporarily, and how it is restored

| Changed | Why | Restored by |
|---|---|---|
| Notification subscriptions of affected devices | avoid false alarms | re-`insert` with identical id, device_id, username |
| `PAGAR_DAFTAR_PUTIH` (empty to `gns3_restart`) | without it gate 2 refuses and the recoverer never runs | monkeypatch, not `.env` |
| Working hours (default 08 to 17, patched to 0 to 24) | injection ran at night | monkeypatch, not `.env` |
| `PEMULIH_GNS3_AKTIF` (0 to 1) | Stage 4 kill switch | monkeypatch, not `.env` |

All gate relaxations are monkeypatches **inside the script, never edits to
`.env`**. If the script dies midway, `.env` stays clean and automation stays off;
there is no way for it to leave "automation on and nobody knows". The `finally`
block also force-starts the node if it is still stopped, a last safety net that
worked: the first attempt failed midway and R1 was still restored with no manual
step.

## 5. What it proves

Order is deliberate: **the brake is proven before the engine.** The recorded
second run passed every check (25 passed, 0 failed; the script has since grown to
31 checks).

1. **Gate refuses, reason 1:** empty allow list, so refuse.
2. **Gate refuses, reason 2:** on the allow list but outside working hours, so
   still refuse.
3. **Fault injected:** R1 `started` to `stopped`.
4. **Real two-level detection:** raw ping starts failing after about **10 s**;
   the official `DOWN` row in `device_events` appears after about **40 s**. The
   gap proves the consecutive-failure threshold is really used (default
   `DOWN_THRESHOLD=5`; see [NETWORK-STATUS](design/NETWORK-STATUS.md)).
5. **Dependency attribution:** R1 is the root; R2, SW-B and LDAP are effects.
6. **Diagnosis panel:** R1 listed as a cause; LDAP, R2, SW-B among effects.
7. **Automation-storm filter:** of 3 raw candidates (R1, R2, SW-B) only R1 is
   passed on (`orkestrasi._saring_hulu`).
8. **All six gates pass:** the recoverer calls the API and R1 starts again.
9. **Phase-2 verification:** R1 reported `UP` after 40 s, and
   `status_verifikasi=True` is recorded in `pagar_tindakan`.

The six gates (`pagar_otomasi.py`, in order): risk class, allow list, freeze
window, working hours, circuit breaker, rate limit.

## 6. Two traps that cost time

### 6.1 MySQL REPEATABLE READ: the script read the past

The first attempt reported "R1 still alive" for **five full minutes** while the
on-screen topology map already showed it red. The poller and data were fine. MySQL's
default isolation is REPEATABLE READ: once a transaction reads, it keeps seeing
one snapshot even after other sessions commit. `session.expire_all()` does not
help; it only drops Python's object cache and asks the same snapshot again.

**Fix:** `db.commit()` before every read that must see another process's writes
(`segarkan()` in `injeksi_r1.py`). This applies to any monitoring script that
waits for the poller to write something.

### 6.2 Working-hours upper bound is exclusive

`(0, 23)` means 00:00 to 22:59, **not** all day; the test is
`start <= hour < end`. Use `(0, 24)` for all day. This exposed a real bug:
`PAGAR_JAM_SELESAI` was once validated to at most 23, so 23:00 to 23:59 could
not be covered by any setting. The upper bound is now 24 (values 0 to 23 keep
their meaning).

## 7. Standing rules

1. **Never run these in CI.** CI collects `uji_*.py`; `injeksi_*.py` never
   matches, and the one `uji_` script that cuts the network (`uji_penyangga.py`)
   is under `dikecualikan` in `backend/ci_manifest.json`.
2. **Always a `finally` that restores everything:** node, gate settings, and
   touched data.
3. **Silence outgoing notifications first.**
4. **Prove refusal before action.** Automation that can act but cannot hold back
   is more dangerous than none.
5. **Prove in pairs:** every "does not act when it should not" must be paired with
   "still acts when it should", or totally broken automation that never does
   anything also passes.
6. **Get the operator's permission** and state what else will go down.

## 8. Running it

From the project's `backend/` folder:

```bash
cd C:\Users\<user>\NSM\backend
venv\Scripts\python.exe -u injeksi_r1.py
```

Needs a reachable GNS3 controller, the lab running, the nsm-app poller running,
and access to the MySQL data server. About 3 to 5 minutes when it goes well;
wait limits are 3 min (ping fails), 5 min (DOWN verdict), 6 min (recovery). To
target another node, change `NODE` and `DEVICE_ID` at the top and **repeat all of
section 3 for that node**, especially the subscription list and knock-on
effects. Do not copy assumptions from R1.

## 9. Related scripts

| Script | What it does |
|---|---|
| `injeksi_r1_otomatis.py` | Stops R1 and then only watches. The nsm-app poller must recover it by itself; proof is the audit row `poller_pemulih_gns3` in `PagarTindakan.diminta_oleh`. Does not touch `.env`; powers R1 back on if nothing recovers it within 10 min. A recorded run recovered R1 in 78 s (62 s to detect and decide, 16 s to act and verify). |
| `injeksi_layanan.py` | Stops `smbd` on the file server to prove the service recoverer. Run **on nsm-app**. Needs `UJI_105_PASS` and refuses to run without it; the recoverer's own account can only restart services, so a separate admin path injects the fault. |
| `injeksi_interface.py` | Proves interface recovery using an interface with zero impact (unused `FastEthernet1/1` on R1): the fault is declaring an intent the snapshot does not match. |
| `injeksi_terjadwal.py` | Gate only. Refuses unless `INJEKSI_TERJADWAL_AKTIF=1`, only considers GNS3 nodes, and skips devices whose error budget is low. Reports who would be eligible and writes `injeksi-terakhir.json`; it never injects anything itself. Without `--sungguhan` it only reports. |

## 10. Lessons

- Tests that fake the network cannot find wrong addresses or missing credentials.
  The first nsm-app injection showed the recoverer pointed at `127.0.0.1` (a
  machine with no GNS3) and looked for credentials in a Windows-only file;
  `GNS3_URL`, `GNS3_USER` and `GNS3_PASSWORD` in `.env` exist because of that.
  Setting `GNS3_URL` also requires the controller to listen on a reachable
  address, which is the lab owner's decision.
- Dangerous behavior is about the **method**, not the act: stopping R1 via the API
  is safe, scheduling a reload from its CLI was not.

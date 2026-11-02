# Design: LDAP replica at Site A

**Status: proposal. Not implemented.** Written 19 August 2026 for discussion
before building. Everything runs in the author's personal lab; see the
[README](../../README.md).

## Context and problem

The only LDAP directory is on `192.168.20.101` at Site B. NSM and the lab
E-Canteen app both authenticate against it, and the path to it runs through R1,
the ISP and R2. The [R1 post-mortem](../POSTMORTEM-R1.md) showed the consequence:
one router failing at Site A left nobody able to log in to either application.

The dependency also became lopsided once the MySQL replica existed
([MYSQL](../MYSQL.md)): data is copied Site A to Site B, but identity is not
copied the other way. Site B can now survive on its own longer than Site A. This
design closes the remaining half.

Facts about the current server, taken from the host on 19 August:

| Fact | Value |
|---|---|
| Software | `slapd` (OpenLDAP) 2.6.10, Ubuntu 24.04 |
| Backend / config style | `back_mdb`, `cn=config` (dynamic OLC) |
| Base DN | `dc=bsp,dc=id` (lab label) |
| Entries | 16 |
| Modules loaded | `back_mdb` only; **`syncprov` is not loaded** |
| TLS | StartTLS on 389 with the lab CA ([LDAP-TLS](../LDAP-TLS.md)) |

With 16 entries, initial sync takes seconds and an idle `slapd` is small, so the
replica VM can be light.

## Goals and non-goals

Goals:

- Keep NSM and E-Canteen logins working when the Site A to Site B path is down.
- Change the existing directory as little as possible.
- Make replica health visible from day one (see Safety).

Non-goals:

- Writing to the directory from Site A. Applications only ever read LDAP.
- Multi-master replication, or write chaining to the provider.

## Design

### Options considered

| Option | Verdict |
|---|---|
| **Read-only `syncrepl` consumer** | **Chosen.** One writer, many readers, which matches how `.101` is already used. |
| Multi-master | Rejected. No need to write from Site A; it adds write-conflict risk for a problem this lab does not have. |
| Chaining of writes to the provider | Not needed. Nothing attempts writes; stated so it reads as a decision, not an omission. |

### Provider (`.101`): minimal change

1. Load the `syncprov` module through `cn=config`.
2. Add the `syncprov` overlay to the existing database. No new database, no schema
   change, the 16 entries are untouched.
3. Optionally `accesslog` for `refreshAndPersist`. For a directory this small,
   periodic `refreshOnly` (for example every 60 s) is probably enough and simpler
   to run.
4. Allow 389 (StartTLS) from the consumer's address on the host firewall, the
   same pattern used for the other lab hosts.

### Consumer (new VM at Site A)

- A **separate VM**, not a tenant of an existing server, keeping "one role, one
  machine".
- Ubuntu 24.04 with the **same** `slapd` 2.6.x; mismatched provider and consumer
  versions are a common source of replication bugs.
- `olcSyncrepl` consumer pointing at `.101`, authenticating as a dedicated
  **read-only** replication account, not `cn=admin`, so a leaked consumer
  credential does not mean write access.
- TLS required, using the existing lab CA.
- An address in the Site A range, for example `192.168.56.106` (not final).

### Clients: failover, not replacement

`sssd` accepts a comma-separated list in a **single** `ldap_uri` line. Repeating
the key keeps only the last line:

```
ldap_uri = ldap://192.168.56.106, ldap://192.168.20.101
```

Local consumer first, `.101` second: the local server is faster and does not
depend on R1, the ISP or R2, the components that failed in the incident.

## Safety and failure modes

The MySQL replica's open item was that it initially had no monitoring, and an
unmonitored replica gives unfounded confidence. This design must not repeat that.
Before it counts as done (not merely installed), it includes:

1. NSM watches **replication lag** (provider `contextCSN` versus consumer), using
   the same approach as the MySQL replica check: ask over the existing SSH path
   with a read-only account, rather than opening new network paths.
2. The Health page shows the LDAP replica state explicitly, not just "consumer
   answers ping". Open port is not proof of a live service, a trap found repeatedly
   in this project.
3. A notification if replication stops for more than N minutes, so "a replica
   exists" cannot quietly become "the replica is stale and nobody knows".

Other risks: a mistake mid-way could disrupt the logins currently in use, so build
it away from any demo; a wrong `ldap_uri` ordering in `sssd` would make logins slower
instead of safer.

## Data model and interfaces

No new application data. Interfaces are: `syncrepl` between `.101` and the
consumer (389 with StartTLS), the replication bind account, and the client
`ldap_uri` list.

## Testing in the lab

Not yet run. Planned checks: initial sync entry count equals provider; a change on
the provider appears on the consumer within the refresh interval; stopping the
Site A to Site B path leaves `sssd` logins working; consumer stopped leaves
logins working through `.101`; the replica Health row turns red when the consumer
stops.

## Lessons carried over

- Copying data without monitoring the copy is worse than no copy.
- Replicate with the same software version on both ends.

## Open questions

1. **Refresh mode:** `refreshOnly` (simple, up to 60 s delay) versus
   `refreshAndPersist` (real time, needs `accesslog`).
2. Final IP of the new VM.
3. Name of the replication account and where its credential is stored, following
   the single-source-of-truth rule for credentials.
4. **Application logins are not covered yet.** Reading the code, NSM's Spring
   login (`nsm.ldap.url`) and the Python directory reader (`LDAP_URL`) each take
   a single URL, and the proposal only changes `sssd`. Since the motivating
   failure was web login, those need a failover design too.
5. When to build it: it touches VM, provider, consumer, `sssd` on three hosts and
   monitoring.

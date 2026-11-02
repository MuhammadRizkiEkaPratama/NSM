# Configuration compliance: judging stored configs, not just storing them

**Status:** implemented. 23 rules (14 Cisco IOS, 9 Linux) are scored against every stored configuration snapshot, and results are kept per snapshot and shown on their own page. **Not built:** a finding timeline (appeared / resolved), alerts for new high-severity findings, any automatic fix.

Numbers come from the author's lab (emulated Cisco routers, Ubuntu VMs). Code identifiers are Indonesian: `kepatuhan` = compliance, `temuan` = finding, `aturan` = rule, `potret` = snapshot, `keparahan` = severity.

## Context and problem

NSM stored device configs for weeks before anything read them. A config backup answers "what changed?", never "is what is there now safe?". Reading one early snapshot of the lab's first router (R1) by hand fired 10 of 14 checks: the monitoring account had `privilege 15`, there was no `logging` and no NTP, console and AUX had `exec-timeout 0 0`, no `enable secret`, MD5 (`secret 5`) hashes, no vty restriction, no password-encryption, no banner.

Two of those shaped the design:

- **`username nsm privilege 15`.** NSM's SSH connector refuses write commands, but that guard sits on the NSM side, not the device. Whoever holds the NSM database holds credentials that can write anything to the router. It also means the write path in [CLOSED-LOOP-AUTOMATION.md](CLOSED-LOOP-AUTOMATION.md) rests on one promise ("only catalogued commands are sent").
- **No logging.** A change made outside NSM leaves only the next snapshot's diff: what changed, never who or when.

## Goals and non-goals

Goals: score each snapshot against explainable rules; show severity, the evidence line and the fix; keep results per snapshot; touch no device.

Non-goals: rules that need a secret's raw value (secrets are masked before storage and stay masked); routing/ACL rules (they need topology intent); a full CIS/STIG score (copying items nobody understands yields findings nobody can explain); a single percentage; automatic fixing.

## Design

**Rules are data.** `connectors/kepatuhan.py` holds `KATALOG`, a list of dicts (`id`, `judul`, `platform`, `keparahan`, `cara` = `harus_ada` or `tidak_boleh_ada`, `dalam` = block to search, `pola`, optional `pola_alternatif`, `kenapa`, `perbaikan`). A rule written as a function cannot be listed or explained; as data, the page ships the whole catalog and "which rules does NSM check?" has an answer on screen.

**Block-aware.** Cisco IOS marks ownership by indentation, so `pecah_blok()` splits a config into blocks; "no telnet inside `line vty`" differs from "no telnet anywhere". Linux snapshots are assembled by `connectors/konfig_linux.py` from several sources under `### name` headers, handled by the same splitter.

**Three outcomes.** `PATUH` (applies and met), `TEMUAN` (applies, not met), `TIDAK_BERLAKU` (wrong platform, or the inspected block does not exist). Without the third, a Linux host looks "100% compliant" against Cisco rules never run on it, which is true arithmetic and still a lie.

**Scored when the snapshot is stored.** The config poller (`nsm/pemantau/konfig.py`, every 15 minutes) stores a snapshot only when its fingerprint changes, and in the same transaction writes one `konfig_temuan` row per rule. Configs change a few times a month; a periodic scoring job would repeat identical work thousands of times.

**Counts per severity, never one percentage.** `ringkas()` returns e.g. `2 high, 6 medium, 2 low`. "78% compliant" adds up things that are not comparable (open telnet versus a missing banner).

**Masking is not loosened.** Without raw values NSM can still judge whether a line exists, the hash *type* (`secret 5` vs `secret 9`) and the privilege on an account. What cannot be judged is reported as not judgeable, not guessed.

Catalog: Cisco `vty_telnet`, `ssh_v2`, `snmp_community`, `akun_privilege15`, `logging` (high); `http_server`, `ntp`, `exec_timeout_nol`, `aux_aktif`, `enable_secret`, `hash_lemah`, `vty_dibatasi` (medium); `password_encryption`, `banner` (low). Linux rules were added after the original design (which excluded Linux): monitoring account in `lxd`/`docker` or `sudo`, root SSH login, password and empty-password SSH, firewall off, extra UID 0, pending security updates, X11 forwarding.

## Safety and failure modes

- **Zero device contact.** Scoring reads snapshot text already in the database.
- **Unscored is not clean.** The API returns `dinilai: false` for a snapshot with no result rows rather than "0 findings". Snapshot and results are written in one transaction, so an unscored snapshot should not exist. When a failed buffer flush once orphaned findings, `perbaiki_temuan_yatim.py` re-paired them under strict conditions (same device, earlier snapshot, under 5 s apart).
- **Rules follow how devices really behave.** IOS writes `no ip http server` only when the server is off, so `http_server` requires that line (a rule looking for `ip http server` would pass untouched devices). `vty_dibatasi` accepts `access-class` or `login block-for`. `linux_ssh_sandi` requires `PasswordAuthentication no` because OpenSSH accepts passwords by default. A missing block (no `line aux`) is not applicable, not a finding.
- **Linux rules read files, not effective config.** `sshd -T` is more accurate but needs root, and a rule needing more privilege than the monitoring account has would force that account to be raised. `sshd_config.d/` includes are read because they override the main file.
- **Fix text must not hurt.** The first `sudo` fix was `gpasswd -d <account> sudo`; on both lab VMs that account was the only admin, so it would lock the owner out. The fix is now "create a separate read-only account and point NSM at it".

## Data model and interfaces

```sql
CREATE TABLE konfig_temuan (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER REFERENCES konfig_snapshots(id),
    device_id INTEGER REFERENCES devices(id),
    aturan_id VARCHAR, hasil VARCHAR, keparahan VARCHAR,
    baris_bukti VARCHAR, nomor_baris INTEGER, dinilai DATETIME
);
CREATE UNIQUE INDEX ux_temuan_snapshot_aturan ON konfig_temuan (snapshot_id, aturan_id);
```

`baris_bukti` (the triggering line, already masked) is stored so a finding can be checked without hunting through the snapshot. The unique index makes re-scoring overwrite instead of duplicate.

| Piece | How |
|---|---|
| Create table | [manual] `python migrate_kepatuhan.py` in `backend/`, poller and API stopped |
| Backfill / re-score | [script] `python nilai_kepatuhan.py` (dry run), `--jalankan`, `--jalankan --ulang-semua` |
| API | `GET /konfig/kepatuhan[?device_id=]`: latest snapshot per device, counts, full catalog (registered before `/konfig/{snapshot_id}` or "kepatuhan" is parsed as an id) |
| Frontend | page `/admin/konfig/kepatuhan` via `NetmonApiClient.getKonfigKepatuhan()` |

## Testing in the lab

`backend/uji_kepatuhan.py` scores two hand-written configs per platform, one violating every rule and one satisfying every rule; each rule must answer `TEMUAN` then `PATUH` (23 rules x 2), so a rule that always says "compliant" cannot pass. It also covers the block splitter, wrong-platform and missing-block cases, the alternative pattern, and requires a sample pair for every platform in the catalog. An early bug in the test itself: Linux rules were tested against the Cisco sample and counted as wrong; each rule is now tested on its own platform.

## Lessons learned

- Check what the monitoring account can read before writing a rule (`cek_hak_akun.py` audits its rights, read-only). The Linux twin of the router finding was the account in group `lxd` (root without a password) on both VMs; `set_akun_pemantau.py` repoints NSM to a dedicated account created on the VM ([manual]).
- Missing NTP got a concrete cause: router clocks start from zero, so ACL-deny log stamps matched no other machine's logs (see [BLAST-RADIUS.md](BLAST-RADIUS.md)).
- Hand-made samples hold only shapes someone thought of; see the recorded-output approach in [DEVICE-AGNOSTIC.md](DEVICE-AGNOSTIC.md).

## Open questions

- The design allowed a registered exception list for privileged accounts; the code has none, so every `privilege 15` account is a finding. Lowering the monitoring account on R1 would break the write path unless that path gets its own account.
- Alerting on a new high-severity finding should reuse the existing notification path, not add a second one; not wired yet.
- A resolved-finding timeline is derivable from the per-snapshot rows but has no view.
- Windows and other platforms need a snapshot format before they can have rules.

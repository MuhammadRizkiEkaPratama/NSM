# Incremental backup: one rolling parent file, verified by restore

**Status:** implemented (`backend/backup_incremental.py`). Per the project's notes and code comments, since 24 August 2026 it is the primary backup method and the daily full backup task was switched off; `backup_nsm.py` remains as the full-dump implementation that the incremental run reuses. Day-to-day usage is in [BACKUP.md](../BACKUP.md).

Numbers come from the author's lab database. Code identifiers are Indonesian: `induk` = parent, `mingguan` = weekly, `bulanan` = monthly, `posisi` = position.

## Context and problem

A question from the field supervisor: why does NSM back up everything from scratch every day instead of only what changed? The honest answer was that it had never been designed. The original scheme was a rotation of full dumps: every night, all tables dumped again, 14 copies kept, in two places (a plain zip locally, an AES-256-GCM encrypted copy in a cloud-synced folder). Ping rows from weeks ago, which never change, were re-dumped 14 times in two locations.

## Goals and non-goals

Goals: back up only new rows of the big append-only tables; keep one file that is merged forward; keep a few restore points; prove a restore works before trusting the scheme.

Non-goals: MySQL binary-log backup; purging binary logs (the same binlog feeds replication to the lab replica, so `PURGE BINARY LOGS` would break it); removing the old full backups before the new parent restores correctly.

## Measurement first

Three approaches were measured against the lab's own data (one day's window, compressed, since compressed size is what costs disk), using `ukur_incremental.py`:

| Approach | Raw | Compressed | vs full |
|---|---|---|---|
| Full dump (previous scheme) | 150.3 MB | 23.1 MB | 1.0x |
| Incremental by row window | 23.4 MB | 3.3 MB | 0.14x |
| Incremental via binlog | 151.7 MB | 112.6 MB | 4.9x |

The binlog route, the one most tutorials recommend, was almost five times worse here: `binlog_format=ROW` with full row images is binary and barely compresses (1.3:1), while the repetitive text SQL dump compresses 6.5:1. Generic advice cannot be copied without measuring; "incremental is always cheaper" is false for some workloads. This data is nearly all append-only (pings, bandwidth samples, TCP flows, access logs), so "what is new since last time" is a simple range query. Saving: about 86 % per day.

## Design

- **Incremental tables** (`TABEL_INCREMENTAL`): `status_logs`, `bandwidth_samples`, `service_checks`, `akses_web`, `flow_koneksi`, `penolakan_acl`. Each run dumps only new rows and appends them to that table's accumulated file inside the parent.
- **Everything else is dumped in full each run**, discovered from `information_schema` at run time so a new table is backed up by default. Devices, services, users, events and snapshots can be updated, not just appended, and a range-based incremental would miss those changes silently. Account/auth data also stays a full dump.
- **Parent file.** `incremental/induk.zip` is rewritten each run (merge old extract + new delta, write `induk.zip.baru`, then atomic `os.replace`, so a crash mid-zip leaves the old parent intact). `induk.meta.json` stores the last position per table.
- **Restore points.** One weekly copy (refreshed when the last is 7+ days old) and one monthly copy (30+ days) of the parent, each overwritten in place. That gives three distinct points in time: latest, up to about a week old, up to about a month old. (The first estimate of "a dozen" restore points was too generous for this layout.) Without them a deletion noticed five days late is unrecoverable, because the parent only holds the latest state.
- **Second location.** Only `induk.zip` is copied there, encrypted (`sandi_backup`, AES-256-GCM with scrypt key derivation) when a passphrase is configured; otherwise the copy is made unencrypted and the run records a warning.
- **After the run:** a `manifest.log` line is written and the backup status is reported to NSM (`lapor_backup.py`) so the Backup page does not go stale.

## Safety and failure modes

- **Position by `id`, not by time, with a closed window `(a, b]`.** Two real bugs were found by the first restore test against real data:
  1. *Duplicates.* The cut point was taken before the dump but the dump had no upper bound, so rows arriving during the dump were captured twice (`ERROR 1062` on restore). Each run now bounds both ends; adjacent windows have no gap and no overlap.
  2. *Rows lost forever (silent).* A timestamp column was the first marker. For tables whose time is the event time in a source log (web log, `ss -tin`, router ACL log), a row can be committed minutes after its own timestamp when the poller catches up on a big log. The next run filters `time > old cut point` and never sees it. Auto-increment `id` is fixed at commit and never reused, so a row that commits late simply falls into the next window.
- **Lost `induk.meta.json`** makes the next run start over and duplicate rows; the Backup page flags it.
- **Unprivileged backup account.** The auth-database dump runs with `terbatas=True`, because `mysqldump` otherwise issues `SHOW EVENTS`, which needs a privilege the backup account must not have. When this flag was missing on the incremental path, the auth database silently dropped out of the backup (the server had no scheduled events anyway). Granting the privilege would also "fix" it and is the wrong fix.
- **Scheduler caveat.** The incremental task uses an interactive logon, so it runs only when the lab laptop is logged in at its scheduled time. A skipped night is safe: the next run catches up because it works by `id`.
- **Never delete the old full backups first.** An untested backup is a hope, not a copy.

## Testing in the lab

- `uji_backup_incremental.py`: merge logic with synthetic data and no MySQL (bootstrap, append on later runs, full tables replaced rather than stacked, chain correct after repeated merges, atomic replace survives a failure mid-write).
- `uji_pulih_incremental.py`: restores the real `induk.zip` into a scratch database with the real `mysql` client and compares per-table row counts with the live database, bounded at the same positions. It refuses to run if the scratch name equals the live one. After the two fixes all six tables matched exactly (for example `status_logs` 1,239,387 restored of 1,239,387). Once the verifier itself misled: `mysql.exe` sometimes returned success with empty output and a `-1` sentinel was counted as a huge row loss. It now retries and reports a measurement failure as such.
- `uji_pulih_backup.py` covers the full-dump path.

## Lessons learned

- A size that looks plausible would never have revealed either bug; only a row-count comparison against the live database did.
- Fixing a flag in one caller does not fix the other caller of the same function (the `terbatas` case).
- When a new method replaces an old one, the surrounding views must follow: the Backup page needed to read the nested `incremental/` folder, and `manifest.log` had to be written by the new path, or the history table froze on the old method without any error.
- A stale history is more misleading than an empty one.

## Open questions

- Restore tests currently run from the laptop against the laptop's own backups; a test from a second machine is not set up.
- The scheduler task could run without an interactive login, which needs storing the OS account password in Task Scheduler ([manual]).
- Retention beyond three points (a fuller GFS scheme) if the lab data ever matters more.

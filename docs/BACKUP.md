# Backup and Restore

NSM backs up its databases on a schedule, copies the result to a second
location (encrypted), and proves the backups can be restored. This guide covers
setting it up, running it, restoring from it, and the checks that keep it honest.

> All hosts, paths and numbers here are from the author's personal lab
> (see the disclaimer in the [README](../README.md)). Backups run from the
> Windows host (`LAB-PC`) with Task Scheduler. Script output is in Indonesian;
> a glossary is in [Reading the output](#reading-the-output).

Step markers: `[manual]` = you run it on your machine, `[script]` = a repo script
does it.

## Two methods

| Method | Script | Result | Status |
|---|---|---|---|
| Full | `backend/backup_nsm.py` | a new dated zip `nsm-backup-YYYYMMDD_HHMMSS.zip` every run | original method, kept as a safety net |
| Incremental | `backend/backup_incremental.py` | one rolling `incremental/induk.zip` plus weekly/monthly copies | primary method since 24 Aug 2026 |

Lab schedule (from the Backup page text in `backup_status.py`): full 02:00,
incremental 03:00, restore verification Sundays 04:00. Nothing in the repo
registers these tasks; you create them in Task Scheduler (below).

## What is backed up

Contents of a full-backup zip:

| File | Source | Present when |
|---|---|---|
| `nsm.sql` | MySQL database `nsm` (devices, ping history, incidents, bandwidth, ...) | NSM runs on MySQL (`NSM_DB_HOST` set) |
| `nsm.db` | SQLite file `backend/nsm.db` | NSM runs on SQLite only (`NSM_DB_HOST` empty) |
| `nsm_auth.sql` | the Spring Boot database (accounts, audit log, blocked IPs, ...) | always |
| `audit_logs.csv` | `audit_logs` table, UTF-8 with BOM so Excel opens it | always |

Why both a `.sql` dump and a CSV: the dump restores a database; the CSV lets a
human read the audit trail without installing MySQL.

MySQL credentials are read from the application's existing configuration, so
they are not entered a second time (one source of truth avoids a silent
mismatch that breaks backups while the app still works).

## Design choices

- **SQLite is copied with SQLite's online backup API**, then checked with
  `PRAGMA integrity_check`. A plain file copy while the poller writes can yield
  a truncated copy that looks fine.
- **The MySQL password never appears on a command line.** A temporary
  `--defaults-extra-file` is written and deleted right after the dump.
- **Partial failure does not cancel the run.** If `mysqldump` is missing the rest
  still completes and the manifest says `SEBAGIAN` (partial).
- **Least privilege.** The dump account is not granted extra rights. Instead the
  script avoids requesting what the account lacks: `--single-transaction`,
  `--set-gtid-purged=OFF`, `--skip-masking-policies`, `--no-tablespaces`, and
  `--skip-routines --skip-events` for restricted dumps.
- **Empty or tiny dumps are rejected.** A dump under 1 KB, or a failed dump, is
  deleted rather than zipped (an empty file named like a dump looks complete
  until someone restores it).
- **Completeness guard.** After the dump, `periksa_dump.py` streams the file and
  compares its `CREATE TABLE` statements with the live table list. Missing
  tables are named in the manifest and the run is marked `SEBAGIAN`. If the live
  list cannot be read, the script says "not checked" rather than "nothing
  missing".
- **Second-location honesty.** `periksa_lokasi_kedua()` warns when the second
  folder is on the same drive as the first, or its path says OneDrive but
  OneDrive is not installed. It never fails the backup, only refuses to call it a
  second copy.

## Setup

### 1. Choose locations [manual]

In `backend\.env` (template: `backend/.env.contoh`):

```
BACKUP_DIR=C:\Users\<user>\NSM\backup
BACKUP_DIR2=C:\Users\<user>\OneDrive\NSM-backup
BACKUP_KEEP=14
```

- `BACKUP_DIR`: primary folder, created if missing. Default: `<project>/backup`.
- `BACKUP_DIR2`: second copy. Leave empty to disable. Use another physical disk
  or a folder that a sync client really uploads.
- `BACKUP_KEEP`: how many full backups to keep (default 14); older ones are deleted
  in both locations (`.zip` and `.zip.enc`).

A backup on the same disk as its data is not a backup.

### 2. Encrypt the second copy [manual]

Set a long passphrase in the Spring configuration
(`frontend/src/main/resources/application.properties`, template
`application.properties.contoh`):

```
nsm.backup-passphrase=<BACKUP_PASSPHRASE>
```

It lives there, not in `.env`, and that file is not inside the zip, so the
passphrase is never inside the file it locks. With it set, the second copy is
`<name>.zip.enc`: AES-256-GCM, key derived with scrypt (N=2^15, r=8, p=1), random
salt and nonce per file, header authenticated (a changed byte fails to open
instead of producing garbage). Without a passphrase the copy is made in plain
form, the manifest records "second copy not encrypted", and the run is
`SEBAGIAN`.

Store the passphrase **outside this machine** (password manager or paper). If the
disk dies with the only copy of the passphrase, every encrypted backup is
unrecoverable.

Open an encrypted copy:

```
python buka_backup.py <file.zip.enc>
python buka_backup.py <file.zip.enc> --tanya     # ask for the passphrase (use on another machine)
```

### 3. Run once by hand [manual]

```
cd C:\Users\<user>\NSM\backend
venv\Scripts\activate
python backup_nsm.py
python backup_incremental.py
```

If it prints `mysqldump tidak ditemukan`, add the tool paths to `.env`
(adjust the version):

```
MYSQLDUMP_PATH=C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe
MYSQL_PATH=C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe
```

The scripts search `MYSQLDUMP_PATH`/`MYSQL_PATH`, then `PATH`, then
`C:\Program Files\MySQL`. They look for `mysqldump.exe`/`mysql.exe`, so as
written they are Windows-only. Do not schedule anything before a manual run
succeeds.

### 4. Register in Task Scheduler [manual]

Create tasks with **Create Task...** (not Basic Task):

| Task name | Time | Arguments |
|---|---|---|
| `NSM Backup Harian` | daily 02:00 | `backup_nsm.py` |
| `NSM Backup Incremental` | daily 03:00 | `backup_incremental.py` |
| (weekly check) | Sundays 04:00 | `verifikasi_pulih.py` |

Settings common to all:

- **General:** *Run whether user is logged on or not*; *Run with highest privileges*.
- **Actions:** program `C:\Users\<user>\NSM\backend\venv\Scripts\python.exe`,
  *Start in* `C:\Users\<user>\NSM\backend`. **"Start in" is mandatory**:
  without it the script runs from another folder and fails every night unnoticed.
- **Conditions:** untick *both* "Start the task only if the computer is on AC
  power" **and** "Stop if the computer switches to battery power" (the second
  stays ticked when you clear the first; Windows then kills a running backup and
  reports `0x800710E0`). Optionally tick *Wake the computer to run this task*.
- **Settings:** tick *Run task as soon as possible after a scheduled start is
  missed*. Without it a missed 02:00 is lost forever, `manifest.log` stays empty
  for days, and the task still looks `Ready` with a sane Next Run.

The Backup page's schedule panel queries a task named exactly `NSM Backup
Harian` (`NAMA_TUGAS` in `backup_status.py`) and flags it if it is missing. When
you move to incremental, **disable** the full task
(`Disable-ScheduledTask -TaskName "NSM Backup Harian"`, Administrator PowerShell)
instead of deleting it.

### 5. Verify the task settings, not just one run [manual]

Right-click the task, **Run**, then:

```
type C:\Users\<user>\NSM\backup\manifest.log
```

A task can look healthy and still be misconfigured. Check the settings
(normal PowerShell):

```
$t = Get-ScheduledTask -TaskName "NSM Backup Harian"; $t | Get-ScheduledTaskInfo | Select-Object LastRunTime, LastTaskResult, NextRunTime; $t.Settings | Select-Object StartWhenAvailable, StopIfGoingOnBatteries, DisallowStartIfOnBatteries
```

Expected: `StartWhenAvailable` True, `StopIfGoingOnBatteries` False,
`DisallowStartIfOnBatteries` False, `LastTaskResult` 0. To fix (Administrator
PowerShell; a `RunLevel: Highest` task rejects changes otherwise):

```
$t = Get-ScheduledTask -TaskName "NSM Backup Harian"; $s = $t.Settings; $s.StartWhenAvailable = $true; $s.StopIfGoingOnBatteries = $false; Set-ScheduledTask -TaskName "NSM Backup Harian" -Settings $s
```

## Reading the output

Each run appends a line to `manifest.log` in `BACKUP_DIR` (both scripts write it):

```
2026-07-27 16:59:29  SUKSES    nsm-backup-20260727_165929.zip     1.1 dtk  tanpa kendala
```

| Word | Meaning |
|---|---|
| `SUKSES` | success, everything present |
| `SEBAGIAN` | partial: something skipped or flagged, zip still produced |
| `GAGAL` | nothing produced |
| `dtk` | seconds |
| `tanpa kendala` | no problems |
| `[LEWAT]` | step skipped (tool missing) |
| `[BOLONG]` | dump is missing live tables |

Open `manifest.log` weekly, or better, use the Backup page (`/admin/backup`),
which combines the manifest, the Task Scheduler state and the second folder. A
backup the page marks stale is older than 26 hours.

## Incremental backup

`backup_incremental.py` requires MySQL mode.

- `incremental/induk.zip` ("parent") is **overwritten** each run, replaced
  atomically (written to `.baru`, then renamed), so a crash leaves the old one
  intact.
- Large append-only tables (`status_logs`, `bandwidth_samples`,
  `service_checks`, `akses_web`, `flow_koneksi`, `penolakan_acl`) dump only rows
  in the window `id > last AND id <= new` and append them to the accumulated
  file in the parent. It uses `id`, never a timestamp column: event-time columns
  can be committed late and rows would be skipped forever.
- Every other table is dumped in full each run (they can be updated, so id-based
  increments would miss changes). The list comes from `information_schema`, so
  new tables are included by default.
- Accounts/audit (`nsm_auth.sql`, `audit_logs.csv`) are full each run.
- `incremental/induk.meta.json` stores the last id per table. **If it is lost,
  the next run starts over and duplicates rows**; the Backup page flags this.
- `incremental/mingguan/induk-mingguan.zip` (refreshed at ≥ 7 days) and
  `incremental/bulanan/induk-bulanan.zip` (≥ 30 days) give extra restore
  points; the parent alone is only the latest state.
- The second location gets `incremental/induk.zip.enc` (or a plain `.zip` plus a
  warning).
- At the end it calls `lapor_backup.py` so the Backup page on the `nsm-app` VM
  has a fresh report.

The first run is a full "bootstrap". It was proven by restoring the real parent
into a scratch database and matching row counts per table before the full backup
was retired (24 checks, 0 failures in the lab).

## Restoring

> Run restore drills; a backup never restored is a hope, not a backup. The first
> drill in this lab, after 14 backups, found they did not restore (GTID issue
> below).

1. If the file ends in `.enc`, open it with `buka_backup.py` (above).
2. Unzip.
3. **SQLite (`nsm.db`)**: stop the poller and uvicorn, replace `backend\nsm.db`,
   start them again.
4. **MySQL dumps** (`nsm.sql`, `nsm_auth.sql`): they contain `CREATE DATABASE`,
   so no pre-creation is needed, but **they overwrite the live database of that
   name**:

   ```
   mysql -u <admin-user> -p < nsm_auth.sql
   ```

5. **Incremental parent**: the zip holds `_lain_full.sql` (all non-incremental
   tables with schema), one `<table>.sql` per incremental table,
   `nsm_auth.sql` and `audit_logs.csv`. Run `_lain_full.sql` first, then the
   incremental files, into the target database (this is exactly what
   `uji_pulih_incremental.py` does).

**GTID error on old dumps.** A dump made without `--set-gtid-purged=OFF` contains
`SET @@GLOBAL.GTID_PURGED=...` and fails when restored to the same server:
`ERROR 3546 ... must not overlap with @@GLOBAL.GTID_EXECUTED`. Current scripts
pass the flag. For an older dump, strip the line:

```
findstr /v /c:"SET @@GLOBAL.GTID_PURGED" nsm_auth.sql > nsm_auth_clean.sql
mysql -u <admin-user> -p < nsm_auth_clean.sql
```

## Proving restores work

```
python uji_pulih_backup.py          # latest full zip
python uji_pulih_incremental.py     # incremental parent
python verifikasi_pulih.py          # runs both, writes verifikasi-pulih-terakhir.json
```

`uji_pulih_backup.py` checks the zip opens, expected files are present, the
second copy exists, is the same backup and really starts with the encrypted-file
header, `PRAGMA integrity_check` (SQLite mode), and then **executes** the MySQL
dumps into a scratch database `<NSM_DB_NAME>_ujipulih`, comparing row counts with
the live database (short-lived token tables are explicitly exempted by name). The
scratch database is always dropped afterwards. Guards:

- Backtick-quoted database names are rewritten to the scratch name; the script
  refuses to run if any live name remains, so it cannot overwrite live data.
- The backup account needs rights on the scratch database name.
- A lock (`nsm-kunci-pemulihan.lock` in the temp folder) stops two restore tests
  running at once; they share one scratch database.
- Row counts are retried 3 times; a measurement failure is reported as such
  ("GAGAL PENGUKURAN"), never as a row difference.

`uji_pulih_incremental.py` compares per table against the live database
**bounded by the saved id position**, because the live DB keeps growing.

`verifikasi_pulih.py` postpones itself (recording why) when free host RAM is
below 1536 MB; a restore test once starved the host and froze the `nsm-app` VM.

After adding a table:

```
venv\Scripts\python.exe migrate_xxx.py
venv\Scripts\python.exe backup_nsm.py
venv\Scripts\python.exe uji_pulih_backup.py
```

The last step is the one that proves the new table restores.

## Backup page and `nsm-app`

NSM's primary lab instance runs on the `nsm-app` VM (Ubuntu), but backups run on
the Windows host. The Backup page cannot inspect `C:\...` from Linux, so
`lapor_backup.py` (called at the end of `backup_incremental.py`, or run by hand
on the host) stores a metadata-only report (names, sizes, times, verification
results; never contents or passphrase) in the database. The page shows it and
marks it stale after 26 hours. The Task Scheduler panel uses `schtasks` and is
Windows-only.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Task ran, no zip | "Start in" empty |
| No 02:00 line in `manifest.log` though task is Ready | `StartWhenAvailable` False and the machine was off/asleep |
| Last Run Result `0x800710E0` | task killed by Windows; `StopIfGoingOnBatteries` still True |
| Second folder not growing | `BACKUP_DIR2` unset ("Lokasi kedua belum diatur") or sync client inactive |
| `mysqldump tidak ditemukan` | set `MYSQLDUMP_PATH` / `MYSQL_PATH` |
| MySQL dump authentication failure | database credentials in the app config changed |
| `[BOLONG]` in the log | a table was added after the dump list; re-run, check dump account rights |
| `SEBAGIAN` | read the last manifest column for what failed |
| Account database missing from a zip | dump account denied `EVENT`; keep `terbatas=True`, do not grant the right |
| Parent grows duplicates | `induk.meta.json` was deleted |

## Security

Backups contain everything in the databases, including stored device
credentials and password hashes. Never put the backup folder in Git (the
`.gitignore` excludes it), keep the cloud folder private, and encrypt any copy
that leaves the machine. Device credentials are stored unencrypted in the
database (see [SECURITY](../SECURITY.md)).

## Limitations

- In the lab the host has one physical disk and no signed-in cloud client, so the
  "second copy" is still on the same disk; the scripts say so on every run. Real
  protection needs a second disk or a working sync.
- Only the Windows host has scheduled backups. `nsm-app` has none of its own:
  Task Scheduler, `schtasks`, `.exe` tool names and `C:\` defaults are Windows.
  A Linux port needs a `systemd` timer or cron, a Linux-aware schedule panel, a
  decision on where backups live (not the same VM disk) and who owns the
  passphrase.
- MySQL replication to the second database VM is not a backup; a bad delete
  replicates in seconds.

## Lessons learned

- A fresh, plausible-looking backup can be useless (GTID line, missing tables,
  frozen `nsm.db` after the move to MySQL, empty `nsm_auth`). Verify by
  restoring.
- Do not widen account rights to silence a dump error; stop requesting what does
  not exist.
- A verifier that reports data loss when its own measuring tool hiccups gets
  ignored. Separate "could not measure" from "differs".
- Alarms that are always red or always green stop being read; keep status
  accurate per mode (SQLite vs MySQL, full vs incremental).

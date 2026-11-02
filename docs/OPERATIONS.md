# Operations Runbook

How to run, check, deploy and troubleshoot NSM on the **`nsm-app` VM (the "primary lab instance")**.

> **Lab project.** NSM runs entirely in a personal lab (VirtualBox + GNS3). "Primary instance" means the `nsm-app` VM in that lab, not a company production system. All counts and timings are lab numbers.

This file covers the *software*. For the machines (VMs, GNS3, start order) read [LAB-SETUP.md](LAB-SETUP.md) first: starting NSM on a half-alive lab produces pages full of wrong numbers, which is harder to diagnose than a page that will not open.

---

## 1. What runs where

| Unit | Process | Port | Notes |
|---|---|---|---|
| `nsm-poller` | `poller.py` (APScheduler: ping, services, SNMP/SSH, correlation, notifications, ...) | UDP `1514` syslog, UDP `1162` SNMP trap (only if enabled) | Writes to MySQL; falls back to local SQLite buffer |
| `nsm-api` | `uvicorn main:app` (FastAPI, all business logic) | TCP `8000`, **127.0.0.1 only** | No authentication by design; never bind it to a network |
| `nsm-frontend` | Spring Boot jar (Thymeleaf "blind viewer") | TCP `8080` | Talks to the API only through `NetmonApiClient` |

- Host: `192.168.56.156`, user `nsmapp`, code under `/home/nsmapp/NSM` (`backend/`, `frontend/`).
- Web UI: `http://192.168.56.156:8080`. Database: MySQL on `192.168.56.104` (`nsm`, and `nsm_auth` for accounts and audit).
- The units are `enable`d, so NSM starts by itself when the VM boots; no one needs to be logged in on the host laptop. The unit files are not in the repo; the notes here describe what the scripts expect (unit names, `WorkingDirectory` set to `backend/`, jar path `/home/nsmapp/NSM/frontend/target/frontend-0.0.1-SNAPSHOT.jar`).
- `ufw` allows `22/tcp`, `8080/tcp`, and UDP `1514`/`1162`. The receivers use ports above 1024 on purpose: the process that parses unauthenticated network input should not run as root.

---

## 2. Start, stop, restart

```bash
ssh nsmapp@192.168.56.156
sudo systemctl status nsm-poller nsm-api nsm-frontend
sudo systemctl restart nsm-poller nsm-api nsm-frontend     # restart everything
sudo systemctl restart nsm-poller nsm-api                  # backend only
```

`systemd` restarts a crashed process (`Restart=on-failure`, per the lab notes; verify with `systemctl cat`). Manual intervention is rarely needed.

**Restart all three after any change.** Python does not re-read files after start, and a wrong guess about which process loads which module produces no error: the old process keeps running old code while looking healthy. A connector bug once ran for ten hours that way. A few seconds of missing data is cheaper; the availability maths excludes time when the poller was down (`jeda.py`).

Which process loads what (to understand why something "did not change"):

| Changed | Poller | API | Frontend jar |
|---|:-:|:-:|:-:|
| `poller.py`, `models.py`, `config.py` | yes | yes | no |
| `connectors/*` | yes | yes (`ssh`, `konfig`, `perintah` only) | no |
| `main.py`, `nsm/`, `report_service/` | no | yes | no |
| `diagnosa.py`, `jeda.py`, `database.py`, `rollup.py` | yes | yes | no |
| `notifikasi.py`, `identitas.py` | yes | no | no |
| `*.java`, `templates/`, `static/` | no | no | rebuild jar + restart |
| `.env` switches read at call time | see section 5 | | |
| new `pip` package | yes | yes | no |

HTML and JS live inside the jar (Spring copies `src/main/resources` at build), so editing a file on the VM changes nothing; rebuild. After a UI change, hard-refresh the browser (Ctrl+Shift+R): CSS/JS are cached aggressively and a half-old page looks broken.

### Local development mode

`restart_nsm.ps1` (Windows) starts the three processes locally for development; it is **not** how the primary instance runs. `-Status` only checks, `-TanpaJava` skips Spring. It sets the truststore variable for you. Manually, from `backend/`: `python -u poller.py`, `python -m uvicorn main:app --port 8000`, then in `frontend/`: `mvnw spring-boot:run` with `JAVA_TOOL_OPTIONS` set (section 7). Use `-u` for the poller; without it stdout is buffered when detached and logs look empty while the poller works.

---

## 3. Health checks

Prove answers, not process existence.

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/devices      # 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/login        # 200
ss -ulnp | grep -E '1514|1162'                                              # receivers, if enabled
cd /home/nsmapp/NSM/backend && ./venv/bin/python cek_segar.py               # seconds since last poller row
```

- `cek_segar.py` prints one number: age in seconds of the newest `status_logs` row (`-1` = no rows; exit code 2 = database unreachable). Under about 60 is healthy. A hung poller looks identical to a healthy one in a process list, so judge it by its newest row.
- `GET /kesehatan` (API) and the **`/admin/kesehatan`** page (UI, role ADMIN) summarise each poller job (still writing?), database, backups, restore test, MySQL and SMTP reachability. **Open this before guessing.** It stays reachable even when the API is down so it can say so.
- After a restart `systemctl is-active` is not proof: it answers `active` for a process that never restarted. Compare `systemctl show <unit> -p ActiveEnterTimestamp --value` before and after.
- `curl -s http://127.0.0.1:8000/syslog/ringkas` shows the syslog stream; `/baseline`, `/pola-log`, `/prakiraan`, `/agen-soc` show insight data.
- Lab-wide reachability: `python uji_terjangkau.py` (see LAB-SETUP section 7).

Pages (UI labels are Indonesian): `/insiden` and `/insiden/{id}` (incidents, timeline, MTTR), `/wawasan` (behaviour baselines, log patterns, forecasts), `/agen` (kill-switch state and SOC-agent proposals), `/syslog`, `/report`, `/services`, `/admin/tenant` (ADMIN). All are read-only.

- `/agen` is empty while `AGEN_SOC_AKTIF=0`; that is correct, and the page says so.
- `/wawasan` needs the poller; baselines and log patterns refresh every 300 s, so it is empty for the first minutes after a poller restart.
- A yellow banner "NSM has only heard syslog for N hours, shorter than the 24 h window" on `/wawasan` is not an error: while NSM's own syslog history is shorter than the window every pattern counts as new. It clears itself; do not filter the list to hide it.

---

## 4. Logs

```bash
sudo journalctl -u nsm-poller -n 100 --no-pager
sudo journalctl -u nsm-api -f
sudo journalctl -u nsm-frontend -n 100 --no-pager
```

If poller output seems empty although it is working, the unit may be running Python without `-u` (buffered stdout). Trust the data (`cek_segar.py`, `/admin/kesehatan`) over the screen. Local development logs go to `%TEMP%\nsm-layanan\`.

Useful lines: `poll_all skipped: maximum number of running instances reached` (a round overran its interval; see the "ping round density" card on `/admin/kesehatan` and the WAL size on the database card); `[ping borongan gagal, kembali ke satu per satu]` (batch ICMP failed, fell back to one-by-one: data is right, only slower; investigate if frequent).

---

## 5. Configuration (`.env`)

`backend/.env` is untracked; `backend/.env.contoh` is the template with notes. `frontend/src/main/resources/application.properties` is likewise untracked (template: `application.properties.contoh`).

- The file path is anchored to `config.py`, so scripts run from any directory read the same file.
- Values are cached by file fingerprint (mtime + size), so edits are picked up on the next read **without restart**. Things fixed at process start still need a restart: scheduler intervals, which jobs are registered, and the syslog/trap listeners. When in doubt, restart the poller and API.
- `.env` is never deployed by `kirim_ke_nsmapp.py`: it differs deliberately per machine.
- Keep real values out of git; use the `<PLACEHOLDER>` pattern from `.env.contoh`.

Database selection: set `NSM_DB_HOST`, `NSM_DB_PORT`, `NSM_DB_NAME`, `NSM_DB_USER`, `NSM_DB_PASS`. **Empty `NSM_DB_HOST` falls back to local SQLite** with no code change. If MySQL is unreachable the poller writes to `penyangga.db` (same schema) and catches up later; `devices` and `services` are mirrored into it every successful round so the poller can keep working.

### Switches (all conservative by default)

Code defaults when a key is absent:

| Key | Default | Meaning |
|---|---|---|
| `SYSLOG_AKTIF`, `SYSLOG_PORT` | `0`, `1514` | UDP syslog receiver |
| `SNMPTRAP_AKTIF`, `SNMPTRAP_PORT`, `SNMPTRAP_COMMUNITY` | `0`, `1162`, `public` | SNMP trap receiver; community is a coarse filter, not authentication |
| `KORELASI_AKTIF` | `1` | Incident correlation (read-only) |
| `NOTIF_PER_INSIDEN` | `0` | One email per incident instead of per event |
| `NOTIF_INSIDEN_PULIH` | `1` | One closing email when an incident closes |
| `AGEN_SOC_AKTIF` | `0` | SOC agent runs at all |
| `AGEN_SOC_MODE` | `usul` | `usul` = log proposals only; `jalan` = proposals go to the gate. Unknown values fall back to `usul` |
| `AGEN_SOC_NARASI` | `0` | May call an external LLM API to narrate incidents (sends device names/IPs/sequences outside the lab); needs an API key |
| `AGEN_SOC_INTERVAL` | `120` | Seconds between agent rounds |
| `AUTO_BAN_AKTIF` | `0` | Automatic IP blocking |
| `PEMULIH_GNS3_AKTIF`, `PEMULIH_LAYANAN_AKTIF`, `PEMULIH_INTERFACE_AKTIF`, `PEMULIH_KONFIG_AKTIF` | `0` | The four recoverers, each with its own switch |
| `OTOMASI_PENUH_LAYANAN` / `_INTERFACE` / `_KONFIG` | `0` | Extra "when proven" permission per recoverer |
| `PAGAR_DAFTAR_PUTIH` | empty | Allowlist of automatic action kinds |
| `PAGAR_JAM_MULAI`, `PAGAR_JAM_SELESAI` | `8`, `17` | Working-hours window for automatic actions (`0` and `24` for all day) |
| `PAGAR_JENDELA_BEKU` | empty | Freeze windows, `start|end;start|end` ISO datetimes |
| `PAGAR_BATAS_DEVICE_PER_JAM`, `PAGAR_BATAS_GLOBAL_PER_JAM` | `3`, `10` | Rate limits |
| `BATAS_RESTART_LAYANAN_HARIAN` | `3` | Service restarts per day |
| `ALAMAT_NSM`, `ALAMAT_DILINDUNGI`, `ROUTER_ACL` | auto / empty / empty | Never-block addresses and router ACL paths |
| `GNS3_URL`, `GNS3_USER`, `GNS3_PASSWORD` | `http://127.0.0.1:3080`, - | GNS3 controller access for the GNS3 recoverer |

Note that `backend/.env.contoh` ships with `AUTO_BAN_AKTIF=1`; set it to `0` in a new install unless you have read [design/AUTO-BAN.md](design/AUTO-BAN.md). Also note `nyalakan_otomasi.py` writes a `PAGAR_JAM_KERJA` key, but `config.py` reads `PAGAR_JAM_MULAI`/`PAGAR_JAM_SELESAI`; use those. Design background: [design/CLOSED-LOOP-AUTOMATION.md](design/CLOSED-LOOP-AUTOMATION.md).

**Switching on the optional features, in order:**

1. `NOTIF_PER_INSIDEN=1` (four emails become one).
2. `AGEN_SOC_AKTIF=1` in `usul` mode; read `/agen` for a few weeks and compare with human decisions.
3. `AGEN_SOC_NARASI=1` once an API key is set and you accept data leaving the lab.
4. `AGEN_SOC_MODE=jalan` only after step 2 looked sensible. Proposals still pass the same gate (allowlist, freeze window, working hours, rate limit, circuit breaker, risk assessment).

Restart the poller after changing these (`poll_agen_soc` and `poll_notifikasi_insiden` return immediately while their switch is off).

### Syslog and SNMP trap senders

Point devices at the receivers (the poller must have them enabled and restarted):

```
logging host 192.168.56.156 transport udp port 1514
snmp-server host 192.168.56.156 version 2c <community> udp-port 1162
```

The four Cisco devices are configured and saved to startup-config. Check with `show startup-config | include logging host`. To (re)apply: `python pasang_logging_perangkat.py --terapkan --simpan` (undo: `--terapkan --cabut`, limit with `--hanya <name>`). `write memory` on old IOS can be slow enough that netmiko reports a `ReadTimeout` although the save succeeded; the script verifies `show startup-config` instead. Syslog and traps are unauthenticated UDP: evidence and triggers for checks, never a direct trigger for actions.

---

## 6. Deploying code

NSM runs from a **compiled jar built on the host**; `nsm-app` has no Maven or JDK. The `.java`/`.html`/`.js` files on the VM are copies the runtime does not use, so anyone reading them can draw wrong conclusions. There is no CI/CD to the VM.

From `backend/` on the host (credentials come from the untracked `.env`):

```powershell
cd frontend; .\mvnw.cmd package; cd ..\backend
python kirim_ke_nsmapp.py              # report only: shows what would be sent
python kirim_ke_nsmapp.py --jalankan   # do it
python cek_sinkron_nsmapp.py           # exit 0 = source on the VM equals source on the host
```

`kirim_ke_nsmapp.py` order, chosen so the riskiest step is last:

1. back up the running jar; 2. send changed backend files; 3. install `drain3` if missing and prove it by importing; 4. run additive, idempotent migrations (`migrate_pagar.py`, `migrate_pemulih.py`, `migrate_insiden.py`, `migrate_gejala_pulih_pada.py`, `migrate_notif_insiden.py`, `migrate_paket_c.py`, `migrate_tenant.py`, `migrate_backup_laporan.py`); 5. restart `nsm-poller` and `nsm-api` and verify `ActiveEnterTimestamp` changed; wait until `GET /devices` answers; 6. send the new jar; 7. restart `nsm-frontend` only if the jar changed, and roll back to the backed-up jar if it fails; 8. print the kill-switch state and run the sync check.

It never touches `.env`, `venv/`, `target/`, or database files. After deploying, prove it over HTTP (`:8000/devices`, `:8080/login` are 200), not just `is-active`. A `sudo` run over non-interactive SSH needs the password on stdin; a plain `sudo systemctl restart` fails silently with "a password is required" and the old code keeps running.

Retry the API check several times: uvicorn needs seconds to bind after systemd reports `active`, so one shot right after a restart can report a healthy API as down.

`pip` from `nsm-app` works over IPv4 only: the VM has no IPv6 route and `pypi.org` DNS may return only IPv6, so `curl https://pypi.org/simple/` fails and looks like "no internet". Use `curl -4`. Keep dependencies small: `nsm-app` has about 4 GB RAM; `river` and `scikit-learn` are deliberately not installed.

### Migrations

Idempotent and additive. `kirim_ke_nsmapp.py` runs them against MySQL while services are up. On a **SQLite** database stop the poller and API first (file locks). Older migrations (`migrate_add_platform.py`, `migrate_report_tables.py`, `migrate_bandwidth_table.py`, `migrate_snmp_columns.py`, `migrate_aktif_column.py`, `migrate_notifikasi.py`, `migrate_services.py`, `migrate_ssh_key.py`, `migrate_traffic.py`, `migrate_rollup_jam.py`, `migrate_kepatuhan.py`, `migrate_identitas.py`) apply to legacy `nsm.db`. `no such column: devices.xxx` means a migration has not run. The Java side uses `ddl-auto=update`, which only adds columns/tables.

---

## 7. Scheduled tasks on the host

Four tasks live in the host laptop's Task Scheduler (the backup tasks are created by hand; only `NSM CI` and the tunnel have commands in the repo):

| Task | Schedule | Does |
|---|---|---|
| NSM Backup Harian | 02:00 daily | Full backup, encryption, rotation (`backup_nsm.py`) |
| NSM Backup Incremental | 03:00 daily | Delta since the full backup (`backup_incremental.py`) |
| NSM Verifikasi Pemulihan | Sunday 04:00 | Proves backups restore into a scratch database (`verifikasi_pulih.py`) |
| NSM Terowongan GNS3 | every 10 min | Keeps the reverse SSH tunnel host to `nsm-app` for the GNS3 API |
| NSM CI | 07:00 daily | Runs the "pure" tests (`pasang_ci.ps1` installs it) |

Details: [BACKUP.md](BACKUP.md).

**Why the GNS3 tunnel.** NSM runs on `nsm-app`, but the GNS3 controller binds `127.0.0.1` on the host. Without a tunnel the GNS3 recoverer always fails: during a fault injection the poller detected R1 down, the gate allowed recovery three times, all three failed, and the circuit breaker opened. Binding GNS3 to `0.0.0.0` was rejected because GNS3's own docs rate remote-access security as low and the emulator consoles would be exposed. The task is normally **Running** continuously; that is correct (it runs `ssh -N` as a child and stays alive, because Task Scheduler kills the process tree when the main process ends; `ssh -f` does not survive). Check without changing anything:

```powershell
cd backend
venv\Scripts\python.exe terowongan_gns3.py --periksa     # HIDUP (HTTP 401) = healthy
```

`401` means the request reached the controller and it asked for authentication. If the tunnel cannot be opened the script deliberately turns `PEMULIH_GNS3_AKTIF` off on `nsm-app`: better a recoverer that is visibly off than one that is on and always failing. `atur_gns3_nsmapp.py` does the one-time setup (writes `GNS3_*` into `.env` after proving the controller is reachable from `nsm-app`). Recreate the task:

```
schtasks /Create /TN "NSM Terowongan GNS3" /TR "\"<path>\backend\venv\Scripts\pythonw.exe\" \"<path>\backend\terowongan_gns3.py\"" /SC MINUTE /MO 10 /F
```

### Frontend truststore

The jar must trust the lab CA, or LDAP StartTLS fails with `PKIX path building failed` and **every login shows "wrong username or password"**, because the login code treats a broken LDAP as closed. On `nsm-app` the unit sets it permanently. Build the truststore as in [LAB-SETUP.md](LAB-SETUP.md) section 8 (JDK `cacerts` copy plus the lab CA).

---

## 8. Database maintenance

Run from `backend/` with the venv. Each reports first and changes data only with a flag.

```bash
python bangun_rollup.py                  # which hours would be summarised
python bangun_rollup.py --jalankan       # summarise raw rows into status_rollup_jam
python pangkas_data.py                   # preview old rows to drop (raw data older than 35 days)
python pangkas_data.py --jalankan        # drop (add --vacuum to shrink a SQLite file)
python hapus_event_hantu.py [--hapus]    # events without failed-ping evidence
python cek_kesehatan.py                  # read-only data checks (SQLite nsm.db only; skipped if absent)
```

**Always summarise before pruning.** Raw `status_logs` are pruned at 35 days while long history lives in `status_rollup_jam`. Dropping rows that were never summarised destroys what you meant to keep. The pruner refuses to run if the summary lags, but remember the order. Data-changing maintenance should run with the poller and API stopped.

Other helpers: `set_layanan.py --daftar|--hapus N|--jeda N|--lanjut N` (tests before saving), `set_lokal.py`, `set_snmp.py`, `add_laptop_ssh.py --hapus`, `cek_hak_akun.py` (monitoring account rights on each device).

Do not delete `nsm.db-wal` / `nsm.db-shm` or `penyangga.db-*` while the app runs: WAL mode keeps readers from queueing behind the writer, and those files are part of it.

### Tests

```bash
python jalankan_ci.py --mode semua     # everything (some tests need the live lab and skip themselves)
python jalankan_ci.py --mode murni     # lab-free tests only
python uji_jalur_db.py                 # run this first: the DB opened is always backend's own
python -m pytest backend/tests
cd frontend && ./mvnw test             # needs MySQL for the context-loading test
```

Three test files change real devices and run only with `--semua`. If `uji_jalur_db.py` is red, do not trust the others: tests that read real data pass on an empty database. `uji_pulih_backup.py` restores into a scratch database `nsm_auth_ujipulih` and drops it; it refuses to run if the live database name would remain in the dump.

---

## 9. Troubleshooting

Start at `/admin/kesehatan`.

| Symptom | Likely cause |
|---|---|
| Dashboard/report empty, "cannot connect to backend" | `nsm-api` down |
| Device status never changes, "last check" frozen | `nsm-poller` down or hung (`cek_segar.py`) |
| Port 8080 will not open | `nsm-frontend` down |
| Login error or empty audit log | MySQL down or `nsm_auth` unreachable |
| Every login says "wrong username or password" | LDAP unreachable or the truststore is missing (see below) |
| Page opens but is empty, buttons dead | Browser console (F12): a Content-Security-Policy violation means an inline script slipped in; `ReferenceError` means wrong script order |
| UI unchanged after deploy | Jar not rebuilt/sent, or browser cache (Ctrl+Shift+R) |
| `ModuleNotFoundError` on start | `pip install -r requirements.txt drain3` |
| `database is locked` during migration | SQLite only: stop poller and API |
| `/admin/kesehatan`: SMTP unreachable | Port 587 to the mail host is blocked; alerts reach nobody meanwhile |
| LDAP VM "running" but its address is silent after an unclean power-off | VM stuck at the GRUB menu (LAB-SETUP section 6) |

**Expected behaviours that look like bugs:**

| You see | Why |
|---|---|
| Availability much lower than successful-ping percentage | Unmonitored time (poller down, device paused while DOWN) is excluded and shown as "... not monitored". If that note is missing while numbers look odd, the API was not restarted after `jeda.py` changed |
| Outage duration shorter than start-to-recovery span | Only observed outage time counts; the rest is in the small "not monitored" line |
| Device card green but a "<N> layanan mati" badge | Ping proves the machine is up; a service on it can be down |
| Service availability differs from its device | A service may be registered later, so its observation window is shorter |
| Audit log shows far fewer rows | `VIEW_*` browsing rows are hidden by default; a pill shows how many |
| Old audit rows say `DEVICE_NOTIFY`, new say `DEVICE_NOTIFY_TOGGLE`/`_SENT` | The name was split because two writers used it differently; old rows are unchanged |
| Device detail sections collapsed | Charts, traffic and file-access sections start closed; the choice is remembered in the browser |
| "No registered services" on a device card | The device has no `services` rows; add them with `set_layanan.py` |
| Services section shows an old state | The list is read when you click the icon; close and reopen |
| Evidence chain shows a red port that was never installed | Poller or API not restarted after `diagnosa.py` changed |

### Cannot log in because LDAP is down

The login page says the identity server (LDAP) cannot be reached, so the username cannot be checked. Believe it: the attempt is **not** counted as a wrong password and will not lock the account. Accounts that exist only in the directory cannot log in while it is down. A local break-glass administrator (`darurat` flag on the account) is accepted only when LDAP is unreachable, and every such login is recorded prominently in the audit log; while LDAP answers, local accounts are refused, including that one.

Diagnose read-only: `ping 192.168.20.101`; ping its neighbours `192.168.20.1`/`.2` (healthy segment?); VM state in VirtualBox; console screenshot (`VBoxManage controlvm nsm-ubuntu screenshotpng ...`). A past case: VM `running`, OS booted to the login prompt, neighbours reachable, yet no traffic at all, so **the OS was healthy and the interface had no address**. Inside the VM console:

```bash
ip -br addr
ip -br link
sudo netplan status     # does netplan name an interface that still exists? (enp0s3 became enp0s8)
```

When the address is back nothing in NSM needs restarting; the poller finds it next round and LDAP login resumes. Do **not** toggle host-only adapters on the host as trial and error; that once severed the whole lab network.

### Poller started before the lab

If NSM was up before the servers booted it records real outages for them. Cleaner: pause the device on the dashboard before shutting a VM down and resume after; paused time is excluded from availability.

### Multi-tenancy

Tenant columns and filters are live, but the lab is one organisation: one tenant (`BSP (lab)`, id 1) owns all devices and `users.tenant_id` is empty. While it is empty the frontend sends no `X-NSM-Tenant` header, the API filters nothing, and NSM behaves as before multi-tenancy. To assign accounts to a tenant, set `users.tenant_id` (and optionally role `ADMIN_PLATFORM`) in `nsm_auth`. Check the filter without changing anything:

```bash
curl -s -H "X-NSM-Tenant: 999" http://127.0.0.1:8000/devices     # must print []
```

If it returns devices, the filter is not installed.

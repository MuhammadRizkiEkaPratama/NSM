# Contributing to NSM

NSM (Network Status Monitor) is a lab project with a single maintainer. It runs
in a personal lab (VirtualBox + GNS3), and the code is released under the
[MIT License](LICENSE). Issues, pull requests, and questions are welcome. There
is no guaranteed response time.

This document has two jobs: say how to contribute, and record the **working
rules** the project follows. Most of those rules exist because of a real
failure in this codebase, so each one comes with its reason.

Steps are marked **[manual]** (you run it on your machine) or **[script]**
(automated by a script in the repo).

## Ways to contribute

| What | How |
|---|---|
| Bug report | Open an issue with the version or commit, steps to reproduce, and what you expected |
| Security vulnerability | **Do not** use a public issue. See [`SECURITY.md`](SECURITY.md) |
| Question about a design decision | Open an issue labelled `question`. The reasoning is also written in code comments and in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Code or docs change | Pull request, after the process in [How to propose a change](#how-to-propose-a-change) |
| Device profile or recorded device output | Very useful. See [`backend/perangkat/README.md`](backend/perangkat/README.md) and [`backend/perangkat/rekaman/README.md`](backend/perangkat/rekaman/README.md) |

By submitting a contribution you agree that it is licensed under the same MIT
license. Commit with **your own identity** (`git config user.name` and
`user.email`), never someone else's or a shared one.

---

## Working rules

### 1. Set up

**[manual]** Python 3.12+, JDK 25 (see `frontend/pom.xml`), and Node.js (only for
the JavaScript tests) are needed. MySQL is optional: without `NSM_DB_HOST` the
backend uses local SQLite.

```bash
python -m venv backend/venv
source backend/venv/bin/activate          # Windows: backend\venv\Scripts\activate
pip install -r backend/requirements.txt
pip install pytest pytest-xdist ruff mypy
cp backend/.env.contoh backend/.env       # then edit; leave NSM_DB_HOST empty for SQLite
cp frontend/src/main/resources/application.properties.contoh \
   frontend/src/main/resources/application.properties
```

**[script]** Create an empty database:

```bash
python backend/init_db.py
```

Note: `pyproject.toml` declares an optional `dev` extra, but `pip install -e .`
currently fails on the repository's flat layout (several top-level folders), so
use the `requirements.txt` route above, which is also what CI does.

Run the three processes (each in its own terminal), then open
`http://localhost:8080`:

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000   # run from backend/
python backend/poller.py
cd frontend && ./mvnw spring-boot:run                     # Windows: mvnw.cmd
```

The API binds to `127.0.0.1` on purpose (it has no authentication of its own;
see [`SECURITY.md`](SECURITY.md)). Never change that to `0.0.0.0`.

### 2. Tests and linters

| Check | Command | Notes |
|---|---|---|
| **[script]** Lint | `ruff check .` | Run from the repo root. CI runs it |
| **[script]** Types | `mypy` | Covers only `backend/nsm` (the clean-architecture layer) |
| **[script]** Tests, no lab | `pytest -m murni` | Files classified as not needing the lab |
| **[script]** Tests, with lab | `pytest --lab` | Needs the lab VMs, routers, and LDAP running |
| **[script]** Tests that change devices | `pytest --ubah-perangkat` | Opt-in only, see "Lab-only testing" |
| **[script]** Legacy runner | `python backend/jalankan_ci.py --mode murni` (or `lab`, `semua`) | Exit code 0 = green, 1 = red or stale manifest, 2 = manifest missing |
| **[script]** Re-measure the manifest | `python backend/ci_klasifikasi.py` (all, slow) or `--berkas uji_x.py` (one file) | Needed when you add or rename a `uji_*.py` file |
| **[script]** Java | `cd frontend && ./mvnw -B test` | Some tests need the MySQL datasource configured |
| **[script]** JavaScript | `python backend/uji_insiden_js.py`, `python backend/uji_wawasan_js.py` | Without `node` on `PATH` they report SKIPPED, not passed |

Background: most `uji_*.py` files run their checks at import time, so pytest
wraps each one in a subprocess (`backend/tests/test_warisan.py`). Do not point
pytest at `backend/` directly. Details are in
[`backend/tests/README.md`](backend/tests/README.md). Counts of "passing tests"
from pytest currently count **files**, not individual checks.

CI (`.github/workflows/ci.yml`) runs only what works without the lab and says
so in its output. A green CI run is not proof that lab-dependent behaviour
works.

### 3. Architecture rules that must not be broken

- **Data flows one way:** Browser -> Java -> Python -> database. Nothing skips a layer.
- **Java is a blind viewer.** It has no access to the monitoring database, no
  SSH or SNMP, and no business logic. Reject the temptations "just filter it in
  Java" and "just compute it in Java". The only HTTP path from Java to Python is
  `NetmonApiClient`.
- **Ownership split.** Accounts, email, and the audit log belong to Java
  (`nsm_auth` schema). Devices and monitoring history belong to Python (`nsm`
  schema). Python does not read Java's user tables; it hands notifications to
  Java's localhost-only `/internal/**` endpoints.
- **Write a secret in one place.** If two components need the same secret, one
  reads it from the other's file rather than keeping a second copy.
- **Anti-XSS.** Device names, locations, and log text come from outside, so they
  go through `textContent`, never `innerHTML` with data. Syslog text is
  unauthenticated UDP and must be treated as hostile.
- **Migrations are idempotent** and run while the poller and API are stopped.
  Old data is never dropped. Indexes and columns created by a migration must
  also be declared in `models.py`, or a fresh database will lack them.
- **Devices are not hard-coded.** Moving from the lab to other devices means
  changing `ip_address` rows, not code. New platforms are a YAML file in
  `backend/perangkat/`, starting at `teruji: dokumentasi` (read-only).
- **NSM does not run on a machine it monitors.** A monitor that dies with its
  target is useless exactly when needed.
- **Risky or invasive capabilities are opt-in and off by default** (for example
  `AUTO_BAN_AKTIF`, the `PEMULIH_*_AKTIF` remediators, `SYSLOG_AKTIF`,
  `SNMPTRAP_AKTIF`, `SADAP_HTTP`, `AGEN_SOC_AKTIF`). A new capability that
  touches devices or reads payloads follows the same pattern.
- **Deploy artefacts carry no secrets.** Deploy scripts never overwrite config
  files or uploaded data.
- **Anything that decides *who may see or do what* fails closed.** Unknown or
  empty values fall to the least privilege, and the source of "whose data" is
  always server-side and cleared in a `finally` block.

### 4. The six-gate safety philosophy (any automation change)

Every automatic action that can touch a device must pass
`pagar_otomasi.putuskan()` **at the point of execution**. The caller's earlier
decision is never trusted. The gates, in order (a refusal at any gate stops
evaluation):

1. **Risk class.** Actions classified `wajib_manusia` (human required) are refused unless gate 1b's evidence is present *and* the operator enabled the matching `OTOMASI_PENUH_*` switch. Passing 1b is not permission; the other gates still apply.
2. **Allowlist.** The operator must name each key in `PAGAR_DAFTAR_PUTIH`. Empty by default.
3. **Freeze window.** No automatic action during `PAGAR_JENDELA_BEKU`.
4. **Working hours.** Default 08:00-17:00, so a human can check.
5. **Circuit breaker.** After `PAGAR_GAGAL_BERUNTUN_MAKS` (default 3) consecutive failures for a (device, action), that action type stops until one succeeds or a human calls `reset_pemutus()` (which writes its own audit row with who and why).
6. **Rate limit.** Per device and per hour (default 3), and globally per hour (default 10).

Rules that follow from this design, and that any change must keep:

- **Audit allows and denials.** One row per decision. A refusal that leaves no
  trace is indistinguishable from a question never asked.
- **Safe by default.** Functions that touch devices default to a dry run
  (`sungguhan=False`): they run the whole flow and return what *would* happen
  without opening a connection. A forgotten argument must end in "nothing
  happened", never in a changed device.
- **Prove the safety net, do not assume it.** After arming a rollback (for
  example `reload in N` on a Cisco device), read it back. If it cannot be
  proven, stop. Release the net only *after* verification.
- **Never merge a machine deadline with a human deadline.** Auto-rollback
  timers and "waiting for the operator to decide" are separate things.
- **Verify the outcome.** After a change, show that the device still answers
  *and* that the state is what was intended.
- **Use the same definition of "down" as the humans see.** Automation must not
  act on a single raw failed ping when NSM itself needs several consecutive
  failures before alerting. Automation that trusts more easily than a person is
  automation that will break healthy things.
- **Asking must not cost anything.** `putuskan(..., simulasi=True)` runs every
  gate identically but writes no audit row, so advisors such as the SOC agent
  cannot burn the real rate limit. Never add a second decision path.
- **The SOC agent only proposes.** It has no code path to a device; its
  proposals go through the same gates as any other requester.
- **Syslog and SNMP traps never trigger actions.** They are evidence and a
  reason to run a check, because anyone on the network can forge them.
- **Test in pairs.** A test that proves restraint ("does not restart a healthy
  router") passes on a completely broken module that never acts. Pair it with a
  test that proves it *does* act when it should. The same goes for gates: show
  they can refuse **and** allow.
- **Platforms earn write access.** Only device profiles marked `teruji: lab`
  (actually run on a device) may write. Documentation or recordings only prove
  we can read. This is enforced in code.

### 5. Lab-only testing rules

- Anything that changes a device runs **only against your own lab**, never
  against equipment you do not own or are not authorised to change.
- Tests that change devices stay out of the default run and out of CI. They are
  run alone and on purpose; a `finally` block does not run if the process is
  killed, so never put them in a long unattended suite.
- Every such script must have a `finally` that restores *everything* it
  touched: node state, gate settings, and any data it changed.
- **Relax gates by in-script monkeypatching, never by editing `.env`.** If the
  script dies, `.env` stays clean and automation stays off.
- **Before taking a device down, find out who will be emailed.** Real
  notification subscriptions send real mail. Suspend affected subscriptions and
  restore them (same ids) in the `finally`. A false alarm sent to a real inbox
  trains people to ignore the next real one.
- **Read the dependency graph first** to know what else goes dark when you stop
  a device, and start from a clean state (device up in GNS3 *and* UP in NSM).
- **Stop emulated nodes through the GNS3 API (`stop`/`start`), never with a
  device `reload`.** In GNS3/Dynamips `reload` halts the emulated machine
  permanently. See [`docs/POSTMORTEM-R1.md`](docs/POSTMORTEM-R1.md) and
  [`docs/FAULT-INJECTION.md`](docs/FAULT-INJECTION.md).
- Prove refusal before proving action: show the gate refuses first, then that
  the automation works.
- Before changing network settings on a lab host, test the change on a
  throwaway; for example, assigning an IP address on Windows can disable DHCP
  on that adapter.

### 6. Definition of done

A change is done when all of these hold. If one cannot be verified, say so in
the pull request instead of implying it.

1. Relevant tests pass and `ruff check .` is clean. You **read the output**,
   not just the exit status: several real defects here were spotted from
   numbers inside passing output.
2. If you touched Java, it compiles (`./mvnw -q -DskipTests compile`) and the
   related tests pass.
3. If you touched a page, you **looked at it**, including at 375 px width
   (`document.documentElement.scrollWidth > clientWidth` must be `false`) and,
   if print output is affected, in print preview. Fixed-position elements
   repeat on every printed page.
4. Backend and frontend processes were restarted (all three, not only the ones
   you think changed) and answer real HTTP requests (`/devices` on the API,
   `/login` on the frontend). On a systemd host, compare
   `systemctl show <service> -p ActiveEnterTimestamp --value` before and after;
   `is-active` alone cannot prove a restart.
5. New tables or columns: migration is idempotent, declared in `models.py`, and
   a backup was run afterwards (`periksa_dump.py` checks that every live table
   is in the dump).
6. A shared quantity is computed by one function. If a number appears in a new
   place, reuse the existing calculation or add a test forcing both to match.
7. A user-visible sentence that explains a state is correct in the *opposite*
   state too. List every branch, including mixed ones.
8. Comments explain **why**. When moving or refactoring code, the reasoning and
   incident history in comments move with it.
9. Docs updated where behaviour changed.
10. No secrets, real device configs, or personal data (next section).

### 7. What must never be committed

`.gitignore` covers these; CI also fails if secret-looking files are tracked.

- Local config with real values: `.env`, `application.properties`. Commit the
  `*.contoh` (example) files with placeholders such as `<PLACEHOLDER>` instead.
- Keys and certificates' private parts: `*.key`, `*.pem`, `*.jks`, `*.p12`, SSH
  private keys, and password lists or hash exports for lab accounts.
- Real device configurations. Recorded device output under
  `backend/perangkat/rekaman/` must be genuine **and** have secrets masked
  first (use `connectors.konfig.samarkan`), with its origin noted in
  `manifes.yaml`. The test suite scans the recordings for secrets.
- Databases and runtime state (`nsm.db`, `penyangga.db`, WAL files), backups,
  logs, generated reports.
- Personal data: real email addresses, home paths, or hostnames. Use
  `owner@example.com`, `C:\Users\<user>\...`, and so on.

Git history is permanent and spreads with every clone. Removing a secret later
costs far more than keeping it out. If you committed one by accident, do not
just delete it in a new commit: rotate the secret and tell the maintainer
privately (see [`SECURITY.md`](SECURITY.md)). Scan for **values**, not only
patterns: `git log -S "<value>"` finds what a pattern grep misses, including
inside archives and `.docx` files.

### 8. How to propose a change

1. **Open an issue first** for anything non-trivial, and always for changes to
   architecture, the database schema, or anything that touches devices. If a
   request can be read two ways, ask rather than guess.
2. **Branch** from `main`: `fix/<topic>`, `feat/<topic>`, `docs/<topic>`.
   (CI also runs on pushes to `main` and `refactor/**`, and on pull requests
   to `main`.)
3. **Commit** small and focused: one logical change per commit, an imperative
   subject line, and a body that says *why*. Use your own identity.
4. **Before you read a "looks wrong" piece of code as a bug, read the comments
   around it.** If a reason is written there, the decision was made on
   purpose; argue against the reason explicitly or leave it.
5. **Pull request description:** what changed, why, how you verified it, and
   what you could *not* verify. Mention whether it adds or touches a path that
   can change a device.
6. Keep CI green. Do not weaken a correct test to make it pass; if a test
   needed changing, its protection must stay the same.

---

## Lessons learned

Technical lessons from real defects in this project. Most share one shape:
**nothing raised an error, the result was just wrong.**

- **Silent failure is worse than loud failure.** A relative path made SQLite
  create a new empty database; a patched test passed while hitting the real
  network; `except Exception: pass` swallowed a bug that made a feature useless.
  Anchor paths to `__file__`, and check the *default* returned after an `except`.
- **"No error" is not proof of success, and "an error" is not proof of
  failure.** A cleanup reported 12 passed, 0 failed while leaving interfaces up
  (the dry-run default). A slow `write memory` timed out in the SSH library
  although it had saved. Check the resulting state.
- **Test the checker.** A verification tool that has never been shown to catch
  a fault gives false confidence. Plant a deliberate fault and confirm it fails.
  `ast.parse` does not catch everything `compile()` does (for example repeated
  keyword arguments).
- **Give every checker a third state: "could not measure".** A timeout, an
  empty tool output, or a sentinel value must not be reported as a failure or as
  a difference (a `-1` sentinel once produced a "32,598 missing rows" alarm). A
  result equal to the timeout is a truncated measurement.
- **Test exact values for numbers people decide on**, not ranges (`mttr >= 0`
  passes on code that always returns 0), and try the test against the old
  behaviour to see it fail.
- **When two places should agree, make one the source.** Two availability
  figures (96.805% vs 96.528%) came from two calculations; a CI that ran only
  manifest-listed tests reported green while 15 files were never run. Fix the
  function every caller shares, and grep for *all* callers.
- **Averages of averages are wrong.** Hourly rollups store sum and count.
- **Do not judge "down" from raw samples** when NSM applies a consecutive-failure
  threshold; and exclude time NSM itself was not watching from the availability
  denominator.
- **Fake data proves the formula, not the answer.** Run a module once on real
  data in a non-mutating mode before calling it done. Models learning from
  history need a bounded learning window and a "not ready" state.
- **Unknown/unset values must not grant rights.** A typo in a mode setting falls
  back to the safest mode. `None` is not "not given" - use a dedicated sentinel
  in permission checks. `isinstance(True, int)` is true.
- **Match state words exactly.** `"active" in "inactive"` is true.
  `systemctl is-active ufw` says `active` while `ufw status` says `inactive`;
  ask the program itself.
- **Every network client needs a timeout** (ldap3, paramiko, requests, sockets);
  `get_info=ALL` in ldap3 downloads the whole schema and cost 17 s over a WAN.
- **MySQL REPEATABLE READ** keeps a snapshot per transaction. A script waiting
  for another process's write must `commit()` before each read;
  `expire_all()` is not enough.
- **Moving a database:** compare real `COUNT(*)` and the *time range*, not
  `information_schema` estimates or row counts alone. Keep application and
  database in one location (152 ms vs 2.2 ms per query); LDAP and files can
  cross sites. Dropping `id`s when copying breaks parent-child links.
- **Unique indexes are guards, not decoration**, and indexes created by
  migration scripts must be copied into the models.
- **Use `subprocess.run(..., text=True)` only with `encoding="utf-8",
  errors="replace"`** (and `-X utf8` for Python children) on Windows; a
  stray cp1252 byte kills the reader silently.
- **`os.kill(pid, 0)` kills the process on Windows.** Use a real liveness check
  with three answers: alive, dead, unknown.
- **A guard that writes state nobody reads is decoration.** Grep that every
  written field has a reader.
- **Devices sending to NSM** must be told their source interface
  (`logging source-interface`, `snmp-server trap-source`), or they appear as
  unknown senders. Keep unknown senders instead of dropping them.
- **Long-output device commands** can fail half-way (`snmp-server enable traps`
  with no arguments). Name arguments explicitly and check what was applied after
  a failure.
- **In GNS3, API status `started` does not mean the router is alive.** Read the
  console (`R1#` vs `VM is not running`).
- **sudo/ssh/system administration:** `ssh -t` is needed for `sudo` over SSH;
  `sudo` elevates only the first command in a `&&` chain; scope sudo rules to
  exact arguments and test that dangerous ones are refused; build sudoers files
  in `/tmp` and check with `visudo -c` first; run `sshd -t` before restarting
  `sshd`; `ufw` rules with identical match criteria replace each other
  regardless of allow/deny; a Linux VM clone inherits machine-id, SSH host keys,
  and hostname; give servers static addresses, not DHCP leases; a netplan file
  that mentions an interface takes it over.
- **A failed login with no audit row** means the password was never checked
  (stale CSRF token, expired session, or IP block): look before suspecting the
  credentials.
- **Frontend:** a clock field inside a payload defeats "skip if unchanged"
  comparisons (compare a content hash computed where the data lives). Search
  `nsm.css` before reusing a class name or styling a form element outside a
  form; global rules written for one page shape break another. Colour/icons
  locked at creation lie when the view updates in place (use `currentColor` and
  CSS classes). Look at pages at narrow widths; a missing viewport meta tag went
  unnoticed because every screenshot was 1920 px.
- **Deploy scripts report first and send only on explicit request.** Read paths
  and unit names from the system rather than from memory; prove the new code is
  running rather than that the old process is healthy.
- **Failing slowly looks like failing wrongly.** Rerun a red test alone before
  diagnosing, especially anything crossing the emulated WAN, and do not publish
  a confident diagnosis before other suspects are ruled out.

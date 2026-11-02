# Clean architecture in the Python backend, without changing behaviour

**Status:** implemented incrementally (strangler-fig, not a rewrite). Large files are split, routes live in per-area routers, the poller only schedules, and a new `nsm/` layer (domain, application, infrastructure, interface) exists for the parts moved so far. **Not done:** moving the ~100 test files and one-off scripts out of the flat `backend/` directory, shrinking the legacy wrapper, and moving the remaining routes to managed sessions.

Numbers come from the author's lab codebase. Identifiers are Indonesian: `aplikasi` = application, `antarmuka` = interface, `pemantau` = monitors, `gudang` = repository, `rute` = routes, `pengaturan` = settings.

## Context and problem

The top-level architecture was right and stays: the Python backend is the brain, the Java frontend a blind viewer, one integration point (`NetmonApiClient`). What was missing was any boundary *inside* the Python backend between business rules, storage and presentation. Measured at the time:

| Measure | Value |
|---|---|
| `.py` files in one flat directory | 238 (tests, migrations, one-off scripts and production code indistinguishable) |
| `report_service.py` | 6,046 lines, about 100 functions, imported by 43 files |
| `poller.py` | 3,159 lines, 20 jobs |
| `main.py` | 1,534 lines, 74 routes |
| Direct `SessionLocal()` callers | 56 files |
| `config.py` | ~60 `get_*` functions re-reading `.env` from disk on every call |

Three wrong-way links: the read-only report module imported `ubah_acl_router`, the module that changes router config (importing a report loaded a write path to devices); `config`/`models` and `report_service` formed an import cycle held only by function-local imports; and `/devices` ran one `StatusLog` query per device (N+1) against MySQL over the network.

## Goals and non-goals

Goals: separate business rules from storage and presentation; keep every endpoint and every number identical; make code testable without a database or a real `.env`.

Non-goals: rewriting `report_service`, which encodes expensive lessons not visible from function shapes (unmonitored windows removed from the availability denominator, hourly rollups storing sum and count because an average of averages was proven wrong, 96.805 % versus 96.528 % for the same data, and the "ping blocked" versus "dead" distinction). Every retyped line is a chance to lose one silently. The system was also already running as systemd services on the nsm-app VM.

## Design

```
backend/
  main.py                38 lines: exposes `app` via rakit.buat_aplikasi()
  poller.py              330 lines: scheduling only
  report_service/        package of 12 modules, re-exporting every old name
  nsm/
    pengaturan.py        frozen Settings object, read once
    domain/              pure: no DB, network or .env (time ranges, frozen dataclasses)
    aplikasi/            Protocol contracts + use cases
    infrastruktur/       SQLAlchemy repositories, clock, sessions, legacy wrapper
    antarmuka/http/      wiring.py (composition root), rakit.py (app factory), rute/ (18 routers)
    pemantau/            periodic jobs, previously inside poller.py
```

Dependency rule: `antarmuka -> aplikasi -> domain`, with `infrastruktur` implementing the `aplikasi` contracts and never called back. Only `wiring.py` decides which implementation fills which contract. `Protocol` (structural) was chosen over abstract base classes so existing classes satisfy contracts without edits.

What changed in practice:

| Area | Before | After |
|---|---|---|
| Duration formulas | mixed with SQL | `domain/waktu.py`, testable without a DB |
| Sessions | 56 files managed their own; one route leaked on error | `sesi()` for reads, `unit_kerja()` for writes via `Depends(wiring.beri_sesi)` (the other routes still create their own) |
| Settings | `.env` re-read per call | `Pengaturan` frozen, buildable in tests; `config.py` itself later gained a cache keyed on file mtime and size, and `.env` edits are still picked up without a restart |
| App assembly | two paths (production 17 routers, test factory 2) | one factory, `rakit.buat_aplikasi()`; the two had silently diverged |
| `/devices` | 12 queries, 52.2 ms | 2 queries, 9.1 ms (11 devices, via `terakhir_semua()`) |
| Routes | one file | 18 router modules (74 routes at refactor time, 78 now with later additions) |

## Safety and failure modes

- **No big-bang.** Routes moved in stages (4, then 70), `report_service` and `poller` were split behind unchanged public names, and every step had a parity check.
- **One deliberate behaviour fix**, stated openly: `/devices/{id}/info` was the only route that closed its session without `finally` (65 of 74 used `try/finally`, 8 made no session). It leaked only when its single query failed, exactly when connections are scarce. Its response is unchanged.
- **Deploy and verify.** `kirim_ke_nsmapp.py` copies, it does not delete, so the old `report_service.py` stayed beside the new package on the VM; Python was already importing the package, but correctness resting on module search order is not acceptable, so the stale file and its `.pyc` were backed up and removed. "Service active" is not proof for a poller, since a service failing every round still reads active; proof was `status_logs` growing (40 rows in 40 s at a 1 s ping interval), 74 routes served, and `cek_sinkron_nsmapp.py` reporting no difference.

## Testing in the lab

Parity guards written for the refactor:

| File | Guards against |
|---|---|
| `uji_arsitektur_baru.py` | new path output differing from the old path, field by field |
| `uji_daftar_rute.py` | route paths, methods or resolver functions changing; also calls every read route to completion |
| `uji_middleware_tenant_rute_baru.py` | tenant filter not applying to `APIRouter` routes |
| `uji_permukaan_paket.py` | an old `report_service`/`poller` name disappearing or changing signature |
| `uji_nama_terdefinisi.py` | undefined global names, found statically with `symtable` (it first has to catch a deliberately planted defect) |
| `uji_tambal_sampai.py` | tests that patch a name on a module which only forwards |

Parity is measured with a **bracketing control**: `old() -> new() -> old()`. Fields that differ between the two old calls are legitimately unstable (a dead device's availability reads `0.0 %` then `0.003 %` because the window grew a second) and only those are forgiven; any other difference is a defect. Loosening the comparison until that passes would let real defects through. Final run of the whole suite: 99 passed, 3 failed, 3 skipped (the skipped ones modify real devices). The three failures were checked on the old code and are unrelated (two depend on syslog history age; one restore test reported a table missing from the restore result, which is worth its own investigation).

## Lessons learned

- **Patches that do not arrive.** After splitting, `poller.py` only forwards names. `poller.cek_port_terbuka = fake` replaces a copy nobody reads, and the real function runs and touches the network: the test passes, doesn't blow up. Seven test files were affected; only some failed by luck. `uji_permukaan_paket.py` gave false comfort, because it proves names exist, not that they can be replaced. `bantu_tambal.tambal(name, value)` patches every module that owns the name (one name existed in two modules), and `uji_tambal_sampai.py` scans test files by AST and rejects attribute assignment on forwarding modules.
- **A test that patches `main.SessionLocal` passes while writing to the real database** if routers bind their own `from database import SessionLocal`; the patch now sweeps all router modules.
- **Route prefix duplication** (`prefix="/report"` plus full `"/report/slo"` gave `/report/report/slo`, three routes gone, no Python error) was caught by the route-list test.
- **A multi-line import was read by the auto-fixer as its first line only**, so `/ldap/direktori` died with `NameError` while imports, 78 report tests and the 74-route list all stayed green. Two new tests close the gap from both sides (call every GET route; static undefined-name scan, which also found a missing import on a 409 branch that might not have run for months).
- An attack-surface test that read raw `app.routes` reported zero write endpoints after the move, because it saw wrapper nodes: a check that reports zero by misreading is worse than a loose one.

## Open questions

- Move the ~100 test files and ~60 scripts into `uji/` and `alat/`. Deferred on purpose: about half compute paths from `__file__` assuming they sit in `backend/`, so a move means auditing 77 files for no coupling reduction, and a wrong path fails only when that script is next run (some migrations run once a year). If done, in small groups with path checks first.
- Shrink `nsm/infrastruktur/warisan/laporan.py` as calculations move into use cases; delete it when empty.
- Convert the remaining routes from `SessionLocal()` in the body to `Depends(wiring.beri_sesi)`, area by area, with a parity check first.
- Replace the remaining ~60 `config.get_*` callers with `Pengaturan` gradually.

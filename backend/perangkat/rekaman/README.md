# Recordings of real device output

Output that actually came out of devices, stored as is, used to test
**parsing**.

Read by `dialek_perangkat.rekaman()`; tested by
[`tests/test_rekaman.py`](../../tests/test_rekaman.py).

---

## Why this exists

The secret-masking tests in
[`tests/test_rahasia_perangkat.py`](../../tests/test_rahasia_perangkat.py) use
examples **written by hand** from vendor documentation. That is useful, but it
has a limit that cannot be passed:

> An invented example only contains the shapes someone already thought of.
> Shapes nobody thought of never appear there, and so never fail.

This was proven the day the corpus was built. Sweeping 100 real configuration
snapshots found one secret form that slipped past **every** pattern:

```
snmp-server host 192.168.56.156 version 2c <COMMUNITY> udp-port 1162
```

The base pattern only caught `snmp-server community X`. A community string at
the tail of a `snmp-server host` line was never touched, and no invented example
contained it, because nobody thought of it. **The device thought of it.**

---

## Contents today

| Platform | Recordings | Origin |
|---|---|---|
| `cisco_ios` | 4 | two routers and two switches: `show running-config` from the `konfig_snapshots` table of the primary lab instance |
| `linux` | 4 | four lab Ubuntu VMs: output of `connectors/konfig_linux.ambil()` |

The five `dokumentasi` platforms (MikroTik, Junos, EOS, VRP, FortiOS) **have no
recordings yet**, which is why they are still `dokumentasi`. There is no such
device here. Recording invented output and calling it a recording would be
exactly the lie this whole evidence-level system exists to prevent.

(File names contain `lokasi-a` / `lokasi-b`: site A and site B of the lab.)

---

## Rules

1. **Recordings must be real.** Output of an actual device, not hand-written. A
   hand-written example belongs in a test file as an example, not here.
2. **Secrets are masked before they enter.** This corpus is committed to the
   repository. Once a secret is in Git history, removing it means rewriting
   history, and until then it exists in every copy anyone has taken.
   `test_tidak_ada_rahasia_di_rekaman` sweeps every file and **fails** for a
   recording that carries a secret.
3. **Provenance is recorded** in `manifes.yaml`. A recording with no note of
   where it came from cannot be told apart from an invented example, and the
   whole value lies in that difference.
4. **`teruji: rekaman` must have its recordings.** Enforced by
   `test_yang_mengaku_rekaman_memang_punya_rekamannya`. An evidence level that
   can be typed without its proof is not an evidence level; it is a claim with a
   more convincing name.

> **A recording does NOT grant write permission.** Only `teruji: lab` does. A
> recording proves we can **read** what a device says; it proves nothing about
> what a write command **does** on that device. However many
> `show running-config` outputs are recorded, none tells us that `write memory`
> there behaves as we assume, and that is what took R1 down
> ([post-mortem](../../../docs/POSTMORTEM-R1.md)).

---

## Contributing a recording

If you have a device that is not here (MikroTik, Junos, EOS, VRP, FortiOS, or
another vendor), this is the most useful thing you can offer. See
[CONTRIBUTING.md](../../../CONTRIBUTING.md) for what the project accepts; opening
an issue first is the safest route.

1. Capture the output of the read command listed under `baca:` in the platform's
   definition file, for example `/export` for RouterOS.
2. **Check the secrets yourself**, then run the masker. From the `backend/`
   directory:

   ```bash
   python -c "from connectors import konfig; import sys; print(konfig.samarkan(sys.stdin.read()))" < raw.txt > perangkat/rekaman/<platform>/<command>.<label>.txt
   ```

   If any secret form is **not** masked, that is a finding, and more valuable
   than the recording itself. Add its pattern under `rahasia:` in that
   platform's definition file.
3. Add a row to `manifes.yaml`: `berkas` (file), `platform`, `perintah`
   (command), `perangkat` (device), `direkam` (recorded at).
4. Run `pytest backend/tests/test_rekaman.py` from the repository root. All the
   parsing tests run against your new recording with no code added.
5. If everything is green, the platform may move up to `teruji: rekaman`.

You should **not** need to edit code. If a new recording forces that, the
definition schema is lacking, and that is what should be fixed.

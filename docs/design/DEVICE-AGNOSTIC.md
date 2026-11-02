# Device-agnostic design: platform definitions as files

**Status:** implemented. Nine platform definition files, a validating loader, capability queries replacing most `platform ==` branches, per-platform secret masking, a corpus of recorded device output, and approval-gated subnet discovery. Only Cisco IOS, Linux, Windows and the local machine have been run against real devices in the lab.

Numbers come from the author's lab. Code identifiers are Indonesian: `perangkat` = device, `teruji` = tested, `kemampuan` = capability, `rekaman` = recording, `penemuan` = discovery, `jaring_pengaman` = safety net.

## Context and problem

NSM's reading layer (ping, TCP, SNMP, service checks) was already vendor-neutral. The layers that read configuration, act on devices and identify them assumed the developer's lab: Cisco IOS, Ubuntu, GNS3 nodes. At the start of this work there were 52 `platform ==` branches in the code, four known platform values, read-config commands registered for two platforms, and a GNS3-specific column (`Device.gns3_node`) used by five modules. The lab devices are test fixtures; the assumption to remove is "the test device is the user's device".

Devices already came from the `devices` table, not from code, which is the right base.

## Goals and non-goals

Goals: add a device type without editing code (one definition file); basic monitoring for a platform with no definition ("not recognised" is not "not monitored"); discover devices by scanning a subnet; never switch on a write path by accident.

Non-goals: replacing netmiko/paramiko (proven in the lab); adding NAPALM; importing thousands of NetBox device types (no racks or PDUs here); a driver system (per-vendor code that never runs is code that is silently broken); auto-discovery that activates devices on its own.

Why not NAPALM, by the numbers: it has five core drivers (ios, iosxr, nxos, eos, junos), covering three of the seven target vendors. The already-installed netmiko knows 175 device types and includes all seven. What NSM lacked was a table of which platform uses which command.

## Design

**One YAML per platform** in `backend/perangkat/`, read by `dialek_perangkat.py` (modelled on `dialek.py`, which gathers SQLite-versus-MySQL differences in one place; database dialects are code because there are two, device dialects are files because they must grow). Sections: `deteksi` (SNMP `sysObjectID` prefix, the LibreNMS approach), `akses`, `baca` (read commands), `tulis` (write and safety net), `kemampuan`, `rahasia` (extra masking patterns), `alias`. Full schema and how to add a platform: [backend/perangkat/README.md](../../backend/perangkat/README.md).

**Evidence level binds permissions.** Each file declares `teruji`:

| Value | Meaning | Allowed |
|---|---|---|
| `lab` | run on a real device (`sumber` required) | read and write |
| `rekaman` | parsing tested against recorded real output | read only |
| `dokumentasi` | written from vendor docs, never run | read only, after human approval |

`Definisi.boleh_menulis` returns true only for `lab`. A file cannot raise its own rights: the five documentation-tier definitions (MikroTik, Junos, EOS, VRP, FortiOS) say `didukung: true` and are still answered "no". The reason is [POSTMORTEM-R1.md](../POSTMORTEM-R1.md): a command correct per the vendor docs (`reload in N`) permanently powered off an emulated router. Recordings prove NSM can read what a device says, not what a write command does.

**Capabilities instead of brands.** Six closed keys replaced the branches: `firewall` (`acl`/`ufw`/`netsh`/none), `identitas` (`cisco`/`linux`/`windows`/none), `baca_sumberdaya`, `baca_trafik`, `baca_konfig_layanan`, `lokal`. `dialek.ambil(p).kemampuan("baca_sumberdaya")` asks "can CPU be read?" rather than "is it Linux?". A key exists only if real code needed it, and an unmentioned key means "cannot" (a new file that forgets `firewall` must not make NSM try `ufw` on a device without it). SQL uses `Device.platform.in_(platform_dengan("firewall", "ufw"))`. Brand-naming branches fell from 40 to 5; the remaining ones are deliberate (`connectors/ssh.py` picks labelled command tables whose labels are on-screen text; one bandwidth special case for a duplicate row). Behaviour was proven unchanged by freezing the old per-platform lists as literals in a test and by computing each polling job's device set under the old and new rules against the lab database: identical for all nine jobs.

**Safety-net abstraction.** The old field `reload_aman` named one Cisco mechanism for a general question: is there something that self-heals if a change cuts the connection, and how is it installed, proven installed and confirmed? Both mechanisms have the same shape (stay silent: the device recovers; confirm: the change stays):

| Platform | `jaring_pengaman.jenis` | NSM can install |
|---|---|---|
| Cisco IOS | `reload` (`reload in N` / `reload cancel`) | yes |
| Juniper Junos | `commit_confirmed` | yes |
| Arista EOS, MikroTik | `commit_confirmed` | no |
| Huawei VRP | `reload` | no |
| FortiOS, Linux, Windows, local | `tidak_ada` | n/a |

An empty `pasang` differs from `tidak_ada`: "exists, NSM does not know how to run it" versus "does not exist". `kirim_perintah.py` refuses to send to a platform that cannot install a net, and the validator rejects `pasang` without `penanda_terpasang`, since an install can fail silently. `Device.gns3_node` stays for now (the per-device override may only make behaviour stricter, never looser).

**Per-platform masking.** The base masking patterns are Cisco-shaped. `connectors/konfig.py: olah(raw, platform)` adds the platform's `rahasia` patterns (for example `set password=` on RouterOS, `set psksecret ENC` on FortiOS, `local-user ... password irreversible-cipher` on Huawei). Without them the first non-Cisco device would store all its secrets in the database that is backed up off-host.

**Discovery.** `penemuan.py`: scan a private subnet, identify by `sysObjectID`, match to a definition, and offer the host. Routes: `POST /penemuan/pindai`, `GET /penemuan`, `POST /penemuan/{id}/setujui` (creates the device inactive), `POST /penemuan/{id}/abaikan`. Layer 1 (ICMP + TCP 22/80/443/161) needs no credentials; layer 2 (SNMPv3 `sysObjectID` only) runs only when credentials are given. Unmatched hosts are still offered with an empty platform and get ping/TCP monitoring once approved. Lesson from Zabbix: discovery that finds a device and shows no data is moved work, not help.

## Safety and failure modes

- Unknown platform: `ambil()` never raises and never returns None; it returns an empty safe definition.
- Misspelled keys are rejected at load; a silently ignored key would surface months later.
- Scans: invalid network, more than 1024 addresses, or public ranges are rejected before any packet is sent; `izinkan_publik` must be explicit. The size is checked before building the address list (the first version built 16.7 million addresses for a `/8` and only then rejected; a pure test file took 30.7 s, then 1.6 s).
- Scanning is a POST, because a GET could be re-fired by a reload button.
- Discovery never inserts into `devices` by itself; an auto-added host lets anyone who can plug in an IP add load to the monitor.

## Testing in the lab

`tests/test_dialek_perangkat.py` (schema, loader, evidence rules, capabilities, safety net), `tests/test_rahasia_perangkat.py` (masking with a guard that every registered pattern actually fires), `tests/test_rekaman.py`, `tests/test_penemuan.py`. Without the device you can test command selection, output parsing (recorded output, as ntc-templates does), per-vendor masking and `sysObjectID` matching. You cannot test login/paging/enable (netmiko's job) or the write path, which is why it stops at `dokumentasi`. Recorded output: 4 Cisco configs and 4 Linux snapshots from the lab ([rekaman README](../../backend/perangkat/rekaman/README.md)); the five other vendors have none yet, and fabricated recordings are refused. A first scan of the lab's `/24` took 27.9 s, 7 hosts answered; two live hosts were unregistered and two registered devices were dead.

## Lessons learned

- MikroTik's `/export` had sat in production code with no MikroTik device ever present; the evidence field makes such a risk visible instead of adding one.
- Five of fifteen first-draft masking patterns never fired (already caught by the base pattern, no sample exercised them, or an invented line shape). A dead pattern in a secret-guarding file gives false confidence; a test now fails on one.
- Sweeping 100 real snapshots found a secret form no handmade sample covered: the community string at the tail of `snmp-server host <addr> version 2c <community> udp-port ...`. Patching it took two tries, both wrong because the regex backtracked past an optional group (first it masked the word `version`, then masking was not stable so the fingerprint changed every cycle and NSM reported changes on an idle device); fixed with lookaheads at line start. Already stored snapshots were re-masked with `samarkan_ulang_potret.py` (dry run by default, aborts if any changed line is not an `snmp-server host` line).
- Code and doc disagreed on whether `rekaman` may write. The doc was right; `boleh_menulis` is now `lab` only.

## Open questions

- Recordings or lab runs for the five documentation-tier vendors (containerlab/vrnetlab can supply devices to contributors, as an option, not a requirement).
- Installing safety nets for EOS, VRP and RouterOS.
- Removing `Device.gns3_node` once definitions fully replace it.

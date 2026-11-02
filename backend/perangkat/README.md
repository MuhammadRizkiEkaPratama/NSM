# Device definitions

One YAML file per platform. Adding support for a new device means adding one
file here, **without touching code**.

Read by [`dialek_perangkat.py`](../dialek_perangkat.py); tested by
[`tests/test_dialek_perangkat.py`](../tests/test_dialek_perangkat.py).

Note: key names in the YAML files are Indonesian identifiers used by the code
(`teruji` = tested/proven level, `sumber` = source, `baca` = read, `tulis` =
write, `kemampuan` = capabilities, `rahasia` = secrets, `jaring_pengaman` =
safety net). They are kept as is.

---

## The most important rule: `teruji`

Every file must state **how strong its evidence is**.

| Value | Meaning | What may be enabled |
|---|---|---|
| `lab` | has been run on a real (lab) device | read **and** write |
| `rekaman` | parsing is tested against real recorded output | **read only** |
| `dokumentasi` | written from vendor documentation, never run | **read only** |

> **A file cannot raise its own rights.** A definition at the `dokumentasi`
> **or** `rekaman` level that sets `tulis.didukung: true` is still answered
> **no** by `Definisi.boleh_menulis`. This is enforced in code, not in this
> document.
>
> **Only `lab` may write**, and the distinction is not negotiable: a recording
> proves we can **read** what a device says; it proves nothing about what a
> write command **does** on that device. However many `show running-config`
> outputs are recorded, none tells us that `write memory` there behaves as we
> assume, and that kind of assumption is what took R1 down.

Why so strict: [the R1 post-mortem](../../docs/POSTMORTEM-R1.md) records a
command that is **correct according to Cisco documentation** (`reload in N`)
permanently powering off a lab router, because the real environment differed
from what the documentation assumes. A command that is right on paper and wrong
in reality is not a hypothetical worry; it has happened in this project.

`lab` and `rekaman` **must** fill in `sumber`: on which device, or recorded
from where. An evidence level without its origin is a claim, not evidence, and
the loader rejects such files.

---

## Schema

```yaml
nama: contoh_os              # REQUIRED, must equal the file name
keterangan: Example OS 7.x   # REQUIRED, shown on screen
teruji: dokumentasi          # REQUIRED: lab | rekaman | dokumentasi
sumber: ""                   # required when teruji = lab/rekaman
alias: []                    # other names people type (e.g. ubuntu)

deteksi:
  sysobjectid:               # PREFIX, not a full OID (the LibreNMS way)
    - ".1.3.6.1.4.1.12345."
  nama_mengandung: []        # fallback when SNMP is down

akses:
  netmiko_device_type: contoh_os   # name netmiko understands
  jenis: jaringan                  # jaringan (network) | host
  butuh_enable: false
  paging_mati: ""                  # command that disables paging, if any

baca:                        # keys are free-form, values must be command text
  konfigurasi: ...
  konfigurasi_startup: ...
  identitas: ...
  nama_host: ...
  uptime: ...
  interface_ringkas: ...
  interface_rinci: ...
  tabel_rute: ...
  cpu: ...
  memori: ...
  disk: ...

tulis:
  didukung: false
  mode_konfig: ...
  simpan: ...
  jaring_pengaman:           # see its own section below
    jenis: tidak_ada         # reload | commit_confirmed | tidak_ada
    pasang: ""
    bukti: ""
    penanda_terpasang: []
    kukuhkan: ""
    penanda_lepas: []

kemampuan:                   # CLOSED LIST, see the table below
  firewall: ""               # acl | ufw | netsh | ""
  identitas: ""              # cisco | linux | windows | ""
  baca_sumberdaya: false
  baca_trafik: false
  baca_konfig_layanan: false
  lokal: false

rahasia:                     # EXTRA masking specific to this platform
  - pola: "^(\\s*set password\\s+).+$"
    ganti: "\\1<DISAMARKAN>"
```

Keys **not** in this list are rejected at load time. That is deliberate: a
silently ignored typo turns "fails at load" into "quietly has no effect", and
the second is found months later.

### Notes per key

- **`baca.konfigurasi_startup`**: leave it out if the platform does not separate
  running from saved configuration. Absent means something different from empty:
  a device that has no such concept must not be reported as having unsaved
  configuration.
- **`rahasia`**: only **additional** patterns. The base Cisco-style patterns
  (`enable secret`, `snmp-server community`, `password 7 ...`) are applied to
  all platforms by `connectors/konfig.py`; matches are replaced by
  `<DISAMARKAN>`.
- **`tulis.jaring_pengaman`**: see its own section below. A per-device value
  (`Device.gns3_node`) may only make things **stricter**, never looser.
- **`alias`**: other names people may type in the platform column. `linux.yaml`
  accepts `ubuntu` and `debian`. An alias applies to **every** question.

---

## `kemampuan`: questions, not brands

Each key replaces one `if platform == "..."` branch that used to be scattered
through the code. The difference is more than location:

```python
if d.platform == "linux"                          # "is this Linux?"
if dialek.ambil(p).kemampuan("baca_sumberdaya")   # "can its CPU be read?"
```

The first has to be edited whenever a new operating system turns out to qualify
too. The second does not.

| Key | Values | Answers | Used by |
|---|---|---|---|
| `firewall` | `acl` / `ufw` / `netsh` / `""` | how addresses are blocked on this device | `ubah_firewall`, `ubah_acl_router`, `penjaga_aksi`, poller and firewall reports |
| `identitas` | `cisco` / `linux` / `windows` / `""` | how to collect MAC, serial, machine-id | `identitas_sumber` |
| `baca_sumberdaya` | yes/no | CPU, RAM, disk over SSH | `pemantau/sumberdaya` |
| `baca_trafik` | yes/no | user command log (auditd) | `pemantau/trafik` |
| `baca_konfig_layanan` | yes/no | service configuration files | `pemantau/konfig` |
| `lokal` | yes/no | the machine NSM itself runs on | poller, bandwidth report |

Two binding rules, both in the same spirit as `teruji`:

1. **A file's silence means "cannot".** An unmentioned key answers `false` or
   `""`. If it were the other way round, a new file that forgot `firewall`
   would make NSM run `ufw` on a device without ufw, and trying means opening
   SSH, sending a command, and storing the failure as an event.
2. **`teruji: dokumentasi` may not claim any capability.** Each capability turns
   on a path that contacts the device in a specific way, and a platform that has
   never been contacted may not turn on any of them.

For SQL queries that cannot call `ambil()` per row:

```python
Device.platform.in_(dialek_perangkat.platform_dengan("firewall", "ufw"))
```

---

## `jaring_pengaman`: a question, not a mechanism

This field was originally called `reload_aman` ("safe reload"). That name made
**three of nine** platforms misleadingly answer "no safety net": the net exists,
it just is not `reload`.

The real question, taken from the flow in `kirim_perintah.py`:

> Is there a way to install something that **recovers by itself** if the change
> cuts the connection, and if so, how do you install it, prove it is installed,
> and confirm that the change may stay?

The two mechanisms turn out to have **exactly the same shape**, which is why one
schema holds both:

```
do nothing -> the device recovers by itself
confirm    -> the change stays
```

| | install (`pasang`) | confirm (`kukuhkan`) |
|---|---|---|
| Cisco IOS | `reload in N` | `reload cancel` |
| Juniper Junos | `commit confirmed N` | `commit` |

Current state:

| Platform | `jenis` | Does NSM know how to install it? |
|---|---|---|
| `cisco_ios` | `reload` | **yes** |
| `juniper_junos` | `commit_confirmed` | **yes** |
| `arista_eos` | `commit_confirmed` | no: `configure session` + `commit timer`, two steps |
| `huawei_vrp` | `reload` | no: the scheduled-reboot command form is not certain |
| `mikrotik_routeros` | `commit_confirmed` | no: safe mode is entered with Ctrl-X, not a command |
| `fortinet`, `linux`, `windows`, `lokal` | `tidak_ada` | n/a |

**An empty `pasang` means something different from `jenis: tidak_ada`**, and the
distinction is honest: the first means "the mechanism exists, NSM does not know
how to run it"; the second means "there is none". Treating them as the same
would erase information the owner of such a device needs.

`kirim_perintah.py` **refuses to send** to a platform whose `pasang` is empty.
Not "send anyway without a net": the whole design of that module stands on the
net, and without it one wrong command means a device that can no longer be
reached from anywhere.

`penanda_terpasang` is **required** whenever `pasang` is set; the validator
rejects the file otherwise. The install command can fail silently (permissions,
an unanswered prompt, an unexpected reply), and a net that cannot be proven
installed is not a net.

---

## Adding a new platform

1. Copy the closest file and change its contents. Start with
   `teruji: dokumentasi`.
2. Cite the **source** in a comment on each command: a vendor documentation
   link, or the recording file name.
3. Run `pytest backend/tests/test_dialek_perangkat.py` from the repository root.
4. Move up to `rekaman` once a real output recording and its test exist; move up
   to `lab` only after it has actually run on the device.

What you should **not** need to do: add the platform to a table inside the code.
If a change forces that, the schema here is lacking, and that is what should be
fixed.

---

## What exists today

| File | Level | Write | Notes |
|---|---|---|---|
| `cisco_ios.yaml` | `lab` | yes | the lab's emulated Cisco routers (Dynamips) and L2 switches |
| `linux.yaml` | `lab` | no | the lab's Ubuntu VMs; its write path goes through `ubah_firewall.py` |
| `windows.yaml` | `lab` | no | the lab laptop over OpenSSH, restricted account |
| `lokal.yaml` | `lab` | no | the machine NSM runs on, read through psutil |
| `mikrotik_routeros.yaml` | `dokumentasi` | no | `/export` has long existed in the main code without any device to run it on |
| `juniper_junos.yaml` | `dokumentasi` | no | candidate/active model, not running/startup |
| `arista_eos.yaml` | `dokumentasi` | no | similar to IOS; each similarity is stated as checked, not assumed |
| `huawei_vrp.yaml` | `dokumentasi` | no | `display` / `system-view` / `save`; `save` asks Y/N |
| `fortinet.yaml` | `dokumentasi` | no | netmiko changes the device's console settings when it connects |

The **Write** column is the answer of `Definisi.boleh_menulis`, not the content
of `tulis.didukung` in the file. All five `dokumentasi` files set
`didukung: true`, and are still answered **no**.

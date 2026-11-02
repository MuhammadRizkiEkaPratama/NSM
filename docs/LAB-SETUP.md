# Lab Setup

How to reproduce the NSM lab: the VMs, the emulated network, the start order, and how to check that each piece works before you start NSM itself.

> **Lab project.** NSM was built during an internship in the Network Security division of PT Bumi Siak Pusako (BSP). It runs entirely in a personal lab (VirtualBox + GNS3 on one laptop) and has no connection to any BSP system, network, or data. Names like "BSP" in the lab artifacts (LDAP domain `dc=bsp,dc=id`, CA name, Java package `id.bsp`) are lab labels only. "Primary instance" means the `nsm-app` VM in that lab, not a company production system.

Steps are marked **[manual]** (you do it on your machine or in a VM console) or **[script]** (a script in this repo does it). For the software side after the lab is up, see [OPERATIONS.md](OPERATIONS.md). For the network design, see [TOPOLOGY.md](TOPOLOGY.md).

All addresses, accounts and numbers below are lab values. The example credential used in this repo is `ExampleLabPass123`; anything else is shown as a `<PLACEHOLDER>`. Use your own secrets and never reuse them outside the lab.

---

## 1. Prerequisites

| Item | Notes |
|---|---|
| Host machine | The scripts assume a **Windows** host (PowerShell, `VBoxManage.exe`, `%APPDATA%\GNS3\2.2\gns3_server.ini`). A Linux host works only if you adapt those paths. Plan for roughly 16 GB RAM: the VMs plus the GNS3 VM use most of it. |
| VirtualBox | Two host-only networks (see section 3). |
| GNS3 2.2 + GNS3 VM | The GNS3 VM runs the emulated nodes. The controller runs on the host. |
| Cisco images | **Bring your own licensed Cisco images. None are included in this repo.** You need an image for an emulated Cisco router (Dynamips) and one for an emulated L2 switch. The scripts refer to GNS3 *template names*, not image files (see section 4). |
| Python 3.12+ | Host and `nsm-app` (`backend/requirements.txt`, plus `drain3`). |
| JDK 25 | `frontend/pom.xml` sets `java.version` to 25. Build the jar on the host. |
| Ubuntu Server ISO | For the VMs. `nsm-ubuntu` ran Ubuntu 24.04. |
| A truststore | Java must trust the lab CA for LDAP StartTLS (section 8). |

---

## 2. Machines and roles

| Machine | Address | Role | What breaks if it is down |
|---|---|---|---|
| Host laptop | `192.168.56.1` | VirtualBox/GNS3 host, GNS3 controller, scheduled backups | All VMs and GNS3 |
| GNS3 VM | `192.168.56.102` | Compute server for the emulated nodes | The whole `192.168.20.0/24` side and the WAN |
| R1 / SW-A | `192.168.56.60` / `.61` | Site A router and access switch | Path between sites |
| R2 / SW-B | `192.168.20.1` / `.2` | Site B router and access switch | Site B |
| ISP | `10.10.10.2` / `10.10.20.1` | Transit router between the sites (not monitored) | Path between sites |
| `nsm-ubuntu` | `192.168.20.101` | LDAP directory (slapd), MySQL read-only replica | NSM and E-Canteen logins, `sssd` on other VMs |
| `nsm-data` | `192.168.56.104` | MySQL primary (`nsm`, `nsm_auth`, `ecanteen`), lab time source | All NSM data; the poller falls back to a local SQLite buffer |
| `testUbuntu` | `192.168.56.103` | Apache, E-Canteen demo app, SFTP file server | The workload NSM watches |
| `nsm-files` (hostname `file-server`) | `192.168.56.105` | Samba file server with audit log | SMB shares and the share audit trail |
| `nsm-app` | `192.168.56.156` | NSM itself: poller, API, web UI (systemd) | NSM (the "primary lab instance") |
| `kali-linux` | `192.168.56.151` | Attack simulation only; may stay off | Nothing |

Two names refer to the same machine for the file server: the VirtualBox VM is `nsm-files`, the Linux hostname is `file-server`. Keep both in mind when reading logs.

**Account naming lesson.** Do not give a local admin account the same name as an LDAP user. Audit logs record names, not UIDs, so "user X deleted a file" becomes untraceable when two different people share the name. Keep local admin, LDAP users and the NSM read-only robot account (`nsmro`) as three separate sets.

---

## 3. Network

Two VirtualBox host-only networks act as the "wires" of the two sites:

| VirtualBox network | Subnet | Role |
|---|---|---|
| Host-only #1 | `192.168.56.0/24` (host = `.1`) | Site A wire |
| Host-only #2 | none needed on the host | Site B wire (pure L2 to the GNS3 VM) |

1. **[manual]** Create both host-only networks. On #1, note the DHCP range: VirtualBox's default hands out `.101-.254`. **Give every server a static address**; a server that holds a DHCP lease will eventually move and silently break every config that names its address.
2. **[manual]** GNS3 VM: NIC 1 on host-only #1 (inside the VM `eth0`, becomes node `LAN-A`), NIC 3 on host-only #2 (`eth2`, becomes node `LAN-B`). NIC 2 is not part of the topology. Set **Promiscuous Mode: Allow All** on every NIC that GNS3 bridges. With the default `Deny`, frames leave but replies addressed to emulated MACs are dropped (symptom: ARP `Incomplete` both ways). After changing it, toggle the cable (`VBoxManage controlvm <vm> setlinkstate<N> off` then `on`).
3. **[manual]** Site B VMs (`nsm-ubuntu`) attach to host-only #2. Site A VMs attach to #1.
4. **[manual]** Route from the host to Site B through R1 (permanent):

```powershell
route -p add 192.168.20.0 mask 255.255.255.0 192.168.56.60
```

5. **[manual]** On Site A servers that need Site B (for LDAP), add `192.168.20.0/24 via 192.168.56.60`. Note that `testUbuntu` uses NetworkManager while `nsm-ubuntu` uses netplan: add the route with `nmcli connection modify '<connection>' +ipv4.routes ...` on the former. Adding a netplan file that names an interface NetworkManager owns takes it away and leaves it without an address.

After `netplan apply`, check `ip -br addr`: it adds addresses but does not remove ones from older files such as a leftover cloud-init file.

---

## 4. Build the emulated network

The topology is built from code over the GNS3 REST API so it can be re-run and reviewed. Details and rationale are in [TOPOLOGY.md](TOPOLOGY.md).

1. **[manual]** In GNS3, create a project named `nsm-lab`. Create a Dynamips router node `R1` with one FastEthernet adapter in slot 0 and an SSH-capable IOS. Configure it by console: `Fa0/0 192.168.56.60/24`, a monitoring user, SSH v2, SNMPv3. Sanitized reference configs are in `docs/project-report/lampiran-data/`.
2. **[manual]** In the GNS3 template library create two templates **named exactly** `SW` (emulated L2 switch) and `R2` (a second Dynamips router type with two FastEthernet ports). The scripts look templates up by those names. Add a `Cloud` node `Cloud1` bound to `eth0`.
3. **[script]** From `gns3/`:

```powershell
cd gns3
python bangun_topologi.py      # SW-A, SW-B, R2, Cloud2 (eth2 only), all cables
python tambah_isp.py           # inserts ISP between R1 and R2, renames Cloud1/2 to LAN-A/LAN-B
python lihat_topologi.py       # review nodes, cables, empty ports
```

All three are re-runnable: existing nodes are skipped and cables are not duplicated. The API password is read from GNS3's own settings file, never from the repo.

4. **[script]** Push the IOS configuration over the GNS3 *console* (raw socket), because new devices have no IP or SSH yet:

```powershell
python konfigurasi_lokasi.py   # R1 Fa1/0 + route, R2, SW-A, SW-B
python konfigurasi_isp.py      # ISP two legs, static routes, R2 WAN fix
python acl_lokasi_b.py         # ACL DARI-LOKASI-A on R2 Fa0/1 inbound
python pasang_ntp_router.py    # sync router clocks to 192.168.56.104 (UTC)
python nyalakan_log_router.py  # logging buffered, so ACL denies are readable
```

Assumptions baked into these scripts: GNS3 VM at `192.168.56.102`, console ports R1 `5000`, SW-A `5002`, SW-B `5003`, R2 `5004`, ISP `5006`, and the router password read from the `devices` table of the local SQLite file (device id 5). If your console ports or password source differ, edit the constants at the top of each script. Run `pasang_ntp_router.py` after `nsm-data` is up, since it is the time source.

5. **[manual]** Save running configs (`write memory`). Without it all work is lost when the nodes stop.

IOS version differences matter inside one lab: `crypto key generate rsa modulus 1024` works on newer IOS but older IOS needs `general-keys`. Switch images enable `ip routing` by default, which makes `ip default-gateway` inert; the scripts use `no ip routing` on the switches.

**Readiness check.** GNS3 node status `started` does not mean the router is forwarding. Dynamips starts the process instantly while IOS boots for about a minute. Ping the router before moving on:

```powershell
ping -n 2 192.168.56.60
ping -n 2 192.168.20.1     # wait until this answers, do not trust the GNS3 colours
```

---

## 5. Create the VMs

All VMs: Ubuntu Server, static addresses (section 2), OpenSSH server. **[manual]** for all of this section unless noted.

| VM | Install and configure |
|---|---|
| `nsm-ubuntu` | OpenLDAP (`slapd`) with base `dc=bsp,dc=id`; MySQL replica later. Load users with the generated LDIF (below). StartTLS: see [LDAP-TLS.md](LDAP-TLS.md). |
| `nsm-data` | MySQL 8 primary. Databases `nsm`, `nsm_auth`, `ecanteen`; a least-privilege `nsm_app` user. See [MYSQL.md](MYSQL.md). Also serves NTP for the routers. |
| `testUbuntu` | Apache, the E-Canteen demo app (a separate project, not in this repo), `sssd`, SFTP file server. See [LAB-WEBSERVER.md](LAB-WEBSERVER.md). |
| `nsm-files` | Samba plus `auditd`, `sssd`. Identity from LDAP via `sssd`; SMB passwords are stored locally with `smbpasswd`, so changing a password takes two steps. LDAP is only read, never written. |
| `nsm-app` | Python venv, JRE for the jar, the repo under `/home/nsmapp/NSM`. Set up in section 9. |

**LDAP users and groups. [script]** `ldap/buat_ldif.py` generates the directory structure, eight fictional users (arif, dewi, siti, joko, ...) and groups. Passwords are written as SSHA hashes into the LDIF; the plaintext goes once to `ldap/sandi-user.txt`, which is untracked. Do not copy that file to any server. Copy the LDIF to `nsm-ubuntu` and apply it with `ldapadd`.

**`sssd`. [manual]** `ldap/sssd.conf` is the `nsm-ubuntu` version (only group `sysadmin` may log in). `sftp/pasang-sftp.sh` (**[script]**, run with sudo on `testUbuntu`) installs the chrooted SFTP server and adjusts `sssd` there to also allow group `berkas`.

**Monitoring account. [manual]** Create a read-only account `nsmro` on each Linux server with an SSH key for NSM. Optional narrow sudo rights are installed by scripts in `firewall/` (all **[script]**, run with sudo on the server):

| Script | Grants `nsmro` |
|---|---|
| `pasang-baca-firewall.sh` | only `ufw status verbose` / `ufw status numbered` |
| `pasang-ubah-firewall.sh` (+ `nsm-ubah-firewall`) | one wrapper that can block a single IPv4 for 1-1440 min, and unblock its own rules; cannot disable the firewall |
| `pasang-restart-layanan.sh` (+ `nsm-restart-layanan`) | one wrapper that can restart/status only listed units (`apache2 ecanteen smbd nmbd auditd`); never `ssh`, `slapd` or `mysql` |

`nyalakan-firewall.sh` enables `ufw` with a timed safety net that disables it again after 10 minutes (argument 2-60) unless you cancel it after proving you still have access. Enabling a firewall on a network-only machine is the riskiest step in this setup; keep the timer.

---

## 6. Start order

Dependencies run network, then identity, then data, then what is monitored, then NSM.

1. **[manual]** GNS3: open `nsm-lab`, **Start all nodes**. Wait until `192.168.20.1` answers ping (section 4).
2. **[script]** Start VMs headless, `nsm-ubuntu` first because `sssd` on the others queries it at boot:

```powershell
$vbox = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
foreach ($vm in "nsm-ubuntu","nsm-data","testUbuntu","nsm-files","nsm-app") {
  & $vbox startvm $vm --type headless
}
```

3. Wait about a minute, then verify (section 7).
4. `nsm-app` starts NSM by itself (systemd units are enabled). Open `http://192.168.56.156:8080`.

If you start NSM before the lab is healthy it records real outages for machines that simply have not booted yet, and pages fill with wrong numbers. Verify first.

### Shutting down

Reverse order, and use **ACPI shutdown**, never "Power Off":

```powershell
foreach ($vm in "nsm-app","nsm-files","testUbuntu","nsm-data","nsm-ubuntu") {
  & $vbox controlvm $vm acpipowerbutton
}
& $vbox list runningvms      # repeat until only the GNS3 VM remains
```

Then stop GNS3 nodes and close GNS3. "Power Off the Machine" is the same as pulling the plug. Files usually survive, but Ubuntu records a failed boot (`recordfail=1`) and GRUB then waits at its menu for a keypress forever. The VM shows as `running` but never boots, its address is silent, and the symptoms appear elsewhere (for example NSM cannot reach LDAP and the login page says "wrong username or password"). "Save the machine state" does not break booting but can confuse a VM if its hardware changed in between.

**A VM that will not boot.** Take a screenshot of its console and send Enter if it sits at GRUB:

```powershell
& $vbox controlvm nsm-ubuntu screenshotpng $env:TEMP\vm.png
& $vbox controlvm nsm-ubuntu keyboardputscancode 1c 9c
```

Inside the VM, `last -x | head -5` showing two `reboot ... still running` lines without `shutdown` between them confirms an unclean stop. To make the trap harmless, set a timeout in each VM:

```bash
echo 'GRUB_RECORDFAIL_TIMEOUT=5' | sudo tee -a /etc/default/grub && sudo update-grub
```

---

## 7. Verify each component

| Check | How | Expected |
|---|---|---|
| Routers | `ping 192.168.56.60`, `ping 192.168.20.1` | answers |
| Path | `traceroute 192.168.20.2` from R1 | three hops: ISP, R2, SW-B |
| GNS3 computes | `GET /v2/computes` on the controller (`127.0.0.1:3080`) | both computes `connected: true`. The GNS3 VM's own compute answers on port **80**, not 3080. |
| Whole lab | **[script]** `cd backend; python uji_terjangkau.py` | `HASIL: 13 lolos, 0 gagal` |
| LDAP | `getent passwd <ldap-user>` on `testUbuntu` | the entry |
| MySQL | from `nsm-app`: `mysql -h 192.168.56.104 -u nsm_app -p nsm` | connects |

`uji_terjangkau.py` is more than a port scan: it runs real SSH commands as `nsmro` (it expects the key path set at the top of the script, adjust it), looks up an LDAP user through `sssd`, and performs a real E-Canteen login using `ldap/sandi-user.txt`. If any check fails, stop and fix it before starting NSM. The script skips itself when the lab is unreachable.

Other lab checks: `uji_ldap_ssh.py`, `uji_ldap_ecanteen.py`, `uji_ldap_hidup.py`.

---

## 8. Java truststore

Spring talks to LDAP with StartTLS and verifies the certificate. The JVM does not know the lab CA, and an untrusted certificate shows up as **"wrong username or password" for every account**, because the login code treats a broken LDAP as a closed door. Build a truststore that is a copy of the JDK's `cacerts` **plus** the lab CA (a store with only the lab CA would break every public CA):

```powershell
keytool -importkeystore -srckeystore "$env:JAVA_HOME\lib\security\cacerts" -srcstorepass <TRUSTSTORE_PASSWORD> -destkeystore nsm-truststore.jks -deststorepass <TRUSTSTORE_PASSWORD>
keytool -importcert -alias bsp-lab-ca -file bsp-lab-ca.crt -keystore nsm-truststore.jks -storepass <TRUSTSTORE_PASSWORD> -noprompt
```

Run the frontend with:

```
JAVA_TOOL_OPTIONS=-Djavax.net.ssl.trustStore=<path>/nsm-truststore.jks -Djavax.net.ssl.trustStorePassword=<TRUSTSTORE_PASSWORD>
```

On `nsm-app` this is set in the `nsm-frontend` systemd unit. `*.jks` is git-ignored.

---

## 9. Install NSM on `nsm-app`

1. **[manual]** Copy the repo to `/home/nsmapp/NSM` (or deploy with `backend/kirim_ke_nsmapp.py`, see [OPERATIONS.md](OPERATIONS.md)). Create the venv and install:

```bash
cd /home/nsmapp/NSM/backend
python3 -m venv venv
./venv/bin/pip install -r requirements.txt drain3
```

2. **[manual]** `cp .env.contoh .env` and fill in the placeholders: database host/user/password, device SSH user, LDAP URL (`ldap://192.168.20.101:389`). For the frontend copy `application.properties.contoh` to `application.properties` and set the datasource, SMTP and base URL. Both files are git-ignored.
3. **[script]** Create the schema, then register devices:

```bash
./venv/bin/python init_db.py            # creates tables from models; seeds 3 sample rows on an empty DB
./venv/bin/python add_cisco_router.py   # routers/switches (reads DEVICE_SSH_* from .env)
./venv/bin/python add_testubuntu.py
./venv/bin/python add_file_server.py
./venv/bin/python set_layanan.py --daftar
```

Some `add_*`/`migrate_*` scripts write the legacy SQLite file `nsm.db` directly; with MySQL as the database, prefer the scripts that go through `database.py` (for example `add_file_server.py`, `set_layanan.py`, and the `migrate_*` scripts that use SQLAlchemy `inspect`). Leaving `NSM_DB_HOST` empty runs NSM on local SQLite, which is enough to try it without the full lab.

4. **[manual]** Create three systemd units: `nsm-poller` (`python -u poller.py`), `nsm-api` (`python -m uvicorn main:app --host 127.0.0.1 --port 8000`), `nsm-frontend` (`java -jar .../frontend-0.0.1-SNAPSHOT.jar`, with the truststore variable). Set `WorkingDirectory=/home/nsmapp/NSM/backend` for the Python units; unit files are not included in the repo. Build the jar on the host with `frontend/mvnw package`. `ufw` on `nsm-app` should allow only `22/tcp` and `8080/tcp` (plus UDP `1514` and `1162` if you enable the receivers).
5. **[manual]** Enable and start: `sudo systemctl enable --now nsm-poller nsm-api nsm-frontend`.
6. First login: the first admin password is generated randomly and printed **once** to the frontend console/journal on first start (`journalctl -u nsm-frontend`). Copy it then. With LDAP enabled, only directory users with an NSM group (`nsm-admin` or `nsm-viewer`) can log in.

---

## 10. What a populated lab looks like

Snapshot of the inventory NSM watches (lab numbers, 11 devices):

| Device | Address | Type |
|---|---|---|
| Home ISP router | `192.168.1.1` | router |
| Host laptop (local connector) | home LAN address | pc |
| LDAP directory (`nsm-ubuntu`) | `192.168.20.101` | Linux server |
| R1 | `192.168.56.60` | Cisco IOS router |
| Web server (`testUbuntu`) | `192.168.56.103` | Linux server |
| Host laptop (via SSH, restricted account) | `192.168.56.1` | Windows pc |
| SW-A | `192.168.56.61` | Cisco IOS switch |
| R2 | `192.168.20.1` | Cisco IOS router |
| SW-B | `192.168.20.2` | Cisco IOS switch |
| Data server (`nsm-data`) | `192.168.56.104` | Linux server |
| File server (`nsm-files`) | `192.168.56.105` | Linux server |

Critical devices (`penting=1`): the LDAP directory, R1, the data server. Cisco devices and Linux servers also carry SNMPv3 (authPriv, SHA/AES) credentials; set them with `set_snmp.py` (see [SNMP.md](SNMP.md)). The laptop is monitored with the local connector (`set_lokal.py`), which opens no port and stores no credentials. See [SSH-WINDOWS.md](SSH-WINDOWS.md) for the SSH variant. Backups are covered in [BACKUP.md](BACKUP.md).

On a healthy lab most tables hold little: the local SQLite buffer (`penyangga.db`) is only a fallback for when MySQL is unreachable, so a nearly empty buffer is normal.

Indicative sizes from the lab: `testUbuntu` and `nsm-data` 25 GB disks, `nsm-ubuntu` about 10 GB (the fullest, around 70%), `nsm-app` about 4 GB RAM (poller about 270 MB, JVM about 670 MB). GNS3 VM RAM 3 GB; node RAM about 1.4 GB (R1 512 MB, R2 256, ISP 256, SW-A 192, SW-B 192).

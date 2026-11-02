# Enabling SNMPv3 on Devices

NSM reads interface counters over SNMPv3 (authPriv, read-only) and falls back to
SSH when SNMP is not configured or fails. Steps A and B are done **on the
devices**; step C registers the credentials in NSM. All addresses are from the
author's lab (see the [README](../README.md) disclaimer).

Step markers: `[manual]` = you run it on a device or your machine, `[script]` =
done by a repo script.

## Why SNMP, and why v3

An SSH read means TCP connect, key exchange, login, command, close: 1-2 seconds
and device CPU, every 30 seconds. SNMP is one UDP request and one reply. That is
why Zabbix, LibreNMS, PRTG and Cacti use it for periodic data.

| | v2c | v3 |
|---|---|---|
| Identity | community string (a single shared secret) | user name + passwords |
| On the wire | **plaintext, sniffable** | authenticated (hash) |
| Payload | **plaintext** | **encrypted** (priv) |
| Setup | one line | several lines |

NSM uses **authPriv** (SHA authentication, AES encryption). SNMP here is
read-only and returns counters and status (bytes, interface state, uptime), not
the content of traffic. Reader selection order in the poller is: local (if the
device is the NSM host itself), SNMP, then SSH.

SNMP traps are a separate channel and are not covered here: the trap receiver
(`SNMPTRAP_AKTIF`, UDP 1162) is v2c and unauthenticated, so traps are treated as
evidence, never as a trigger for action.

## Credentials to choose [manual]

Pick once; reuse the same on every device.

| | Value |
|---|---|
| SNMP user | `nsmmon` (example) |
| Auth password | `<SNMP_AUTH_PASSWORD>`, at least **8 characters** |
| Privacy key | `<SNMP_PRIV_PASSWORD>`, at least **8 characters** |
| Protocols | SHA (auth) + AES (privacy) |

SNMPv3 requires at least 8 characters; shorter values are rejected without a
clear message. Use values different from the device's SSH password.

## A. Ubuntu VMs [manual]

Identical for every Linux VM (lab: `192.168.56.103` and others). Run on the VM.

1. Install:

   ```bash
   sudo apt update
   sudo apt install -y snmpd snmp
   ```

2. Stop the daemon first. SNMPv3 users cannot be added while it runs:

   ```bash
   sudo systemctl stop snmpd
   ```

3. Create a read-only user:

   ```bash
   sudo net-snmp-create-v3-user -ro -A '<SNMP_AUTH_PASSWORD>' -a SHA -X '<SNMP_PRIV_PASSWORD>' -x AES nsmmon
   ```

   `-ro` read-only, `-A/-a` auth password/protocol, `-X/-x` privacy
   key/protocol. The user is written to `/var/lib/snmp/snmpd.conf`.

4. Listen on the VM's lab address. By default Ubuntu's `snmpd` listens on
   localhost only:

   ```bash
   sudo nano /etc/snmp/snmpd.conf
   ```

   Change `agentaddress  127.0.0.1,[::1]` to (use that VM's own address):

   ```
   agentaddress  127.0.0.1,192.168.56.103
   ```

   Do not use `0.0.0.0`: it listens on every network, including any NAT/internet
   facing adapter. A specific address limits the attack surface.

5. Start and enable:

   ```bash
   sudo systemctl start snmpd
   sudo systemctl enable snmpd
   sudo systemctl status snmpd      # expect: active (running)
   ```

6. Test from the VM itself:

   ```bash
   snmpget -v3 -l authPriv -u nsmmon -a SHA -A '<SNMP_AUTH_PASSWORD>' -x AES -X '<SNMP_PRIV_PASSWORD>' localhost 1.3.6.1.2.1.1.5.0
   ```

   It must return the host name. If it fails, fix the VM before touching NSM.

7. Optional: the same command from your workstation with the VM's IP instead of
   `localhost`. Step C also tests the connection.

If a host firewall is active, allow UDP 161 from the NSM host (for example
`sudo ufw allow from 192.168.56.1 to any port 161 proto udp`).

## B. Cisco IOS router [manual]

Emulated Cisco router (Dynamips). Via the GNS3 console or SSH:

```
enable
configure terminal

snmp-server view NSMVIEW iso included
snmp-server group NSMGRUP v3 priv read NSMVIEW
snmp-server user nsmmon NSMGRUP v3 auth sha <SNMP_AUTH_PASSWORD> priv aes 128 <SNMP_PRIV_PASSWORD>

end
write memory
```

The view defines what may be read; the group requires `priv` (auth + encryption)
and grants **read only** on that view; there is no `write` keyword anywhere, so
the device cannot be changed over SNMP. Verify:

```
show snmp user
show snmp group
```

Emulated Dynamips routers are slow; an occasional missing SNMP reply is an
emulation limit, not a misconfiguration. NSM retries, then falls back to SSH.

## C. Register in NSM [manual + script]

On the NSM host. The poller and uvicorn may keep running; the commands write one
row.

```
cd C:\Users\<user>\NSM\backend
venv\Scripts\activate
pip install -r requirements.txt          # pysnmp>=7,<8 (asyncio API)
```

The six SNMP columns (`snmp_user`, `snmp_auth_pass`, `snmp_priv_pass`,
`snmp_auth_proto`, `snmp_priv_proto`, `snmp_port`) exist in the model, so a fresh
`init_db.py` creates them. Only a database created before SNMP support needs
`python migrate_snmp_columns.py` (it migrates the SQLite file `nsm.db`; run it
with the poller and uvicorn stopped).

List devices and their ids:

```
python set_snmp.py --daftar
```

Register each device (ids are those in your database; lab examples):

```
python set_snmp.py 4 nsmmon <SNMP_AUTH_PASSWORD> <SNMP_PRIV_PASSWORD>
python set_snmp.py 5 nsmmon <SNMP_AUTH_PASSWORD> <SNMP_PRIV_PASSWORD> --proto SHA AES
```

Options: `--proto <AUTH> <PRIV>` (auth SHA, SHA256, MD5; privacy AES, DES; default
SHA/AES), `--port <n>` (default 161). The script **tests the connection first**
and stores credentials only on success. Remove SNMP from a device (back to SSH):

```
python set_snmp.py 4 --hapus
```

Restart the poller so it loads the credentials, then look for the proof in its
console:

```
[bw] <device>: 2 interface terbaca (via snmp)
```

`via snmp` means SNMP was used; `via ssh` means it was not. If SNMP fails and the
device has SSH credentials the poller prints `SNMP gagal (...) -> coba SSH` and
reads over SSH.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `set_snmp.py` cannot connect | `snmpd` not running, or `agentaddress` still localhost only |
| Works inside the VM, fails from the host | `agentaddress` not changed, or a firewall blocks UDP 161 |
| Fails only across sites | the inter-site ACL must permit UDP 161 from the NSM host to that device (see [TOPOLOGY](TOPOLOGY.md)) |
| `net-snmp-create-v3-user` refuses | `snmpd` still running |
| Cisco rejects `snmp-server user` | password shorter than 8 characters |
| Poller still prints `via ssh` | poller not restarted after `set_snmp.py` |
| Intermittent failures on emulated routers | emulation latency; SSH fallback covers it |

## Security notes

- SNMP credentials are stored as plain text in the NSM database, like SSH
  passwords for password-authenticated devices. Keep database files and backups
  out of Git and encrypt copies that leave the machine (see
  [BACKUP](BACKUP.md)).
- Use SNMP passwords different from SSH passwords.
- The user is read-only everywhere: a leaked credential exposes statistics, not
  configuration.
- Only poll devices you own or are explicitly authorized to poll; never guess
  community strings or credentials of devices that are not yours.

# SSH Remote Access to a Windows Host

This guide opens an SSH path to the Windows laptop (`LAB-PC`) and then locks it
down as far as it will go. The result: NSM can read the Windows machine remotely
the same way it reads a Linux VM, which also demonstrates remote access to
Windows. Everything is done by hand on the Windows host (`[manual]`); only the
final registration uses a repo script (`[script]`).

## Why one machine has two device rows

| Row | Path | Used for |
|---|---|---|
| **Laptop Sendiri** ("own laptop") | local (`psutil`) | daily data: bandwidth every 30 s, CPU, memory, disk |
| **Laptop (via SSH)** | SSH + key | proving remote access to Windows |

The local path opens no port and stores no credentials, so it stays the daily
source. The SSH row is read occasionally (when you open its detail view), not
every 30 seconds. The dashboard shows both side by side so the numbers and the
cost difference can be compared.

## Why a key, not a password

Device passwords are stored as-is in the NSM database, and backups of that
database leave the machine (see [BACKUP](BACKUP.md)). With a key, the database
holds only the **path** of the key file.

Honest limit: the private key has no passphrase, because the poller runs
unattended. What actually improves: the secret is no longer inside files that get
copied off the machine, and revoking access is deleting one line instead of
changing a Windows account password.

## Step 1: a dedicated Windows account [manual]

Do not use your main account. In PowerShell **as Administrator**:

```
$pw = Read-Host -AsSecureString "Password for the nsmssh account"; New-LocalUser -Name "nsmssh" -Password $pw -FullName "NSM Monitoring" -Description "Read-only account for Network Status Monitor" -PasswordNeverExpires
```

The password is needed once, in Step 3, and replaced by a random one in Step 5.
Confirm the account is **not** an administrator:

```
Get-LocalGroupMember -Group "Administrators" | Select-Object Name
```

`nsmssh` must not appear.

## Step 2: firewall first, service second [manual]

Installing OpenSSH creates a rule that allows port 22 from anywhere. If the
service starts first, the laptop briefly accepts SSH from whatever Wi-Fi network
it is on. In PowerShell **as Administrator**, one command at a time:

```
Get-WindowsCapability -Online -Name OpenSSH.Server* | Select-Object Name, State
```

If `State` is not `Installed`:

```
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
```

Disable the permissive default rule:

```
Get-NetFirewallRule -Name *OpenSSH-Server* -ErrorAction SilentlyContinue | Disable-NetFirewallRule
```

Add a rule that allows only the lab network:

```
New-NetFirewallRule -Name "NSM-SSH-LabOnly" -DisplayName "SSH from NSM lab network only" -Enabled True -Direction Inbound -Protocol TCP -LocalPort 22 -RemoteAddress 192.168.56.0/24 -Action Allow
```

Now start the service:

```
Start-Service sshd; Set-Service -Name sshd -StartupType Automatic; Get-Service sshd
```

Check that port 22 is open only to the lab network:

```
Get-NetFirewallRule -Direction Inbound -Enabled True -Action Allow | Where-Object { ($_ | Get-NetFirewallPortFilter).LocalPort -eq 22 } | Select-Object Name, @{n='From';e={ ($_ | Get-NetFirewallAddressFilter).RemoteAddress }}
```

Expect **exactly one** rule, from `192.168.56.0/255.255.255.0` (Windows prints the
long mask for `/24`).

## Step 3: log in once so the profile folder exists [manual]

Windows creates `C:\Users\nsmssh` only after the first login; the key list needs
that folder. Avoid the "Switch user" screen (new local accounts often do not
appear on the Windows 11 lock screen). Use SSH over loopback, which the firewall
rule does not filter. Normal PowerShell:

```
ssh nsmssh@localhost
```

Answer `yes` to the host fingerprint and enter the Step 1 password. A prompt like
`nsmssh@LAB-PC C:\Users\nsmssh>` means success; type `exit`.

## Step 4: create the key and install the public half [manual]

Normal PowerShell, as your own account:

```
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\nsm_laptop" -N '""' -C "NSM monitoring"
```

No passphrase, deliberately (see above); safety comes from the restricted account
and the firewall. Tighten the private key's permissions:

```
icacls "$env:USERPROFILE\.ssh\nsm_laptop" /inheritance:r /grant "$env:USERNAME:F"
```

Install the public key, in PowerShell **as Administrator** (replace `<user>` with
your Windows user name):

```
$pub = (Get-Content "C:\Users\<user>\.ssh\nsm_laptop.pub" -Raw).Trim(); $dir = "C:\Users\nsmssh\.ssh"; New-Item -ItemType Directory -Force -Path $dir | Out-Null; Set-Content -Path "$dir\authorized_keys" -Value $pub -Encoding ascii; icacls "$dir\authorized_keys" /inheritance:r /grant "nsmssh:R" /grant "SYSTEM:F" /grant "Administrators:F"
```

Two silent-failure traps are handled in that command:

- `-Encoding ascii`, not `utf8`: PowerShell 5.1 adds an invisible BOM and OpenSSH
  rejects a BOM-prefixed file without any message.
- `icacls ... /inheritance:r`: OpenSSH rejects an `authorized_keys` that other
  accounts can write, also silently. `nsmssh:R` is read-only, so the account can
  read the list that admits it but cannot add keys for itself.

## Step 5: test the key, then discard the password [manual]

`BatchMode=yes` disables password fallback, so success proves the key worked:

```
ssh -i "$env:USERPROFILE\.ssh\nsm_laptop" -o BatchMode=yes nsmssh@192.168.56.1 hostname
```

It must print the computer name without prompting. Then replace the account
password with a random one (Administrator PowerShell); nobody needs to know it:

```
Add-Type -AssemblyName System.Web; Set-LocalUser -Name "nsmssh" -Password (ConvertTo-SecureString ([System.Web.Security.Membership]::GeneratePassword(28,8)) -AsPlainText -Force)
```

## Step 6: register in NSM [script]

```
cd C:\Users\<user>\NSM\backend
venv\Scripts\activate
python add_laptop_ssh.py nsmssh C:\Users\<user>\.ssh\nsm_laptop --ip 192.168.56.1
```

Use `192.168.56.1`, the VirtualBox host-only address of the host: it never
changes when you switch networks (Wi-Fi addresses do), and it matches the
firewall rule, so NSM tests the permitted path rather than the loopback gap.

The script tests the connection and **saves only on success**. It stores no
password (the password column stays empty, only the key path is saved) and
creates the device row `Laptop (via SSH)` (platform `windows`). Pass the
**private** key, not the `.pub` file (the script refuses `.pub`). Then restart the
poller and uvicorn.

## What can and cannot be read

NSM runs a fixed list of read-only commands over a single SSH connection for a
Windows device: `hostname`, `ver`, `whoami`, the IPv4 line of `ipconfig`, and the
free-space line of `dir C:\`. Measured in the lab against the `nsmssh` account
(Windows 11 build 26200):

| Command | Result |
|---|---|
| `hostname`, `ver`, `whoami` | works |
| `ipconfig` IPv4 address | works |
| `dir C:\` free space | works |
| `tasklist` | **Access denied** |
| `systeminfo` | **Access denied** |
| any `Get-CimInstance` (WMI) | **Access denied** |
| `wmic` | removed from this Windows 11 build |

The short list is the lockdown working: if the key leaks, an attacker can read
the computer name and free disk space. Do **not** add `nsmssh` to *Performance
Monitor Users* to get WMI; loosening the account defeats the reason it exists.
Full data for the same machine comes from the `Laptop Sendiri` row. PowerShell is
avoided in the command list (about 5.8 s startup per SSH call, and still
denied). Reusing one connection, the whole command list took 619 ms; separate
`ssh` invocations cost about 400 ms each.

## Comparing the two paths

| | Laptop Sendiri (local) | Laptop via SSH |
|---|---|---|
| Open ports | none | 22, limited to `192.168.56.0/24` |
| Secrets in the NSM database | none | none (key auth) |
| Secrets on disk | none | the private key file |
| Accounts involved | none | `nsmssh`, non-admin |
| Time to fetch | immediate | TCP connection + crypto handshake |
| Works for other machines | no | yes, which is the point |

SSH exists not because it is better, but because without it a machine that is not
running NSM cannot be reached at all.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `ssh` asks for a password despite `-i` | `authorized_keys` permissions too loose; repeat the `icacls` in Step 4 |
| `Connection refused` | `sshd` not running: `Start-Service sshd` |
| `Connection timed out` from a VM | Step 2 rule missing, or the VM is outside `192.168.56.0/24` |
| `Permission denied (publickey)` | public key not in `authorized_keys`, or the wrong `.pub` was pasted |
| `C:\Users\nsmssh` missing | the account never logged in (Step 3) |
| NSM fails but manual `ssh` works | registered key path is wrong or points to the `.pub` file |

## Revoking access

Four steps, most decisive first:

```
python add_laptop_ssh.py --hapus
```

```
Stop-Service sshd; Set-Service -Name sshd -StartupType Disabled
```

```
Remove-NetFirewallRule -Name "NSM-SSH-LabOnly"
```

```
Remove-LocalUser -Name "nsmssh"
```

To remove the OpenSSH server entirely (Administrator PowerShell):

```
Remove-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
```

## Design decisions worth keeping

A separate non-admin account, key instead of password authentication, a firewall
rule limited to one subnet, and a prepared revocation path. Known limit:
device credentials for password-authenticated devices are stored unencrypted in
the database in this lab (see [SECURITY](../SECURITY.md)); the key-based path
avoids that for this host only.

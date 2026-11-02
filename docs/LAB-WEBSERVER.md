# Lab Web Server and Database Server

This guide adds two roles to the lab and connects them: an Apache + PHP web
server and a MySQL database server. They exist to be a **lab-only target**: a
simple, deliberately minimal application whose services NSM monitors, whose
failures you can cause on purpose, and whose traffic feeds NSM's traffic log and
the attack/probe simulations. Everything is done in VirtualBox and inside the
VMs (`[manual]`); NSM registers the result as monitored services.

> **Lab only.** The page below keeps database credentials in its source, which is
> acceptable for a throwaway lab page and wrong for a real application. Do not
> expose these VMs to a real network. Addresses are from the author's
> single-site layout (host-only `192.168.56.0/24`); see
> [Status in the final lab](#status-in-the-final-lab).

## What gets built

| Role | VM | Address | Software |
|---|---|---|---|
| Web server | testUbuntu | `192.168.56.103` | Apache2 + PHP |
| Database server | Ubuntu | `192.168.56.101` | MySQL |
| Monitor | host | `192.168.56.1` | NSM |

A PHP page on `.103` reads a table from MySQL on `.101`. When the page shows the
row, the connection between two devices is proven on screen. Two VMs are used
rather than one because the point is traffic **between** devices; on one machine
the conversation never crosses the network and NSM could observe nothing.

`.103` already has internet, SSH and SNMPv3 working, so it takes Apache. `.101`
has no internet yet, which Part A fixes.

## Part A: give `192.168.56.101` internet access

`apt install` needs it.

### A1. Power the VM off completely [manual]

Network adapters cannot be added while it runs:

```
sudo shutdown -h now
```

Do not use "Save the machine state": the saved hardware list conflicts with the
new adapter.

### A2. Add Adapter 2 = NAT [manual]

VirtualBox Manager: VM > Settings > Network > **Adapter 2** > Enable > Attached
to **NAT** > OK.

Do not touch Adapter 1; it carries the host-only `192.168.56.101` that NSM
monitors. Using the empty slot keeps Adapter 1 as `enp0s3` and the new one
appears as `enp0s8`. If NAT were inserted as Adapter 1, the host-only adapter
would be pushed to slot 2, interface names would swap, netplan would bind the
wrong name and the VM would lose `.101` until fixed from the console.

### A3. Check the new interface [manual]

```
ip -br addr
```

`enp0s3` should still hold `192.168.56.101`. If `enp0s8` already has `10.0.x.15`
(the third octet follows the slot number), skip to A5. If it has no address,
continue.

### A4. Tell netplan [manual]

```
ls /etc/netplan/
sudo nano /etc/netplan/50-cloud-init.yaml
```

Add `enp0s8` at the same indentation as the existing `enp0s3`, leaving `enp0s3`
unchanged:

```yaml
network:
  version: 2
  ethernets:
    enp0s3:
      addresses:
        - 192.168.56.101/24
    enp0s8:
      dhcp4: true
```

YAML needs spaces, never tabs. Then:

```
sudo netplan apply
```

### A5. Prove both paths work [manual]

In the VM:

```
ping -c 2 8.8.8.8
ip -br addr
```

Internet must work and `enp0s3` must still be `192.168.56.101`. Then from the
host:

```
ping 192.168.56.101
```

If that fails, Adapter 1 was disturbed. Restore `enp0s3` in netplan from the VM
console and run `sudo netplan apply`. Do not continue until this ping works (NSM
is recording the VM as DOWN meanwhile).

### A6. Optional: enable SNMPv3 on `.101`

Not required (its bandwidth is already read over SSH). Follow
[SNMP](SNMP.md) section A **inside the VM** (install and configure `snmpd`,
`agentaddress  127.0.0.1,192.168.56.101`), then return to the host and register
it with `set_snmp.py`. Note that the NSM scripts exist only on the host; running
them in the VM fails with `Command 'python' not found`.

## Part B: MySQL on `192.168.56.101`

### B1. Install [manual]

```
sudo apt update
sudo apt install -y mysql-server
sudo systemctl status mysql        # expect: active (running); q to exit
```

### B2. Allow the web server to connect [manual]

MySQL listens on `127.0.0.1` by default:

```
sudo nano /etc/mysql/mysql.conf.d/mysqld.cnf
```

```
bind-address = 192.168.56.101
```

Use the specific address, not `0.0.0.0`; otherwise MySQL would also listen on the
NAT adapter. Then:

```
sudo systemctl restart mysql
```

### B3. Database and a restricted user [manual]

```
sudo mysql
```

At the `mysql>` prompt:

```sql
CREATE DATABASE labweb CHARACTER SET utf8mb4;
CREATE USER 'webapp'@'192.168.56.103' IDENTIFIED BY '<WEBAPP_DB_PASSWORD>';
GRANT SELECT, INSERT, UPDATE, DELETE ON labweb.* TO 'webapp'@'192.168.56.103';
USE labweb;
CREATE TABLE pesan (id INT AUTO_INCREMENT PRIMARY KEY, isi VARCHAR(200), dibuat DATETIME DEFAULT CURRENT_TIMESTAMP);
INSERT INTO pesan (isi) VALUES ('Hello World dari MySQL di 192.168.56.101');
FLUSH PRIVILEGES;
EXIT;
```

Choose your own value for `<WEBAPP_DB_PASSWORD>`; it will appear in a PHP file, so
do not reuse a password from anywhere else. The three restrictions to keep:

1. User `webapp`, not `root`: a compromised page exposes one database only.
2. Host `'192.168.56.103'`, not `'%'`: a leaked credential is useless from any
   other machine.
3. No `DROP` or `CREATE`: the app needs only row access.

## Part C: Apache and PHP on `192.168.56.103`

All commands run inside testUbuntu.

### C1. Install [manual]

```
sudo apt update
sudo apt install -y apache2 php libapache2-mod-php php-mysql
sudo systemctl status apache2      # expect: active (running)
```

### C2. Test Apache from the host first [manual]

Open `http://192.168.56.103` in a browser. The default Apache page must appear.
If not, stop: the problem is network or Apache, and adding PHP only adds
suspects.

### C3. The connectivity page [manual]

```
sudo nano /var/www/html/hello.php
```

```php
<?php
// Two-device connectivity test:
// web server 192.168.56.103, database 192.168.56.101.
// If a row from `pesan` shows up, the conversation really crossed the network.

$db_host = '192.168.56.101';
$db_user = 'webapp';
$db_pass = '<WEBAPP_DB_PASSWORD>';   // lab only; real apps keep this outside the web root
$db_name = 'labweb';

header('Content-Type: text/html; charset=utf-8');
echo "<h1>Hello World</h1>";
echo "<p>Web server: 192.168.56.103 (Apache + PHP " . phpversion() . ")</p>";

$mysqli = @new mysqli($db_host, $db_user, $db_pass, $db_name);

if ($mysqli->connect_errno) {
    // Shown as-is on purpose: this is a lab page, and an honest failure message
    // is more useful than "an error occurred".
    http_response_code(503);
    echo "<p style='color:#b00'>FAILED to connect to the database at $db_host</p>";
    echo "<pre>" . htmlspecialchars($mysqli->connect_error) . "</pre>";
    exit;
}

echo "<p style='color:#070'>Connected to MySQL at $db_host</p>";

$result = $mysqli->query("SELECT id, isi, dibuat FROM pesan ORDER BY id DESC LIMIT 5");
echo "<ul>";
while ($row = $result->fetch_assoc()) {
    echo "<li>" . htmlspecialchars($row['isi'])
       . " <small>(" . htmlspecialchars($row['dibuat']) . ")</small></li>";
}
echo "</ul>";

$mysqli->close();
```

Open `http://192.168.56.103/hello.php`. Success is the green line "Connected to
MySQL at 192.168.56.101" **and** the row `Hello World dari MySQL di
192.168.56.101` fetched from the other VM. (If you keep the English strings
above, adjust any NSM "expected text" check accordingly; the lab's own checks used
the Indonesian originals.)

### C4. A large file for traffic tests [manual]

```
sudo dd if=/dev/urandom of=/var/www/html/uji-50mb.bin bs=1M count=50
```

Without a file this size the bandwidth numbers never leave zero. Random bytes
are a decoy file, not real data. Downloading it from the host later proves the
traffic log records who fetched what.

## Register the services in NSM [script]

On the host (ids come from `--daftar`; lab examples):

```
cd C:\Users\<user>\NSM\backend
venv\Scripts\activate
python set_layanan.py --daftar
python set_layanan.py 6 http  80   --nama "Web Server" --path /hello.php
python set_layanan.py 6 http  80   --nama "Hello page" --path /hello.php --teks "Hello World"
python set_layanan.py 4 mysql 3306 --nama "MySQL labweb"
```

`set_layanan.py` tests the service first and refuses to save one that fails
(`--paksa` overrides). Kinds are `tcp`, `http`, `mysql`; `--teks` makes an HTTP
check fail when an error page still returns 200. Pause a service without losing
history with `--jeda <service-id>` / `--lanjut <service-id>`; delete with
`--hapus <service-id>`.

## Part D: break things one at a time, watch NSM catch them

| You do (in the VM) | NSM should show |
|---|---|
| `sudo systemctl stop apache2` on `.103` | ping stays green, **HTTP service red** ("connection refused") |
| `sudo systemctl start apache2` | HTTP green again, the incident closes with its duration |
| `sudo systemctl stop mysql` on `.101` | MySQL service red on `.101`, **and** `hello.php` answers 503 |
| download `uji-50mb.bin` from the host | traffic log: the host IP downloaded 50 MB from `.103` |

Stopping Apache versus powering off the VM is the heart of the feature: the host
still answers ping, so ping-only monitoring would report everything healthy while
the service is down.

The repo's `simulasi_serangan.py` (port probes against ports the firewall is
expected to deny) targets the same lab servers; it makes plain TCP connection
attempts to closed ports so the firewall pages have refusals to show, and
exploits nothing.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `apt update` on `.101` cannot resolve | Adapter 2 not NAT, or `enp0s8` has no address; redo A3 and A4 |
| Host cannot ping `.101` after Part A | Adapter 1 disturbed; check `enp0s3` in netplan via the console |
| `hello.php`: `Connection refused` | `bind-address` unchanged, or MySQL not restarted |
| `hello.php`: `Access denied for user 'webapp'` | host in `CREATE USER` must be exactly `'webapp'@'192.168.56.103'` |
| `hello.php` shows raw PHP | `libapache2-mod-php` missing; reinstall and `sudo systemctl restart apache2` |
| Apache page loads, `hello.php` is 404 | file not in `/var/www/html/` |
| Everything right, host cannot open `.103` | `sudo ufw status`; if active, `sudo ufw allow 80/tcp` |

## Security notes

- The database password sits in `hello.php` in clear text. Fine for this page;
  in anything real move it to configuration outside the web root.
- `.101` now has outbound internet via NAT. NAT does not allow inbound
  connections, but keep the VM patched (`apt upgrade`).
- `uji-50mb.bin` is random data on purpose.

## Status in the final lab

This guide describes the original single-site layout. When the lab became a
two-site topology (see [TOPOLOGY](TOPOLOGY.md)), the directory/database VM moved
to `192.168.20.101` behind the inter-site ACL, which no longer permits MySQL
across sites. `hello.php` would then point at an address that no longer
exists; NSM was the thing that noticed (the TCP check passed, the page-content
check failed). The service check was paused rather than fixed, because the
E-Canteen demo app exercises the same web-to-database path more realistically
and because a database queried dozens of times per page belongs next to its web
server (a cross-site hop was measured at about 152 ms per round trip).
To reproduce the guide as written, keep both VMs on the host-only network.

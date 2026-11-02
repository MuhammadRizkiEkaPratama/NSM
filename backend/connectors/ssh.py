from netmiko import ConnectHandler

from connectors.base import BaseConnector

# Read-only commands for Linux, run via SSH exec (paramiko).
LINUX_CMDS = {
    "Hostname": "hostname",
    "OS": "grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"'",
    "Kernel": "uname -r",
    "Alamat IP": "ip -br addr",
    "Uptime": "uptime -p",
    "Beban CPU (load average)": "uptime",
    "Memori": "free -h",
    "Disk (/)": "df -h /",
    "User yang login": "loginctl list-sessions 2>/dev/null || who",
    # Top processes by CPU, excluding the measuring processes themselves (`ps`, `awk`
    # and the wrapping shell). Otherwise `ps` reports ~200% for itself and pushes a
    # real process out of the top five.
    #
    # `sshd-session` is deliberately kept: SSH connections are real load on the
    # device. That some of them belong to NSM is stated in the note below the output.
    #
    # `head -7` = one header line plus one spare line to replace filtered ones.
    "5 proses teratas (CPU, tanpa proses pengukurnya)":
        "ps -eo pcpu,pmem,comm --sort=-pcpu | "
        "awk 'NR==1 || ($3!=\"ps\" && $3!=\"awk\" && $3!=\"sh\" && $3!=\"bash\")' | "
        "head -6",
}

CATATAN_LINUX = {
    "5 proses teratas (CPU, tanpa proses pengukurnya)":
        "Baris sshd-session yang muncul di sini sebagian adalah sambungan NSM "
        "sendiri: membaca daftar proses lewat SSH ikut menambah beban yang "
        "sedang diukur. Proses `ps` yang menjalankan pengukuran ini sudah "
        "dibuang dari daftar karena ia selalu melaporkan dirinya di urutan "
        "teratas dan mendorong keluar satu proses sungguhan.",
}


# Read-only commands for Windows over SSH exec.
#
# The list is short on purpose. A non-admin account cannot read WMI, the process
# list, or system statistics (access denied), and `wmic` no longer exists on
# Windows 11. PowerShell is avoided: ~5.8 s startup per call over SSH, and it is
# still denied. This row only proves the remote path works; full data for the
# same machine comes from the local connector.
WINDOWS_CMDS = {
    "Hostname": "hostname",
    "OS": "ver",
    "Akun yang dipakai NSM": "whoami",
    "Alamat IP": "ipconfig | findstr /i \"IPv4\"",
    "Sisa disk C:": "dir C:\\ | findstr /i \"free\"",
    "Cara dibaca": ("echo Lewat SSH dari 192.168.56.1 memakai kunci, sebagai "
                    "akun non-admin. Isinya sengaja terbatas: akun ini tidak "
                    "punya hak membaca WMI, daftar proses, atau statistik "
                    "sistem. Untuk data lengkap mesin yang sama, lihat device "
                    "Laptop Sendiri yang dibaca langsung."),
}


class SshConnector(BaseConnector):
    def __init__(self, ip_address, platform=None, username=None, password=None,
                 key_path=None):
        super().__init__(ip_address)
        self.platform = platform      # linux / windows / cisco_ios
        self.username = username
        self.password = password
        # If set, key-based login is used and the password is ignored.
        self.key_path = key_path or None

    def check_reachable(self):
        """SSH relies on ICMP for the up/down check."""
        from connectors.icmp import IcmpConnector
        return IcmpConnector(self.ip_address).check_reachable()

    def get_info(self):
        if self.platform == "cisco_ios":
            return self._cisco_info()
        if self.platform == "windows":
            return self._exec_info(WINDOWS_CMDS)
        return self._exec_info(LINUX_CMDS, catatan=CATATAN_LINUX)  # default: linux

    # ---- Cisco IOS: netmiko (needs an IOS CLI session) ----
    def _cisco_info(self):
        if not self.platform:
            raise ValueError("Platform belum diisi untuk device ini")
        conn = ConnectHandler(
            device_type=self.platform,
            host=self.ip_address,
            username=self.username,
            password=self.password,
        )
        try:
            hasil = {
                "Hostname": conn.send_command("show run | include hostname").strip(),
                "Versi IOS": conn.send_command("show version | include Cisco IOS Software").strip(),
                "Uptime": conn.send_command("show version | include uptime").strip(),
                "Interface (ringkas)": conn.send_command("show ip interface brief").strip(),
                "Tabel Routing": conn.send_command("show ip route").strip(),
                "CPU": conn.send_command("show processes cpu | include CPU utilization").strip(),
            }
        finally:
            conn.disconnect()
        return hasil

    # Bandwidth: read per-interface byte counters. The rate is computed from two
    # readings (see poller.py); the functions here only read the counters.

    def get_bandwidth(self):
        """Return {iface: {"in_octets": x, "out_octets": y}}.

        For Cisco the result holds "in_bps"/"out_bps" instead, because IOS already
        reports a rate (see `_cisco_bandwidth`).
        """
        if self.platform == "cisco_ios":
            return self._cisco_bandwidth()
        if self.platform == "windows":
            # Intentionally empty, not a failure. The Windows SSH row only proves remote
            # access; the same machine's counters come from the local connector.
            return {}
        return self._linux_bandwidth()

    # ---- Linux: /proc/net/dev ----
    def _linux_bandwidth(self):
        """Read /proc/net/dev, the authoritative interface statistics on Linux.
        Column 1 is bytes received, column 9 is bytes sent.
        """
        output = self._exec_info({"raw": "cat /proc/net/dev"})
        teks = output.get("raw", "")
        hasil = {}
        for line in teks.splitlines():
            if ":" not in line:
                continue  # first two lines are headers
            nama, number = line.split(":", 1)
            nama = nama.strip()
            if nama == "lo":
                continue
            section = number.split()
            if len(section) < 9:
                continue
            try:
                hasil[nama] = {
                    "in_octets": float(section[0]),
                    "out_octets": float(section[8]),
                }
            except ValueError:
                continue
        return hasil

    # ---- Cisco IOS: show interfaces ----
    def _cisco_bandwidth(self):
        """Read the rate from 'show interfaces'.

        IOS computes it itself ("5 minute input rate 2000 bits/sec, ..."), so no counter
        delta is needed. It is IOS's 5-minute moving average, not an instantaneous
        rate: smoother, but slow to react to spikes.
        """
        import re

        conn = ConnectHandler(
            device_type=self.platform,
            host=self.ip_address,
            username=self.username,
            password=self.password,
        )
        try:
            teks = conn.send_command("show interfaces")
        finally:
            conn.disconnect()

        hasil = {}
        iface = None
        for line in teks.splitlines():
            # Interface header lines are not indented, e.g. "FastEthernet0/0 is up, ...".
            if line and not line[0].isspace() and " is " in line:
                iface = line.split()[0]
                if iface not in hasil:
                    hasil[iface] = {"in_bps": None, "out_bps": None}
                continue
            if iface is None:
                continue
            cocok = re.search(r"input rate\s+(\d+)\s+bits/sec", line)
            if cocok:
                hasil[iface]["in_bps"] = float(cocok.group(1))
            cocok = re.search(r"output rate\s+(\d+)\s+bits/sec", line)
            if cocok:
                hasil[iface]["out_bps"] = float(cocok.group(1))

        return {k: v for k, v in hasil.items()
                if v.get("in_bps") is not None or v.get("out_bps") is not None}

    # ---- Linux & Windows: direct SSH exec (paramiko), no prompt detection ----
    def jalankan_perintah(self, perintah, timeout=15):
        """Run ONE read-only command and return its raw output.

        Used by the saturation job, which needs raw numbers rather than the labeled
        tables of `_exec_info`. Read-only is not enforced here; it relies on the `nsmro`
        account's sudoers limits on the device. State-changing commands go through
        `kirim_perintah.py`, which has permissions and an audit trail.
        """
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            if self.key_path:
                client.connect(self.ip_address, username=self.username,
                               key_filename=self.key_path, timeout=timeout,
                               banner_timeout=timeout + 5,
                               allow_agent=False, look_for_keys=False)
            else:
                client.connect(self.ip_address, username=self.username,
                               password=self.password, timeout=timeout,
                               banner_timeout=timeout + 5,
                               allow_agent=False, look_for_keys=False)
            _in, out, err = client.exec_command(perintah, timeout=timeout)
            return (out.read() + err.read()).decode("utf-8", "replace")
        finally:
            client.close()

    def _exec_info(self, cmds, timeout=12, catatan=None):
        """Run a set of read-only commands and return {label: output}.

        `catatan` (optional) maps a label to a note appended below its output, e.g.
        that part of the load comes from NSM's own SSH session.
        """
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        # allow_agent=False, look_for_keys=False are required.
        #
        # By default paramiko tries the local SSH agent and every key in ~/.ssh before
        # the password. That can fail with a confusing "lost ssh-agent" error even when
        # the password is right, or log in with an unrelated key. The identity must be
        # exactly the one in the device row (the key file if set, otherwise the password).
        if self.key_path:
            client.connect(self.ip_address, username=self.username,
                           key_filename=self.key_path, timeout=timeout,
                           allow_agent=False, look_for_keys=False)
        else:
            client.connect(self.ip_address, username=self.username,
                           password=self.password, timeout=timeout,
                           allow_agent=False, look_for_keys=False)
        hasil = {}
        try:
            for label, cmd in cmds.items():
                try:
                    _in, out, err = client.exec_command(cmd, timeout=timeout)
                    o = out.read().decode(errors="replace").strip()
                    e = err.read().decode(errors="replace").strip()
                    hasil[label] = o if o else (e if e else "(kosong)")
                except Exception as ex:
                    hasil[label] = f"(gagal: {ex})"
                if catatan and label in catatan:
                    hasil[label] += "\n\n# " + catatan[label]
        finally:
            client.close()
        return hasil

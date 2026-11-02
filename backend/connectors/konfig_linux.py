"""Security configuration snapshot of a Linux machine, assembled into one text.

Cisco IOS has one command that returns the whole configuration as text; Linux does not.
Security settings are spread over many files and runtime states: `/etc/ssh/sshd_config`,
group membership, listening ports, firewall state, UID 0 accounts. This module ASSEMBLES
them into one fixed-shape document so everything built for Cisco works unchanged:
`konfig_snapshots` stores it, the fingerprint decides when a real change happened,
line diffs work, and `connectors/kepatuhan.py` judges it with the same evaluator.

READ-ONLY: no command changes anything, and none needs sudo (checked beforehand with
`cek_hak_akun.py` on both VMs).

Why not `sshd -T`: it gives the EFFECTIVE configuration, a more accurate answer than
reading the file, but it needs root. A rule needing more privilege than the monitoring
account has would force raising that account's rights, the opposite of the finding being
reported. The file is read instead, and the result states that limit openly.
"""
import re

# Collector commands, written out as a list so anyone can inspect them before they run and
# "what does NSM read from my machine" has an answer that can be pointed at.
#
# Shape: (section title, shell command)
PERINTAH = [
    # INCLUDED FILES ARE READ TOO, for correctness. On Ubuntu `/etc/ssh/sshd_config` contains
    # `Include /etc/ssh/sshd_config.d/*.conf`, and files there OVERRIDE the ones above them:
    # the cloud provider's `50-cloud-init.conf` routinely sets `PasswordAuthentication yes`.
    #
    # Reading only the main file would give a confident wrong answer: a rule would report
    # "passwords refused" for a machine that accepts them.
    ("sshd",
     "cat /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null "
     "| grep -vE '^\\s*(#|$)' | sort -u"),
    ("port-mendengarkan",
     # Address:port column only, sorted. PID and process name are deliberately NOT collected:
     # `ss -p` needs root for other users' processes, and what is judged is the open door, not
     # who opened it.
     "ss -tlnH 2>/dev/null | awk '{print $4}' | sort -u"),
    ("firewall", "systemctl is-active ufw 2>/dev/null || echo tidak-terpasang"),
    ("akun-uid0", "awk -F: '$3==0 {print $1}' /etc/passwd 2>/dev/null | sort"),
    ("akun-bershell",
     "awk -F: '$7 !~ /(nologin|false)$/ {print $1\":\"$7}' /etc/passwd "
     "2>/dev/null | sort"),
    ("grup-istimewa",
     # Members of root-equivalent groups. `lxd` and `docker` count: both are widely documented
     # privilege-escalation paths, often missed because their names do not sound like "admin".
     #
     # This section is for humans and for diff history. Compliance rules do NOT judge it; see
     # the next section.
     "getent group sudo wheel admin lxd docker adm 2>/dev/null "
     "| awk -F: '{print $1\":\"$4}' | sort"),
    # GROUPS OF THE MONITORING ACCOUNT ITSELF, separate from the list above.
    #
    # The rule about the monitoring account being root-equivalent once checked
    # `### grup-istimewa`, which lists ANYONE, including the VM owner's human account that
    # must keep sudo as the only admin. The finding could then never clear, however correct the
    # fix. A title promising one thing while the check does another is worse than no rule: it
    # teaches readers that NSM findings can be ignored.
    #
    # `id -Gn` answers for the account CURRENTLY connected, which is the one NSM uses and
    # exactly what the rule asks.
    ("akun-pemantau-grup",
     "id -Gn | tr ' ' '\\n' | grep -Ex '(sudo|wheel|admin|lxd|docker)' | sort"),
    # `apt-check` is used, NOT matching repository pocket names.
    #
    # Counting `apt list --upgradable` lines containing `-security` MISSED security updates:
    # Ubuntu puts some of them in the `noble-updates` pocket. The VM's login message said "1 of
    # these updates is a standard security update" while the NSM rule reported zero; two
    # sources disagreeing on one machine is a finding. `apt-check` answered `30;1`, the old
    # way `0`.
    #
    # `apt-check` is what the login message itself uses, so using it removes any chance of NSM
    # and the machine reporting two different numbers. Its output is `total;security` on
    # stderr, and the second part is used.
    ("pembaruan-keamanan-tertunda",
     "/usr/lib/update-notifier/apt-check 2>&1 | cut -d';' -f2 "
     # Fallback for systems without update-notifier (plain Debian, containers). If this fails
     # too, the `!!` line from `ambil()` is printed and the rule becomes UNASSESSABLE instead of
     # silently reporting zero.
     "|| apt list --upgradable 2>/dev/null | grep -c -- -security"),
]

# Lines that change by themselves without anyone touching the machine. Dropped before the
# fingerprint is computed, for the same reason as `ntp clock-period` on Cisco: a "config
# changed" alert firing hourly for untouched machines stops being read.
BUANG = [
    # Ephemeral ports used by outgoing connections, not services that were opened.
    re.compile(r"^\S*:(3[2-9]\d{3}|[4-6]\d{4})$"),
]


def _bersih(teks):
    hasil = []
    for line in (teks or "").splitlines():
        b = line.rstrip()
        if not b:
            continue
        if any(p.search(b) for p in BUANG):
            continue
        hasil.append(b)
    return hasil


def ambil(conn_ssh, timeout=25):
    """Assemble the security config snapshot over an already-open SSH session.

    Takes a connected paramiko client, like `akseslog.ambil()` and `flow.ambil()`: one round
    needs one connection for all commands. Returns fixed-shape text ready to store as a
    snapshot.
    """
    section = []
    for title, perintah in PERINTAH:
        _i, o, e = conn_ssh.exec_command(perintah, timeout=timeout)
        keluar = o.read().decode("utf-8", errors="replace")
        error = e.read().decode("utf-8", errors="replace").strip()
        line = _bersih(keluar)
        section.append(f"### {title}")
        if line:
            section.extend(line)
        elif error:
            # FAILURES ARE WRITTEN TOO, not skipped silently. A section that vanishes without a note
            # would be judged "no findings", the subtlest lie: correct in form.
            section.append(f"!! tidak bisa dibaca: {error.splitlines()[0][:80]}")
        else:
            section.append("!! kosong")
        section.append("")
    return "\n".join(section).rstrip() + "\n"


def nilai_sshd(teks, kunci):
    """Get the value of an sshd setting from the snapshot; None if not mentioned.

    A `sshd_config` that does not mention a setting uses the DEFAULT, which differs between
    OpenSSH versions. So "not mentioned" is returned as None and treated by the rules as
    UNASSESSABLE, not guessed to be safe.
    """
    for line in (teks or "").splitlines():
        b = line.strip()
        if not b or b.startswith("###") or b.startswith("!!"):
            continue
        section = b.split(None, 1)
        if len(section) == 2 and section[0].lower() == kunci.lower():
            return section[1].strip()
    return None

"""Saturation: how full a device is, as a NUMBER.

The fourth golden signal (alongside latency, traffic, errors) and the only one
that warns before something breaks. In the lab the database host's disk holds
both the NSM and E-Canteen databases, so a full disk stops monitoring and the
app together.

Numbers, not text blobs: text cannot be thresholded, compared with yesterday, or
trigger anything. All three measurements come from one SSH command in one
session, because each session adds load to the machine being measured. Output
is key=value so it does not depend on `df`/`free` table formats, which differ
across distributions.
"""
import re

# One line, three answers, fixed format:
#
#   disk  percent used on /, from `df -P` (POSIX format is guaranteed)
#   mem   (total - available) / total. Not the `used` column: Linux counts the
#         page cache as used, so a healthy machine can read 90% and warn falsely.
#   load  1-minute load divided by core count, comparable across machines
PERINTAH_LINUX = (
    "df -P / | awk 'NR==2{gsub(/%/,\"\",$5); print \"disk=\"$5}'; "
    "free -m | awk '/^Mem:/{if($2>0) printf \"mem=%.1f\\n\", ($2-$7)/$2*100}'; "
    "awk '{print \"load1=\"$1}' /proc/loadavg; "
    "nproc | awk '{print \"inti=\"$1}'"
)

# Default thresholds. Two levels on purpose: `perhatian` (warning, time to plan)
# and `bahaya` (critical, act now). A single threshold forces a choice between
# warning too early (and being ignored) or too late.
AMBANG = {
    "disk": (80.0, 90.0),
    "mem": (85.0, 95.0),
    # Load per core. 1.0 means all cores fully used on average; above that, tasks
    # are queuing.
    "load": (1.5, 3.0),
}


def urai(teks):
    """Turn command output into numbers. Return {} if unreadable.

    Never guesses: a value missing from the output is left out, so "not measured"
    stays distinguishable from "measured zero".
    """
    hasil = {}
    for k in ("disk", "mem", "load1", "inti"):
        m = re.search(r"^%s=([0-9.]+)$" % k, teks or "", re.M)
        if m:
            try:
                hasil[k] = float(m.group(1))
            except ValueError:
                pass

    if "load1" in hasil and hasil.get("inti", 0) > 0:
        hasil["load"] = round(hasil["load1"] / hasil["inti"], 3)
    return hasil


def vonis(nilai_ukur, ambang=None):
    """{'disk': 'bahaya'|'perhatian'|'sehat', ...} for measured values only.

    Unmeasured values are omitted; rating them 'sehat' would report an unreadable
    machine as healthy.
    """
    ambang = ambang or AMBANG
    keluar = {}
    for kunci, (perhatian, bahaya) in ambang.items():
        v = nilai_ukur.get(kunci)
        if v is None:
            continue
        keluar[kunci] = ("bahaya" if v >= bahaya
                         else "perhatian" if v >= perhatian
                         else "sehat")
    return keluar


# Human-readable sentences, keyed like the measurements above. Each states the
# consequence rather than repeating the number.
ARTI = {
    "disk": ("Ruang disk hampir habis. Basis data yang gagal menulis berhenti "
             "tanpa pesan yang jelas, dan pemantauan ikut berhenti bersamanya."),
    "mem": ("Memori hampir habis. Kernel akan mulai mematikan proses sendiri, "
            "dan yang dipilihnya biasanya proses terbesar — di mesin ini "
            "berarti basis data atau aplikasinya."),
    "load": ("Beban jauh di atas jumlah inti. Permintaan mulai antre menunggu "
             "giliran, dan layanannya akan terasa lambat sebelum ada satu pun "
             "yang benar-benar gagal."),
}

LANGKAH = {
    "disk": [
        "df -h   — lihat partisi mana yang penuh",
        "du -xh / --max-depth=2 2>/dev/null | sort -rh | head   — apa yang besar",
        "kalau basis data: jalankan pangkas_data.py --jalankan dari NSM",
    ],
    "mem": [
        "free -m   — berapa yang benar-benar tersisa",
        "ps -eo rss,comm --sort=-rss | head   — siapa pemakai terbesar",
        "journalctl -k | grep -i oom   — pernahkah kernel mematikan proses?",
    ],
    "load": [
        "uptime   — beban 1, 5, dan 15 menit; naik atau turun?",
        "ps -eo pcpu,comm --sort=-pcpu | head   — proses mana yang sibuk",
        "beban tinggi yang menurun tidak perlu ditindak, cukup diawasi",
    ],
}

SATUAN = {"disk": "%", "mem": "%", "load": "x inti"}
NAMA = {"disk": "Ruang disk", "mem": "Memori", "load": "Beban CPU"}

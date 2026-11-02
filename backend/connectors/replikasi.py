"""State of the MySQL replica at site B, read from the replica machine itself.

WHY IT EXISTS. The source database has a copy that follows it on the replica machine, so a
failure of the source does not stop monitoring and the app at once. But an unmonitored
replica is **worse than none**: it gives unfounded confidence. Replication can stop with no
visible symptom (the source keeps serving, pages stay open, numbers keep moving), and its
absence is discovered on the day it is needed, the worst day to find out.

WHY OVER SSH, NOT BY CONNECTING TO PORT 3306. Asking the replica directly needs a new ACL
rule on the site B router and a new `ufw` allowance, and the cross-site 3306 permission was
deliberately revoked when the database moved to site A. Reopening it for one check would
undo a decision made for a reason. The SSH permission from NSM to site B already exists and
is used to fetch configuration; riding an accounted-for path beats opening a new one.

THE ACCOUNT HAS NO PASSWORD, ON PURPOSE. The MySQL account `nsm`@`localhost` on the replica
uses `auth_socket`: identity is proven by the **OS user connecting over the Unix socket**,
not by a password. No secret is created, stored in a file, or can leak from NSM.

Its only privilege is `REPLICATION CLIENT`, verified rather than assumed:

    select count(*) from nsm.status_logs   -> SELECT command denied
    create database coba_saja              -> --read-only
    sudo -n true                           -> a password is required

It can answer "is replication running" and nothing else, following the rule already held by
`konfig_linux.py`: the monitoring account must not need more privilege than the question it
asks.
"""
import re

# `Seconds_Behind_Source` IS USED BUT NOT TRUSTED ALONE.
#
# It reports the age of the event CURRENTLY being processed, not the remaining queue. While
# this replica caught up on a backlog it was seen RISING from 892 to 1027 and then jumping to
# 0, not because it got worse and then recovered, but because it does not measure "how far
# behind".
#
# It is still shown as a rough sign, but the verdict depends on whether both threads are
# RUNNING. Stopped replication reports lag 0 forever, which is its worst state.
#
# THE THRESHOLD IS SET TO THIS LAB'S REALITY, NOT TO A NUMBER THAT SOUNDS GOOD. Measured: NSM
# writes about 2 rows/s, while the IO thread can pull less than that over the 152 ms path. The
# gap grows steadily (about 90 rows per 45 s) and NEVER catches up. `binlog_transaction_
# compression` was tried and did **not help at all** (still +90 per round), so the limit is
# not byte volume but the request-wait pattern on a high-latency path, like SFTP reaching only
# 3 KB/s of a nominal 13.7 KB/s.
#
# With a 15-minute threshold this section would be yellow FOREVER. An alarm that is always on
# is not an alarm; it trains people to ignore this page, which is the page that must be
# trusted during a real incident.
#
# So only states that truly matter are judged hard: a thread that has STOPPED. Lag is shown
# as a plain number and counts as danger only once it exceeds the binlog age at the source (3
# days), the point at which the replica must be re-copied from scratch.
AMBANG_LAG_PERHATIAN = 86400  # 1 day
AMBANG_LAG_BAHAYA = 259200  # 3 days = binlog age at the source

PERINTAH = 'mysql -e "SHOW REPLICA STATUS\\G" 2>&1'

_MEDAN = ("Replica_IO_Running", "Replica_SQL_Running", "Seconds_Behind_Source",
          "Source_Host", "Last_IO_Error", "Last_SQL_Error",
          "Retrieved_Gtid_Set", "Executed_Gtid_Set", "Last_IO_Errno")


def urai(teks):
    """Turn `SHOW REPLICA STATUS` vertical output (`G` terminator) into a dict.

    That format puts one field per line as `Name: value`, with indentation that varies so the
    names right-align. The indentation is dropped; only names and values are used.
    """
    hasil = {}
    for line in (teks or "").splitlines():
        m = re.match(r"\s*(\w+):\s?(.*)$", line)
        if m and m.group(1) in _MEDAN:
            hasil[m.group(1)] = m.group(2).strip()
    return hasil


def vonis(data, terjangkau=True, galat=None):
    """Replication state values. Returns a dict ready to display.

    The shape deliberately matches the other Health page sections (`nama`, `vonis`, `nilai`,
    `ket`, `rincian`) so the template needs no special case.
    """
    if not terjangkau:
        # UNREACHABLE DOES NOT MEAN BROKEN and must not be reported as broken. The path to site B
        # can drop, and then the right answer is "unknown", not a guess in either direction. An alarm
        # that lies when unsure is the quickest way to make this page stop being trusted.
        return {
            "nama": "Replika basis data (Lokasi B)",
            "vonis": "perhatian",
            "nilai": "tidak terjangkau",
            "ket": ("Tidak bisa menanyakan keadaan replika di 192.168.20.101 "
                    "(%s). Ini BELUM tentu berarti replikasinya berhenti — "
                    "yang pasti hanya bahwa NSM sedang tidak bisa "
                    "memeriksanya. Kalau jalur ke Lokasi B memang sedang "
                    "putus, bagian ini akan pulih sendiri begitu jalurnya "
                    "kembali." % (galat or "sebab tidak diketahui")),
            "rincian": [],
        }

    io_ = data.get("Replica_IO_Running", "")
    sql_ = data.get("Replica_SQL_Running", "")

    if not io_ and not sql_:
        return {
            "nama": "Replika basis data (Lokasi B)",
            "vonis": "bahaya",
            "nilai": "TIDAK DIKONFIGURASI",
            "ket": ("Server di 192.168.20.101 menjawab, tetapi tidak punya "
                    "replikasi yang berjalan sama sekali. Salinan basis data "
                    "yang seharusnya ada di Lokasi B tidak sedang dibuat."),
            "rincian": [],
        }

    try:
        lag = int(data.get("Seconds_Behind_Source") or 0)
    except ValueError:
        lag = None  # "NULL" when the thread has stopped

    rincian = [
        {"label": "Sumber", "nilai": data.get("Source_Host", "?"),
         "ket": "Basis data yang diikuti."},
        {"label": "Utas IO", "nilai": io_,
         "ket": "Menarik perubahan dari sumber lewat WAN. Berhenti = tidak "
                "ada perubahan baru yang masuk."},
        {"label": "Utas SQL", "nilai": sql_,
         "ket": "Menerapkan perubahan yang sudah ditarik. Berhenti = data "
                "sudah sampai tetapi tidak dipasang."},
        {"label": "Tertinggal",
         "nilai": ("%d detik" % lag) if lag is not None else "tidak terukur",
         "ket": "Angka kasar. Ia melaporkan umur kejadian yang sedang "
                "diproses, bukan sisa antrean, jadi bisa naik justru saat "
                "replika sedang mengejar."},
    ]

    error_io = data.get("Last_IO_Error") or ""
    error_sql = data.get("Last_SQL_Error") or ""
    if error_io:
        rincian.append({"label": "Galat IO terakhir", "nilai": error_io[:160],
                        "ket": "Pesan dari percobaan menyambung yang gagal."})
    if error_sql:
        rincian.append({"label": "Galat SQL terakhir", "nilai": error_sql[:160],
                        "ket": "Pesan dari perubahan yang gagal diterapkan."})

    # A STOPPED THREAD IS ALWAYS WORSE THAN ANY LAG.
    #
    # Stopped replication reports lag NULL or 0, so a verdict taken from lag would make the
    # worst state look the healthiest.
    if io_ != "Yes" or sql_ != "Yes":
        down = []
        if io_ != "Yes":
            down.append("utas IO (%s)" % io_)
        if sql_ != "Yes":
            down.append("utas SQL (%s)" % sql_)
        return {
            "nama": "Replika basis data (Lokasi B)",
            "vonis": "bahaya",
            "nilai": "BERHENTI",
            "ket": ("Replikasi berhenti: %s. Salinan di Lokasi B TIDAK lagi "
                    "mengikuti, dan ia makin tertinggal setiap detik. %s "
                    "Binlog di sumber hanya disimpan 3 hari — kalau ini "
                    "dibiarkan lebih lama dari itu, replikanya harus disalin "
                    "ulang dari awal."
                    % (" dan ".join(down),
                       ("Pesan terakhir: " + (error_io or error_sql))
                       if (error_io or error_sql) else "")),
            "rincian": rincian,
        }

    if lag is not None and lag >= AMBANG_LAG_BAHAYA:
        return {
            "nama": "Replika basis data (Lokasi B)", "vonis": "bahaya",
            "nilai": "tertinggal %d menit" % (lag // 60),
            # The sentence names the THRESHOLD instead of a fixed number typed separately. An earlier
            # version said "more than one hour" after the threshold had long become 3 days: the threshold
            # moved, the sentence did not, and readers were misled. A fixed sentence describing a state
            # will lie in states nobody thought of when writing it.
            "ket": ("Kedua utas jalan, tetapi replika tertinggal lebih dari "
                    "%d jam -- melewati umur binlog di sumber, jadi replika "
                    "ini kemungkinan TIDAK BISA lagi mengejar sendiri dan "
                    "harus disalin ulang dari awal."
                    % (AMBANG_LAG_BAHAYA // 3600)),
            "rincian": rincian,
        }

    if lag is not None and lag >= AMBANG_LAG_PERHATIAN:
        return {
            "nama": "Replika basis data (Lokasi B)", "vonis": "perhatian",
            "nilai": "tertinggal %d menit" % (lag // 60),
            "ket": ("Replikasi jalan tetapi tertinggal lebih dari %d jam. "
                    "Lag sesaat itu normal sesudah ledakan penulisan; yang "
                    "TIDAK normal adalah angka sebesar ini bertahan atau "
                    "terus naik -- itu berarti replika tidak sanggup "
                    "mengejar laju tulis sumbernya, bukan sedang mengejar."
                    % (AMBANG_LAG_PERHATIAN // 3600)),
            "rincian": rincian,
        }

    return {
        "nama": "Replika basis data (Lokasi B)", "vonis": "sehat",
        "nilai": "mengikuti",
        "ket": ("Salinan basis data di Lokasi B mengikuti sumbernya. Kalau "
                "server data Lokasi A rusak, datanya masih ada di lokasi "
                "yang lain."),
        "rincian": rincian,
    }

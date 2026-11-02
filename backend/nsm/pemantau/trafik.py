from datetime import datetime

import dialek_perangkat
import penyangga
from config import get_access_log_path
from connectors import akseslog, flow, perintahlog, sambaaudit, sftplog
from models import (
    AksesWeb,
    Device,
    Flow,
    PerintahPengguna,
    PosisiLog,
    Service,
    SesiSftp,
    TransferBerkas,
)

from ._inti import kerjakan_bersamaan, posisi_log, sasaran, status_terakhir


def jalur_log_web(db, device_id):
    """All access logs to read on a device: a list, not one path.
    An empty list means "not a web server". Paths come from `services.log_akses`;
    empty values use the config default, and duplicates are dropped so a shared
    file is read once.
    Returns `[(path, service_id), ...]`. `service_id` is None for the config
    default, i.e. when NSM does not know which service owns the log; guessing
    would make per-service numbers look certain.
    """
    default = get_access_log_path()
    hasil = []
    visible = set()
    for s in (db.query(Service)
              .filter(Service.device_id == device_id,
                      Service.jenis == "http",
                      Service.aktif != 0)
              .order_by(Service.id).all()):
        owned_own = (s.log_akses or "").strip()
        j = owned_own or default
        if j in visible:
            continue
        visible.add(j)
        hasil.append((j, s.id if owned_own else None))
    return hasil


def jalur_log_sftp(db, device_id):
    """SFTP logs to read on a device; may be empty (not a file server).
    Same shape as `jalur_log_web()`. Filtered by `jenis='sftp'` so it never collides
    with the access-log reader (`jenis='http'`): a file sent to the wrong reader
    raises no error, it just yields zero recognized lines.
    """
    hasil = []
    visible = set()
    for s in (db.query(Service)
              .filter(Service.device_id == device_id,
                      Service.jenis == "sftp",
                      Service.aktif != 0)
              .order_by(Service.id).all()):
        j = (s.log_akses or "").strip() or "/var/log/auth.log"
        if j in visible:
            continue
        visible.add(j)
        hasil.append((j, s.id))
    return hasil


def jalur_log_smb(db, device_id):
    """Samba audit logs to read on a device; may be empty.
    Same shape as `jalur_log_web()`. Filtered by `jenis='smb'`. The default is
    `/var/log/samba-audit.log`, where rsyslog separates `full_audit` output (see
    `connectors/sambaaudit.py`). Regular Samba logs are deliberately not read: they
    are service diagnostics, not an access trail.
    """
    hasil = []
    visible = set()
    for s in (db.query(Service)
              .filter(Service.device_id == device_id,
                      Service.jenis == "smb",
                      Service.aktif != 0)
              .order_by(Service.id).all()):
        j = (s.log_akses or "").strip() or "/var/log/samba-audit.log"
        if j in visible:
            continue
        visible.add(j)
        hasil.append((j, s.id))
    return hasil


def jalur_log_perintah(db, device_id):
    """auditd logs (command history) to read on a device.
    Same shape as `jalur_log_smb()`, filtered by `jenis='auditd'`. Default
    `/var/log/audit/audit.log`, read as-is because the `execve` rule on the server
    already filters by the key `perintah_pengguna`.
    """
    hasil = []
    visible = set()
    for s in (db.query(Service)
              .filter(Service.device_id == device_id,
                      Service.jenis == "auditd",
                      Service.aktif != 0)
              .order_by(Service.id).all()):
        j = (s.log_akses or "").strip() or "/var/log/audit/audit.log"
        if j in visible:
            continue
        visible.add(j)
        hasil.append((j, s.id))
    return hasil


def sesi_sftp_terbuka(db, device_id):
    """pid -> user map for SFTP sessions still open on a device.
    Read from the database, not memory, because the user name appears only ONCE in
    the log (the "session opened" line); if the map were lost on restart, the rest
    of that session's transfers would be recorded without an owner.
    """
    peta = {}
    for s in (db.query(SesiSftp)
              .filter(SesiSftp.device_id == device_id)
              .order_by(SesiSftp.id).all()):
        peta[s.pid] = {"pengguna": s.pengguna, "ip": s.ip_klien,
                       "mulai": s.mulai}
    return peta


def baca_traffic_device(tugas):
    """Network work only: read access logs and flows over ONE SSH connection.
    `tugas` is `(Sasaran, daftar_log, daftar_sftp)`; an empty list means that part
    is skipped. Returns raw data for the caller to write. No database access (runs
    in a worker thread).
    """
    import paramiko
    s, daftar_log, list_sftp, list_smb, daftar_perintah = tugas
    hasil = {"log": [], "flow": [], "sftp": [], "smb": [], "perintah": []}

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    sambung = {"timeout": 20, "allow_agent": False, "look_for_keys": False}
    if s.ssh_key_path:
        client.connect(s.ip_address, username=s.username,
                       key_filename=s.ssh_key_path, **sambung)
    else:
        client.connect(s.ip_address, username=s.username,
                       password=s.password, **sambung)
    try:
        for jalur, posisi, service_id in daftar_log:
            try:
                entri, posisi_baru, diputar, _n, exists = akseslog.ambil(
                    client, jalur, posisi or 0)
                if not exists:
                    # File MISSING, unlike empty. Usually a misconfiguration (log path registered
                    # but the app not writing it). Reported as a failure so it is visible instead of
                    # passing as "zero new requests".
                    raise FileNotFoundError(
                        "berkas log belum ada di perangkat")
            except Exception as e:
                # One failing log must not take down the other logs on the same machine.
                hasil["log"].append({"jalur": jalur, "service_id": service_id,
                                     "galat": str(e), "entri": [],
                                     "posisi_baru": posisi or 0,
                                     "diputar": False})
                continue
            hasil["log"].append({"jalur": jalur, "service_id": service_id,
                                 "galat": None, "entri": entri,
                                 "posisi_baru": posisi_baru,
                                 "diputar": diputar})

        for jalur, posisi, service_id, session_begin in list_sftp:
            try:
                (transfer, sesi, selesai, posisi_baru, diputar,
                 exists) = sftplog.ambil(client, jalur, posisi or 0, session_begin)
                if not exists:
                    raise FileNotFoundError(
                        "berkas log belum ada di perangkat")
            except Exception as e:
                hasil["sftp"].append({"jalur": jalur, "service_id": service_id,
                                      "galat": str(e), "transfer": [],
                                      "sesi": session_begin, "selesai": [],
                                      "posisi_baru": posisi or 0,
                                      "diputar": False})
                continue
            hasil["sftp"].append({"jalur": jalur, "service_id": service_id,
                                  "galat": None, "transfer": transfer,
                                  "sesi": sesi, "selesai": selesai,
                                  "posisi_baru": posisi_baru,
                                  "diputar": diputar})

        for jalur, posisi, service_id in list_smb:
            try:
                (kejadian, disaring, posisi_baru, diputar,
                 exists) = sambaaudit.ambil(client, jalur, posisi or 0)
                if not exists:
                    raise FileNotFoundError(
                        "berkas log belum ada di perangkat")
            except Exception as e:
                hasil["smb"].append({"jalur": jalur, "service_id": service_id,
                                     "galat": str(e), "kejadian": [],
                                     "disaring": 0,
                                     "posisi_baru": posisi or 0,
                                     "diputar": False})
                continue
            hasil["smb"].append({"jalur": jalur, "service_id": service_id,
                                 "galat": None, "kejadian": kejadian,
                                 "disaring": disaring,
                                 "posisi_baru": posisi_baru,
                                 "diputar": diputar})

        for jalur, posisi, service_id in daftar_perintah:
            try:
                (kejadian, disaring, posisi_baru, diputar,
                 exists) = perintahlog.ambil(client, jalur, posisi or 0)
                if not exists:
                    raise FileNotFoundError(
                        "berkas log belum ada di perangkat")
            except Exception as e:
                hasil["perintah"].append({"jalur": jalur, "service_id": service_id,
                                          "galat": str(e), "kejadian": [],
                                          "disaring": 0,
                                          "posisi_baru": posisi or 0,
                                          "diputar": False})
                continue
            hasil["perintah"].append({"jalur": jalur, "service_id": service_id,
                                      "galat": None, "kejadian": kejadian,
                                      "disaring": disaring,
                                      "posisi_baru": posisi_baru,
                                      "diputar": diputar})

        hasil["flow"] = flow.ambil(client)
    finally:
        client.close()
    return hasil


def simpan_traffic_device(db, s, bacaan):
    """Database work only: store one device's read results.
    The read-position marker is updated in the SAME transaction as the rows;
    otherwise a failure in between would re-read and double-record lines.
    A device can have several access logs, but the marker is ONE PER FILE: sharing
    one would make progress in one file skip unread lines in another.
    """
    n_access = 0
    fail = []
    for log in bacaan["log"]:
        if log.get("galat"):
            fail.append((log["jalur"], log["galat"]))
            continue
        for e in log["entri"]:
            db.add(AksesWeb(device_id=s.id,
                            service_id=log.get("service_id"), **e))
        n_access += len(log["entri"])
        p = posisi_log(db, s.id, log["jalur"])
        p.posisi = log["posisi_baru"]
        p.diperbarui = datetime.now()

    n_transfer = 0
    for log in bacaan.get("sftp", []):
        if log.get("galat"):
            fail.append((log["jalur"], log["galat"]))
            continue
        for t in log["transfer"]:
            # SFTP rows are marked with their source explicitly; "empty means SFTP" only
            # holds for old rows.
            db.add(TransferBerkas(device_id=s.id, sumber="SFTP", **t))
        n_transfer += len(log["transfer"])
        simpan_sesi_sftp(db, s.id, log["sesi"], log["selesai"])
        p = posisi_log(db, s.id, log["jalur"])
        p.posisi = log["posisi_baru"]
        p.diperbarui = datetime.now()

    # Samba audit goes into the SAME TABLE as SFTP (same question: who touched which
    # file). The `sumber` column tells them apart.
    n_smb = 0
    for log in bacaan.get("smb", []):
        if log.get("galat"):
            fail.append((log["jalur"], log["galat"]))
            continue
        for k in log["kejadian"]:
            db.add(TransferBerkas(device_id=s.id, **k))
        n_smb += len(log["kejadian"])
        p = posisi_log(db, s.id, log["jalur"])
        p.posisi = log["posisi_baru"]
        p.diperbarui = datetime.now()

    n_perintah = 0
    for log in bacaan.get("perintah", []):
        if log.get("galat"):
            fail.append((log["jalur"], log["galat"]))
            continue
        # A session IP missing from this chunk may already be known from stored rows:
        # the `USER_START` line appears once per SSH session and falls out of the read
        # window. Look it up in the database (recorded fact) instead of guessing; one
        # query per session, cached for this round.
        cache_ip_session = {}
        for k in log["kejadian"]:
            if not k.get("ip_klien") and k.get("sesi"):
                sesi = k["sesi"]
                if sesi not in cache_ip_session:
                    cache_ip_session[sesi] = (
                        db.query(PerintahPengguna.ip_klien)
                        .filter(PerintahPengguna.device_id == s.id,
                                PerintahPengguna.sesi == sesi,
                                PerintahPengguna.ip_klien.isnot(None))
                        .order_by(PerintahPengguna.waktu.desc())
                        .limit(1).scalar())
                if cache_ip_session[sesi]:
                    k["ip_klien"] = cache_ip_session[sesi]
            db.add(PerintahPengguna(device_id=s.id, **k))
        n_perintah += len(log["kejadian"])
        p = posisi_log(db, s.id, log["jalur"])
        p.posisi = log["posisi_baru"]
        p.diperbarui = datetime.now()

    waktu = datetime.now()
    for k in bacaan["flow"]:
        db.add(Flow(device_id=s.id, waktu=waktu, **k))
    return n_access, len(bacaan["flow"]), fail, n_transfer + n_smb + n_perintah


def simpan_sesi_sftp(db, device_id, sesi, selesai):
    """Save the pid -> user map for SFTP sessions still open.
    Closed sessions are deleted, not marked finished: the map is only working
    memory and the history lives in `transfer_berkas`. PIDs are reused by the OS,
    so an old row with the same pid is overwritten; otherwise a new session could
    inherit a previous owner's name.
    """
    for pid in selesai:
        (db.query(SesiSftp)
           .filter(SesiSftp.device_id == device_id, SesiSftp.pid == pid)
           .delete())

    for pid, content in sesi.items():
        line = (db.query(SesiSftp)
                 .filter(SesiSftp.device_id == device_id, SesiSftp.pid == pid)
                 .first())
        if line is None:
            line = SesiSftp(device_id=device_id, pid=pid,
                             mulai=content.get("mulai") or datetime.now())
            db.add(line)
        # [:100]/[:45] are a second safety net like `_potong()` in `sftplog.py`: the
        # NAME/IP columns are length-limited and these lines write them directly.
        pengguna = content.get("pengguna")
        ip = content.get("ip")
        line.pengguna = pengguna[:100] if pengguna else pengguna
        line.ip_klien = ip[:45] if ip else ip
        line.diperbarui = datetime.now()


def poll_traffic():
    """Collect access logs and flows from SSH-reachable Linux devices.
    Deliberately not SNMP: it has no notion of who the peer is.
    Three phases like poll_all() and poll_bandwidth(): select devices + last read
    position (DB), open SSH to all devices concurrently (network), store rows and
    advance the position (DB). This is the most expensive of the three jobs: a full
    SSH session per device. The read position is never advanced from worker threads,
    so a failure cannot leave a marker ahead of rows that were never saved.
    """
    db, _buffered = penyangga.sesi()
    try:
        choice = []
        for d in db.query(Device).all():
            # Selected by "are user command logs readable", not "is this Linux"
            # (`kemampuan.baca_trafik`).
            if (d.aktif == 0
                    or not dialek_perangkat.ambil(d.platform)
                             .kemampuan("baca_trafik")):
                continue
            if not (d.username and (d.password or d.ssh_key_path)):
                continue
            last = status_terakhir(db, d.id)
            if last is not None and last.event_type == "DOWN":
                continue
            daftar_log = []
            for jalur, service_id in jalur_log_web(db, d.id):
                # Read only, NOT created if missing. The row is created in phase 3 via
                # posisi_log(), so this phase writes nothing before something was actually read.
                p = (db.query(PosisiLog)
                     .filter(PosisiLog.device_id == d.id,
                             PosisiLog.jalur == jalur)
                     .first())
                daftar_log.append((jalur, (p.posisi or 0) if p is not None else 0,
                                   service_id))

            # SFTP logs are read the same way, plus session memory. The map is read HERE in
            # the DB phase and carried to worker threads as data; worker threads must not
            # touch the database.
            list_sftp = []
            path_sftp = jalur_log_sftp(db, d.id)
            sesi = sesi_sftp_terbuka(db, d.id) if path_sftp else {}
            for jalur, service_id in path_sftp:
                p = (db.query(PosisiLog)
                     .filter(PosisiLog.device_id == d.id,
                             PosisiLog.jalur == jalur)
                     .first())
                list_sftp.append((jalur,
                                    (p.posisi or 0) if p is not None else 0,
                                    service_id, sesi))

            # Samba audit log. No session memory needed: each full_audit line carries its own
            # user name.
            list_smb = []
            for jalur, service_id in jalur_log_smb(db, d.id):
                p = (db.query(PosisiLog)
                     .filter(PosisiLog.device_id == d.id,
                             PosisiLog.jalur == jalur)
                     .first())
                list_smb.append((jalur,
                                   (p.posisi or 0) if p is not None else 0,
                                   service_id))

            # auditd log (command history). Like SMB, each line carries its own user via AUID.
            daftar_perintah = []
            for jalur, service_id in jalur_log_perintah(db, d.id):
                p = (db.query(PosisiLog)
                     .filter(PosisiLog.device_id == d.id,
                             PosisiLog.jalur == jalur)
                     .first())
                daftar_perintah.append((jalur,
                                        (p.posisi or 0) if p is not None else 0,
                                        service_id))

            choice.append((sasaran(d), daftar_log, list_sftp, list_smb,
                            daftar_perintah))
        if not choice:
            return

        # --- Tahap 2: kerja jaringan, bersamaan ---
        hasil = kerjakan_bersamaan(choice, baca_traffic_device)

        for (s, _list_log, _list_sftp, _list_smb,
             _daftar_perintah), (_, bacaan, galat) in zip(choice, hasil):
            if galat is not None:
                print(f"[trf] {s.name}: gagal ({galat})")
                continue
            try:
                n_access, n_flow, log_fail, n_transfer = simpan_traffic_device(
                    db, s, bacaan)
                # Same reason as poll_bandwidth(). This job writes the most rows at once (one per
                # web request), so the write lock would be held longest here.
                db.commit()
                if n_access or n_flow or n_transfer:
                    putar = (" (log diputar, baca ulang dari awal)"
                             if any(l.get("diputar") for l in bacaan["log"])
                             else "")
                    berkas = (f", {n_transfer} berkas" if n_transfer else "")
                    print(f"[trf] {s.name}: {n_access} permintaan web, "
                          f"{n_flow} koneksi aktif{berkas}{putar}")
                # Logs that failed to read are reported, not silenced. A missing file is normal
                # (e.g. Tomcat not yet told to write it), but staying quiet would show the Traffic
                # page with partial data and no sign of it.
                for jalur, message in log_fail:
                    print(f"[trf] {s.name}: log {jalur} tidak terbaca "
                          f"({str(message)[:70]})")
            except Exception as e:
                # Rolled back, not saved. If saving fails midway, some rows are in while the read
                # position was NOT advanced; saving would re-read and double-record those lines.
                db.rollback()
                print(f"[trf] {s.name}: gagal menyimpan ({e})")
    finally:
        db.close()

"""`trafik` section of report_service."""
from sqlalchemy import case, desc, func
from models import (Device, AksesWeb, Flow, NamaAlamat, TransferBerkas, PerintahPengguna)

from ._inti import (BATAS_LOG, PORT_UMUM, SESI_GABUNG_DETIK, _di_luar_jaringan, _hias_orang, _ip_bersih, _peta_device, _peta_layanan_port, _peta_orang, format_durasi, rentang)



def format_byte(b):
    """Human-readable file size.

    Deliberately bytes, not Mbps: access logs record amounts, not rates.
    """
    if b is None:
        return "-"
    b = float(b)
    for unit, batas in (("GB", 1073741824), ("MB", 1048576), ("KB", 1024)):
        if b >= batas:
            return f"{b / batas:.2f} {unit}"
    return f"{b:.0f} B"


def _teks_status_http(kode):
    """Short phrase for an HTTP status code.

    Unknown codes fall back to their class (hundreds group).
    """
    arti = {
        400: "permintaan tidak dimengerti server",
        401: "perlu login",
        403: "ditolak, hak akses berkasnya tidak mengizinkan",
        404: "berkas atau alamatnya tidak ada",
        405: "cara permintaannya tidak diizinkan untuk alamat itu",
        408: "klien terlalu lama mengirim permintaan",
        413: "yang dikirim terlalu besar",
        429: "terlalu banyak permintaan, server membatasi",
        500: "kesalahan di dalam server (biasanya galat skrip PHP)",
        502: "server perantara tidak dapat jawaban yang sah",
        503: "layanan sedang tidak tersedia atau kewalahan",
        504: "server perantara kehabisan waktu menunggu",
    }
    if kode in arti:
        return arti[kode]
    if kode is None:
        return "tanpa kode status"
    if 400 <= kode < 500:
        return "permintaan dari klien ditolak server"
    if kode >= 500:
        return "kesalahan di sisi server"
    return "-"


def traffic_device(db, device_id, period, batas=15):
    """Traffic of one web server: which address fetched what, when, and what the server answered."""
    mulai, selesai, label = rentang(period)
    d = db.query(Device).filter(Device.id == device_id).first()
    if not d:
        return {"error": "Device tidak ditemukan"}

    peta = _peta_device(db)
    base = (db.query(AksesWeb)
             .filter(AksesWeb.device_id == device_id,
                     AksesWeb.waktu >= mulai, AksesWeb.waktu <= selesai))

    total_permintaan = base.count()
    if total_permintaan == 0:
        return {
            "periode": label, "device": d.name, "ada_data": False,
            "alasan": ("Belum ada permintaan web tercatat pada periode ini. "
                       "Access log hanya dibaca untuk device yang punya layanan "
                       "HTTP terdaftar di NSM, dan hanya baris BARU sejak "
                       "pembacaan terakhir yang dimasukkan."),
            "klien": [], "path": [], "lawan": [],
        }

    per_client = (
        db.query(AksesWeb.ip_klien,
                 func.count(AksesWeb.id),
                 func.sum(AksesWeb.byte_kirim),
                 func.sum(AksesWeb.byte_terima),
                 func.max(AksesWeb.waktu),
                 func.sum(case((AksesWeb.status >= 400, 1), else_=0)))
        .filter(AksesWeb.device_id == device_id,
                AksesWeb.waktu >= mulai, AksesWeb.waktu <= selesai)
        .group_by(AksesWeb.ip_klien)
        .order_by(desc(func.sum(AksesWeb.byte_kirim)))
        .limit(batas).all())

    klien = []
    for ip, jml, send, receive, terakhir, gagal in per_client:
        top = (db.query(AksesWeb.path, AksesWeb.byte_kirim)
               .filter(AksesWeb.device_id == device_id,
                       AksesWeb.ip_klien == ip,
                       AksesWeb.waktu >= mulai)
               .order_by(desc(AksesWeb.byte_kirim)).first())

        # Detail of FAILED requests, limited to the latest five (samples to start tracing, not the full list).
        detail_fail = []
        if gagal:
            for p, st, w in (db.query(AksesWeb.path, AksesWeb.status, AksesWeb.waktu)
                             .filter(AksesWeb.device_id == device_id,
                                     AksesWeb.ip_klien == ip,
                                     AksesWeb.waktu >= mulai,
                                     AksesWeb.waktu <= selesai,
                                     AksesWeb.status >= 400)
                             .order_by(desc(AksesWeb.waktu)).limit(5).all()):
                detail_fail.append({
                    "path": p,
                    "status": st,
                    "status_teks": _teks_status_http(st),
                    "waktu": w.isoformat() if w else None,
                })

        klien.append({
            "ip": ip,
            "device": peta.get(ip),
            "permintaan": jml,
            "unduh_byte": float(send or 0),
            "unduh_teks": format_byte(send or 0),
            "unggah_byte": float(receive or 0) if receive else None,
            "unggah_teks": format_byte(receive) if receive else None,
            "gagal": int(gagal or 0),
            "gagal_rinci": detail_fail,
            "terakhir": terakhir.isoformat() if terakhir else None,
            "path_terbesar": top[0] if top else None,
            "path_terbesar_teks": format_byte(top[1]) if top and top[1] else None,
        })

    per_path = (
        db.query(AksesWeb.path,
                 func.count(AksesWeb.id),
                 func.sum(AksesWeb.byte_kirim))
        .filter(AksesWeb.device_id == device_id,
                AksesWeb.waktu >= mulai, AksesWeb.waktu <= selesai)
        .group_by(AksesWeb.path)
        .order_by(desc(func.sum(AksesWeb.byte_kirim)))
        .limit(batas).all())
    path = [{"path": p, "permintaan": n, "byte": float(b or 0),
             "teks": format_byte(b or 0)} for p, n, b in per_path]

    waktu_flow = (db.query(func.max(Flow.waktu))
                  .filter(Flow.device_id == device_id).scalar())
    lawan = []
    if waktu_flow:
        for r in (db.query(Flow.ip_lawan,
                           func.count(Flow.id),
                           func.sum(Flow.byte_masuk),
                           func.sum(Flow.byte_keluar))
                  .filter(Flow.device_id == device_id, Flow.waktu == waktu_flow)
                  .group_by(Flow.ip_lawan)
                  .order_by(desc(func.sum(Flow.byte_keluar))).all()):
            ip, jml, masuk, keluar = r
            lawan.append({
                "ip": ip, "device": peta.get(ip), "koneksi": jml,
                "masuk_teks": format_byte(masuk or 0),
                "keluar_teks": format_byte(keluar or 0),
            })

    total_unduh = sum(k["unduh_byte"] for k in klien)
    dari_nsm = (db.query(func.count(AksesWeb.id))
                .filter(AksesWeb.device_id == device_id,
                        AksesWeb.waktu >= mulai,
                        AksesWeb.dari_nsm == 1).scalar()) or 0

    return {
        "periode": label,
        "device": d.name,
        "ada_data": True,
        "total_permintaan": total_permintaan,
        "total_unduh_teks": format_byte(total_unduh),
        "permintaan_dari_nsm": int(dari_nsm),
        "waktu_flow": waktu_flow.isoformat() if waktu_flow else None,
        "klien": klien,
        "path": path,
        "lawan": lawan,
        # The Apache combined log does not record request body size, so uploads are invisible
        # unless mod_logio is enabled. All figures here count data leaving the server.
        "catatan_unggah": ("Semua angka di bagian ini menghitung data yang "
                           "diambil DARI server. Besar data yang dikirim KE "
                           "server tidak diukur sama sekali, karena log bawaan "
                           "Apache tidak mencatatnya kecuali mod_logio "
                           "dinyalakan. Jadi tidak adanya angka unggahan di "
                           "sini berarti TIDAK DIKETAHUI, bukan nol."),
    }


def _gabung_sesi_baca(baris):
    """Merge consecutive successful SMB AMBIL/KIRIM events on the SAME file into ONE display row
    with a time range and occurrence count.

    Windows Explorer reopens the same file repeatedly during one interaction, so several
    reads are one engagement session. Only the displayed summary is merged; raw rows stay
    intact in `transfer_berkas`.

    Applies only to `sumber == "SMB"` and successful (`hasil == "ok"`) AMBIL/KIRIM events.
    HAPUS, GANTI_NAMA, BUAT_FOLDER, SAMBUNG/PUTUS and all failed attempts are never merged.
    """
    hasil = []
    aktif = {}
    # `baris` is newest first (DESC): the first entry for a key is the latest (`_akhir`);
    # later matches are older and push `_awal` back.
    for r in baris:
        can_merge = (r.sumber == "SMB" and r.aksi in ("AMBIL", "KIRIM")
                       and r.hasil == "ok")
        kunci = (r.pengguna, r.aksi, r.jalur) if can_merge else None
        if kunci and kunci in aktif:
            group = hasil[aktif[kunci]]
            pause = (group["_awal"] - r.waktu).total_seconds()
            if 0 <= pause <= SESI_GABUNG_DETIK:
                group["_awal"] = r.waktu
                group["_jumlah"] += 1
                continue
        group = {"_baris": r, "_akhir": r.waktu, "_awal": r.waktu, "_jumlah": 1}
        hasil.append(group)
        if kunci:
            aktif[kunci] = len(hasil) - 1
    return hasil


def _perkiraan_byte_jaringan(db, mulai, selesai, device_ip_pasangan):
    """Estimate SMB bytes from real TCP traffic (`flow_koneksi`), used ONLY when Samba
    `full_audit` does not report sizes (see the note in `berkas_transfer`).

    Per SESSION, not per file: touching three files in one connection yields their combined total.

    `device_ip_pasangan` is the set of (device_id, client_ip) pairs already proven to be used
    by this person over SMB in the same period (read from `transfer_berkas`).

    Returns (ambil_byte, kirim_byte), from the CLIENT's point of view: Flow `byte_keluar` is
    the client downloading, `byte_masuk` is the client uploading.
    """
    if not device_ip_pasangan:
        return 0.0, 0.0
    fetch = send = 0.0
    for dev_id, ip in device_ip_pasangan:
        # One row per connection, taking the largest sampled value in the period: `ss -tin` reports
        # cumulative counters, so the maximum is the total so far (same pattern as `percakapan_jaringan()`).
        baris = (db.query(Flow.port_lokal, Flow.port_lawan,
                          func.max(Flow.byte_masuk), func.max(Flow.byte_keluar))
                 .filter(Flow.device_id == dev_id, Flow.ip_lawan == ip,
                         Flow.waktu >= mulai, Flow.waktu <= selesai)
                 .group_by(Flow.port_lokal, Flow.port_lawan).all())
        for _pl, _plw, m, k in baris:
            send += float(m or 0)
            fetch += float(k or 0)
    return fetch, send


def berkas_transfer(db, period, batas=15):
    """Who moved which files over SFTP/SMB, and who typed what over SSH; two different questions.

    Four views:
        per orang          per-person totals
        per berkas         per-file totals and number of people
        terbaru            latest FILE activity (SMB/SFTP)
        riwayat_perintah   latest COMMANDS (auditd/SSH), kept separate from file activity
    """
    mulai, selesai, label = rentang(period)

    base = (db.query(TransferBerkas)
             .filter(TransferBerkas.waktu >= mulai,
                     TransferBerkas.waktu <= selesai))
    dasar_perintah = (db.query(PerintahPengguna)
                       .filter(PerintahPengguna.waktu >= mulai,
                               PerintahPengguna.waktu <= selesai))
    total = base.count() + dasar_perintah.count()
    if total == 0:
        return {
            "periode": label, "ada_data": False,
            "alasan": ("Belum ada perpindahan berkas atau perintah tercatat "
                       "pada periode ini. NSM membaca log SFTP/SMB/auditd "
                       "hanya dari device yang punya layanan terdaftar, dan "
                       "hanya baris BARU sejak pembacaan terakhir."),
            "orang": [], "berkas": [], "terbaru": [], "riwayat_perintah": [],
        }

    # Only AMBIL and KIRIM carry volume. HAPUS/GANTI_NAMA count as events but add no bytes.
    total_fetch = float(base.with_entities(
        func.sum(TransferBerkas.byte_baca)).scalar() or 0)
    total_send = float(base.with_entities(
        func.sum(TransferBerkas.byte_tulis)).scalar() or 0)

    # Per person, ordered by event count rather than bytes: Samba `full_audit` (SMB) never
    # reports byte sizes, so byte ordering would push SMB-only users out of the ranking.
    # Bytes are shown as extra information.
    per_person = (
        db.query(TransferBerkas.pengguna,
                 func.count(TransferBerkas.id),
                 func.sum(TransferBerkas.byte_baca),
                 func.sum(TransferBerkas.byte_tulis),
                 func.max(TransferBerkas.waktu),
                 func.sum(case((TransferBerkas.aksi == "AMBIL", 1), else_=0)),
                 func.sum(case((TransferBerkas.aksi == "KIRIM", 1), else_=0)))
        .filter(TransferBerkas.waktu >= mulai, TransferBerkas.waktu <= selesai)
        .group_by(TransferBerkas.pengguna)
        .order_by(desc(func.count(TransferBerkas.id)))
        .limit(batas).all())

    map_person = _peta_orang(db)

    orang = []
    for nama, jml, baca, tulis, terakhir, n_fetch, n_send in per_person:
        ident = _hias_orang(map_person, nama)
        # Largest file fetched; only for rows that have a size (SFTP). Deliberately None for
        # SMB-only users, since their size was never measured.
        top = (db.query(TransferBerkas.jalur, TransferBerkas.byte_baca)
               .filter(TransferBerkas.waktu >= mulai,
                       TransferBerkas.waktu <= selesai,
                       TransferBerkas.byte_baca > 0)
               .filter(TransferBerkas.pengguna.is_(None) if nama is None
                       else TransferBerkas.pengguna == nama)
               .order_by(desc(TransferBerkas.byte_baca)).first())

        # "0 B" and "unknown" mean different things; do not conflate them.
        fetch_known = float(baca or 0) > 0
        send_known = float(tulis or 0) > 0

        ambil_teks = format_byte(baca or 0) if fetch_known else None
        kirim_teks = format_byte(tulis or 0) if send_known else None

        # Network estimate: tried only when `full_audit` reports no bytes (SMB) and the person
        # has AMBIL/KIRIM events.
        if (not fetch_known and n_fetch) or (not send_known and n_send):
            pair = set(
                (dev_id, ip) for dev_id, ip in
                db.query(TransferBerkas.device_id, TransferBerkas.ip_klien)
                .filter(TransferBerkas.waktu >= mulai, TransferBerkas.waktu <= selesai,
                        TransferBerkas.sumber == "SMB",
                        TransferBerkas.ip_klien.isnot(None))
                .filter(TransferBerkas.pengguna.is_(None) if nama is None
                        else TransferBerkas.pengguna == nama)
                .distinct().all())
            net_fetch, net_send = _perkiraan_byte_jaringan(
                db, mulai, selesai, pair)
            # The "≈" prefix is required: this is the total for the whole session with that address,
            # not this file's own bytes.
            if not fetch_known:
                ambil_teks = (("≈ %s (dari lalu lintas jaringan, per sesi)"
                               % format_byte(net_fetch))
                              if net_fetch > 0 else "ukuran tak diketahui (SMB)")
            if not send_known:
                kirim_teks = (("≈ %s (dari lalu lintas jaringan, per sesi)"
                               % format_byte(net_send))
                              if net_send > 0 else "ukuran tak diketahui (SMB)")

        orang.append({
            # None is shown as "(tidak diketahui)": the session started before NSM began reading, so
            # its opening row was never seen.
            "pengguna": nama or "(tidak diketahui)",
            "dikenali": nama is not None,
            # Full name and title from the directory. May be None (system accounts such as `nsmro` have neither).
            "nama_lengkap": ident["nama"],
            "jabatan": ident["jabatan"],
            "kejadian": int(jml),
            "ambil_byte": float(baca or 0),
            "kirim_byte": float(tulis or 0),
            "ambil_teks": ambil_teks or "-",
            "kirim_teks": kirim_teks or "-",
            "terakhir": terakhir.isoformat() if terakhir else None,
            "berkas_terbesar": top[0] if top else None,
            "berkas_terbesar_teks": format_byte(top[1]) if top else None,
        })

    # Per file. Grouped over ALL events (AMBIL/KIRIM/SALIN) and ordered by event count, like
    # per person. Sums byte_baca + byte_tulis, since an SMB file may have all its size in byte_tulis.
    per_file = (
        db.query(TransferBerkas.jalur,
                 func.count(TransferBerkas.id),
                 func.count(func.distinct(TransferBerkas.pengguna)),
                 func.sum(func.coalesce(TransferBerkas.byte_baca, 0)
                          + func.coalesce(TransferBerkas.byte_tulis, 0)),
                 func.max(TransferBerkas.waktu))
        .filter(TransferBerkas.waktu >= mulai, TransferBerkas.waktu <= selesai,
                TransferBerkas.aksi.in_(("AMBIL", "KIRIM", "SALIN")))
        .group_by(TransferBerkas.jalur)
        .order_by(desc(func.count(TransferBerkas.id)))
        .limit(batas).all())

    berkas = [{
        "jalur": j,
        "kali": int(n),
        "orang": int(n_person),
        "total_byte": float(b or 0),
        "total_teks": format_byte(b or 0) if (b or 0) > 0 else "ukuran tak diketahui (SMB)",
        "terakhir": t.isoformat() if t else None,
    } for j, n, n_person, b, t in per_file]

    # Latest FILE activity only. Fetches BATAS_LOG+1 rows and trims, to tell "more remain"
    # from "exactly at the limit" without an extra COUNT query.
    baris = (base.order_by(desc(TransferBerkas.waktu))
             .limit(BATAS_LOG + 1).all())
    terbaru_dipotong = len(baris) > BATAS_LOG
    baris = baris[:BATAS_LOG]
    terbaru = [{
        # `waktu` is the LAST occurrence within the session; `waktu_mulai` differs only when
        # `jumlah_kali` > 1 (see _gabung_sesi_baca()).
        "waktu": group["_akhir"].isoformat() if group["_akhir"] else None,
        "waktu_mulai": (group["_awal"].isoformat()
                         if group["_jumlah"] > 1 else None),
        "jumlah_kali": group["_jumlah"],
        "durasi_teks": (format_durasi(round(
            (group["_akhir"] - group["_awal"]).total_seconds()))
            if group["_jumlah"] > 1 else None),
        "pengguna": r.pengguna or "(tidak diketahui)",
        "dikenali": r.pengguna is not None,
        "nama_lengkap": _hias_orang(map_person, r.pengguna)["nama"],
        "jabatan": _hias_orang(map_person, r.pengguna)["jabatan"],
        "ip_klien": r.ip_klien,
        "aksi": r.aksi,
        "jalur": r.jalur,
        "jalur_baru": r.jalur_baru,
        # `sumber` None = old row from before the column existed; SFTP was the only source then.
        "sumber": r.sumber or "SFTP",
        # SMB only: client machine name from Samba `%m`.
        "mesin_klien": r.mesin_klien,
        "berbagi": r.berbagi,
        # "ok" / "gagal". None for SFTP means unknown (the SFTP reader does not record failures), NOT success.
        "hasil": r.hasil,
        "ukuran_teks": (format_byte(r.byte_baca) if (r.byte_baca or 0) > 0
                        else format_byte(r.byte_tulis)
                        if (r.byte_tulis or 0) > 0 else "-"),
    } for group in _gabung_sesi_baca(baris) for r in [group["_baris"]]]

    # Command history (auditd): its own table, separate from file activity but on the same page.
    # File events say who touched which file; commands say what was typed, which includes
    # many non-file actions (`systemctl`, `whoami`, ...).
    baris_perintah = (dasar_perintah.order_by(desc(PerintahPengguna.waktu))
                      .limit(BATAS_LOG + 1).all())
    perintah_dipotong = len(baris_perintah) > BATAS_LOG
    riwayat_perintah = [{
        "waktu": p.waktu.isoformat() if p.waktu else None,
        "pengguna": p.pengguna or "(tidak diketahui)",
        "dikenali": p.pengguna is not None,
        "nama_lengkap": _hias_orang(map_person, p.pengguna)["nama"],
        "jabatan": _hias_orang(map_person, p.pengguna)["jabatan"],
        "ip_klien": p.ip_klien,
        "perintah": p.argumen or p.perintah,
        "hasil": "ok" if p.berhasil else "gagal",
    } for p in baris_perintah[:BATAS_LOG]]

    return {
        "periode": label,
        "ada_data": True,
        "total_kejadian": total,
        "total_ambil_teks": format_byte(total_fetch),
        "total_kirim_teks": format_byte(total_send),
        "orang": orang,
        "berkas": berkas,
        "terbaru": terbaru,
        "riwayat_perintah": riwayat_perintah,
        # If the period holds more events than were sent, the page must say so.
        "terbaru_dipotong": terbaru_dipotong,
        "perintah_dipotong": perintah_dipotong,
        "batas_log": BATAS_LOG,
        # Administrator scp is counted here too, deliberately; readers should know that.
        "catatan": ("Angka di sini datang dari log SFTP, jadi yang disebut "
                    "adalah ORANG (dari LDAP), bukan alamat IP. `scp` ikut "
                    "terhitung karena OpenSSH menjalankannya di atas protokol "
                    "yang sama — termasuk berkas yang dikirim administrator "
                    "saat memasang sesuatu."),
    }


def _peta_ip_ke_id(db):
    """IP address -> device id, to name the port on the REMOTE side correctly."""
    peta = {}
    for d in db.query(Device).all():
        if d.ip_address:
            peta[d.ip_address] = d.id
    return peta


def _peta_id_ke_nama(db):
    """device id -> name.

    Used instead of lookup by local address: outgoing connections from the VirtualBox VM
    leave via the NAT address `10.0.2.15`, not a monitored lab address. The id is always
    right because it determines which machine the row was read from.
    """
    return {d.id: d.name for d in db.query(Device).all()}


def percakapan_jaringan(db, period, batas=25):
    """Who talks to whom, through which port, and how much.

    Source is `flow_koneksi`: periodic snapshots of live TCP connections on each SSH-reachable
    Linux device. Two limits: (1) 60-second snapshots, so connections that start and end
    between two snapshots are never seen; (2) only SSH-enabled Linux devices are read, so Cisco
    routers and laptops are excluded and this is not all lab traffic.
    """
    mulai, selesai, label = rentang(period)
    device_map = _peta_device(db)
    map_service = _peta_layanan_port(db)
    map_ip_id = _peta_ip_ke_id(db)
    map_id_name = _peta_id_ke_nama(db)

    # DNS names are read from the cache, NOT resolved here: one reverse lookup takes 4.5 to 9 s,
    # which would freeze the self-refreshing page. The `poll_nama_alamat` poller job fills the cache.
    #
    # A missing `nama_alamat` table is handled (migrations run only while the poller and uvicorn
    # are stopped, so new code can briefly run first); the gap is reported in `catatan`.
    try:
        map_name_dns = {n.ip: n.nama for n in db.query(NamaAlamat)
                         .filter(NamaAlamat.nama.isnot(None)).all()}
        nama_dns_siap = True
    except Exception:
        db.rollback()
        map_name_dns = {}
        nama_dns_siap = False

    # First time each address was seen, computed over the whole history rather than the selected
    # period. This tells "busy today" apart from "never seen before".
    #
    # Address forms are normalized because `::ffff:` and the plain form are the same machine.
    pertama_kali = {}
    for ip, w in (db.query(Flow.ip_lawan, func.min(Flow.waktu))
                  .group_by(Flow.ip_lawan).all()):
        clean = _ip_bersih(ip)
        if w and (clean not in pertama_kali or w < pertama_kali[clean]):
            pertama_kali[clean] = w

    # One row per connection (5-tuple), valued at its LAST state, so a long connection is not
    # counted once per snapshot.
    tuple_koneksi = (
        db.query(Flow.device_id, Flow.ip_lokal, Flow.port_lokal,
                 Flow.ip_lawan, Flow.port_lawan,
                 func.max(Flow.byte_masuk), func.max(Flow.byte_keluar),
                 func.max(Flow.waktu))
        .filter(Flow.waktu >= mulai, Flow.waktu <= selesai)
        .group_by(Flow.device_id, Flow.ip_lokal, Flow.port_lokal,
                  Flow.ip_lawan, Flow.port_lawan)
        .all())

    per_opposite = {}
    per_gate = {}
    total_enter = total_exit = 0.0

    for dev_id, ip_lokal, port_lokal, ip_lawan, port_lawan, masuk, keluar, terakhir in tuple_koneksi:
        lawan = _ip_bersih(ip_lawan)
        masuk = float(masuk or 0)
        keluar = float(keluar or 0)
        total_enter += masuk
        total_exit += keluar

        # Which side is server and which is client matters: "someone hit our port 8080" and "we
        # contacted 443 outside" mean very different things. The remote-side port is named with the
        # REMOTE device's id, not the id of the device being read.
        id_opposite = map_ip_id.get(lawan)
        reg_local = map_service.get((dev_id, int(port_lokal))) if port_lokal else None
        reg_opposite = (map_service.get((id_opposite, int(port_lawan)))
                     if id_opposite and port_lawan else None)
        um_local = PORT_UMUM.get(int(port_lokal)) if port_lokal else None
        um_opposite = PORT_UMUM.get(int(port_lawan)) if port_lawan else None

        if reg_local:
            arah, port_service, name_service = "masuk", port_lokal, reg_local
        elif reg_opposite:
            arah, port_service, name_service = "keluar", port_lawan, reg_opposite
        elif um_local:
            arah, port_service, name_service = "masuk", port_lokal, um_local
        elif um_opposite:
            arah, port_service, name_service = "keluar", port_lawan, um_opposite
        else:
            # Two high ports: nothing can honestly be named.
            arah, port_service, name_service = "?", port_lokal, None

        p = per_opposite.setdefault(lawan, {
            "ip": lawan, "device": device_map.get(lawan),
            "koneksi": 0, "masuk_byte": 0.0, "keluar_byte": 0.0,
            "terakhir": None, "_pintu": set(), "_device_lokal": set(),
            "luar_jaringan": _di_luar_jaringan(lawan),
        })
        p["koneksi"] += 1
        p["masuk_byte"] += masuk
        p["keluar_byte"] += keluar
        if terakhir and (p["terakhir"] is None or terakhir > p["terakhir"]):
            p["terakhir"] = terakhir
        if name_service:
            p["_pintu"].add(f"{name_service} ({port_service})")
        elif port_service:
            p["_pintu"].add(f"port {port_service}")
        name_dev = map_id_name.get(dev_id)
        if name_dev:
            p["_device_lokal"].add(name_dev)

        kunci = (dev_id, int(port_service or 0), arah)
        q = per_gate.setdefault(kunci, {
            "port": int(port_service or 0),
            "nama": name_service,
            "arah": arah,
            "device": map_id_name.get(dev_id) or f"device {dev_id}",
            "koneksi": 0, "masuk_byte": 0.0, "keluar_byte": 0.0,
            "_lawan": set(),
        })
        q["koneksi"] += 1
        q["masuk_byte"] += masuk
        q["keluar_byte"] += keluar
        q["_lawan"].add(lawan)

    # "First seen" only means something with enough history behind it: observations must reach
    # back at least ONE FULL WINDOW before the window being viewed (48 hours of history for a
    # 24-hour period). Otherwise nearly every row gets flagged and readers learn to ignore the marker.
    awal_pengamatan = min(pertama_kali.values()) if pertama_kali else None
    width = selesai - mulai
    bisa_nilai_baru = bool(awal_pengamatan and awal_pengamatan <= mulai - width)

    def rapikan_lawan(p):
        begin = pertama_kali.get(p["ip"])
        baru = bool(begin and begin >= mulai and bisa_nilai_baru)
        return {
            "ip": p["ip"],
            "device": p["device"],
            "nama_dns": map_name_dns.get(p["ip"]),
            "pertama_kali": begin.isoformat() if begin else None,
            "baru_terlihat": baru,
            "koneksi": p["koneksi"],
            "masuk_byte": p["masuk_byte"],
            "keluar_byte": p["keluar_byte"],
            "masuk_teks": format_byte(p["masuk_byte"]),
            "keluar_teks": format_byte(p["keluar_byte"]),
            "terakhir": p["terakhir"].isoformat() if p["terakhir"] else None,
            "pintu": sorted(p["_pintu"])[:6],
            "device_lokal": sorted(p["_device_lokal"]),
            "luar_jaringan": p["luar_jaringan"],
        }

    def rapikan_pintu(q):
        return {
            "port": q["port"],
            "nama": q["nama"],
            "arah": q["arah"],
            "device": q["device"],
            "koneksi": q["koneksi"],
            "lawan": len(q["_lawan"]),
            "masuk_teks": format_byte(q["masuk_byte"]),
            "keluar_teks": format_byte(q["keluar_byte"]),
            "byte_total": q["masuk_byte"] + q["keluar_byte"],
        }

    opposite_sort = sorted(per_opposite.values(),
                        key=lambda x: -(x["masuk_byte"] + x["keluar_byte"]))
    gate_sort = sorted(per_gate.values(),
                        key=lambda x: -(x["masuk_byte"] + x["keluar_byte"]))

    # Tidied ONCE: calling rapikan_lawan() twice on the same rows risks the two numbers diverging.
    all_opposite = [rapikan_lawan(p) for p in opposite_sort]

    time_last = (db.query(func.max(Flow.waktu)).scalar())

    return {
        "periode": label,
        "ada_data": bool(tuple_koneksi),
        "koneksi": len(tuple_koneksi),
        "lawan_jumlah": len(per_opposite),
        "lawan_luar": sum(1 for p in per_opposite.values() if p["luar_jaringan"]),
        "lawan_baru": sum(1 for p in all_opposite if p["baru_terlihat"]),
        "total_masuk_teks": format_byte(total_enter),
        "total_keluar_teks": format_byte(total_exit),
        "terakhir": time_last.isoformat() if time_last else None,
        "percakapan": all_opposite[:batas],
        "pintu": [rapikan_pintu(q) for q in gate_sort[:batas]],
        "nama_dns_siap": nama_dns_siap,
        # Stated so the page can tell "no new addresses" from "not enough history to judge".
        "bisa_nilai_baru": bisa_nilai_baru,
        "awal_pengamatan": (awal_pengamatan.isoformat()
                            if awal_pengamatan else None),
        "catatan": ("Angka di bagian ini dibaca dari koneksi TCP yang sedang "
                    "hidup, dipotret tiap 60 detik. Koneksi yang lahir dan "
                    "mati di antara dua potret tidak terlihat sama sekali, "
                    "jadi ini batas bawah, bukan jumlah pasti. Hanya device "
                    "Linux yang bisa di-SSH yang terbaca; router dan laptop "
                    "belum ikut."
                    + ("" if nama_dns_siap else
                       " Nama DNS belum tersedia: migrasi `nama_alamat` belum "
                       "dijalankan, jadi alamat masih tampil apa adanya.")),
    }


def anomali_lalu_lintas(db, period):
    """Anomaly findings for the period, with comparison figures.

    The history used to recognize a never-seen address is taken from the period BEFORE the
    range, not the whole database; otherwise yesterday's new address would already be "old" today.
    """
    import anomali as _an
    mulai, selesai, label = rentang(period)
    width = selesai - mulai

    def fetch(a, b):
        return [{
            "waktu": r.waktu, "ip_klien": r.ip_klien, "path": r.path,
            "status": r.status, "byte_kirim": r.byte_kirim,
            "user_agent": r.user_agent, "dari_nsm": r.dari_nsm,
        } for r in (db.query(AksesWeb)
                    .filter(AksesWeb.waktu >= a, AksesWeb.waktu <= b).all())]

    hasil = _an.periksa(fetch(mulai, selesai), fetch(mulai - width, mulai))
    hasil["periode"] = label
    return hasil


def traffic_semua(db, period, batas=20):
    """Traffic ranking across all devices, for the summary page.

    Returns TWO sources: the access log (which files were fetched, HTTP only) and TCP
    conversations (who talks to whom, all protocols). Either alone would mislead.
    """
    mulai, selesai, label = rentang(period)
    peta = _peta_device(db)

    baris = (db.query(AksesWeb.ip_klien,
                      func.count(AksesWeb.id),
                      func.sum(AksesWeb.byte_kirim),
                      func.max(AksesWeb.waktu),
                      func.sum(case((AksesWeb.dari_nsm == 1, 1), else_=0)))
             .filter(AksesWeb.waktu >= mulai, AksesWeb.waktu <= selesai)
             .group_by(AksesWeb.ip_klien)
             .order_by(desc(func.sum(AksesWeb.byte_kirim)))
             .limit(batas).all())

    klien = [{
        "ip": ip, "device": peta.get(ip), "permintaan": n,
        "unduh_byte": float(b or 0), "unduh_teks": format_byte(b or 0),
        "terakhir": t.isoformat() if t else None,
        "dari_nsm": int(nsm or 0),
    } for ip, n, b, t, nsm in baris]

    line_path = (db.query(AksesWeb.path,
                           func.count(AksesWeb.id),
                           func.sum(AksesWeb.byte_kirim),
                           func.max(AksesWeb.waktu),
                           func.sum(case((AksesWeb.dari_nsm == 1, 1), else_=0)))
                  .filter(AksesWeb.waktu >= mulai, AksesWeb.waktu <= selesai)
                  .group_by(AksesWeb.path)
                  .order_by(desc(func.sum(AksesWeb.byte_kirim)))
                  .limit(batas).all())

    path = [{
        "path": p,
        "permintaan": n,
        "byte": float(b or 0),
        "teks": format_byte(b or 0),
        "terakhir": t.isoformat() if t else None,
        "dari_nsm": int(nsm or 0),
        "rata_teks": format_byte((b or 0) / n) if n else None,
    } for p, n, b, t, nsm in line_path]

    flow = percakapan_jaringan(db, period)

    # Number of addresses actually seen, counted from BOTH sources.
    all_address = {k["ip"] for k in klien} | {p["ip"] for p in flow["percakapan"]}

    return {
        "periode": label,
        "klien": klien,
        "path": path,
        "berkas_terlihat": len(path),
        "total_unduh_teks": format_byte(sum(k["unduh_byte"] for k in klien)),
        "total_permintaan": sum(k["permintaan"] for k in klien),
        "alamat_terlihat": len(all_address),
        "flow": flow,
    }

"""Config command send path: the only file in NSM allowed to change a network
device's state.

FLOW, AND WHY THIS ORDER
------------------------
    1  guards: identity, platform, pause, catalog
    2  BEFORE snapshot                      (evidence of the initial state)
    3  install `reload in N`                (safety net FIRST)
    4  send the command
    5  prove the device still answers       (ping + SSH + re-read)
    6  AFTER snapshot + line diff
    7  a human decides: keep / cancel

Step 3 precedes step 4; that is the core of the design. A safety net installed
after a command that cuts the connection is useless: once the connection is gone
there is no way left to install anything.

Step 5 cannot be skipped. "Command sent" is not "command broke nothing"; the only
meaningful evidence is that the device is still reachable and its config really
changed as requested.

NO ANSWER AT STEP 7 IS A SAFE STATE, NOT A HANGING ONE
------------------------------------------------------
If the operator leaves, the network drops, or NSM itself dies midway, the device
restores itself to its saved config. That is the only design that stays correct
when whoever controls it disappears.

EXCEPTION: GNS3/DYNAMIPS NODES (`Device.gns3_node`)
---------------------------------------------------
On GNS3/Dynamips, `reload` PERMANENTLY powers off the emulated machine instead of
rebooting it (see docs/POSTMORTEM-R1.md), so `reload in N` is NEVER installed on
these devices. The safety net goes through the GNS3 controller API
(`connectors/gns3_pemulihan.py`) and fires ONLY if the device is proven unreachable
after the command is sent. Trade-off, accepted knowingly: if NSM itself dies
exactly between sending and recovery, nothing on the device brings it back, unlike
a physical device. The worst case is "no automatic recovery", not "node dead
forever". For the same reason "cancel" is not done by sending the inverse command;
see `putuskan()` below.

ACTUAL SENDING MUST BE REQUESTED EXPLICITLY
-------------------------------------------
`kirim()` defaults to `sungguhan=False`: it runs the whole flow, builds every
command, and returns exactly what WOULD happen without opening a connection. With
a safe default, forgetting one argument results in nothing happening, not in a
device changing with nobody deciding.
"""
import time
from datetime import datetime

import dialek_perangkat
import identitas
from connectors import gns3_pemulihan
from connectors import konfig as _konfig
from connectors import perintah as _pr
from models import Device, KonfigSnapshot

# How long the safety net waits before the device restores itself.
#
# Ten minutes: five proved too short, because `reload cancel` arrived after the
# device had already entered `SHUTDOWN in 0:01:00` and a valid change was lost. Only
# applies when the net is deliberately kept; see `lepas_setelah_terbukti` in `kirim()`.
MENIT_RELOAD = 10

# Platforms that have a send path. A closed list, not derived from "any platform with
# a catalog": adding a platform to the catalog must not silently grant it write access.
PLATFORM_BISA_KIRIM = ("cisco_ios",)


class Ditolak(Exception):
    """Raised by the guard before anything is sent; the device is untouched."""


# ---------------------------------------------------------------------------
# Penjaga
# ---------------------------------------------------------------------------

def periksa_izin(db, device_id, perintah_id=None):
    """May this command be sent to this device? Raises `Ditolak`.

    `perintah_id=None` checks everything EXCEPT the command's presence in the catalog;
    `simpan_permanen()` uses it because `write memory` is not a catalog entry.

    Called twice: before building and again RIGHT before sending. Not waste: a network
    config read in between can take tens of seconds, and a permission that was valid 30
    seconds ago proves nothing about the device that will receive the command now.
    """
    d = db.query(Device).filter(Device.id == device_id).first()
    if d is None:
        raise Ditolak("Perangkat tidak ada.")

    if (d.platform or "") not in PLATFORM_BISA_KIRIM:
        raise Ditolak(
            f"Platform '{d.platform}' belum punya jalur kirim. "
            f"Yang ada baru: {', '.join(PLATFORM_BISA_KIRIM)}.")

    # Paused devices are not touched: pausing means no longer watching, and changing
    # something unwatched defeats the point of the button.
    #
    # `== 0`, NOT `is False`: `aktif` is an INTEGER column (0/1) and `0 is False` is False
    # in Python, so the guard would never fire. `== 0` also holds for NULL (the column has
    # `default=1`), the convention used throughout the poller.
    if d.aktif == 0:
        alasan = d.jeda_alasan or "tanpa alasan tercatat"
        raise Ditolak(f"Pemantauan perangkat ini sedang dijeda ({alasan}). "
                      f"Lanjutkan pemantauannya dulu sebelum mengubah apa pun.")

    if perintah_id is not None and not any(
            p["id"] == perintah_id for p in _pr.daftar(d.platform)):
        raise Ditolak(f"Perintah '{perintah_id}' tidak tersedia untuk "
                      f"platform '{d.platform}'.")

    if not (d.username and (d.password or d.ssh_key_path)):
        raise Ditolak("Perangkat ini tidak punya kredensial SSH di NSM.")

    # Identity guard, last and most decisive: `reload in` protects against a wrong
    # command, not a wrong device. A perfect command sent to someone else's device runs
    # smoothly and raises no warning.
    allowed, verdict, kenapa = identitas.boleh_ditulisi(db, device_id)
    if not allowed:
        raise Ditolak(f"Identitas perangkat belum memenuhi syarat "
                      f"(vonis: {verdict}). {kenapa}")
    return d


# ---------------------------------------------------------------------------
# Sambungan
# ---------------------------------------------------------------------------

def _sambung(d):
    from netmiko import ConnectHandler
    return ConnectHandler(device_type=d.platform, host=d.ip_address,
                          username=d.username, password=d.password)


def _jawab_prompt(conn, teks_perintah, jawaban_awal=None):
    """Send one exec command that may prompt back, then answer.

    `reload in 5` on IOS can raise TWO different prompts:

        System configuration has been modified. Save? [yes/no]:
        Proceed with reload? [confirm]

    The first MUST be answered **no**. "yes" would save the running config to
    startup-config, so after the reboot the device returns to exactly the state being
    undone and the safety net becomes a tool that makes the mistake permanent.
    """
    keluar = conn.send_command_timing(teks_perintah)
    jejak = [keluar]
    for _ in range(4):
        low = keluar.lower()
        if "save?" in low or "[yes/no]" in low:
            keluar = conn.send_command_timing("no")
        elif "confirm" in low or "[yes]" in low:
            keluar = conn.send_command_timing("\n")
        elif jawaban_awal and jawaban_awal in low:
            keluar = conn.send_command_timing("\n")
        else:
            break
        jejak.append(keluar)
    return "\n".join(jejak)


def _potret(conn, platform):
    return _konfig.bersihkan(_konfig.ambil(conn, platform))



def kirim(db, device_id, perintah_id, nilai, oleh=None,
          menit=MENIT_RELOAD, sungguhan=False, lepas_setelah_terbukti=True):
    """Send one change, with the safety net installed first.

    TWO DIFFERENT JOBS, AND WHY MERGING THEM IS A MISTAKE
    -----------------------------------------------------
    The first design used `reload in N` for two jobs at once:

        (a) rescue the device if the command CUTS THE CONNECTION
        (b) give a human a deadline to decide keep or cancel

    (a) is settled within seconds, as soon as the device answers again after the
    command. (b) waits for a human to read the result and think, which can take any
    time. Merging them puts a human under a deadline that need not exist: a valid change
    was lost when `reload cancel` arrived after the device had entered
    `SHUTDOWN in 0:01:00`.

    `lepas_setelah_terbukti=True` (default) separates them: once the device is proven
    to answer, the safety net is released. Job (a) is done and (b) has no deadline.
    Cancelling stays fully available and just as reliable: nothing was written to
    startup-config, so a `reload` at any time restores the pre-change state line for
    line. Only the trigger changes, from a ticking timer to a decision taken when ready.

    `lepas_setelah_terbukti=False` keeps the old behavior, for changes that should be
    guarded by a deadline.

    `sungguhan=False` (default) runs the whole flow WITHOUT opening a connection and
    returns exactly what would be done. A safe default means forgetting an argument
    results in nothing happening.

    Cancelling is a human decision made after reading the result (`putuskan()`), never
    made inside this function.
    """
    d = periksa_izin(db, device_id, perintah_id)

    snapshot_old = (db.query(KonfigSnapshot)
                   .filter(KonfigSnapshot.device_id == device_id)
                   .order_by(KonfigSnapshot.waktu.desc()).first())
    iface = _konfig.daftar_interface(snapshot_old.teks) if snapshot_old else None

    pratinjau = _pr.pratinjau(perintah_id, nilai, iface)
    if not pratinjau.get("ok"):
        raise Ditolak("Parameter tidak lolos: %s" % pratinjau.get("galat"))

    # Reject commands that target the interface NSM itself uses to reach the device: the
    # connection would drop mid-send, with no way back through that same interface to fix
    # it. Earlier failed `iface_mati`/`iface_hidup` sends fit this pattern (see
    # docs/POSTMORTEM-R1.md).
    #
    # `sendiri` may be None if the snapshot is incomplete or unrecognized. That counts as
    # "cannot tell", NOT "safe", and blocks nothing. This is an extra guard, not a
    # guarantee, and a missing snapshot must not read as permission.
    if pratinjau["memutus"] and snapshot_old and nilai and "interface" in nilai:
        own = _konfig.interface_untuk_ip(snapshot_old.teks, d.ip_address)
        if own and own == nilai["interface"]:
            raise Ditolak(
                "%s adalah interface yang dipakai NSM sendiri untuk "
                "menyambung ke %s (%s). Mengirim perintah ini akan memutus "
                "sambungan di tengah jalan, dan tidak ada jalan balik lewat "
                "interface yang sama untuk memperbaikinya."
                % (own, d.name, d.ip_address))

    is_gns3 = bool(d.gns3_node)

    # The safety net is read from the definition file (`perangkat/<platform>.yaml`,
    # section `tulis.jaring_pengaman`), not written here, so vendor-specific knowledge
    # stays out of this module. A platform with no way to install a net is rejected below
    # instead of being sent a `reload in N` it does not understand.
    _def = dialek_perangkat.ambil(d.platform)
    net = _def.jaring_pengaman

    if not is_gns3 and not _def.bisa_pasang_jaring_pengaman:
        raise Ditolak(
            "Perangkat %s berplatform %r, dan NSM belum tahu cara memasang "
            "jaring pengaman di platform itu (jenis mekanisme: %s). Tidak ada "
            "satu perintah pun yang dikirim -- mengirim tanpa jaring berarti "
            "satu perintah salah membuat perangkat tidak bisa dihubungi lagi."
            % (d.name, d.platform, net["jenis"]))

    line = _pr.susun(perintah_id, nilai, iface)
    plan = {
        "device_id": d.id,
        "device": d.name,
        "perintah_id": perintah_id,
        "perintah": pratinjau["perintah"],
        "memutus": pratinjau["memutus"],
        "oleh": oleh,
        "menit_reload": None if is_gns3 else menit,
        "gns3_node": d.gns3_node,
        "urutan": (
            (["configure terminal"] + line + ["end"])
            if is_gns3 else
            ([net["pasang"].format(menit=menit)
              + "   <- jaring pengaman, dipasang DULU"]
             + ["configure terminal"] + line + ["end"])
        ),
    }
    # BLAST RADIUS: if this command turns out wrong, who ELSE goes dark.
    #
    # The guard above only rejects commands on the interface NSM uses to reach THIS
    # device (one hop). Shutting `Fa1/0` on R1 does not cut R1 (NSM still enters via
    # `Fa0/0`) but cuts R2, SW-B and LDAP at once.
    #
    # This number blocks nothing; it goes in the plan so it is read BEFORE pressing send.
    # Blocking automatically would be wrong: sometimes the transit device is exactly what
    # needs changing.
    try:
        import ketergantungan as _kg
        _g = _kg.graf(db)
        _downstream = _kg.hilir(db, d.id, g=_g)
        _complete, _disconnect = _kg.graf_lengkap(db, _g)
        plan["dampak_hilir"] = [{"id": x["id"], "nama": x["nama"]}
                                   for x in _downstream]
        plan["dampak_hilir_jumlah"] = len(_downstream)
        plan["dampak_hilir_pasti"] = bool(_complete)
        if _downstream:
            plan["dampak_hilir_kalimat"] = (
                "Kalau perintah ini salah, %d perangkat lain ikut kehilangan "
                "jalur dari NSM: %s."
                % (len(_downstream), ", ".join(x["nama"] for x in _downstream)))
        elif _complete:
            plan["dampak_hilir_kalimat"] = (
                "Tidak ada perangkat lain yang jalurnya melewati %s."
                % d.name)
        else:
            plan["dampak_hilir_kalimat"] = (
                "Radius dampak TIDAK BISA DIPASTIKAN: %d perangkat tidak "
                "punya jalur tercatat di `device_link`. Ini bukan berarti "
                "aman -- berarti NSM tidak tahu."
                % len(_disconnect))
    except Exception as e:
        # Extra safeguard, not a requirement: its failure must NOT stop a legitimate command.
        # Same as the upstream filter in `pemulih/orkestrasi.py`.
        plan["dampak_hilir"] = None
        plan["dampak_hilir_pasti"] = False
        plan["dampak_hilir_kalimat"] = (
            "Radius dampak gagal dihitung (%s) -- diperlakukan sebagai TIDAK "
            "DIKETAHUI, bukan sebagai aman." % str(e)[:120])

    if is_gns3:
        plan["catatan_jaring"] = (
            "Node GNS3 (%s) -- TIDAK memakai `reload in N`. Jaring "
            "pengamannya: kalau perangkat terbukti tidak menjawab lagi "
            "sesudah perintah dikirim, NSM memulihkannya lewat API "
            "controller GNS3 (hentikan lalu nyalakan ulang node itu saja)."
            % d.gns3_node)

    if not sungguhan:
        plan.update({
            "terkirim": False,
            "kenapa": "Mode aman: `sungguhan=False`. Tidak ada koneksi yang "
                      "dibuka dan tidak ada satu pun perintah yang dikirim.",
        })
        return plan

    start = datetime.now()
    conn = _sambung(d)
    catatan = []
    try:
        periksa_izin(db, device_id, perintah_id)

        before = _potret(conn, d.platform)
        catatan.append("potret sebelum diambil (%d baris)" % len(before.splitlines()))

        if not is_gns3:
            # 3. Safety net FIRST, then the command (physical devices; GNS3 nodes skip this
            # block entirely, see `is_gns3` above).
            _jawab_prompt(conn, net["pasang"].format(menit=menit))

            # PROVEN, not assumed. The reload command can fail silently (permission denied, an
            # unanswered prompt, an unexpected reply). If we then went on, the command would run
            # with NO safety net, which looks the same from outside until something goes wrong.
            #
            # `show reload` answers "Reload scheduled for ..." if installed and "No reload is
            # scheduled." if not.
            bukti = conn.send_command(net["bukti"])
            if not any(p.lower() in bukti.lower()
                       for p in net["penanda_terpasang"]):
                raise Ditolak(
                    "Jaring pengaman TIDAK terpasang — `%s` menjawab: "
                    "%r. Tidak ada satu perintah pun yang dikirim."
                    % (net["bukti"], bukti.strip()[:160]))
            catatan.append("%s terpasang, dibuktikan `%s`: %s"
                           % (net["pasang"].format(menit=menit),
                              net["bukti"], bukti.strip()[:90]))
        else:
            catatan.append("node GNS3 (%s) -- reload in N TIDAK dipasang, "
                           "jaring pengamannya lewat API GNS3 kalau perlu"
                           % d.gns3_node)

        # 4. Perintahnya.
        exit_send = conn.send_config_set(line)
        catatan.append("perintah dikirim")

        time.sleep(1)
        after = _potret(conn, d.platform)
        catatan.append("perangkat masih menjawab sesudah perubahan")

        # 5b. The "connection cut" threat has passed: the device just answered. The net is
        # released here instead of waiting on the human, because that deadline is not theirs.
        # Cancelling stays available: startup-config is untouched.
        jaring_terpasang = True
        if is_gns3:
            jaring_terpasang = False
        elif lepas_setelah_terbukti:
            _jawab_prompt(conn, net["kukuhkan"])
            remaining = conn.send_command(net["bukti"])
            if any(p.lower() in remaining.lower() for p in net["penanda_lepas"]):
                jaring_terpasang = False
                catatan.append("jaring pengaman dilepas (perangkat sudah "
                               "terbukti menjawab); dibuktikan `show reload`")
            else:
                catatan.append("PERINGATAN: gagal melepas jaring pengaman, "
                               "tenggat masih berjalan: %s" % remaining.strip()[:90])

    except Exception as e:
        try:
            conn.disconnect()
        except Exception:
            pass

        recovery = None
        if is_gns3 and pratinjau["memutus"]:
            # The network path just proved untrustworthy: call the GNS3 controller API DIRECTLY,
            # not through the SSH/network that just failed.
            try:
                recovery = gns3_pemulihan.pulihkan(d.gns3_node)
                recovery["ok"] = True
            except gns3_pemulihan.GagalPulih as ge:
                recovery = {"ok": False, "galat": str(ge)}

        if recovery and recovery.get("ok"):
            kenapa = ("Gagal di tengah jalan. Node GNS3 %s dipulihkan "
                     "otomatis lewat API controller (dihentikan lalu "
                     "dinyalakan ulang) -- tunggu satu putaran poller "
                     "berikutnya untuk konfirmasi ia sudah menjawab lagi."
                     % d.gns3_node)
        elif recovery:
            kenapa = ("Gagal di tengah jalan, DAN pemulihan otomatis lewat "
                     "API GNS3 JUGA gagal (%s). Perangkat mungkin masih "
                     "tidak terjangkau -- periksa manual, jangan diasumsikan "
                     "pulih sendiri." % recovery.get("galat"))
        else:
            kenapa = ("Gagal di tengah jalan. Kalau jaring pengaman sudah "
                     "terpasang, ia SENGAJA tidak dibatalkan: perangkat akan "
                     "mengembalikan dirinya sendiri.")

        plan.update({
            "terkirim": False,
            "galat": str(e),
            "catatan": catatan,
            "reload_masih_terpasang": (not is_gns3) and any("reload" in c for c in catatan),
            "pemulihan_gns3": recovery,
            "kenapa": kenapa,
        })
        return plan

    add, delete, _chunk = _konfig.beda_baris(before, after)
    conn.disconnect()

    plan.update({
        "terkirim": True,
        "catatan": catatan,
        "keluaran": exit_send,
        "baris_bertambah": add,
        "baris_berkurang": delete,
        "berubah": bool(add or delete),
        "reload_masih_terpasang": jaring_terpasang,
        "batas_waktu": start.isoformat(),
        "lama_detik": round((datetime.now() - start).total_seconds(), 1),
        "langkah_berikutnya": (
            f"Perangkat akan menyala ulang dalam {menit} menit dan kembali ke "
            f"konfigurasi tersimpan, KECUALI kamu memilih 'pertahankan'."
            if jaring_terpasang else
            "Tidak ada tenggat. Perubahan berlaku sekarang tetapi BELUM "
            "permanen — startup-config belum tersentuh, jadi `reload` kapan "
            "pun akan mengembalikan perangkat ke keadaan sebelum perubahan. "
            "Menyimpan permanen adalah tombol terpisah."),
    })
    return plan


def putuskan(db, device_id, tindakan, sungguhan=False):
    """Step 7: keep or cancel.

    WHY "CANCEL" DOES NOT SEND THE INVERSE COMMAND
    ----------------------------------------------
    Tempting: remember the sent command and send its opposite (`no shutdown` for
    `shutdown`, `no description` for `description`). Rejected on purpose. An inverse is
    only right if the previous state was empty: `no description` on an interface that
    already had one deletes the old description instead of restoring it. Doing it right
    means NSM reconstructing the old state of every touched line, i.e. writing an IOS
    config-reversal engine, far bigger than the rest of this module, whose failures
    would show up at the worst moment: while repairing something already broken.

    What is used instead: the device already holds the answer, because startup-config
    still contains the pre-change state. "Cancel" means letting the device restore
    itself, exact to the last line, since the device does it rather than an NSM guess.
    The price is one reboot, which is cheap for a lab router, and the honesty of "NSM
    cannot partially cancel" beats a cancel button that is only sometimes right.

    GNS3 NODES: NEVER CLI `reload`
    ------------------------------
    `batalkan_sekarang` below recovers `gns3_node` devices through
    `gns3_pemulihan.pulihkan()` (controller API), NOT a raw CLI `reload`, which is the
    same IOS command that permanently powers off the node in Dynamips. Since `kirim()`
    never installs `reload in N` for GNS3 nodes, `pertahankan` has nothing to release
    for them either.
    """
    if tindakan not in ("pertahankan", "batalkan", "batalkan_sekarang"):
        raise Ditolak(f"Tindakan '{tindakan}' tidak dikenal.")

    d = db.query(Device).filter(Device.id == device_id).first()
    if d is None:
        raise Ditolak("Perangkat tidak ada.")

    is_gns3 = bool(d.gns3_node)

    if tindakan == "batalkan":
        return {
            "device_id": d.id, "device": d.name, "tindakan": tindakan,
            "dikirim": [],
            "hasil": (
                "Node GNS3 (%s) tidak pernah memasang `reload in N` -- "
                "perubahan yang tadi terkirim sudah berlaku sejak saat itu, "
                "TETAPI belum permanen (startup-config belum tersentuh). "
                "Tidak ada tenggat yang berjalan dan tidak ada yang perlu "
                "dibatalkan." % d.gns3_node
                if is_gns3 else
                "Tidak ada perintah yang dikirim, dan itu memang caranya. "
                "`reload in` yang sudah terpasang akan menyalakan ulang "
                "perangkat dan mengembalikannya ke konfigurasi tersimpan. "
                "Pengembaliannya utuh sampai baris terakhir karena yang "
                "mengembalikan adalah perangkatnya sendiri."),
        }

    if not sungguhan:
        return {
            "device_id": d.id, "device": d.name, "tindakan": tindakan,
            "dikirim": (
                (["(tidak ada -- node GNS3 tidak pernah memasang reload]"]
                 if tindakan == "pertahankan" else
                 ["API GNS3: stop lalu start node %s" % d.gns3_node])
                if is_gns3 else
                ["reload cancel" if tindakan == "pertahankan" else "reload"]
            ),
            "terkirim": False,
            "kenapa": "Mode aman: `sungguhan=False`.",
        }

    if is_gns3:
        if tindakan == "pertahankan":
            return {
                "device_id": d.id, "device": d.name, "tindakan": tindakan,
                "terkirim": True, "keluaran": None,
                "hasil": ("Tidak ada apa pun yang perlu dilepas -- node GNS3 "
                         "(%s) ini tidak pernah memasang reload in N. "
                         "Perubahan tetap berlaku, belum permanen."
                         % d.gns3_node),
            }
        try:
            recovery = gns3_pemulihan.pulihkan(d.gns3_node)
        except gns3_pemulihan.GagalPulih as ge:
            raise Ditolak("Pemulihan lewat API GNS3 gagal: %s" % ge)
        return {
            "device_id": d.id, "device": d.name, "tindakan": tindakan,
            "terkirim": True, "keluaran": recovery,
            "hasil": ("Node GNS3 %s dihentikan lalu dinyalakan ulang lewat "
                     "API controller. Ia akan kembali ke konfigurasi "
                     "tersimpan begitu boot selesai -- tunggu satu putaran "
                     "poller berikutnya untuk konfirmasi." % d.gns3_node),
        }

    conn = _sambung(d)
    try:
        if tindakan == "pertahankan":
            keluar = _jawab_prompt(conn, "reload cancel")
            hasil = ("Jaring pengaman dilepas. Perubahan tetap berlaku, TETAPI "
                     "belum permanen: perangkat akan kembali ke konfigurasi "
                     "tersimpan kalau dinyalakan ulang. Menyimpan permanen "
                     "adalah tombol terpisah.")
        else:  # batalkan_sekarang
            keluar = _jawab_prompt(conn, "reload")
            hasil = ("Perangkat dinyalakan ulang sekarang, tanpa menunggu. Ia "
                     "akan kembali ke konfigurasi tersimpan.")
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass

    return {"device_id": d.id, "device": d.name, "tindakan": tindakan,
            "terkirim": True, "keluaran": keluar, "hasil": hasil}


def simpan_permanen(db, device_id, sungguhan=False):
    """`write memory`: a standalone button.

    Deliberately NEVER called by `kirim()` or `putuskan()`. While a change is unsaved,
    rebooting the device still undoes it, so any mistake keeps a way home that needs
    nobody's care. Saving permanently closes that way home, which deserves its own
    decision.
    """
    d = periksa_izin(db, device_id)

    if not sungguhan:
        return {"device_id": d.id, "device": d.name, "dikirim": ["write memory"],
                "terkirim": False, "kenapa": "Mode aman: `sungguhan=False`."}

    conn = _sambung(d)
    try:
        keluar = _jawab_prompt(conn, "write memory")
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass
    return {"device_id": d.id, "device": d.name, "terkirim": True,
            "keluaran": keluar,
            "hasil": "Konfigurasi disimpan permanen. Menyalakan ulang perangkat "
                     "tidak lagi membatalkan perubahan ini."}

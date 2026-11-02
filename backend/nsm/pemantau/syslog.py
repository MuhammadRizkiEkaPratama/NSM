from datetime import datetime
from database import SessionLocal
from config import (get_syslog_aktif, get_syslog_port,
                    get_snmptrap_aktif, get_snmptrap_port,
                    get_snmptrap_community)


_syslog_penerima = None


_snmptrap_penerima = None


_syslog_peta = {}


_syslog_peta_diperbarui = None


def _syslog_simpan(hasil):
    """Called from the receiver thread for every incoming datagram."""
    global _syslog_peta, _syslog_peta_diperbarui
    import syslog_service as _ss

    db = SessionLocal()
    try:
        # Address->device map refreshed every 5 minutes, not per message; syslog can
        # arrive thousands of times per minute.
        sekarang = datetime.now()
        if (_syslog_peta_diperbarui is None
                or (sekarang - _syslog_peta_diperbarui).total_seconds() > 300):
            _syslog_peta = _ss.peta_alamat(db)
            _syslog_peta_diperbarui = sekarang

        line = _ss.simpan(db, hasil, peta=_syslog_peta)
        if line is None:
            return  # suppressed (same template, just seen)

        # Config was just changed -> check drift EARLIER. This only triggers a CHECK,
        # never an action: syslog is easy to spoof, so it must never touch a device directly.
        if _ss.perlu_periksa_konfig(hasil) and line.device_id:
            print("[syslog] %s: konfigurasi diubah -> %s"
                  % (line.alamat, (hasil.get("pesan") or "")[:90]))

        # A pattern never seen before is the most valuable signal in this stream: the
        # device is saying something it has never said.
        elif _ss.templat_baru(db, line.sidik_templat):
            print("[syslog] POLA BARU dari %s: %s"
                  % (line.alamat, (hasil.get("pesan") or "")[:90]))
    except Exception as e:
        # The receiver thread must not die because one message failed to save.
        print("[syslog] gagal menyimpan: %s" % str(e)[:160])
    finally:
        db.close()


def mulai_snmptrap():
    """Start the SNMP trap receiver if the operator allows it.
    Reuses `_syslog_simpan`: traps and syslog answer the same question and share a
    table, so the page, correlation and pattern mining need no duplicate work.
    """
    global _snmptrap_penerima
    if not get_snmptrap_aktif():
        return "mati"
    try:
        from snmptrap_terima import PenerimaTrap
        port = get_snmptrap_port()
        _snmptrap_penerima = PenerimaTrap(
            port=port, simpan=_syslog_simpan,
            community=get_snmptrap_community()).mulai()
        return "dengar UDP %d" % port
    except Exception as e:
        print("[snmptrap] TIDAK bisa dinyalakan: %s" % str(e)[:160])
        return "GAGAL (%s)" % str(e)[:60]


def start_syslog():
    """Start the syslog receiver if the operator allows it."""
    global _syslog_penerima
    if not get_syslog_aktif():
        return "mati"
    try:
        from syslog_terima import Penerima
        port = get_syslog_port()
        _syslog_penerima = Penerima(port=port, simpan=_syslog_simpan).mulai()
        return "dengar UDP %d" % port
    except Exception as e:
        # Port in use or not bindable. The poller keeps running; losing syslog is far
        # less bad than losing monitoring.
        print("[syslog] TIDAK bisa dinyalakan: %s" % str(e)[:160])
        return "GAGAL (%s)" % str(e)[:60]

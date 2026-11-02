"""Every `.env` key that code SETS must actually be READ by `config.py`.

Two tests were once found silently setting keys that `config.py` never read
(`PAGAR_JAM_KERJA` vs `PAGAR_JAM_MULAI/SELESAI`, and a double `_PER` typo in
`PAGAR_BATAS_DEVICE_PER_JAM`). They never had any effect and no error said so;
the tests stayed green by coincidence. `.env.contoh` already warns about
settings code no longer reads; a typo in the name causes the same trap.

Keys read are collected from `config.py` (`_baca().get("X")` and the
`_daftar("X")` helper); keys set are collected from UPPER_CASE string literals
in other Python files. Only keys with known prefixes (`PAGAR_`, `AGEN_SOC_`,
...) are checked; without the prefix limit every uppercase constant would be
caught and the output would be too noisy to read.
"""
import os
import re

import pytest

pytestmark = pytest.mark.murni

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

AWALAN = ("PAGAR_", "AGEN_SOC_", "NOTIF_", "POLL_", "STABIL_", "AUTO_BAN_",
          "PEMULIH_", "OTOMASI_", "BACKUP_", "LDAP_", "SYSLOG_", "KORELASI_",
          "REPLIKASI_", "TRAFFIC_", "SNMP_", "ALAMAT_", "ROUTER_ACL",
          "PROBE_", "SADAP_", "BASELINE_")

# Keys intentionally not read by `config.py`, each with a reason. Keep this
# list short: each entry is one more setting that affects nothing.
DIKECUALIKAN = {
    # Written by `nyalakan_otomasi.py` into the `.env` as a note for
    # humans; the effective values are PAGAR_JAM_MULAI/PAGAR_JAM_SELESAI. Kept so
    # existing `.env` files need no edit, but recorded here as debt.
    "PAGAR_JAM_KERJA",
}


def _kunci_dibaca():
    hasil = set()
    for nama in ("config.py", "database.py"):
        content = open(os.path.join(BACKEND, nama), encoding="utf-8").read()
        hasil |= set(re.findall(
            r'(?:_baca\(\)|env)\.get\(\s*["\']([A-Z][A-Z0-9_]*)["\']', content))
        hasil |= set(re.findall(r'_daftar\(\s*["\']([A-Z][A-Z0-9_]*)["\']', content))
        hasil |= set(re.findall(
            r'_baca\(\)\.get\(\s*["\']([A-Z][A-Z0-9_]*)["\']', content))
    return hasil


def _kunci_disetel():
    """{key: {files}} for settings keys set in other Python files."""
    hasil = {}
    for root_cause, dirs, file in os.walk(BACKEND):
        dirs[:] = [d for d in dirs if d not in ("venv", "__pycache__")]
        for b in file:
            # This file is excluded: its `AWALAN` list and docstring examples look exactly
            # like setting keys, so the scanner would accuse itself.
            if (not b.endswith(".py")
                    or b in ("config.py", "database.py", os.path.basename(__file__))):
                continue
            content = open(os.path.join(root_cause, b), encoding="utf-8",
                          errors="replace").read()
            for k in re.findall(r'["\']([A-Z][A-Z0-9_]{3,})["\']\s*[:,]', content):
                if k.startswith(AWALAN):
                    hasil.setdefault(k, set()).add(b)
            for k in re.findall(
                    r'\b([A-Z][A-Z0-9_]{3,})\s*=\s*["\'][^"\']*["\']\s*\)', content):
                if k.startswith(AWALAN):
                    hasil.setdefault(k, set()).add(b)
    return hasil


def test_setiap_setelan_yang_disetel_benar_benar_dibaca():
    dibaca = _kunci_dibaca()
    disetel = _kunci_disetel()

    down = {k: v for k, v in disetel.items()
            if k not in dibaca and k not in DIKECUALIKAN}

    assert not down, (
        "kunci setelan ini DISETEL tetapi tidak dibaca `config.py` mana pun, "
        "jadi menyetelnya tidak berpengaruh apa-apa:\n"
        + "\n".join("    %-34s dipakai di: %s" % (k, ", ".join(sorted(v)))
                    for k, v in sorted(down.items())))


def test_pengecualiannya_masih_beralasan():
    """Excluded keys must truly not be read. If one starts being read by
    `config.py`, the exclusion is wrong and must be removed; otherwise it hides
    the next typo on the same name.
    """
    dibaca = _kunci_dibaca()
    keliru = sorted(k for k in DIKECUALIKAN if k in dibaca)
    assert not keliru, (
        "kunci ini sekarang DIBACA config.py, jadi pengecualiannya harus "
        "dicabut dari DIKECUALIKAN: %r" % keliru)


def test_pemeriksanya_sendiri_menemukan_yang_dibaca():
    """Guard on the guard: the key collector must actually work. If
    `_kunci_dibaca()` returned an empty set (for example after `config.py` is
    rewritten and the pattern stops matching), the test above would pass for ALL
    keys and silently guard nothing.
    """
    dibaca = _kunci_dibaca()
    assert len(dibaca) > 40, "hanya %d kunci terbaca; polanya tidak cocok lagi" % len(dibaca)
    for required in ("PAGAR_JAM_MULAI", "PAGAR_BATAS_DEVICE_PER_JAM",
                  "AUTO_BAN_AKTIF", "ALAMAT_NSM"):
        assert required in dibaca, "%s seharusnya terbaca sebagai kunci config" % required

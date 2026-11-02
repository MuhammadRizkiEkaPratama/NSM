# -*- coding: utf-8 -*-
"""Guard tests for Layer C (prose translation).

Layer C promises one thing: code does not change. This file enforces that
with an instant token-by-token comparison instead of slow behavioral tests.

Each "must pass" test lists what Layer C MAY edit; each "must be caught"
test lists what it may not.
"""

import pytest

import terjemah_prosa as tp


ASLI = '''"""Docstring modul."""
X = 1


def f(a):
    """Kembalikan a."""
    # komentar
    return a + X
'''


# ------------------------------------------------------------- allowed edits

@pytest.mark.parametrize("nama,lama,baru", [
    ("docstring fungsi", '"""Kembalikan a."""', '"""Return a."""'),
    ("komentar", "# komentar", "# comment"),
    ("docstring modul", '"""Docstring modul."""', '"""Module docstring."""'),
])
def test_prosa_boleh_berubah(nama, lama, baru):
    assert tp.bandingkan(ASLI, ASLI.replace(lama, baru)) is None


def test_docstring_boleh_berubah_jumlah_barisnya():
    """Translations are rarely the same length as the original.

    Layout tokens (NEWLINE, NL, INDENT) are therefore excluded from the
    comparison: line count may change, code content may not.
    """
    baru = ASLI.replace('"""Docstring modul."""',
                        '"""Module docstring.\n\nWith three lines now.\n"""')
    assert tp.bandingkan(ASLI, baru) is None


# ------------------------------------------------------------ must be caught

@pytest.mark.parametrize("nama,lama,baru", [
    ("nama dalam kode", "return a + X", "return a + Y"),
    ("angka", "X = 1", "X = 2"),
    ("tanda tangan", "def f(a):", "def f():"),
    ("operator", "return a + X", "return a - X"),
])
def test_kode_tidak_boleh_berubah(nama, lama, baru):
    assert tp.bandingkan(ASLI, ASLI.replace(lama, baru)) is not None


def test_string_pengguna_tidak_boleh_berubah():
    """Enforces the decision that user-facing text stays Indonesian.

    `"Perangkat tidak menjawab"` is not a docstring, so it is outside Layer C's
    scope. A guard that only asks "is this a string" would let user-facing text
    through and change the wording operators see every day.

    The distinction: a docstring is the FIRST statement of a module, class, or
    function. No other string qualifies.
    """
    asli = 'def f():\n    """Doc."""\n    return "Perangkat tidak menjawab"\n'
    baru = 'def f():\n    """Doc."""\n    return "Device is not responding"\n'
    assert tp.bandingkan(asli, baru) is not None


def test_string_kedua_dalam_fungsi_bukan_docstring():
    """A standalone string on the second line is still not a docstring and stays
    guarded.
    """
    asli = 'def f():\n    """Doc."""\n    "catatan"\n    return 1\n'
    baru = 'def f():\n    """Doc."""\n    "note"\n    return 1\n'
    assert tp.bandingkan(asli, baru) is not None


def test_hasil_yang_rusak_ditolak_bukan_dilaporkan_aman():
    asli = 'def f():\n    """Doc."""\n    return 1\n'
    assert tp.bandingkan(asli, 'def f(\n    """Doc."""\n') is not None


# --------------------------------------------------------------------- size

def test_posisi_docstring_hanya_menemukan_docstring():
    src = ('"""M."""\n'
           'A = "bukan docstring"\n'
           'class K:\n'
           '    """K."""\n'
           '    def m(self):\n'
           '        """M."""\n'
           '        return "juga bukan"\n')
    assert len(tp.posisi_docstring(tp.ast.parse(src))) == 3

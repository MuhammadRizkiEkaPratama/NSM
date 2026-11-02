"""Test: no global name is used without being defined.

When `report_service.py` was split into a package, the automatic import counter
read only the first line of MULTI-LINE imports, so `report_service/identitas.py`
lost `OrangLdap`. Nothing else caught it: the existing tests stayed green and
the module still imported. Python only complains when the line actually runs,
and `/ldap/direktori` is rarely opened.

`symtable` (Python's own scope analyzer) distinguishes local, closure, and
global names. Only names Python itself treats as global are checked, and each
must exist at module level or in `builtins`. No extra linter is installed, to
avoid adding dependencies to the runtime venv.

Pure test: reads files, never runs their code.

Run: py uji_nama_terdefinisi.py
"""
import ast
import builtins
import os
import symtable
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
PAKET = ["report_service", "nsm"]
# Two root files rewritten during the restructuring. The rest of `backend/` is
# deliberately not checked, so old findings do not mix with new ones.
BERKAS_AKAR = ["main.py", "poller.py"]

DIMAAFKAN = {"__file__", "__name__", "__doc__", "__package__", "__path__",
             "__builtins__", "__spec__", "__loader__"}


def berkas_paket():
    for b in BERKAS_AKAR:
        yield os.path.join(DIR, b)
    for package in PAKET:
        for root_cause, _dirs, file in os.walk(os.path.join(DIR, package)):
            if "__pycache__" in root_cause:
                continue
            for b in file:
                if b.endswith(".py"):
                    yield os.path.join(root_cause, b)


def terikat_di_modul(pohon):
    """Names actually defined at module level."""
    nama = set()
    for n in ast.walk(pohon):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                nama.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nama.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            nama.add(n.id)
        elif isinstance(n, ast.Global):
            nama.update(n.names)
    return nama


def global_dirujuk(tabel, keluar=None):
    """Names Python treats as global and that are actually read."""
    keluar = set() if keluar is None else keluar
    for s in tabel.get_symbols():
        if s.is_global() and s.is_referenced():
            keluar.add(s.get_name())
    for child in tabel.get_children():
        global_dirujuk(child, keluar)
    return keluar


def uji_tidak_ada_nama_menggantung():
    default = set(dir(builtins))
    temuan = []
    checked = 0
    for jalur in berkas_paket():
        content = open(jalur, encoding="utf-8").read()
        pohon = ast.parse(content, jalur)
        tabel = symtable.symtable(content, jalur, "exec")
        exists = terikat_di_modul(pohon) | default | DIMAAFKAN
        menggantung = sorted(global_dirujuk(tabel) - exists)
        checked += 1
        for nama in menggantung:
            temuan.append(f"{os.path.relpath(jalur, DIR)}: {nama}")
    assert not temuan, (f"{len(temuan)} nama dipakai tapi tidak pernah "
                        f"didefinisikan: {temuan[:8]}")
    print(f"  {checked} berkas: tidak ada nama global yang menggantung")


def uji_pemeriksanya_sendiri_bekerja():
    """A test that can never fail guards nothing, so the checker is first run against a
    defect shaped like the real one: a model name used without ever being imported.
    """
    example = "def ambil(db):\n    return db.query(OrangLdap).all()\n"
    pohon = ast.parse(example)
    tabel = symtable.symtable(example, "<contoh>", "exec")
    exists = terikat_di_modul(pohon) | set(dir(builtins)) | DIMAAFKAN
    assert "OrangLdap" in global_dirujuk(tabel) - exists, \
        "pemeriksa TIDAK menangkap nama yang jelas-jelas tidak ada"
    print("  pemeriksa menangkap cacat contoh: ya")


if __name__ == "__main__":
    gagal = 0
    for uji in [uji_pemeriksanya_sendiri_bekerja, uji_tidak_ada_nama_menggantung]:
        print(f"{uji.__name__} ...")
        try:
            uji()
        except AssertionError as e:
            gagal += 1
            print(f"  GAGAL: {e}")
    print("LOLOS" if not gagal else f"{gagal} uji gagal")
    sys.exit(1 if gagal else 0)

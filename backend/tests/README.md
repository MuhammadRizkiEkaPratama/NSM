# NSM tests: the pytest scaffold and the conversion recipe

## Running

Run from the repository root with the backend virtualenv active
(`pip install -r backend/requirements.txt pytest pytest-xdist`):

```bash
python -m pytest
```

| Command | What runs |
|---|---|
| `pytest` | everything; tests needing the lab and tests that change devices are **skipped** |
| `pytest -m murni` | the files `ci_manifest.json` classifies as `murni` (96; proven not to need the live lab) |
| `pytest --lab` | also those needing live VMs/routers/LDAP |
| `pytest --ubah-perangkat` | also those that **write to real (lab) devices** |
| `pytest -n auto` | parallel (pytest-xdist); safe, each legacy file is still its own subprocess |
| `pytest -k name` | one file or a group |

The older runner still exists and remains the source of truth until equivalence
is proven file by file:

```bash
python backend/jalankan_ci.py --mode semua
```

---

## Two layers, and why

The full reasoning is in the docstring of `conftest.py`. In short, measured with
an AST scanner over the 105 test files:

| Shape | Count |
|---|---|
| run their tests **at import time** | **79** |
| have no collectable `uji_*` function | **97** |
| safe **and** have a test function | **8** |

pytest imports every file during **collection**. Pointing pytest straight at
`backend/` would therefore run 79 test files before the first official test
starts, touching the network, writing to databases, and, for three files,
**changing real devices**, and then report almost zero collected tests.

**Layer 1** (`test_warisan.py`): each `uji_*.py` is wrapped as one pytest test
that runs it as a subprocess, with the same semantics as `jalankan_ci.py`.

**Layer 2**: files rewritten as native pytest live in `tests/` as `test_*.py`
and are listed in `SUDAH_PINDAH` (12 so far).

---

## Recipe: converting one file

### 1. Read the original file completely

Especially its docstring. **The reasons written there move with it.** Many hold
incident history found nowhere else, which is the most valuable part of these
tests, more than the asserts.

### 2. Map its shape

Almost every file follows the same pattern:

```python
lolos, gagal = [], []

def cek(nama, dapat, harap):
    ...

print("\n1. First scenario")
h = modul.fungsi(...)
cek("what is checked", h["x"], "expected")
```

| Legacy | pytest |
|---|---|
| each `print("\nN. ...")` block | one `test_*` function |
| `cek(nama, dapat, harap)` | `assert dapat == harap, nama` |
| `lolos`/`gagal` counters | dropped; pytest counts |
| `sys.exit(1 if gagal else 0)` | dropped |
| module-level fake data | module constant, or `@pytest.fixture` |
| manifest bucket | `pytestmark = pytest.mark.murni` (or `butuh_lab`) |

### 3. One scenario, one function

In the old shape, a scenario that dies with an exception **stops the scenarios
after it**, and the report names only one failure. As separate functions, one
broken test no longer hides the others. The function name is the report:
`test_data_server_mati_mysql_akibat` beats `test_skenario_1`.

### 4. Prove the conversion can FAIL

A checker never seen failing gives false assurance. Plant a defect on purpose:

```bash
sed 's/== "sebab"/== "akibat"/' backend/tests/test_x.py > backend/tests/test_x_tanam_tmp.py
python -m pytest -q backend/tests/test_x_tanam_tmp.py   # MUST be red
rm backend/tests/test_x_tanam_tmp.py
```

### 5. Register it in `SUDAH_PINDAH`

```python
SUDAH_PINDAH = {
    "uji_akar.py": "test_akar.py",
}
```

`test_rangka.py` enforces three things on this list:

* a registered name **must have a real replacement file**; otherwise one line
  would stop a test file from ever running while the report stays green;
* an original file still on disk **must still be in the manifest**;
* **no** `uji_*.py` may escape both runners at once.

### 6. Do NOT delete the original yet

While `jalankan_ci.py` is the source of truth it runs the original, so every
file runs exactly once in each runner and there is no coverage gap during the
transition. Legacy files are deleted **together** when the old runner is
retired, once equivalence is proven for all 105.

---

## What is not done yet, and must not be claimed

A legacy file that is still wrapped shows up as **one** pytest test, not dozens.
`uji_report_service.py` contains 78 checks, but pytest sees a single green or red
dot until it is converted. So "105 tests passed" in today's report means 105
**files**, not 105 checks; the real number of checks is much larger.

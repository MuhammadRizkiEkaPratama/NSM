"""uvicorn entry point: assembles the app via `nsm/antarmuka/http/rakit.py`.

What remains here belongs to the entry point itself: the `app` name uvicorn looks
up, and a few names the test files read through `main.`.

Assembly lives in `rakit.py` so there is a single assembly path. With two paths
(this file, and a smaller one used only by tests) the tests exercised an app that
never served anyone, and adding a router in one place but not the other raised no
error; the tests just stopped covering it.
"""
# These names STAY here because test files read them through `main.`; moving them
# would mean touching the tests for a change that alters no behavior.
#
# `SessionLocal` in particular: `uji_main.py` patches it (`main.SessionLocal =
# pabrik`) so the test does not write to the primary lab instance's MySQL. If that
# line disappeared, the patch would no longer find its target and the test would NOT
# fail; it would PASS while writing to the real database.
from database import SessionLocal  # noqa: F401
from nsm.antarmuka.http import rakit
from nsm.antarmuka.http.rakit import NAMA_KEPALA_TENANT  # noqa: F401
from nsm.antarmuka.http.rakit import (
    pasang_middleware_tenant as _pasang_middleware_tenant,  # noqa: F401
)

app = rakit.buat_aplikasi()

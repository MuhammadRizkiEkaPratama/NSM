"""Intent renderer: structured data + template -> intended configuration text.

Three required properties:
1. DETERMINISTIC. The same input must always give the same output; drift detection compares
   the render with device snapshots, so a wobbling render reports false drift. Hence no
   clock, no random numbers, and list order is decided here, not by database row order.
2. SANDBOXED. Jinja2 templates are code. Templates are files on disk, but the data fed in
   comes from web forms, and `SandboxedEnvironment` also protects the day someone lets
   templates be edited from an admin page.
3. ERRORS, NOT EMPTY LINES. `undefined=StrictUndefined` makes a misspelled template key raise
   a readable error; the Jinja2 default would print an empty string and silently drop the line.
"""
import hashlib
import os
import re

from jinja2 import FileSystemLoader, StrictUndefined
from jinja2.exceptions import TemplateNotFound
from jinja2.sandbox import SandboxedEnvironment

from sot import katalog

# Absolute path, derived from this file's location. Not relative: a relative path works from one
# working directory and silently fails from another, and this module is called by uvicorn, the
# poller and test files, which do not share a working directory.
FOLDER_TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "templates")

# Platform -> template file name. A CLOSED list.
#
# The folder is deliberately not scanned: a caller-selectable path is where path traversal
# holes come from. Platforms not in this map are rejected, not tried.
TEMPLATE = {
    "cisco_ios": "cisco_ios.j2",
    "linux": "linux.j2",
}


class GagalRender(Exception):
    """Render could not be completed. The message is meant to be read by a human."""


def _lingkungan():
    """The Jinja2 environment used by ALL renders in NSM.

    Created per call, not kept as a module variable: it costs fractions of a millisecond, and a
    shared environment is where state leaks between devices.
    """
    return SandboxedEnvironment(
        loader=FileSystemLoader(FOLDER_TEMPLATE, encoding="utf-8"),
        undefined=StrictUndefined,  # see property 3 in the module docstring
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
        autoescape=False,
    )


def jalur_template(platform):
    """Template file path for a platform. Raises `GagalRender` if the platform is unknown."""
    nama = TEMPLATE.get(platform)
    if nama is None:
        raise GagalRender(
            "platform '%s' belum punya template. Yang ada: %s"
            % (platform, ", ".join(sorted(TEMPLATE))))
    return os.path.join(FOLDER_TEMPLATE, nama)


def sidik_template(platform):
    """sha256 fingerprint of a platform's template content.

    Stored with each render result: intended config changes either because the DATA changed or
    because the TEMPLATE changed, and the latter can silently shift every device at once.
    """
    with open(jalur_template(platform), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


_ANGKA = re.compile(r"(\d+)")


def _kunci_alami(teks):
    """Sort key that treats numbers as numbers.

    Without it `FastEthernet0/10` sorts before `FastEthernet0/2`, which fills diffs with moved
    lines that are not changes.
    """
    return tuple(int(p) if p.isdigit() else p.lower()
                 for p in _ANGKA.split(teks or ""))


def rapikan(teks):
    """Canonical form of configuration text: uniform line endings, no trailing spaces.

    Applied before fingerprinting and storing, so two renders with identical content cannot get
    different fingerprints because one was written on Windows and one on Linux.
    """
    baris = teks.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    baris = [b.rstrip() for b in baris]
    # Trailing blank lines are dropped and exactly one newline is added, so text with no final
    # newline and text with three blank lines do not get different fingerprints.
    while baris and baris[-1] == "":
        baris.pop()
    return "\n".join(baris) + "\n"


def fingerprint_text(teks):
    """sha256 of a configuration text, computed over its canonical form."""
    return hashlib.sha256(rapikan(teks).encode("utf-8")).hexdigest()


def susun_konteks(platform, nilai, interface=None, vlan=None, rute=None):
    """Build the template context. ALL ordering is decided here.

    Order is set in Python, not in the template or the database query, so new templates cannot
    forget to sort, a missing `ORDER BY` cannot change output, and the determinism test
    (`uji_sot_render.py`) checks one place.

    NOT sorted: list-valued items in `nilai` (e.g. `ntp_server`), whose order matters on the
    device (the first NTP server is tried first). Their canonical form is kept by `katalog.periksa()`.
    """
    return {
        "platform": platform,
        # Copies, not references: a template must not change the caller's data, and the caller must not change data already in the render.
        "n": dict(nilai or {}),
        # IANA time zone -> Cisco syntax ('WIB 7 0'). Provided as a FUNCTION in the context rather than
        # a global Jinja filter, to keep `SandboxedEnvironment` as plain as possible. The map lives in
        # `katalog.ZONA_KE_CISCO`, one source for this renderer and the parser in `drift/ekstrak.py`.
        "zona_cisco": katalog.zona_cisco,
        "interface": sorted(interface or [],
                            key=lambda i: _kunci_alami(i.get("nama"))),
        "vlan": sorted(vlan or [], key=lambda v: int(v.get("vlan_id") or 0)),
        "rute": sorted(rute or [],
                       key=lambda r: (_kunci_alami(r.get("tujuan")),
                                      _kunci_alami(r.get("mask")),
                                      _kunci_alami(r.get("next_hop")))),
    }


def render(platform, nilai, interface=None, vlan=None, rute=None):
    """Produce intended configuration text. Touches NO device.

    Returns a dict:
        teks            intended configuration, tidied
        sidik           sha256 of that text
        sidik_template  sha256 of the template file used
        baris           line count

    Raises `GagalRender` for an unknown platform, missing template, or a key the template
    does not know (`StrictUndefined`).
    """
    env = _lingkungan()
    nama = TEMPLATE.get(platform)
    if nama is None:
        raise GagalRender(
            "platform '%s' belum punya template. Yang ada: %s"
            % (platform, ", ".join(sorted(TEMPLATE))))
    try:
        tpl = env.get_template(nama)
    except TemplateNotFound:
        raise GagalRender(
            "berkas template '%s' tidak ditemukan di %s. Template adalah "
            "berkas di disk yang ikut bersama kode -- kalau ia hilang, yang "
            "hilang adalah bagian dari kode, bukan data."
            % (nama, FOLDER_TEMPLATE))

    konteks = susun_konteks(platform, nilai, interface, vlan, rute)
    try:
        raw = tpl.render(**konteks)
    except Exception as e:
        # Wrapped so callers (and web pages) never see a raw Jinja2 traceback. The error class name is
        # kept: `UndefinedError` and `SecurityError` point at very different problems.
        raise GagalRender("template %s gagal dirender (%s): %s"
                          % (nama, type(e).__name__, e))

    teks = rapikan(raw)
    return {
        "teks": teks,
        "sidik": hashlib.sha256(teks.encode("utf-8")).hexdigest(),
        "sidik_template": sidik_template(platform),
        "baris": teks.count("\n"),
    }

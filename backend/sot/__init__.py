"""Source of Truth: layer L1 of the closed-loop automation design (docs/design/CLOSED-LOOP-AUTOMATION.md).

The rest of NSM records what devices ARE (`konfig_snapshots`, `status_logs`). This package
holds what they SHOULD be, which closed-loop automation needs.

Three parts, and the split is a security decision:
    katalog.py     which intent keys exist and what is valid as their value
                   (rules as DATA, like `connectors/kepatuhan.py`).
    render.py      data + template -> intended configuration text.
    templates/     Jinja2 templates, FILES ON DISK.

`templates/` is deliberately not a database table: a Jinja2 template is executed code. A
template editable from the web would let anyone reaching the admin page run code inside the
NSM process, which holds the SSH credentials of every lab device. Only intent DATA is
editable via the web, strictly validated by the catalog before saving. Templates change by
editing files, like any other code.

This package never opens a connection to anything: it reads the database, renders text and
returns it. Comparison with actual state and remediation belong to the layers above, which
must go through the automation guard.
"""

"""Drift detection: layer L2 of docs/design/CLOSED-LOOP-AUTOMATION.md.

The `sot/` package answers "what SHOULD be configured". This package answers
"does what IS configured match it". Without it, even a complete intent is a
dead document.

ZERO device contact. Like `sot/`, this package opens no connection. It compares
two things already stored in NSM's own database:

    intended = sot.service.render_intent()   (from intent_nilai etc.)
    observed = latest KonfigSnapshot.teks    (collected by the poller's poll_konfig())

Not a raw line diff, and that is the core decision. The intent states only PART
of the configuration (deliberately; see `sot/katalog.py` on why secrets never
enter the intent), while a real `show running-config` snapshot holds hundreds of
lines the intent never tries to state (AAA, other ACLs, exec banner, ...). A
line-by-line diff would report hundreds of false "drifts".

So this package does a scoped comparison: for each KEY the intent states, it
extracts the value actually in effect from the snapshot (per-platform patterns
in `ekstrak.py`) and compares VALUE with VALUE, not text with text. Keys the
intent does not state are never checked. That is the same scope declared by
`sot/katalog.py`: answer whether the stated parts match, not a full audit.

Only `cisco_ios` is supported, openly. The Linux snapshot (`_potret_linux` in
poller.py) collects security posture (sshd_config, listening ports, UID 0
accounts), not the hostname/NTP/DNS/timezone that `sot/katalog.py` declares for
`linux`. Nothing in NSM collects those from Linux servers, so Linux devices get
`tidak_didukung` here instead of being silently compared against irrelevant
data (same pattern as `TIDAK_BERLAKU` in `connectors/kepatuhan.py`).
"""

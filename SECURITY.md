# Security Policy

NSM is a lab project (see the disclaimer in [README.md](README.md)). It has no
production deployment, but it handles device credentials and can change device
configuration, so security reports are welcome.

## Reporting a vulnerability

**Do not open a public issue for a security vulnerability.**

Use GitHub private vulnerability reporting: open the repository's *Security*
tab and choose *Report a vulnerability*. If that is not available, email
`owner@example.com` (placeholder address; use the contact on the owner's GitHub
profile if it bounces).

Please include the version or commit, steps to reproduce, and the impact you
observed. A fix is welcome but not required.

This is a one-person project with no response-time guarantee. The only promise
is that your report will be read, and that I will credit you if you wish.

## Threat model (summary)

NSM states the boundaries it relies on, because that is more useful than listing
features.

* **The Python API has no authentication of its own.** It is bound to
  `127.0.0.1` and relies on that network boundary; authorization and auditing
  are done by the Java layer in front of it. Do not expose the API port to a
  network without adding authentication first.
* **Syslog and SNMP traps are unauthenticated UDP** and can be forged. They are
  treated as evidence and as a trigger for verification, never as a basis for
  acting. Actions always go through the automation gates, which verify real
  state first.
* **Device credentials are stored so the system can use them unattended.**
  Protection comes from controlling access to the database. Backups are
  encrypted because they leave the machine.
* **Writes to devices are guarded.** Commands are allow-listed, pass the
  automation gates, are bracketed by configuration snapshots, are followed by a
  liveness check, and default to preview mode. Features that touch devices are
  off until an operator enables them.
* **Secrets are kept out of the repository.** Secret-bearing files are listed in
  `.gitignore` and a CI job fails if one becomes tracked. Examples in the docs
  use placeholders.

Out of scope: findings that need an attacker who already controls the host or
the database, and issues in the emulated lab devices themselves.

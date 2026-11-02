"""NSM clean-architecture package: new layers standing beside the old code
(docs/design/CLEAN-ARCHITECTURE.md).

The backend grew into hundreds of flat files with two large modules (`report_service.py`,
`poller.py`) attracting most logic, and nothing separated business rules from storage and
presentation. Concrete costs: the availability rule could only be tested with a database,
`main.py` held 74 routes that each opened and closed their own session, and `config.py`
re-read `.env` on every lookup.

Dependencies may only point INWARD:

    antarmuka  ->  aplikasi  ->  domain
    infrastruktur  ->  aplikasi/domain (through contracts in `aplikasi.kontrak`)

  * `domain`        pure rules; imports no SQLAlchemy, FastAPI, os, or other NSM file.
  * `aplikasi`      use cases and CONTRACTS (Protocol) over the outside world.
  * `infrastruktur` the suppliers: SQLAlchemy, the clock, wrappers over old code (`warisan/`).
  * `antarmuka`     FastAPI, kept thin: parse the request, call one use case, return the result.

Product behavior is NOT changed (not one number, JSON shape, or key name). The package grows
BESIDE the old code (strangler-fig): the new layer calls old code through
`infrastruktur/warisan`, and `uji_arsitektur_baru.py` proves old and new paths produce
byte-identical output before anything is moved.
"""

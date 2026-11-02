"""Implementation of the `Jam` contract."""
from datetime import datetime


class JamSistem:
    def sekarang(self):
        return datetime.now()


class JamBeku:
    """A clock that does not move, for tests whose result must not depend
    on when they happen to run.
    """

    def __init__(self, waktu):
        self._waktu = waktu

    def sekarang(self):
        return self._waktu

from abc import ABC, abstractmethod


class BaseConnector(ABC):
    """Interface for all ways of accessing a device. A new connector (MikroTik, FortiGate,
    SNMP) subclasses this and implements the relevant methods.
    """

    def __init__(self, ip_address):
        self.ip_address = ip_address

    @abstractmethod
    def check_reachable(self):
        """Kembalikan (is_alive: bool, rtt_ms: float)."""

    def get_info(self):
        """Fetch device details. Not every connector supports this."""
        raise NotImplementedError(
            f"{self.__class__.__name__} tidak mendukung get_info()"
        )

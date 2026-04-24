from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class BaseFirewallProvider(ABC):
    """
    Abstract Base Class for all Firewall Providers (Cisco, Fortinet, Juniper, etc.)
    Ensures consistent method signatures across different vendor implementations.
    """

    def __init__(self, host: str, username: str, password: str, verify_ssl: bool = False):
        self.host = host.rstrip('/')
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.token: Optional[str] = None

    @abstractmethod
    async def authenticate(self) -> bool:
        """Authenticate with the firewall manager/device and store the token/session."""
        pass

    @abstractmethod
    async def get_access_policies(self) -> List[Dict[str, Any]]:
        """Fetch a list of access control policies available on the device."""
        pass

    @abstractmethod
    async def get_access_rules(self, policy_id: str) -> List[Dict[str, Any]]:
        """Fetch all access rules for a specific policy ID."""
        pass

    @abstractmethod
    async def get_network_objects(self) -> List[Dict[str, Any]]:
        """Fetch network objects (hosts, ranges, networks, groups)."""
        pass

    @abstractmethod
    async def get_port_objects(self) -> List[Dict[str, Any]]:
        """Fetch port/service objects (TCP/UDP ports, groups)."""
        pass

    @abstractmethod
    async def test_connection(self) -> bool:
        """Verify that the backend can successfully talk to the device API."""
        pass

    async def normalize_rules_for_ai(self, raw_rules: List[Dict[str, Any]]) -> str:
        """
        Default helper to convert vendor JSON rules into a simplified text format 
        that is optimized for LLM token context windows.
        """
        # This will be overridden by specific vendors if they need custom mapping logic
        return str(raw_rules)

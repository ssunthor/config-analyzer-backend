from typing import Dict, Type, Any
from app.core.providers.base import BaseFirewallProvider
from app.services.firewall.fmc_service import FmcProvider
# from app.services.firewall.forti_service import FortiProvider
# from app.services.firewall.juniper_service import JuniperProvider

class FirewallProviderFactory:
    """
    Factory class to dynamically instantiate the correct firewall provider
    based on the vendor name.
    """
    
    _providers: Dict[str, Type[BaseFirewallProvider]] = {
        "cisco": FmcProvider,
        # "fortinet": FortiProvider,
        # "juniper": JuniperProvider,
    }

    @classmethod
    def get_provider(cls, vendor: str, **kwargs: Any) -> BaseFirewallProvider:
        """
        Returns an instance of the requested firewall provider.
        
        Args:
            vendor: The name of the vendor (cisco, fortinet, juniper)
            **kwargs: Host, username, password, etc.
        """
        provider_class = cls._providers.get(vendor.lower())
        if not provider_class:
            raise ValueError(f"Unsupported vendor: {vendor}. Supported: {list(cls._providers.keys())}")
        
        return provider_class(**kwargs)

    @classmethod
    def register_provider(cls, name: str, provider_class: Type[BaseFirewallProvider]):
        """Helper to register new providers dynamically if needed."""
        cls._providers[name.lower()] = provider_class

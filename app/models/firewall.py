from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class FirewallRule(BaseModel):
    """
    Standardized model for a Firewall Access Rule.
    Vendors like Cisco, Fortinet, and Juniper will map their JSON to this model.
    """
    name: str
    action: str = Field(..., description="Allow, Deny, etc.")
    source_zones: List[str] = []
    destination_zones: List[str] = []
    source_networks: List[str] = []
    destination_networks: List[str] = []
    source_ports: List[str] = []
    destination_ports: List[str] = []
    protocols: List[str] = []
    enabled: bool = True
    description: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Raw vendor-specific data")

class FirewallPolicy(BaseModel):
    """Standardized model for an Access Control Policy."""
    id: str
    name: str
    description: Optional[str] = None
    rule_count: int = 0

class NetworkObject(BaseModel):
    """Standardized model for Network objects (Hosts, Networks, Groups)."""
    name: str
    type: str  # host, network, range, group
    value: Optional[str] = None
    members: List[str] = []

class PortObject(BaseModel):
    """Standardized model for Service/Port objects."""
    name: str
    protocol: str
    port: str
    type: str # singleton, group

import httpx
import logging
from typing import List, Dict, Any, Optional
from app.core.providers.base import BaseFirewallProvider
from app.models.firewall import FirewallPolicy, FirewallRule

logger = logging.getLogger(__name__)

class FmcProvider(BaseFirewallProvider):
    """
    Cisco Firepower Management Center (FMC) Implementation.
    """

    def __init__(self, host: str, username: str, password: str, verify_ssl: bool = False):
        # Ensure host has a protocol
        if not host.startswith(('http://', 'https://')):
            host = f"https://{host}"
        super().__init__(host, username, password, verify_ssl)
        self.domain_uuid: Optional[str] = None
        self.base_url = f"{self.host}/api"

    async def authenticate(self) -> bool:
        """Authenticates with FMC and retrieves access token and domain UUID."""
        url = f"{self.base_url}/fmc_platform/v1/auth/generatetoken"
        try:
            async with httpx.AsyncClient(verify=self.verify_ssl) as client:
                response = await client.post(
                    url, 
                    auth=(self.username, self.password),
                    headers={"Content-Type": "application/json"},
                    content=b"",
                    timeout=30.0
                )
                if response.status_code != 204 and response.status_code != 200:
                    logger.error(f"FMC Authentication failed with status {response.status_code}: {response.text}")
                    return False
                
                self.token = response.headers.get("X-auth-access-token")
                self.domain_uuid = response.headers.get("DOMAIN_UUID")
                
                if not self.token or not self.domain_uuid:
                    logger.error("FMC Authentication failed: Token or Domain UUID missing in response headers")
                    return False

                logger.info(f"FMC Authenticated successfully. Domain: {self.domain_uuid}")
                return True
        except Exception as e:
            logger.error(f"FMC Authentication failed: {str(e)}")
            raise Exception(f"Connection failed: {str(e)}")

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-auth-access-token": self.token or ""
        }

    async def get_access_policies(self) -> List[Dict[str, Any]]:
        """Fetch access policies from FMC."""
        if not self.token or not self.domain_uuid:
            await self.authenticate()

        url = f"{self.base_url}/fmc_config/v1/domain/{self.domain_uuid}/policy/accesspolicies"
        async with httpx.AsyncClient(verify=self.verify_ssl) as client:
            response = await client.get(url, headers=self._get_headers())
            response.raise_for_status()
            return response.json().get("items", [])

    async def get_access_rules(self, policy_id: str) -> List[Dict[str, Any]]:
        """Fetch all rules for a given FMC access policy ID."""
        if not self.token or not self.domain_uuid:
            await self.authenticate()

        url = f"{self.base_url}/fmc_config/v1/domain/{self.domain_uuid}/policy/accesspolicies/{policy_id}/accessrules"
        all_rules = []
        offset = 0
        limit = 1000

        async with httpx.AsyncClient(verify=self.verify_ssl) as client:
            while True:
                params = {"offset": offset, "limit": limit, "expanded": "true"}
                response = await client.get(url, headers=self._get_headers(), params=params)
                response.raise_for_status()
                
                data = response.json()
                rules = data.get("items", [])
                all_rules.extend(rules)

                if not data.get("paging", {}).get("next"):
                    break
                offset += len(rules)
        
        return all_rules

    async def get_network_objects(self) -> List[Dict[str, Any]]:
        """Fetch network objects from FMC."""
        if not self.token or not self.domain_uuid:
            await self.authenticate()

        url = f"{self.base_url}/fmc_config/v1/domain/{self.domain_uuid}/object/networkobjects"
        async with httpx.AsyncClient(verify=self.verify_ssl) as client:
            response = await client.get(url, headers=self._get_headers())
            response.raise_for_status()
            return response.json().get("items", [])

    async def get_port_objects(self) -> List[Dict[str, Any]]:
        """Fetch port objects from FMC."""
        if not self.token or not self.domain_uuid:
            await self.authenticate()

        # Simplified for now, just fetching protocol port objects
        url = f"{self.base_url}/fmc_config/v1/domain/{self.domain_uuid}/object/protocolportobjects"
        async with httpx.AsyncClient(verify=self.verify_ssl) as client:
            response = await client.get(url, headers=self._get_headers())
            response.raise_for_status()
            return response.json().get("items", [])

    async def test_connection(self) -> bool:
        """Test if the credentials and connectivity to FMC are valid."""
        return await self.authenticate()

    async def normalize_rules_for_ai(self, raw_rules: List[Dict[str, Any]]) -> str:
        """
        Convert complex FMC JSON into a human-readable text block for AI analysis.
        Removes metadata noise to focus on logic.
        """
        output = []
        for r in raw_rules:
            name = r.get('name', 'Unnamed')
            action = r.get('action', 'Allow')
            
            src_nets = [n.get('name') for n in r.get('sourceNetworks', {}).get('objects', [])]
            dst_nets = [n.get('name') for n in r.get('destinationNetworks', {}).get('objects', [])]
            dst_ports = [p.get('name') for p in r.get('destinationPorts', {}).get('objects', [])]
            
            rule_str = f"Rule: {name} | Action: {action} | From: {src_nets or 'Any'} | To: {dst_nets or 'Any'} | Ports: {dst_ports or 'Any'}"
            output.append(rule_str)
            
        return "\n".join(output)

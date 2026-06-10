from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from app.services.factory import FirewallProviderFactory

router = APIRouter()

class FetchConfigRequest(BaseModel):
    vendor: str
    host: str
    username: str
    password: str
    verify_ssl: bool = False
    policy_id: Optional[str] = None

@router.post("/policies")
async def fetch_policies(request: FetchConfigRequest):
    """
    Fetch access control policies from a firewall manager.
    """
    try:
        provider = FirewallProviderFactory.get_provider(
            request.vendor,
            host=request.host,
            username=request.username,
            password=request.password,
            verify_ssl=request.verify_ssl
        )
        
        policies = await provider.get_access_policies()
        return {"status": "success", "policies": policies}
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch policies: {str(e)}")

@router.post("/rules")
async def fetch_rules(request: FetchConfigRequest):
    """
    Fetch rules for a specific policy ID and return normalized text for AI analysis.
    """
    if not request.policy_id:
        raise HTTPException(status_code=400, detail="policy_id is required to fetch rules")
        
    try:
        provider = FirewallProviderFactory.get_provider(
            request.vendor,
            host=request.host,
            username=request.username,
            password=request.password,
            verify_ssl=request.verify_ssl
        )
        
        raw_rules = await provider.get_access_rules(request.policy_id)
        normalized_text = await provider.normalize_rules_for_ai(raw_rules)
        
        return {
            "status": "success", 
            "policy_id": request.policy_id,
            "rule_count": len(raw_rules),
            "normalized_configuration": normalized_text
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch rules: {str(e)}")

@router.post("/test-connection")
async def test_connection(request: FetchConfigRequest):
    """
    Verify API connectivity and credentials.
    """
    try:
        provider = FirewallProviderFactory.get_provider(
            request.vendor,
            host=request.host,
            username=request.username,
            password=request.password,
            verify_ssl=request.verify_ssl
        )
        
        is_connected = await provider.test_connection()
        if is_connected:
            return {"status": "success", "message": "Connection established successfully"}
        else:
            return {"status": "error", "message": "Authentication failed"}
            
    except Exception as e:
        return {"status": "error", "message": str(e)}

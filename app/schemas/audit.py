from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime


class AuditLogResponse(BaseModel):
    id: int
    user_id: Optional[int]
    action: str
    resource_type: str
    resource_id: Optional[str]
    old_values: Optional[Dict[str, Any]]
    new_values: Optional[Dict[str, Any]]
    changes: Optional[Dict[str, Any]]
    ip_address: Optional[str]
    user_agent: Optional[str]
    description: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

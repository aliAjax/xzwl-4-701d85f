from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class LockDevicesRequest(BaseModel):
    device_ids: List[int] = Field(..., min_length=1)
    purpose: str = "rental"


class UnlockDevicesRequest(BaseModel):
    device_ids: List[int] = Field(..., min_length=1)


class LockResponse(BaseModel):
    success: bool
    lock_token: Optional[str] = None
    message: str
    errors: List[str] = []
    expires_at: Optional[datetime] = None


class DeviceLockResponse(BaseModel):
    id: int
    device_id: int
    user_id: int
    contract_id: Optional[int]
    lock_token: str
    locked_at: datetime
    expires_at: datetime
    released_at: Optional[datetime]
    purpose: Optional[str]
    is_active: int
    created_at: datetime

    class Config:
        from_attributes = True

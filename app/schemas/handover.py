from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime

from ..models.handover import HandoverType, HandoverStatus
from .user import UserResponse
from .device import DeviceResponse
from .contract import ContractResponse


class HandoverCreate(BaseModel):
    contract_id: int = Field(..., gt=0)
    device_id: int = Field(..., gt=0)
    handover_type: HandoverType
    appearance_description: Optional[str] = None
    accessories: Optional[List[Dict[str, Any]]] = None
    abnormal_remarks: Optional[str] = None


class HandoverUpdate(BaseModel):
    appearance_description: Optional[str] = None
    accessories: Optional[List[Dict[str, Any]]] = None
    abnormal_remarks: Optional[str] = None


class HandoverConfirm(BaseModel):
    appearance_description: Optional[str] = None
    accessories: Optional[List[Dict[str, Any]]] = None
    abnormal_remarks: Optional[str] = None


class HandoverResponse(BaseModel):
    id: int
    handover_number: str
    contract_id: int
    contract: Optional[ContractResponse] = None
    device_id: int
    device: Optional[DeviceResponse] = None
    handover_type: HandoverType
    status: HandoverStatus
    appearance_description: Optional[str]
    accessories: Optional[List[Dict[str, Any]]]
    abnormal_remarks: Optional[str]
    created_by_id: int
    created_by: Optional[UserResponse] = None
    confirmed_by_staff_id: Optional[int]
    confirmed_by_staff: Optional[UserResponse] = None
    confirmed_by_customer_id: Optional[int]
    confirmed_by_customer: Optional[UserResponse] = None
    staff_confirmed_at: Optional[datetime]
    customer_confirmed_at: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

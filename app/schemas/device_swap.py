from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from ..models.device_swap import DeviceSwapStatus
from .user import UserResponse
from .device import DeviceResponse
from .contract import ContractResponse


class DeviceSwapCreate(BaseModel):
    contract_id: int = Field(..., gt=0)
    old_device_id: int = Field(..., gt=0)
    new_device_id: int = Field(..., gt=0)
    fault_description: str = Field(..., min_length=1, max_length=2000)
    fault_category: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class DeviceSwapPreviewRequest(BaseModel):
    contract_id: int = Field(..., gt=0)
    old_device_id: int = Field(..., gt=0)
    new_device_id: int = Field(..., gt=0)


class DeviceSwapPreviewResponse(BaseModel):
    contract: ContractResponse
    old_device: DeviceResponse
    new_device: DeviceResponse
    old_daily_rate: float
    new_daily_rate: float
    keep_original_rate: float
    can_swap: bool
    validation_messages: list[str] = []


class DeviceSwapCancel(BaseModel):
    cancel_reason: str = Field(..., min_length=1, max_length=1000)


class DeviceSwapResponse(BaseModel):
    id: int
    swap_number: str
    contract_id: int
    contract: Optional[ContractResponse] = None
    old_device_id: int
    old_device: Optional[DeviceResponse] = None
    new_device_id: int
    new_device: Optional[DeviceResponse] = None
    contract_item_id: int
    fault_description: str
    fault_category: Optional[str]
    old_daily_rate: float
    new_daily_rate: float
    keep_original_rate: float
    status: DeviceSwapStatus
    repair_record_id: Optional[int]
    created_by_id: int
    created_by: Optional[UserResponse] = None
    completed_by_id: Optional[int]
    completed_by: Optional[UserResponse] = None
    completed_at: Optional[datetime]
    cancelled_by_id: Optional[int]
    cancelled_by: Optional[UserResponse] = None
    cancelled_at: Optional[datetime]
    cancel_reason: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

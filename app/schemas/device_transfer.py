from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from ..models.device_transfer import TransferLocationType, TransferStatus
from .user import UserResponse
from .device import DeviceResponse


class DeviceTransferCreate(BaseModel):
    device_id: int = Field(..., gt=0)
    from_location_type: TransferLocationType
    from_location: str = Field(..., max_length=255)
    to_location_type: TransferLocationType
    to_location: str = Field(..., max_length=255)
    transfer_notes: Optional[str] = None


class DeviceTransferConfirm(BaseModel):
    transfer_notes: Optional[str] = None


class DeviceTransferCancel(BaseModel):
    cancel_reason: str = Field(..., max_length=1000)


class DeviceTransferResponse(BaseModel):
    id: int
    device_id: int
    device: Optional[DeviceResponse] = None
    from_location_type: TransferLocationType
    from_location: str
    to_location_type: TransferLocationType
    to_location: str
    status: TransferStatus
    transfer_notes: Optional[str]
    created_by_id: int
    created_by: Optional[UserResponse] = None
    created_at: datetime
    confirmed_by_id: Optional[int]
    confirmed_by: Optional[UserResponse] = None
    confirmed_at: Optional[datetime]
    cancelled_by_id: Optional[int]
    cancelled_by: Optional[UserResponse] = None
    cancelled_at: Optional[datetime]
    cancel_reason: Optional[str]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

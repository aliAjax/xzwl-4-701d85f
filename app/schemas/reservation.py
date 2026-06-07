from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from ..models.reservation import ReservationStatus
from .user import UserResponse
from .device import DeviceResponse


class ReservationBase(BaseModel):
    device_id: int = Field(..., gt=0)
    start_date: datetime
    end_date: datetime
    purpose: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None


class ReservationCreate(ReservationBase):
    customer_id: Optional[int] = Field(None, gt=0)


class ReservationUpdate(BaseModel):
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    purpose: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None


class ReservationStatusUpdate(BaseModel):
    status: ReservationStatus
    cancellation_reason: Optional[str] = None
    notes: Optional[str] = None


class ReservationCancelRequest(BaseModel):
    cancellation_reason: Optional[str] = None
    notes: Optional[str] = None


class ReservationResponse(BaseModel):
    id: int
    reservation_number: str
    customer_id: int
    device_id: int
    start_date: datetime
    end_date: datetime
    purpose: Optional[str]
    notes: Optional[str]
    status: ReservationStatus
    confirmed_by_id: Optional[int]
    confirmed_at: Optional[datetime]
    cancelled_by_id: Optional[int]
    cancelled_at: Optional[datetime]
    cancellation_reason: Optional[str]
    duration_hours: Optional[float] = None
    customer: Optional[UserResponse] = None
    device: Optional[DeviceResponse] = None
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

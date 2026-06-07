from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from ..models.device import DeviceStatus


class DeviceCategoryBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    daily_rental_rate: float = Field(..., gt=0)
    deposit_amount: float = Field(..., ge=0)
    maintenance_cycle_days: int = Field(30, gt=0)
    disinfection_required: bool = True


class DeviceCategoryCreate(DeviceCategoryBase):
    pass


class DeviceCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    daily_rental_rate: Optional[float] = Field(None, gt=0)
    deposit_amount: Optional[float] = Field(None, ge=0)
    maintenance_cycle_days: Optional[int] = Field(None, gt=0)
    disinfection_required: Optional[bool] = None


class DeviceCategoryResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    daily_rental_rate: float
    deposit_amount: float
    maintenance_cycle_days: int
    disinfection_required: bool
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class DeviceBase(BaseModel):
    serial_number: str = Field(..., max_length=100)
    name: str = Field(..., max_length=100)
    model: Optional[str] = Field(None, max_length=100)
    manufacturer: Optional[str] = Field(None, max_length=100)
    purchase_date: Optional[datetime] = None
    purchase_price: Optional[float] = Field(None, ge=0)
    current_owner: Optional[str] = Field(None, max_length=100)
    location: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None
    category_id: int = Field(..., gt=0)


class DeviceCreate(DeviceBase):
    pass


class DeviceUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    model: Optional[str] = Field(None, max_length=100)
    manufacturer: Optional[str] = Field(None, max_length=100)
    purchase_date: Optional[datetime] = None
    purchase_price: Optional[float] = Field(None, ge=0)
    current_owner: Optional[str] = Field(None, max_length=100)
    location: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None
    category_id: Optional[int] = Field(None, gt=0)


class DeviceStatusUpdate(BaseModel):
    status: DeviceStatus
    notes: Optional[str] = None


class DeviceResponse(BaseModel):
    id: int
    serial_number: str
    name: str
    model: Optional[str]
    manufacturer: Optional[str]
    purchase_date: Optional[datetime]
    purchase_price: Optional[float]
    current_owner: Optional[str]
    location: Optional[str]
    status: DeviceStatus
    notes: Optional[str]
    category_id: int
    category: Optional[DeviceCategoryResponse] = None
    last_disinfection_date: Optional[datetime]
    last_maintenance_date: Optional[datetime]
    next_maintenance_date: Optional[datetime]
    is_available_for_rent: Optional[bool] = None
    needs_maintenance: Optional[bool] = None
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

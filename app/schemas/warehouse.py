from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from datetime import datetime

from ..models.warehouse import WarehouseType, WarehouseStatus


class WarehouseBase(BaseModel):
    code: str = Field(..., max_length=50)
    name: str = Field(..., max_length=100)
    type: WarehouseType = WarehouseType.BRANCH
    status: WarehouseStatus = WarehouseStatus.ACTIVE
    address: Optional[str] = Field(None, max_length=255)
    city: Optional[str] = Field(None, max_length=100)
    province: Optional[str] = Field(None, max_length=100)
    postal_code: Optional[str] = Field(None, max_length=20)
    country: Optional[str] = Field("China", max_length=100)
    contact_person: Optional[str] = Field(None, max_length=100)
    contact_phone: Optional[str] = Field(None, max_length=50)
    contact_email: Optional[EmailStr] = None
    capacity: Optional[int] = Field(0, ge=0)
    is_default: Optional[bool] = False
    notes: Optional[str] = None


class WarehouseCreate(WarehouseBase):
    pass


class WarehouseUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    type: Optional[WarehouseType] = None
    status: Optional[WarehouseStatus] = None
    address: Optional[str] = Field(None, max_length=255)
    city: Optional[str] = Field(None, max_length=100)
    province: Optional[str] = Field(None, max_length=100)
    postal_code: Optional[str] = Field(None, max_length=20)
    country: Optional[str] = Field(None, max_length=100)
    contact_person: Optional[str] = Field(None, max_length=100)
    contact_phone: Optional[str] = Field(None, max_length=50)
    contact_email: Optional[EmailStr] = None
    capacity: Optional[int] = Field(None, ge=0)
    is_default: Optional[bool] = None
    notes: Optional[str] = None


class WarehouseResponse(BaseModel):
    id: int
    code: str
    name: str
    type: WarehouseType
    status: WarehouseStatus
    address: Optional[str]
    city: Optional[str]
    province: Optional[str]
    postal_code: Optional[str]
    country: Optional[str]
    contact_person: Optional[str]
    contact_phone: Optional[str]
    contact_email: Optional[str]
    capacity: int
    current_occupancy: float
    is_default: bool
    notes: Optional[str]
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

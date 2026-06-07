from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

from ..models.contract_reminder import ReminderStatus


class DeviceInfo(BaseModel):
    id: int
    serial_number: str
    name: str
    model: Optional[str] = None
    category: str
    quantity: int

    class Config:
        from_attributes = True


class CustomerContact(BaseModel):
    id: int
    full_name: str
    phone: Optional[str] = None
    email: str

    class Config:
        from_attributes = True


class ContractExpiryResponse(BaseModel):
    contract_id: int
    contract_number: str
    customer: CustomerContact
    end_date: datetime
    devices: List[DeviceInfo] = []
    days_until_expiry: int
    is_overdue: bool
    overdue_days: int
    status: str

    class Config:
        from_attributes = True


class ContractReminderBase(BaseModel):
    contract_id: int = Field(..., gt=0)
    notes: Optional[str] = None


class ContractReminderCreate(ContractReminderBase):
    pass


class ContractReminderUpdateStatus(BaseModel):
    status: ReminderStatus
    notes: Optional[str] = None
    follow_up_date: Optional[datetime] = None


class ContractReminderResponse(BaseModel):
    id: int
    contract_id: int
    contract_number: str
    customer_name: str
    customer_phone: Optional[str] = None
    customer_email: str
    end_date: datetime
    generated_at: datetime
    handled_by_id: Optional[int] = None
    handled_by_name: Optional[str] = None
    status: ReminderStatus
    notes: Optional[str] = None
    follow_up_date: Optional[datetime] = None
    handled_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

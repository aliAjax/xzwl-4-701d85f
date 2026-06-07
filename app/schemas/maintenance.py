from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class MaintenanceRecordBase(BaseModel):
    device_id: int = Field(..., gt=0)
    maintenance_type: str = Field(..., max_length=50)
    scheduled_date: datetime
    technician_name: Optional[str] = Field(None, max_length=100)
    service_provider: Optional[str] = Field(None, max_length=100)
    cost: float = Field(0.0, ge=0)
    description: str
    work_performed: Optional[str] = None
    parts_replaced: Optional[str] = None
    next_maintenance_date: Optional[datetime] = None
    is_successful: bool = True
    notes: Optional[str] = None


class MaintenanceRecordCreate(MaintenanceRecordBase):
    pass


class MaintenanceRecordUpdate(BaseModel):
    maintenance_type: Optional[str] = Field(None, max_length=50)
    status: Optional[str] = Field(None, max_length=50)
    scheduled_date: Optional[datetime] = None
    actual_date: Optional[datetime] = None
    technician_name: Optional[str] = Field(None, max_length=100)
    service_provider: Optional[str] = Field(None, max_length=100)
    cost: Optional[float] = Field(None, ge=0)
    description: Optional[str] = None
    work_performed: Optional[str] = None
    parts_replaced: Optional[str] = None
    next_maintenance_date: Optional[datetime] = None
    is_successful: Optional[bool] = None
    notes: Optional[str] = None


class MaintenanceRecordResponse(BaseModel):
    id: int
    device_id: int
    maintenance_type: str
    status: str
    scheduled_date: datetime
    actual_date: Optional[datetime]
    technician_name: Optional[str]
    service_provider: Optional[str]
    cost: float
    description: str
    work_performed: Optional[str]
    parts_replaced: Optional[str]
    next_maintenance_date: Optional[datetime]
    is_successful: bool
    notes: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

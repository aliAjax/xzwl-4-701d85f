from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from ..models.repair import RepairStatus, RepairPriority


class RepairRecordBase(BaseModel):
    device_id: int = Field(..., gt=0)
    fault_description: str
    fault_category: Optional[str] = Field(None, max_length=100)
    priority: RepairPriority = RepairPriority.MEDIUM
    is_warranty: bool = False
    customer_notes: Optional[str] = None


class RepairRecordCreate(RepairRecordBase):
    pass


class RepairRecordUpdate(BaseModel):
    priority: Optional[RepairPriority] = None
    status: Optional[RepairStatus] = None
    fault_description: Optional[str] = None
    fault_category: Optional[str] = Field(None, max_length=100)
    diagnosis: Optional[str] = None
    diagnosis_date: Optional[datetime] = None
    repair_plan: Optional[str] = None
    repair_start_date: Optional[datetime] = None
    repair_complete_date: Optional[datetime] = None
    parts_used: Optional[str] = None
    parts_cost: Optional[float] = Field(None, ge=0)
    labor_cost: Optional[float] = Field(None, ge=0)
    total_cost: Optional[float] = Field(None, ge=0)
    handled_by_id: Optional[int] = Field(None, gt=0)
    technician_notes: Optional[str] = None
    customer_notes: Optional[str] = None
    is_warranty: Optional[bool] = None
    warranty_expired: Optional[bool] = None


class RepairStatusUpdate(BaseModel):
    status: RepairStatus
    notes: Optional[str] = None


class RepairRecordResponse(BaseModel):
    id: int
    device_id: int
    report_date: datetime
    reported_by_id: int
    priority: RepairPriority
    status: RepairStatus
    fault_description: str
    fault_category: Optional[str]
    diagnosis: Optional[str]
    diagnosis_date: Optional[datetime]
    repair_plan: Optional[str]
    repair_start_date: Optional[datetime]
    repair_complete_date: Optional[datetime]
    parts_used: Optional[str]
    parts_cost: float
    labor_cost: float
    total_cost: float
    handled_by_id: Optional[int]
    technician_notes: Optional[str]
    customer_notes: Optional[str]
    is_warranty: bool
    warranty_expired: bool
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

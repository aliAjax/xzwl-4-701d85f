from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class DisinfectionRecordBase(BaseModel):
    device_id: int = Field(..., gt=0)
    disinfection_date: datetime
    disinfectant_type: str = Field(..., max_length=100)
    disinfection_method: Optional[str] = Field(None, max_length=100)
    duration_minutes: Optional[int] = Field(None, gt=0)
    operator_name: str = Field(..., max_length=100)
    temperature: Optional[float] = None
    concentration: Optional[str] = Field(None, max_length=50)
    lot_number: Optional[str] = Field(None, max_length=100)
    is_qualified: bool = True
    inspection_notes: Optional[str] = None
    notes: Optional[str] = None


class DisinfectionRecordCreate(DisinfectionRecordBase):
    pass


class DisinfectionRecordUpdate(BaseModel):
    disinfection_date: Optional[datetime] = None
    disinfectant_type: Optional[str] = Field(None, max_length=100)
    disinfection_method: Optional[str] = Field(None, max_length=100)
    duration_minutes: Optional[int] = Field(None, gt=0)
    operator_name: Optional[str] = Field(None, max_length=100)
    temperature: Optional[float] = None
    concentration: Optional[str] = Field(None, max_length=50)
    lot_number: Optional[str] = Field(None, max_length=100)
    is_qualified: Optional[bool] = None
    inspection_notes: Optional[str] = None
    notes: Optional[str] = None


class DisinfectionRecordResponse(BaseModel):
    id: int
    device_id: int
    disinfection_date: datetime
    disinfectant_type: str
    disinfection_method: Optional[str]
    duration_minutes: Optional[int]
    operator_name: str
    temperature: Optional[float]
    concentration: Optional[str]
    lot_number: Optional[str]
    is_qualified: bool
    inspection_notes: Optional[str]
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

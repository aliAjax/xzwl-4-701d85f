from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timedelta

from ..models.contract import ContractStatus
from .customer_credit_note import CustomerRiskSummary


class ContractItemBase(BaseModel):
    device_id: int = Field(..., gt=0)
    daily_rate: float = Field(..., gt=0)
    quantity: int = Field(1, ge=1)
    notes: Optional[str] = None


class ContractItemCreate(ContractItemBase):
    pass


class ContractItemResponse(BaseModel):
    id: int
    contract_id: int
    device_id: int
    daily_rate: float
    quantity: int
    subtotal: float
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ContractBase(BaseModel):
    customer_id: int = Field(..., gt=0)
    start_date: datetime
    end_date: datetime
    discount_amount: float = Field(0.0, ge=0)
    notes: Optional[str] = None


class ContractCreate(ContractBase):
    items: List[ContractItemCreate]
    lock_token: Optional[str] = None


class ContractUpdate(BaseModel):
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    discount_amount: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = None
    items: Optional[List[ContractItemCreate]] = None


class ContractStatusUpdate(BaseModel):
    status: ContractStatus
    notes: Optional[str] = None


class RenewContractRequest(BaseModel):
    new_end_date: datetime
    notes: Optional[str] = None


class ReturnContractRequest(BaseModel):
    return_date: Optional[datetime] = None
    notes: Optional[str] = None
    device_condition_notes: Optional[str] = None


class ContractResponse(BaseModel):
    id: int
    contract_number: str
    customer_id: int
    created_by_id: Optional[int]
    start_date: datetime
    end_date: datetime
    actual_return_date: Optional[datetime]
    total_amount: float
    deposit_amount: float
    overdue_fee: float
    discount_amount: float
    final_amount: float
    deposit_refunded: bool
    deposit_refund_date: Optional[datetime]
    status: ContractStatus
    notes: Optional[str]
    rental_days: Optional[int] = None
    overdue_days: Optional[int] = None
    items: List[ContractItemResponse] = []
    created_at: datetime
    updated_at: Optional[datetime]
    customer_risk_summary: Optional[CustomerRiskSummary] = None

    class Config:
        from_attributes = True

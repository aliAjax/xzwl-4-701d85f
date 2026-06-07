from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class DepositBase(BaseModel):
    contract_id: int = Field(..., gt=0)
    customer_id: int = Field(..., gt=0)
    amount: float = Field(..., gt=0)
    payment_date: datetime
    payment_method: Optional[str] = Field(None, max_length=50)
    transaction_id: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class DepositCreate(DepositBase):
    pass


class DepositUpdate(BaseModel):
    payment_date: Optional[datetime] = None
    payment_method: Optional[str] = Field(None, max_length=50)
    transaction_id: Optional[str] = Field(None, max_length=100)
    refund_amount: Optional[float] = Field(None, ge=0)
    refund_date: Optional[datetime] = None
    refund_method: Optional[str] = Field(None, max_length=50)
    refund_transaction_id: Optional[str] = Field(None, max_length=100)
    status: Optional[str] = Field(None, max_length=20)
    deductions: Optional[str] = None
    notes: Optional[str] = None


class DepositRefundRequest(BaseModel):
    refund_amount: float = Field(..., ge=0)
    refund_date: Optional[datetime] = None
    refund_method: Optional[str] = Field(None, max_length=50)
    refund_transaction_id: Optional[str] = Field(None, max_length=100)
    deductions: Optional[str] = None
    notes: Optional[str] = None


class DepositResponse(BaseModel):
    id: int
    contract_id: int
    customer_id: int
    amount: float
    payment_date: datetime
    payment_method: Optional[str]
    transaction_id: Optional[str]
    refund_amount: float
    refund_date: Optional[datetime]
    refund_method: Optional[str]
    refund_transaction_id: Optional[str]
    status: str
    deductions: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

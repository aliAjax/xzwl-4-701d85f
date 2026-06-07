from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from ..models.customer_credit_note import RiskTag


class CustomerCreditNoteBase(BaseModel):
    customer_id: int = Field(..., gt=0)
    risk_tag: RiskTag
    title: str = Field(..., min_length=2, max_length=200)
    content: str = Field(..., min_length=2)
    related_contract_id: Optional[int] = Field(None, gt=0)


class CustomerCreditNoteCreate(CustomerCreditNoteBase):
    pass


class CustomerCreditNoteUpdate(BaseModel):
    risk_tag: Optional[RiskTag] = None
    title: Optional[str] = Field(None, min_length=2, max_length=200)
    content: Optional[str] = Field(None, min_length=2)
    related_contract_id: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None


class CustomerCreditNoteResolve(BaseModel):
    resolution_notes: str = Field(..., min_length=2)


class CustomerCreditNoteResponse(BaseModel):
    id: int
    customer_id: int
    created_by_id: int
    risk_tag: RiskTag
    title: str
    content: str
    related_contract_id: Optional[int]
    is_active: bool
    resolved_by_id: Optional[int]
    resolved_at: Optional[datetime]
    resolution_notes: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class RiskSummaryItem(BaseModel):
    risk_tag: RiskTag
    count: int


class CustomerRiskSummary(BaseModel):
    customer_id: int
    total_active_notes: int
    risk_summary: list[RiskSummaryItem]
    latest_note: Optional[CustomerCreditNoteResponse] = None

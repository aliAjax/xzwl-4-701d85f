from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime

from ..models.quotation import QuotationStatus


class QuotationItemBase(BaseModel):
    category_id: int = Field(..., gt=0)
    quantity: int = Field(..., gt=0)


class QuotationItemCreate(QuotationItemBase):
    pass


class QuotationItemResponse(BaseModel):
    id: int
    category_id: int
    category_name: str
    daily_rate: float
    deposit_amount: float
    quantity: int
    subtotal_rental: float
    subtotal_deposit: float
    created_at: datetime

    class Config:
        from_attributes = True


class QuotationBase(BaseModel):
    customer_id: int = Field(..., gt=0)
    rental_days: int = Field(..., gt=0)
    discount_rate: float = Field(0.0, ge=0, le=100)
    notes: Optional[str] = None


class QuotationCreate(QuotationBase):
    items: List[QuotationItemCreate]


class QuotationUpdate(BaseModel):
    rental_days: Optional[int] = Field(None, gt=0)
    discount_rate: Optional[float] = Field(None, ge=0, le=100)
    notes: Optional[str] = None
    items: Optional[List[QuotationItemCreate]] = None


class QuotationStatusUpdate(BaseModel):
    status: QuotationStatus


class QuotationVoidRequest(BaseModel):
    reason: Optional[str] = None


class QuotationConvertItem(BaseModel):
    quotation_item_id: int = Field(..., gt=0)
    device_ids: List[int] = Field(...)

    @field_validator("device_ids")
    @classmethod
    def check_device_ids_not_empty(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("device_ids cannot be empty")
        if len(v) != len(set(v)):
            raise ValueError("device_ids cannot contain duplicates")
        return v


class QuotationConvertRequest(BaseModel):
    start_date: datetime
    items: List[QuotationConvertItem]
    notes: Optional[str] = None

    @field_validator("items")
    @classmethod
    def check_items_not_empty(cls, v: List[QuotationConvertItem]) -> List[QuotationConvertItem]:
        if not v:
            raise ValueError("items cannot be empty")
        return v


class QuotationCalculationResponse(BaseModel):
    daily_rate: float
    deposit_amount: float
    rental_days: int
    quantity: int
    subtotal_rental: float
    subtotal_deposit: float


class QuotationResponse(BaseModel):
    id: int
    quotation_number: str
    customer_id: int
    customer_name: Optional[str] = None
    created_by_id: int
    created_by_name: Optional[str] = None
    rental_days: int
    discount_rate: float
    total_rental_fee: float
    total_deposit: float
    discount_amount: float
    estimated_total: float
    status: QuotationStatus
    notes: Optional[str] = None
    voided_at: Optional[datetime] = None
    voided_by_id: Optional[int] = None
    voided_by_name: Optional[str] = None
    items: List[QuotationItemResponse] = []
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

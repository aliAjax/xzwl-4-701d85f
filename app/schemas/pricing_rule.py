from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

from ..models.pricing_rule import PricingRuleStatus
from ..models.user import UserRole


class TieredDiscountBase(BaseModel):
    min_days: int = Field(..., ge=1)
    max_days: Optional[int] = Field(None, ge=1)
    discount_rate: float = Field(..., ge=0, le=100)


class TieredDiscountCreate(TieredDiscountBase):
    pass


class TieredDiscountUpdate(BaseModel):
    min_days: Optional[int] = Field(None, ge=1)
    max_days: Optional[int] = Field(None, ge=1)
    discount_rate: Optional[float] = Field(None, ge=0, le=100)


class TieredDiscountResponse(BaseModel):
    id: int
    min_days: int
    max_days: Optional[int]
    discount_rate: float
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class PricingRuleBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    category_id: int = Field(..., gt=0)
    priority: int = Field(0, ge=0)
    min_rental_days: int = Field(1, ge=1)
    deposit_adjustment_factor: float = Field(1.0, gt=0)
    overdue_daily_rate_multiplier: float = Field(1.0, gt=0)
    allowed_customer_roles: Optional[List[str]] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    tiered_discounts: List[TieredDiscountCreate] = Field(default_factory=list)


class PricingRuleCreate(PricingRuleBase):
    pass


class PricingRuleUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    category_id: Optional[int] = Field(None, gt=0)
    status: Optional[PricingRuleStatus] = None
    priority: Optional[int] = Field(None, ge=0)
    min_rental_days: Optional[int] = Field(None, ge=1)
    deposit_adjustment_factor: Optional[float] = Field(None, gt=0)
    overdue_daily_rate_multiplier: Optional[float] = Field(None, gt=0)
    allowed_customer_roles: Optional[List[str]] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    tiered_discounts: Optional[List[TieredDiscountCreate]] = None


class PricingRuleResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    category_id: int
    category: Optional[dict] = None
    status: PricingRuleStatus
    priority: int
    min_rental_days: int
    deposit_adjustment_factor: float
    overdue_daily_rate_multiplier: float
    allowed_customer_roles: Optional[List[str]]
    valid_from: Optional[datetime]
    valid_to: Optional[datetime]
    created_by_id: int
    tiered_discounts: List[TieredDiscountResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class TrialCalcItem(BaseModel):
    category_id: int = Field(..., gt=0)
    quantity: int = Field(1, gt=0)
    daily_rate_override: Optional[float] = Field(None, gt=0)
    deposit_override: Optional[float] = Field(None, ge=0)


class TrialCalcRequest(BaseModel):
    items: List[TrialCalcItem]
    rental_days: int = Field(..., gt=0)
    customer_role: Optional[str] = None
    customer_id: Optional[int] = None
    manual_discount_rate: Optional[float] = Field(None, ge=0, le=100)
    expected_overdue_days: Optional[int] = Field(0, ge=0)


class TrialCalcItemResult(BaseModel):
    category_id: int
    category_name: str
    quantity: int
    daily_rate: float
    base_deposit: float
    applied_discount_rate: float
    applied_pricing_rule_id: Optional[int]
    applied_pricing_rule_name: Optional[str]
    rental_fee: float
    deposit: float
    subtotal: float


class TrialCalcResponse(BaseModel):
    items: List[TrialCalcItemResult]
    rental_days: int
    effective_rental_days: int
    total_rental_fee: float
    total_deposit: float
    total_discount: float
    manual_discount_amount: float
    estimated_overdue_fee: float
    grand_total: float
    applied_rules: List[dict]
    warnings: List[str]

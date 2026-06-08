from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Float, Text, Boolean, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from datetime import datetime, timezone
from typing import List, Optional

from ..database import Base
from ..models.user import UserRole


class PricingRuleStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class PricingRule(Base):
    __tablename__ = "pricing_rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)

    category_id = Column(Integer, ForeignKey("device_categories.id"), nullable=False)
    category = relationship("DeviceCategory")

    status = Column(Enum(PricingRuleStatus), default=PricingRuleStatus.ACTIVE, nullable=False)
    priority = Column(Integer, default=0, nullable=False)

    min_rental_days = Column(Integer, default=1, nullable=False)
    deposit_adjustment_factor = Column(Float, default=1.0, nullable=False)
    overdue_daily_rate_multiplier = Column(Float, default=1.0, nullable=False)

    allowed_customer_roles = Column(JSON, default=list)

    valid_from = Column(DateTime(timezone=True))
    valid_to = Column(DateTime(timezone=True))

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_by = relationship("User", foreign_keys=[created_by_id])

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    tiered_discounts = relationship(
        "TieredDiscount",
        back_populates="pricing_rule",
        cascade="all, delete-orphan",
        order_by="TieredDiscount.min_days"
    )

    def is_available_for_role(self, role: UserRole) -> bool:
        if not self.allowed_customer_roles:
            return True
        return role.value in self.allowed_customer_roles

    def is_within_valid_period(self, check_date: Optional[datetime] = None) -> bool:
        check_date = check_date or datetime.now(timezone.utc)
        if self.valid_from and check_date < self.valid_from:
            return False
        if self.valid_to and check_date > self.valid_to:
            return False
        return True

    def get_applicable_discount(self, rental_days: int) -> float:
        applicable_discount = 0.0
        for discount in self.tiered_discounts:
            if discount.min_days <= rental_days:
                if discount.max_days is None or rental_days <= discount.max_days:
                    applicable_discount = discount.discount_rate
        return applicable_discount

    def calculate_rental_fee(self, daily_rate: float, rental_days: int, quantity: int = 1) -> float:
        discount_rate = self.get_applicable_discount(rental_days)
        base_rental = daily_rate * max(rental_days, self.min_rental_days) * quantity
        discount_amount = base_rental * (discount_rate / 100)
        return round(base_rental - discount_amount, 2)

    def calculate_deposit(self, base_deposit: float, quantity: int = 1) -> float:
        return round(base_deposit * self.deposit_adjustment_factor * quantity, 2)

    def calculate_overdue_fee(self, daily_rate: float, overdue_days: int, quantity: int = 1) -> float:
        if overdue_days <= 0:
            return 0.0
        from ..config import settings
        effective_rate = settings.OVERDUE_DAILY_RATE * self.overdue_daily_rate_multiplier
        return round(effective_rate * overdue_days * quantity, 2)


class TieredDiscount(Base):
    __tablename__ = "tiered_discounts"

    id = Column(Integer, primary_key=True, index=True)
    pricing_rule_id = Column(Integer, ForeignKey("pricing_rules.id"), nullable=False)
    pricing_rule = relationship("PricingRule", back_populates="tiered_discounts")

    min_days = Column(Integer, nullable=False)
    max_days = Column(Integer)
    discount_rate = Column(Float, nullable=False, default=0.0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

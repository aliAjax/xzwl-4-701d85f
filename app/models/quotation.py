from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Float, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from datetime import datetime, timezone

from ..database import Base


class QuotationStatus(str, enum.Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    VOIDED = "voided"


class Quotation(Base):
    __tablename__ = "quotations"

    id = Column(Integer, primary_key=True, index=True)
    quotation_number = Column(String(50), unique=True, nullable=False, index=True)

    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    customer = relationship("User", foreign_keys=[customer_id])

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_by = relationship("User", foreign_keys=[created_by_id])

    rental_days = Column(Integer, nullable=False)
    discount_rate = Column(Float, default=0.0)

    total_rental_fee = Column(Float, nullable=False, default=0.0)
    total_deposit = Column(Float, nullable=False, default=0.0)
    discount_amount = Column(Float, nullable=False, default=0.0)
    estimated_total = Column(Float, nullable=False, default=0.0)

    status = Column(Enum(QuotationStatus), default=QuotationStatus.DRAFT, nullable=False)
    notes = Column(Text)

    voided_at = Column(DateTime(timezone=True))
    voided_by_id = Column(Integer, ForeignKey("users.id"))
    voided_by = relationship("User", foreign_keys=[voided_by_id])

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    items = relationship("QuotationItem", back_populates="quotation", cascade="all, delete-orphan")

    def calculate_totals(self):
        rental_fee = 0.0
        deposit = 0.0
        for item in self.items:
            item_rental = item.daily_rate * self.rental_days * item.quantity
            rental_fee += item_rental
            deposit += item.deposit_amount * item.quantity

        discount_amount = rental_fee * (self.discount_rate / 100)

        self.total_rental_fee = round(rental_fee, 2)
        self.total_deposit = round(deposit, 2)
        self.discount_amount = round(discount_amount, 2)
        self.estimated_total = round(rental_fee - discount_amount + deposit, 2)

    def can_void(self) -> bool:
        return self.status in [QuotationStatus.DRAFT, QuotationStatus.CONFIRMED]

    def void(self, user):
        if not self.can_void():
            return False
        self.status = QuotationStatus.VOIDED
        self.voided_at = datetime.now(timezone.utc)
        self.voided_by_id = user.id
        return True


class QuotationItem(Base):
    __tablename__ = "quotation_items"

    id = Column(Integer, primary_key=True, index=True)
    quotation_id = Column(Integer, ForeignKey("quotations.id"), nullable=False)
    quotation = relationship("Quotation", back_populates="items")

    category_id = Column(Integer, ForeignKey("device_categories.id"), nullable=False)
    category = relationship("DeviceCategory")

    category_name = Column(String(100), nullable=False)
    daily_rate = Column(Float, nullable=False)
    deposit_amount = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False, default=1)

    subtotal_rental = Column(Float, default=0.0)
    subtotal_deposit = Column(Float, default=0.0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def calculate_subtotals(self, rental_days: int):
        self.subtotal_rental = round(self.daily_rate * rental_days * self.quantity, 2)
        self.subtotal_deposit = round(self.deposit_amount * self.quantity, 2)

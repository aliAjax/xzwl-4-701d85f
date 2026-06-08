from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Float, Text, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from datetime import datetime, timedelta, timezone

from ..database import Base
from ..config import settings


class ContractStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    ACTIVE = "active"
    RENEWED = "renewed"
    RETURNED = "returned"
    EXPIRED = "expired"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class Contract(Base):
    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True, index=True)
    contract_number = Column(String(50), unique=True, nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    customer = relationship("User", foreign_keys=[customer_id], back_populates="contracts")

    created_by_id = Column(Integer, ForeignKey("users.id"))
    created_by_user = relationship("User", foreign_keys=[created_by_id], back_populates="created_contracts")

    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    actual_return_date = Column(DateTime(timezone=True))

    total_amount = Column(Float, nullable=False, default=0.0)
    deposit_amount = Column(Float, nullable=False, default=0.0)
    overdue_fee = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    final_amount = Column(Float, default=0.0)

    deposit_refunded = Column(Boolean, default=False)
    deposit_refund_date = Column(DateTime(timezone=True))

    status = Column(Enum(ContractStatus), default=ContractStatus.DRAFT, nullable=False)
    notes = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    items = relationship("ContractItem", back_populates="contract", cascade="all, delete-orphan")
    deposits = relationship("Deposit", back_populates="contract")
    handovers = relationship("Handover", back_populates="contract")

    def calculate_rental_days(self) -> int:
        end = self.actual_return_date or self.end_date
        delta = end - self.start_date
        return max(1, delta.days + 1)

    def calculate_overdue_days(self) -> int:
        if not self.actual_return_date:
            return 0
        if self.actual_return_date <= self.end_date:
            return 0
        delta = self.actual_return_date - self.end_date
        return delta.days

    def calculate_total_amount(self) -> float:
        total = 0.0
        for item in self.items:
            total += item.calculate_item_total()
        return total

    def calculate_overdue_fee(self) -> float:
        overdue_days = self.calculate_overdue_days()
        if overdue_days <= settings.OVERDUE_GRACE_PERIOD_DAYS:
            return 0.0
        return (overdue_days - settings.OVERDUE_GRACE_PERIOD_DAYS) * settings.OVERDUE_DAILY_RATE * len(self.items)

    def update_status_based_on_dates(self):
        now = datetime.now(timezone.utc)
        if self.status in [ContractStatus.ACTIVE, ContractStatus.RENEWED]:
            if now > self.end_date:
                self.status = ContractStatus.OVERDUE
            elif self.actual_return_date:
                self.status = ContractStatus.RETURNED

    def can_renew(self) -> bool:
        return self.status in [ContractStatus.ACTIVE, ContractStatus.OVERDUE, ContractStatus.RENEWED]

    def can_return(self) -> bool:
        return self.status in [ContractStatus.ACTIVE, ContractStatus.OVERDUE, ContractStatus.RENEWED]


class ContractItem(Base):
    __tablename__ = "contract_items"

    id = Column(Integer, primary_key=True, index=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False)
    contract = relationship("Contract", back_populates="items")

    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    device = relationship("Device", back_populates="contract_items")

    daily_rate = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    subtotal = Column(Float, default=0.0)
    notes = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def calculate_item_total(self) -> float:
        rental_days = self.contract.calculate_rental_days()
        return self.daily_rate * rental_days * self.quantity

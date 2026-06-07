from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Enum, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from ..database import Base


class DepositStatus(str, enum.Enum):
    PAID = "paid"
    PARTIAL_REFUND = "partial_refund"
    FULL_REFUND = "full_refund"
    FORFEITED = "forfeited"


class Deposit(Base):
    __tablename__ = "deposits"

    id = Column(Integer, primary_key=True, index=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False)
    contract = relationship("Contract", back_populates="deposits")

    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    customer = relationship("User", back_populates="deposits")

    amount = Column(Float, nullable=False)
    payment_date = Column(DateTime(timezone=True), nullable=False)
    payment_method = Column(String(50))
    transaction_id = Column(String(100))

    refund_amount = Column(Float, default=0.0)
    refund_date = Column(DateTime(timezone=True))
    refund_method = Column(String(50))
    refund_transaction_id = Column(String(100))

    status = Column(String(20), default="paid", nullable=False)

    deductions = Column(Text)
    notes = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

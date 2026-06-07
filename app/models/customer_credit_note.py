from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Text, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from ..database import Base


class RiskTag(str, enum.Enum):
    DEPOSIT_DISPUTE = "deposit_dispute"
    OVERDUE_RETURN = "overdue_return"
    DEVICE_DAMAGE = "device_damage"
    PAYMENT_ISSUE = "payment_issue"
    OTHER = "other"


class CustomerCreditNote(Base):
    __tablename__ = "customer_credit_notes"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    customer = relationship("User", foreign_keys=[customer_id], back_populates="credit_notes")

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_by = relationship("User", foreign_keys=[created_by_id])

    risk_tag = Column(Enum(RiskTag), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    related_contract_id = Column(Integer, ForeignKey("contracts.id"))
    related_contract = relationship("Contract", foreign_keys=[related_contract_id])

    is_active = Column(Boolean, default=True, nullable=False)
    resolved_by_id = Column(Integer, ForeignKey("users.id"))
    resolved_by = relationship("User", foreign_keys=[resolved_by_id])
    resolved_at = Column(DateTime(timezone=True))
    resolution_notes = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def is_resolved(self) -> bool:
        return self.resolved_at is not None or not self.is_active

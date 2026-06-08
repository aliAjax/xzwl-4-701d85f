from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Text, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from ..database import Base


class HandoverType(str, enum.Enum):
    OUTBOUND = "outbound"
    RETURN = "return"


class HandoverStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class Handover(Base):
    __tablename__ = "handovers"

    id = Column(Integer, primary_key=True, index=True)
    handover_number = Column(String(50), unique=True, nullable=False, index=True)

    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False, index=True)
    contract = relationship("Contract")

    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False, index=True)
    device = relationship("Device")

    handover_type = Column(Enum(HandoverType), nullable=False, index=True)
    status = Column(Enum(HandoverStatus), default=HandoverStatus.DRAFT, nullable=False, index=True)

    appearance_description = Column(Text)
    accessories = Column(JSON)
    abnormal_remarks = Column(Text)

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_by = relationship("User", foreign_keys=[created_by_id])

    confirmed_by_staff_id = Column(Integer, ForeignKey("users.id"))
    confirmed_by_staff = relationship("User", foreign_keys=[confirmed_by_staff_id])

    confirmed_by_customer_id = Column(Integer, ForeignKey("users.id"))
    confirmed_by_customer = relationship("User", foreign_keys=[confirmed_by_customer_id])

    staff_confirmed_at = Column(DateTime(timezone=True))
    customer_confirmed_at = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

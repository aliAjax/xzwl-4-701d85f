from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from ..database import Base


class TransferLocationType(str, enum.Enum):
    WAREHOUSE = "warehouse"
    STORE = "store"
    CUSTOMER = "customer"
    REPAIR = "repair"


class TransferStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class DeviceTransfer(Base):
    __tablename__ = "device_transfers"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False, index=True)
    device = relationship("Device", back_populates="transfers")

    from_location_type = Column(Enum(TransferLocationType), nullable=False)
    from_location = Column(String(255), nullable=False)
    to_location_type = Column(Enum(TransferLocationType), nullable=False)
    to_location = Column(String(255), nullable=False)

    status = Column(Enum(TransferStatus), default=TransferStatus.PENDING, nullable=False, index=True)

    transfer_notes = Column(Text)

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_by = relationship("User", foreign_keys=[created_by_id])
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    confirmed_by_id = Column(Integer, ForeignKey("users.id"))
    confirmed_by = relationship("User", foreign_keys=[confirmed_by_id])
    confirmed_at = Column(DateTime(timezone=True))

    cancelled_by_id = Column(Integer, ForeignKey("users.id"))
    cancelled_by = relationship("User", foreign_keys=[cancelled_by_id])
    cancelled_at = Column(DateTime(timezone=True))
    cancel_reason = Column(Text)

    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

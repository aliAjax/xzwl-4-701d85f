from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Text, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from ..database import Base


class DeviceSwapStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class DeviceSwap(Base):
    __tablename__ = "device_swaps"

    id = Column(Integer, primary_key=True, index=True)
    swap_number = Column(String(50), unique=True, nullable=False, index=True)

    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False, index=True)
    contract = relationship("Contract", foreign_keys=[contract_id])

    old_device_id = Column(Integer, ForeignKey("devices.id"), nullable=False, index=True)
    old_device = relationship("Device", foreign_keys=[old_device_id])

    new_device_id = Column(Integer, ForeignKey("devices.id"), nullable=False, index=True)
    new_device = relationship("Device", foreign_keys=[new_device_id])

    contract_item_id = Column(Integer, ForeignKey("contract_items.id"), nullable=False)
    contract_item = relationship("ContractItem", foreign_keys=[contract_item_id])

    fault_description = Column(Text, nullable=False)
    fault_category = Column(String(100))

    old_daily_rate = Column(Float, nullable=False)
    new_daily_rate = Column(Float, nullable=False)
    keep_original_rate = Column(Float, nullable=False)

    status = Column(Enum(DeviceSwapStatus), default=DeviceSwapStatus.PENDING, nullable=False, index=True)

    repair_record_id = Column(Integer, ForeignKey("repair_records.id"))
    repair_record = relationship("RepairRecord", foreign_keys=[repair_record_id])

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_by = relationship("User", foreign_keys=[created_by_id])

    completed_by_id = Column(Integer, ForeignKey("users.id"))
    completed_by = relationship("User", foreign_keys=[completed_by_id])
    completed_at = Column(DateTime(timezone=True))

    cancelled_by_id = Column(Integer, ForeignKey("users.id"))
    cancelled_by = relationship("User", foreign_keys=[cancelled_by_id])
    cancelled_at = Column(DateTime(timezone=True))
    cancel_reason = Column(Text)

    notes = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

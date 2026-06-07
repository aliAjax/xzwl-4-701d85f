from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Enum, Float, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from ..database import Base


class RepairStatus(str, enum.Enum):
    REPORTED = "reported"
    DIAGNOSING = "diagnosing"
    IN_PROGRESS = "in_progress"
    AWAITING_PARTS = "awaiting_parts"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    UNREPAIRABLE = "unrepairable"


class RepairPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class RepairRecord(Base):
    __tablename__ = "repair_records"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    device = relationship("Device", back_populates="repair_records")

    report_date = Column(DateTime(timezone=True), nullable=False)
    reported_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_by = relationship("User", foreign_keys=[reported_by_id], back_populates="created_repairs")

    priority = Column(String(20), default="medium", nullable=False)
    status = Column(String(20), default="reported", nullable=False)

    fault_description = Column(Text, nullable=False)
    fault_category = Column(String(100))

    diagnosis = Column(Text)
    diagnosis_date = Column(DateTime(timezone=True))

    repair_plan = Column(Text)
    repair_start_date = Column(DateTime(timezone=True))
    repair_complete_date = Column(DateTime(timezone=True))

    parts_used = Column(Text)
    parts_cost = Column(Float, default=0.0)
    labor_cost = Column(Float, default=0.0)
    total_cost = Column(Float, default=0.0)

    handled_by_id = Column(Integer, ForeignKey("users.id"))
    handled_by = relationship("User", foreign_keys=[handled_by_id], back_populates="handled_repairs")

    technician_notes = Column(Text)
    customer_notes = Column(Text)

    is_warranty = Column(Boolean, default=False)
    warranty_expired = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

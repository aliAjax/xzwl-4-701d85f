from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from ..database import Base


class MaintenanceType(str, enum.Enum):
    PREVENTIVE = "preventive"
    CORRECTIVE = "corrective"
    INSPECTION = "inspection"
    CALIBRATION = "calibration"


class MaintenanceStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MaintenanceRecord(Base):
    __tablename__ = "maintenance_records"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    device = relationship("Device", back_populates="maintenance_records")

    maintenance_type = Column(String(50), nullable=False)
    status = Column(String(50), default="scheduled", nullable=False)
    scheduled_date = Column(DateTime(timezone=True), nullable=False)
    actual_date = Column(DateTime(timezone=True))

    technician_name = Column(String(100))
    service_provider = Column(String(100))
    cost = Column(Float, default=0.0)

    description = Column(Text, nullable=False)
    work_performed = Column(Text)
    parts_replaced = Column(Text)

    next_maintenance_date = Column(DateTime(timezone=True))
    is_successful = Column(Boolean, default=True)

    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Enum, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from ..database import Base


class TaskType(str, enum.Enum):
    MAINTENANCE = "maintenance"
    DISINFECTION = "disinfection"
    REPAIR = "repair"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class MaintenanceTask(Base):
    __tablename__ = "maintenance_tasks"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    device = relationship("Device")

    task_type = Column(Enum(TaskType), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)

    priority = Column(Enum(TaskPriority), default=TaskPriority.MEDIUM, nullable=False)
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False)

    scheduled_date = Column(DateTime(timezone=True), nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=False)
    completed_date = Column(DateTime(timezone=True))

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_by = relationship("User", foreign_keys=[created_by_id])

    assigned_to_id = Column(Integer, ForeignKey("users.id"))
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])

    maintenance_record_id = Column(Integer, ForeignKey("maintenance_records.id"))
    maintenance_record = relationship("MaintenanceRecord")

    disinfection_record_id = Column(Integer, ForeignKey("disinfection_records.id"))
    disinfection_record = relationship("DisinfectionRecord")

    repair_record_id = Column(Integer, ForeignKey("repair_records.id"))
    repair_record = relationship("RepairRecord")

    completion_notes = Column(Text)
    notes = Column(Text)

    is_overdue = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

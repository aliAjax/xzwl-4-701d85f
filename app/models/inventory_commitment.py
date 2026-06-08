from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Enum, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum
import uuid

from ..database import Base


class CommitmentType(str, enum.Enum):
    CONTRACT = "contract"
    RESERVATION = "reservation"
    TRANSFER = "transfer"
    MAINTENANCE = "maintenance"
    REPAIR = "repair"
    DISINFECTION = "disinfection"
    LOCK = "lock"


class CommitmentStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    EXPIRED = "expired"


class InventoryCommitment(Base):
    __tablename__ = "inventory_commitments"

    id = Column(Integer, primary_key=True, index=True)
    commitment_token = Column(String(100), unique=True, nullable=False, index=True, default=lambda: str(uuid.uuid4()))
    batch_token = Column(String(100), index=True)

    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False, index=True)
    device = relationship("Device", back_populates="inventory_commitments")

    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    warehouse = relationship("Warehouse", back_populates="inventory_commitments")

    category_id = Column(Integer, ForeignKey("device_categories.id"), nullable=False, index=True)
    category = relationship("DeviceCategory")

    commitment_type = Column(String(30), nullable=False, index=True)
    status = Column(String(20), default=CommitmentStatus.PENDING, nullable=False, index=True)

    start_date = Column(DateTime(timezone=True), nullable=False, index=True)
    end_date = Column(DateTime(timezone=True), nullable=False, index=True)

    reference_id = Column(Integer, index=True)
    reference_type = Column(String(50), index=True)

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_by = relationship("User", foreign_keys=[created_by_id])

    expires_at = Column(DateTime(timezone=True))
    confirmed_at = Column(DateTime(timezone=True))
    cancelled_at = Column(DateTime(timezone=True))

    notes = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("idx_commitment_device_dates", "device_id", "start_date", "end_date"),
        Index("idx_commitment_warehouse_category", "warehouse_id", "category_id", "status"),
        Index("idx_commitment_batch_token", "batch_token"),
        Index("idx_commitment_reference", "reference_type", "reference_id"),
    )

    def is_active(self) -> bool:
        if self.status in [CommitmentStatus.CANCELLED, CommitmentStatus.COMPLETED, CommitmentStatus.EXPIRED]:
            return False
        if self.expires_at and datetime.now(timezone.utc) > self.expires_at:
            return False
        return True

    def is_expired(self) -> bool:
        if self.expires_at and datetime.now(timezone.utc) > self.expires_at:
            return True
        return False

    def overlaps_with(self, other_start: datetime, other_end: datetime) -> bool:
        return (self.start_date < other_end) and (self.end_date > other_start)

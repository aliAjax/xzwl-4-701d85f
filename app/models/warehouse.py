from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from ..database import Base


class WarehouseType(str, enum.Enum):
    MAIN = "main"
    BRANCH = "branch"
    SERVICE = "service"
    TRANSIT = "transit"


class WarehouseStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"


class Warehouse(Base):
    __tablename__ = "warehouses"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    type = Column(String(20), default=WarehouseType.BRANCH, nullable=False)
    status = Column(String(20), default=WarehouseStatus.ACTIVE, nullable=False)

    address = Column(String(255))
    city = Column(String(100))
    province = Column(String(100))
    postal_code = Column(String(20))
    country = Column(String(100), default="China")

    contact_person = Column(String(100))
    contact_phone = Column(String(50))
    contact_email = Column(String(100))

    capacity = Column(Integer, default=0)
    current_occupancy = Column(Float, default=0.0)

    is_default = Column(Boolean, default=False)
    notes = Column(Text)

    created_by_id = Column(Integer, ForeignKey("users.id"))
    created_by = relationship("User", foreign_keys=[created_by_id])

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    devices = relationship("Device", back_populates="warehouse")
    inventory_commitments = relationship("InventoryCommitment", back_populates="warehouse")

    def is_active(self) -> bool:
        return self.status == WarehouseStatus.ACTIVE

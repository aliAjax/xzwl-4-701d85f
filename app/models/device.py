from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Enum, Float, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from ..database import Base


class DeviceStatus(str, enum.Enum):
    AVAILABLE = "available"
    IN_USE = "in_use"
    MAINTENANCE = "maintenance"
    REPAIR = "repair"
    DISINFECTION = "disinfection"
    LOCKED = "locked"
    RETIRED = "retired"


class DeviceCategory(Base):
    __tablename__ = "device_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    daily_rental_rate = Column(Float, nullable=False)
    deposit_amount = Column(Float, nullable=False)
    maintenance_cycle_days = Column(Integer, nullable=False, default=30)
    disinfection_required = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    devices = relationship("Device", back_populates="category")


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    serial_number = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    model = Column(String(100))
    manufacturer = Column(String(100))
    purchase_date = Column(DateTime)
    purchase_price = Column(Float)
    current_owner = Column(String(100))
    location = Column(String(255))
    status = Column(Enum(DeviceStatus), default=DeviceStatus.AVAILABLE, nullable=False)
    notes = Column(Text)

    category_id = Column(Integer, ForeignKey("device_categories.id"), nullable=False)
    category = relationship("DeviceCategory", back_populates="devices")

    last_disinfection_date = Column(DateTime(timezone=True))
    last_maintenance_date = Column(DateTime(timezone=True))
    next_maintenance_date = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    contract_items = relationship("ContractItem", back_populates="device")
    disinfection_records = relationship("DisinfectionRecord", back_populates="device")
    maintenance_records = relationship("MaintenanceRecord", back_populates="device")
    repair_records = relationship("RepairRecord", back_populates="device")
    device_locks = relationship("DeviceLock", back_populates="device")
    reservations = relationship("Reservation", back_populates="device")
    transfers = relationship("DeviceTransfer", back_populates="device")

    def is_available_for_rent(self) -> bool:
        if self.status in [DeviceStatus.MAINTENANCE, DeviceStatus.REPAIR, DeviceStatus.RETIRED]:
            return False
        if self.status == DeviceStatus.DISINFECTION:
            return False
        if self.category.disinfection_required and not self.last_disinfection_date:
            return False
        return True

    def needs_maintenance(self) -> bool:
        if not self.next_maintenance_date:
            return False
        from datetime import datetime, timezone
        next_maintenance_date = self.next_maintenance_date
        if next_maintenance_date.tzinfo is None:
            next_maintenance_date = next_maintenance_date.replace(tzinfo=timezone.utc)
        return next_maintenance_date <= datetime.now(timezone.utc)

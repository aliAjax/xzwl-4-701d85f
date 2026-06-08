from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Enum, Float, Text, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from ..database import Base


class ImportStatus(str, enum.Enum):
    PENDING = "pending"
    PREVIEWED = "previewed"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ImportItemStatus(str, enum.Enum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    IMPORTED = "imported"
    FAILED = "failed"
    SKIPPED = "skipped"


class ValidationErrorType(str, enum.Enum):
    SERIAL_DUPLICATE_IN_BATCH = "serial_duplicate_in_batch"
    SERIAL_DUPLICATE_IN_DB = "serial_duplicate_in_db"
    CATEGORY_NOT_FOUND = "category_not_found"
    WAREHOUSE_NOT_FOUND = "warehouse_not_found"
    WAREHOUSE_NOT_ACTIVE = "warehouse_not_active"
    WAREHOUSE_ID_AND_CODE_BOTH_PROVIDED = "warehouse_id_and_code_both_provided"
    PURCHASE_DATE_INVALID = "purchase_date_invalid"
    DEPOSIT_MISSING = "deposit_missing"
    RENTAL_RATE_MISSING = "rental_rate_missing"
    SERIAL_NUMBER_EMPTY = "serial_number_empty"
    NAME_EMPTY = "name_empty"
    CATEGORY_ID_EMPTY = "category_id_empty"
    PURCHASE_PRICE_NEGATIVE = "purchase_price_negative"


class DeviceImport(Base):
    __tablename__ = "device_imports"

    id = Column(Integer, primary_key=True, index=True)
    batch_number = Column(String(50), unique=True, nullable=False, index=True)
    total_count = Column(Integer, nullable=False, default=0)
    valid_count = Column(Integer, nullable=False, default=0)
    invalid_count = Column(Integer, nullable=False, default=0)
    imported_count = Column(Integer, nullable=False, default=0)
    skipped_count = Column(Integer, nullable=False, default=0)
    status = Column(Enum(ImportStatus), default=ImportStatus.PENDING, nullable=False)
    previewed_at = Column(DateTime(timezone=True))
    confirmed_at = Column(DateTime(timezone=True))
    remarks = Column(Text)

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_by = relationship("User", foreign_keys=[created_by_id])

    items = relationship("DeviceImportItem", back_populates="import_batch", cascade="all, delete-orphan")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class DeviceImportItem(Base):
    __tablename__ = "device_import_items"

    id = Column(Integer, primary_key=True, index=True)
    import_id = Column(Integer, ForeignKey("device_imports.id"), nullable=False, index=True)
    row_index = Column(Integer, nullable=False)

    serial_number = Column(String(100))
    name = Column(String(100))
    model = Column(String(100))
    manufacturer = Column(String(100))
    purchase_date_str = Column(String(50))
    purchase_date = Column(DateTime)
    purchase_price = Column(Float)
    current_owner = Column(String(100))
    location = Column(String(255))
    notes = Column(Text)
    category_id = Column(Integer)
    category_name = Column(String(100))
    warehouse_id = Column(Integer)
    warehouse_code = Column(String(50))
    warehouse_name = Column(String(100))

    status = Column(Enum(ImportItemStatus), default=ImportItemStatus.PENDING, nullable=False)
    validation_errors = Column(JSON)
    error_message = Column(Text)

    device_id = Column(Integer, ForeignKey("devices.id"))
    device = relationship("Device", foreign_keys=[device_id])

    import_batch = relationship("DeviceImport", back_populates="items")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

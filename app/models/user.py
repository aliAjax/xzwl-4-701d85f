from sqlalchemy import Column, Integer, String, DateTime, Boolean, Enum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from ..database import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    STAFF = "staff"
    CUSTOMER = "customer"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    full_name = Column(String(100), nullable=False)
    phone = Column(String(20), unique=True, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.CUSTOMER, nullable=False)
    is_active = Column(Boolean, default=True)
    address = Column(String(255))
    id_card = Column(String(50), unique=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    contracts = relationship("Contract", foreign_keys="Contract.customer_id", back_populates="customer")
    deposits = relationship("Deposit", back_populates="customer")
    created_repairs = relationship("RepairRecord", foreign_keys="RepairRecord.reported_by_id", back_populates="created_by")
    handled_repairs = relationship("RepairRecord", foreign_keys="RepairRecord.handled_by_id", back_populates="handled_by")
    audit_logs = relationship("AuditLog", back_populates="user")
    created_contracts = relationship("Contract", foreign_keys="Contract.created_by_id", back_populates="created_by_user")

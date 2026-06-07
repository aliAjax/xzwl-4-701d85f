from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from ..database import Base


class AuditAction(str, enum.Enum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    STATUS_CHANGE = "status_change"
    LOGIN = "login"
    LOGOUT = "logout"
    LOCK = "lock"
    UNLOCK = "unlock"
    DISINFECT = "disinfect"
    MAINTAIN = "maintain"
    REPAIR = "repair"
    RENT = "rent"
    RETURN = "return"
    RENEW = "renew"
    DEPOSIT_PAY = "deposit_pay"
    DEPOSIT_REFUND = "deposit_refund"
    OVERDUE = "overdue"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="audit_logs")

    action = Column(String(50), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(String(100))

    old_values = Column(JSON)
    new_values = Column(JSON)
    changes = Column(JSON)

    ip_address = Column(String(45))
    user_agent = Column(String(255))

    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

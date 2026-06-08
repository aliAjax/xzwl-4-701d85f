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
    RESERVE = "reserve"
    RESERVATION_CONFIRM = "reservation_confirm"
    RESERVATION_CANCEL = "reservation_cancel"
    QUOTE_CREATE = "quote_create"
    QUOTE_VOID = "quote_void"
    QUOTE_CONVERT = "quote_convert"
    TRANSFER_CREATE = "transfer_create"
    TRANSFER_CONFIRM = "transfer_confirm"
    TRANSFER_CANCEL = "transfer_cancel"
    SWAP_CREATE = "swap_create"
    SWAP_COMPLETE = "swap_complete"
    SWAP_CANCEL = "swap_cancel"
    HANDOVER_CREATE = "handover_create"
    HANDOVER_UPDATE = "handover_update"
    HANDOVER_CONFIRM = "handover_confirm"
    HANDOVER_CANCEL = "handover_cancel"
    TASK_CREATE = "task_create"
    TASK_UPDATE = "task_update"
    TASK_CLAIM = "task_claim"
    TASK_START = "task_start"
    TASK_COMPLETE = "task_complete"
    TASK_CANCEL = "task_cancel"
    TASK_GENERATE = "task_generate"


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

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from ..database import Base


class ReminderStatus(str, enum.Enum):
    PENDING = "pending"
    CONTACTED = "contacted"
    NO_ACTION_NEEDED = "no_action_needed"
    FOLLOW_UP_LATER = "follow_up_later"


class ContractReminder(Base):
    __tablename__ = "contract_reminders"

    id = Column(Integer, primary_key=True, index=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False, index=True)
    contract = relationship("Contract", foreign_keys=[contract_id])

    generated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    handled_by_id = Column(Integer, ForeignKey("users.id"))
    handled_by = relationship("User", foreign_keys=[handled_by_id])

    status = Column(Enum(ReminderStatus), default=ReminderStatus.PENDING, nullable=False, index=True)

    notes = Column(Text)
    follow_up_date = Column(DateTime(timezone=True))

    handled_at = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

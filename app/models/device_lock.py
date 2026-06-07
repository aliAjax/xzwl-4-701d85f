from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta, timezone

from ..database import Base
from ..config import settings


class DeviceLock(Base):
    __tablename__ = "device_locks"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False, index=True)
    device = relationship("Device", back_populates="device_locks")

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    contract_id = Column(Integer, ForeignKey("contracts.id"))

    lock_token = Column(String(100), unique=True, nullable=False, index=True)
    locked_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    released_at = Column(DateTime(timezone=True))

    purpose = Column(String(100))
    is_active = Column(Integer, default=1)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def is_expired(self) -> bool:
        now = datetime.now(timezone.utc)
        return now > self.expires_at

    def is_valid(self) -> bool:
        return self.is_active == 1 and not self.is_expired()

    @staticmethod
    def get_lock_duration():
        return timedelta(minutes=settings.DEVICE_LOCK_TIMEOUT_MINUTES)

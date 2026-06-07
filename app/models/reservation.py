from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Enum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum

from ..database import Base


class ReservationStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, index=True)
    reservation_number = Column(String(50), unique=True, index=True, nullable=False)

    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    customer = relationship("User", foreign_keys=[customer_id], back_populates="reservations")

    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False, index=True)
    device = relationship("Device", back_populates="reservations")

    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)

    purpose = Column(String(255))
    notes = Column(Text)

    status = Column(Enum(ReservationStatus), default=ReservationStatus.PENDING, nullable=False)
    confirmed_by_id = Column(Integer, ForeignKey("users.id"))
    confirmed_by = relationship("User", foreign_keys=[confirmed_by_id])
    confirmed_at = Column(DateTime(timezone=True))

    cancelled_by_id = Column(Integer, ForeignKey("users.id"))
    cancelled_by = relationship("User", foreign_keys=[cancelled_by_id])
    cancelled_at = Column(DateTime(timezone=True))
    cancellation_reason = Column(Text)

    lock_id = Column(Integer, ForeignKey("device_locks.id"))
    lock = relationship("DeviceLock")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def get_valid_status_transitions(self):
        return {
            ReservationStatus.PENDING: [ReservationStatus.CONFIRMED, ReservationStatus.CANCELLED],
            ReservationStatus.CONFIRMED: [ReservationStatus.CANCELLED, ReservationStatus.COMPLETED],
            ReservationStatus.CANCELLED: [],
            ReservationStatus.COMPLETED: [],
        }

    def can_transition_to(self, new_status: ReservationStatus) -> bool:
        valid_transitions = self.get_valid_status_transitions()
        return new_status in valid_transitions.get(self.status, [])

    def calculate_duration_hours(self) -> float:
        delta = self.end_date - self.start_date
        return delta.total_seconds() / 3600

    def is_expired(self) -> bool:
        now = datetime.now(timezone.utc)
        if self.status == ReservationStatus.CONFIRMED:
            return now > self.end_date
        return False

    @staticmethod
    def check_time_conflict(
        db,
        device_id: int,
        start_date: datetime,
        end_date: datetime,
        exclude_reservation_id: int = None,
    ) -> bool:
        from sqlalchemy import and_, or_

        query = db.query(Reservation).filter(
            Reservation.device_id == device_id,
            Reservation.status.in_([ReservationStatus.PENDING, ReservationStatus.CONFIRMED]),
            or_(
                and_(Reservation.start_date < end_date, Reservation.end_date > start_date),
                and_(start_date < Reservation.end_date, end_date > Reservation.start_date),
            ),
        )

        if exclude_reservation_id:
            query = query.filter(Reservation.id != exclude_reservation_id)

        return query.first() is not None

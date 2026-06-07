from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from datetime import datetime, timedelta, timezone
import uuid

from ..models.device_lock import DeviceLock
from ..models.device import Device, DeviceStatus
from ..models.user import User
from ..models.contract import Contract
from ..config import settings


class DeviceLockService:
    def __init__(self, db: Session):
        self.db = db

    def _cleanup_expired_locks(self):
        now = datetime.now(timezone.utc)
        expired_locks = (
            self.db.query(DeviceLock)
            .filter(
                DeviceLock.is_active == 1,
                DeviceLock.expires_at < now,
            )
            .all()
        )
        for lock in expired_locks:
            lock.is_active = 0
            lock.released_at = now
        self.db.commit()

    def is_device_locked(self, device_id: int, exclude_user_id: Optional[int] = None) -> bool:
        self._cleanup_expired_locks()
        now = datetime.now(timezone.utc)
        query = self.db.query(DeviceLock).filter(
            DeviceLock.device_id == device_id,
            DeviceLock.is_active == 1,
            DeviceLock.expires_at > now,
        )
        if exclude_user_id:
            query = query.filter(DeviceLock.user_id != exclude_user_id)
        return query.first() is not None

    def get_active_lock(self, device_id: int) -> Optional[DeviceLock]:
        self._cleanup_expired_locks()
        now = datetime.now(timezone.utc)
        return (
            self.db.query(DeviceLock)
            .filter(
                DeviceLock.device_id == device_id,
                DeviceLock.is_active == 1,
                DeviceLock.expires_at > now,
            )
            .first()
        )

    def lock_devices(
        self,
        device_ids: List[int],
        user: User,
        contract: Optional[Contract] = None,
        purpose: str = "rental",
    ) -> tuple[bool, Optional[str], List[str]]:
        self.db.begin_nested()
        try:
            self._cleanup_expired_locks()
            now = datetime.now(timezone.utc)
            lock_token = str(uuid.uuid4())
            errors = []

            for device_id in device_ids:
                device = self.db.query(Device).filter(Device.id == device_id).first()
                if not device:
                    errors.append(f"Device {device_id} not found")
                    continue

                if not device.is_available_for_rent():
                    errors.append(f"Device {device.serial_number} is not available for rent")
                    continue

                existing_lock = self.get_active_lock(device_id)
                if existing_lock and existing_lock.user_id != user.id:
                    errors.append(f"Device {device.serial_number} is locked by another user")
                    continue

            if errors:
                self.db.rollback()
                return False, None, errors

            duration = DeviceLock.get_lock_duration()
            for device_id in device_ids:
                existing_lock = self.get_active_lock(device_id)
                if existing_lock and existing_lock.user_id == user.id:
                    existing_lock.expires_at = now + duration
                    existing_lock.lock_token = lock_token
                    if contract:
                        existing_lock.contract_id = contract.id
                else:
                    lock = DeviceLock(
                        device_id=device_id,
                        user_id=user.id,
                        contract_id=contract.id if contract else None,
                        lock_token=lock_token,
                        locked_at=now,
                        expires_at=now + duration,
                        purpose=purpose,
                        is_active=1,
                    )
                    self.db.add(lock)

            self.db.commit()
            return True, lock_token, []
        except Exception as e:
            self.db.rollback()
            raise e

    def unlock_devices(self, device_ids: List[int], user: User) -> tuple[bool, List[str]]:
        self.db.begin_nested()
        try:
            now = datetime.now(timezone.utc)
            errors = []

            for device_id in device_ids:
                lock = self.get_active_lock(device_id)
                if not lock:
                    continue
                if lock.user_id != user.id and user.role not in ["admin", "staff"]:
                    errors.append(f"Device {device_id} lock owned by another user")
                    continue
                lock.is_active = 0
                lock.released_at = now

            self.db.commit()
            return True, errors
        except Exception as e:
            self.db.rollback()
            raise e

    def unlock_by_token(self, lock_token: str, user: User) -> bool:
        try:
            now = datetime.now(timezone.utc)
            locks = (
                self.db.query(DeviceLock)
                .filter(
                    DeviceLock.lock_token == lock_token,
                    DeviceLock.is_active == 1,
                )
                .all()
            )
            for lock in locks:
                if lock.user_id != user.id and user.role not in ["admin", "staff"]:
                    continue
                lock.is_active = 0
                lock.released_at = now
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            raise e

    def extend_lock(self, lock_token: str, user: User, minutes: Optional[int] = None) -> tuple[bool, List[str]]:
        try:
            now = datetime.now(timezone.utc)
            duration = minutes if minutes else settings.DEVICE_LOCK_TIMEOUT_MINUTES
            errors = []

            locks = (
                self.db.query(DeviceLock)
                .filter(
                    DeviceLock.lock_token == lock_token,
                    DeviceLock.is_active == 1,
                )
                .all()
            )
            for lock in locks:
                if lock.user_id != user.id and user.role not in ["admin", "staff"]:
                    errors.append(f"Lock for device {lock.device_id} owned by another user")
                    continue
                lock.expires_at = now + timedelta(minutes=duration)

            self.db.commit()
            return len(errors) == 0, errors
        except Exception as e:
            self.db.rollback()
            raise e

    def validate_lock(self, device_ids: List[int], lock_token: str, user: User) -> tuple[bool, List[str]]:
        self._cleanup_expired_locks()
        now = datetime.now(timezone.utc)
        errors = []

        for device_id in device_ids:
            lock = (
                self.db.query(DeviceLock)
                .filter(
                    DeviceLock.device_id == device_id,
                    DeviceLock.lock_token == lock_token,
                    DeviceLock.is_active == 1,
                    DeviceLock.expires_at > now,
                )
                .first()
            )
            if not lock:
                errors.append(f"Device {device_id} is not properly locked")
            elif lock.user_id != user.id:
                errors.append(f"Device {device_id} lock does not belong to you")

        return len(errors) == 0, errors

    def get_user_locks(self, user: User) -> List[DeviceLock]:
        self._cleanup_expired_locks()
        now = datetime.now(timezone.utc)
        return (
            self.db.query(DeviceLock)
            .filter(
                DeviceLock.user_id == user.id,
                DeviceLock.is_active == 1,
                DeviceLock.expires_at > now,
            )
            .all()
        )

    def lock_devices_for_reservation(
        self,
        device_ids: List[int],
        user: User,
        start_date: datetime,
        end_date: datetime,
        purpose: str = "reservation",
        exclude_reservation_id: Optional[int] = None,
    ) -> tuple[bool, Optional[str], List[str], Optional[List[DeviceLock]]]:
        self.db.begin_nested()
        try:
            self._cleanup_expired_locks()
            now = datetime.now(timezone.utc)
            lock_token = str(uuid.uuid4())
            errors = []
            created_locks = []

            for device_id in device_ids:
                device = self.db.query(Device).filter(Device.id == device_id).first()
                if not device:
                    errors.append(f"Device {device_id} not found")
                    continue

                if not device.is_available_for_rent():
                    errors.append(f"Device {device.serial_number} is not available for rent")
                    continue

                from ..models.reservation import Reservation
                if Reservation.check_time_conflict(self.db, device_id, start_date, end_date, exclude_reservation_id):
                    errors.append(f"Device {device.serial_number} has a conflicting reservation in this time period")
                    continue

                existing_lock = self.get_active_lock(device_id)
                if existing_lock and existing_lock.user_id != user.id:
                    errors.append(f"Device {device.serial_number} is locked by another user")
                    continue

            if errors:
                self.db.rollback()
                return False, None, errors, None

            for device_id in device_ids:
                existing_lock = self.get_active_lock(device_id)
                if existing_lock and existing_lock.user_id == user.id:
                    existing_lock.expires_at = end_date
                    existing_lock.lock_token = lock_token
                    existing_lock.purpose = purpose
                    created_locks.append(existing_lock)
                else:
                    lock = DeviceLock(
                        device_id=device_id,
                        user_id=user.id,
                        lock_token=lock_token,
                        locked_at=now,
                        expires_at=end_date,
                        purpose=purpose,
                        is_active=1,
                    )
                    self.db.add(lock)
                    created_locks.append(lock)

            self.db.commit()
            for lock in created_locks:
                self.db.refresh(lock)
            return True, lock_token, [], created_locks
        except Exception as e:
            self.db.rollback()
            raise e

    def get_lock_by_token(self, lock_token: str) -> Optional[DeviceLock]:
        self._cleanup_expired_locks()
        now = datetime.now(timezone.utc)
        return (
            self.db.query(DeviceLock)
            .filter(
                DeviceLock.lock_token == lock_token,
                DeviceLock.is_active == 1,
                DeviceLock.expires_at > now,
            )
            .first()
        )

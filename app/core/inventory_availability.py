from typing import Optional, List, Set, Tuple, Dict
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, select
from datetime import datetime, timezone
from abc import ABC, abstractmethod
import enum

from ..models.inventory_commitment import InventoryCommitment, CommitmentStatus
from ..models.device import Device, DeviceStatus
from ..models.warehouse import Warehouse
from ..models.contract import Contract, ContractStatus, ContractItem
from ..models.reservation import Reservation, ReservationStatus
from ..models.device_lock import DeviceLock
from ..models.repair import RepairRecord
from ..models.device_transfer import DeviceTransfer, TransferStatus


class QueryMode(str, enum.Enum):
    BULK = "bulk"
    SINGLE = "single"


class TimeConflict:
    @staticmethod
    def overlaps(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
        return start_a < end_b and end_a > start_b

    @staticmethod
    def build_condition(start_col, end_col, start_date: datetime, end_date: datetime):
        return and_(start_col < end_date, end_col > start_date)


class WarehouseMatcher:
    def __init__(self, db: Session):
        self.db = db

    def get_warehouse_code(self, warehouse_id: int) -> Optional[str]:
        warehouse = self.db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
        return warehouse.code if warehouse else None

    def build_device_condition(self, warehouse_id: Optional[int]):
        if not warehouse_id:
            return None
        warehouse_code = self.get_warehouse_code(warehouse_id)
        return or_(
            Device.warehouse_id == warehouse_id,
            Device.location == warehouse_code,
            Device.location.like(f"{warehouse_code}%") if warehouse_code else False,
        )

    def build_transfer_condition(self, warehouse_id: Optional[int]):
        if not warehouse_id:
            return None
        warehouse_code_subquery = select(Warehouse.code).where(Warehouse.id == warehouse_id).scalar_subquery()
        return or_(
            DeviceTransfer.to_location == warehouse_code_subquery,
            DeviceTransfer.from_location == warehouse_code_subquery,
        )

    def build_commitment_condition(self, warehouse_id: Optional[int]):
        if not warehouse_id:
            return None
        return InventoryCommitment.warehouse_id == warehouse_id

    def is_device_in_warehouse(self, device: Device, warehouse_id: int, warehouse_code: str) -> bool:
        return (
            device.warehouse_id == warehouse_id
            or device.location == warehouse_code
            or (device.location and device.location.startswith(warehouse_code))
        )


class UnavailableSourceQuery(ABC):
    source_name: str = "unknown"
    error_message: str = "Device is unavailable"

    def __init__(self, db: Session, warehouse_matcher: WarehouseMatcher):
        self.db = db
        self.warehouse_matcher = warehouse_matcher

    @abstractmethod
    def get_unavailable_ids(
        self,
        category_id: int,
        start_date: datetime,
        end_date: datetime,
        warehouse_id: Optional[int] = None,
    ) -> Set[int]:
        pass

    @abstractmethod
    def check_device(
        self,
        device_id: int,
        warehouse_id: int,
        warehouse_code: str,
        start_date: datetime,
        end_date: datetime,
        exclude_user_id: Optional[int] = None,
        exclude_commitment_id: Optional[int] = None,
    ) -> Tuple[bool, Optional[str]]:
        pass


class ContractUnavailableQuery(UnavailableSourceQuery):
    source_name = "contracts"
    error_message = "Device has conflicting contract"

    def get_unavailable_ids(
        self,
        category_id: int,
        start_date: datetime,
        end_date: datetime,
        warehouse_id: Optional[int] = None,
    ) -> Set[int]:
        query = (
            self.db.query(Device.id)
            .join(ContractItem, ContractItem.device_id == Device.id)
            .join(Contract, Contract.id == ContractItem.contract_id)
            .filter(
                Device.category_id == category_id,
                Contract.status.in_([ContractStatus.ACTIVE, ContractStatus.RENEWED, ContractStatus.OVERDUE]),
                TimeConflict.build_condition(Contract.start_date, Contract.end_date, start_date, end_date),
            )
        )
        warehouse_condition = self.warehouse_matcher.build_device_condition(warehouse_id)
        if warehouse_condition is not None:
            query = query.filter(warehouse_condition)
        return {row[0] for row in query.all()}

    def check_device(
        self,
        device_id: int,
        warehouse_id: int,
        warehouse_code: str,
        start_date: datetime,
        end_date: datetime,
        exclude_user_id: Optional[int] = None,
        exclude_commitment_id: Optional[int] = None,
    ) -> Tuple[bool, Optional[str]]:
        conflicting = (
            self.db.query(ContractItem)
            .join(Contract, Contract.id == ContractItem.contract_id)
            .filter(
                ContractItem.device_id == device_id,
                Contract.status.in_([ContractStatus.ACTIVE, ContractStatus.RENEWED, ContractStatus.OVERDUE]),
                TimeConflict.build_condition(Contract.start_date, Contract.end_date, start_date, end_date),
            )
            .first()
        )
        if conflicting:
            return False, self.error_message
        return True, None


class ReservationUnavailableQuery(UnavailableSourceQuery):
    source_name = "reservations"
    error_message = "Device has conflicting reservation"

    def get_unavailable_ids(
        self,
        category_id: int,
        start_date: datetime,
        end_date: datetime,
        warehouse_id: Optional[int] = None,
    ) -> Set[int]:
        query = (
            self.db.query(Device.id)
            .join(Reservation, Reservation.device_id == Device.id)
            .filter(
                Device.category_id == category_id,
                Reservation.status.in_([ReservationStatus.PENDING, ReservationStatus.CONFIRMED]),
                TimeConflict.build_condition(Reservation.start_date, Reservation.end_date, start_date, end_date),
            )
        )
        warehouse_condition = self.warehouse_matcher.build_device_condition(warehouse_id)
        if warehouse_condition is not None:
            query = query.filter(warehouse_condition)
        return {row[0] for row in query.all()}

    def check_device(
        self,
        device_id: int,
        warehouse_id: int,
        warehouse_code: str,
        start_date: datetime,
        end_date: datetime,
        exclude_user_id: Optional[int] = None,
        exclude_commitment_id: Optional[int] = None,
    ) -> Tuple[bool, Optional[str]]:
        conflicting = (
            self.db.query(Reservation)
            .filter(
                Reservation.device_id == device_id,
                Reservation.status.in_([ReservationStatus.PENDING, ReservationStatus.CONFIRMED]),
                TimeConflict.build_condition(Reservation.start_date, Reservation.end_date, start_date, end_date),
            )
            .first()
        )
        if conflicting:
            return False, self.error_message
        return True, None


class DeviceLockUnavailableQuery(UnavailableSourceQuery):
    source_name = "locks"
    error_message = "Device is currently locked"

    def get_unavailable_ids(
        self,
        category_id: int,
        start_date: datetime,
        end_date: datetime,
        warehouse_id: Optional[int] = None,
    ) -> Set[int]:
        now = datetime.now(timezone.utc)
        query = (
            self.db.query(Device.id)
            .join(DeviceLock, DeviceLock.device_id == Device.id)
            .filter(
                Device.category_id == category_id,
                DeviceLock.is_active == 1,
                DeviceLock.expires_at > now,
            )
        )
        warehouse_condition = self.warehouse_matcher.build_device_condition(warehouse_id)
        if warehouse_condition is not None:
            query = query.filter(warehouse_condition)
        return {row[0] for row in query.all()}

    def check_device(
        self,
        device_id: int,
        warehouse_id: int,
        warehouse_code: str,
        start_date: datetime,
        end_date: datetime,
        exclude_user_id: Optional[int] = None,
        exclude_commitment_id: Optional[int] = None,
    ) -> Tuple[bool, Optional[str]]:
        now = datetime.now(timezone.utc)
        lock_query = self.db.query(DeviceLock).filter(
            DeviceLock.device_id == device_id,
            DeviceLock.is_active == 1,
            DeviceLock.expires_at > now,
        )
        if exclude_user_id:
            lock_query = lock_query.filter(DeviceLock.user_id != exclude_user_id)
        active_lock = lock_query.first()
        if active_lock:
            return False, self.error_message
        return True, None


class RepairUnavailableQuery(UnavailableSourceQuery):
    source_name = "repairs"
    error_message = "Device is in repair"

    def get_unavailable_ids(
        self,
        category_id: int,
        start_date: datetime,
        end_date: datetime,
        warehouse_id: Optional[int] = None,
    ) -> Set[int]:
        query = (
            self.db.query(Device.id)
            .join(RepairRecord, RepairRecord.device_id == Device.id)
            .filter(
                Device.category_id == category_id,
                RepairRecord.status.notin_(["completed", "cancelled", "unrepairable"]),
                or_(
                    RepairRecord.repair_complete_date.is_(None),
                    RepairRecord.repair_complete_date > end_date,
                ),
            )
        )
        warehouse_condition = self.warehouse_matcher.build_device_condition(warehouse_id)
        if warehouse_condition is not None:
            query = query.filter(warehouse_condition)
        return {row[0] for row in query.all()}

    def check_device(
        self,
        device_id: int,
        warehouse_id: int,
        warehouse_code: str,
        start_date: datetime,
        end_date: datetime,
        exclude_user_id: Optional[int] = None,
        exclude_commitment_id: Optional[int] = None,
    ) -> Tuple[bool, Optional[str]]:
        active_repair = (
            self.db.query(RepairRecord)
            .filter(
                RepairRecord.device_id == device_id,
                RepairRecord.status.notin_(["completed", "cancelled", "unrepairable"]),
                or_(
                    RepairRecord.repair_complete_date.is_(None),
                    RepairRecord.repair_complete_date > end_date,
                ),
            )
            .first()
        )
        if active_repair:
            return False, self.error_message
        return True, None


class DisinfectionUnavailableQuery(UnavailableSourceQuery):
    source_name = "disinfection"
    error_message = "Device is in disinfection"

    def get_unavailable_ids(
        self,
        category_id: int,
        start_date: datetime,
        end_date: datetime,
        warehouse_id: Optional[int] = None,
    ) -> Set[int]:
        query = self.db.query(Device.id).filter(
            Device.category_id == category_id,
            Device.status == DeviceStatus.DISINFECTION,
        )
        warehouse_condition = self.warehouse_matcher.build_device_condition(warehouse_id)
        if warehouse_condition is not None:
            query = query.filter(warehouse_condition)
        return {row[0] for row in query.all()}

    def check_device(
        self,
        device_id: int,
        warehouse_id: int,
        warehouse_code: str,
        start_date: datetime,
        end_date: datetime,
        exclude_user_id: Optional[int] = None,
        exclude_commitment_id: Optional[int] = None,
    ) -> Tuple[bool, Optional[str]]:
        device = self.db.query(Device).filter(Device.id == device_id).first()
        if device and device.status == DeviceStatus.DISINFECTION:
            return False, self.error_message
        return True, None


class TransferUnavailableQuery(UnavailableSourceQuery):
    source_name = "transfers"
    error_message = "Device is in transfer during this period"

    def get_unavailable_ids(
        self,
        category_id: int,
        start_date: datetime,
        end_date: datetime,
        warehouse_id: Optional[int] = None,
    ) -> Set[int]:
        query = (
            self.db.query(Device.id)
            .join(DeviceTransfer, DeviceTransfer.device_id == Device.id)
            .filter(
                Device.category_id == category_id,
                DeviceTransfer.status.in_([TransferStatus.PENDING, TransferStatus.CONFIRMED, TransferStatus.IN_TRANSIT]),
                or_(
                    DeviceTransfer.completed_at.is_(None),
                    DeviceTransfer.completed_at > start_date,
                ),
                or_(
                    DeviceTransfer.cancelled_at.is_(None),
                    DeviceTransfer.cancelled_at > start_date,
                ),
                or_(
                    and_(DeviceTransfer.created_at < end_date, DeviceTransfer.completed_at.is_(None)),
                    and_(DeviceTransfer.created_at < end_date, DeviceTransfer.completed_at > start_date),
                ),
            )
        )
        warehouse_condition = self.warehouse_matcher.build_transfer_condition(warehouse_id)
        if warehouse_condition is not None:
            query = query.filter(warehouse_condition)
        return {row[0] for row in query.all()}

    def check_device(
        self,
        device_id: int,
        warehouse_id: int,
        warehouse_code: str,
        start_date: datetime,
        end_date: datetime,
        exclude_user_id: Optional[int] = None,
        exclude_commitment_id: Optional[int] = None,
    ) -> Tuple[bool, Optional[str]]:
        conflicting = (
            self.db.query(DeviceTransfer)
            .filter(
                DeviceTransfer.device_id == device_id,
                DeviceTransfer.status.in_([TransferStatus.PENDING, TransferStatus.CONFIRMED, TransferStatus.IN_TRANSIT]),
                or_(
                    DeviceTransfer.from_location == warehouse_code,
                    DeviceTransfer.to_location == warehouse_code,
                ),
                or_(
                    DeviceTransfer.completed_at.is_(None),
                    DeviceTransfer.completed_at > start_date,
                ),
                or_(
                    DeviceTransfer.cancelled_at.is_(None),
                    DeviceTransfer.cancelled_at > start_date,
                ),
                or_(
                    and_(DeviceTransfer.created_at < end_date, DeviceTransfer.completed_at.is_(None)),
                    and_(DeviceTransfer.created_at < end_date, DeviceTransfer.completed_at > start_date),
                ),
            )
            .first()
        )
        if conflicting:
            return False, self.error_message
        return True, None


class CommitmentUnavailableQuery(UnavailableSourceQuery):
    source_name = "other_commitments"
    error_message = "Device has conflicting inventory commitment"

    def _cleanup_expired(self):
        now = datetime.now(timezone.utc)
        expired = (
            self.db.query(InventoryCommitment)
            .filter(
                InventoryCommitment.status == CommitmentStatus.PENDING,
                InventoryCommitment.expires_at.isnot(None),
                InventoryCommitment.expires_at < now,
            )
            .all()
        )
        for c in expired:
            c.status = CommitmentStatus.EXPIRED
        if expired:
            self.db.commit()

    def get_unavailable_ids(
        self,
        category_id: int,
        start_date: datetime,
        end_date: datetime,
        warehouse_id: Optional[int] = None,
    ) -> Set[int]:
        self._cleanup_expired()
        query = (
            self.db.query(InventoryCommitment.device_id)
            .filter(
                InventoryCommitment.category_id == category_id,
                InventoryCommitment.status.in_([CommitmentStatus.PENDING, CommitmentStatus.CONFIRMED]),
                TimeConflict.build_condition(
                    InventoryCommitment.start_date, InventoryCommitment.end_date, start_date, end_date
                ),
            )
        )
        warehouse_condition = self.warehouse_matcher.build_commitment_condition(warehouse_id)
        if warehouse_condition is not None:
            query = query.filter(warehouse_condition)
        return {row[0] for row in query.all()}

    def check_device(
        self,
        device_id: int,
        warehouse_id: int,
        warehouse_code: str,
        start_date: datetime,
        end_date: datetime,
        exclude_user_id: Optional[int] = None,
        exclude_commitment_id: Optional[int] = None,
    ) -> Tuple[bool, Optional[str]]:
        self._cleanup_expired()
        commitment_query = self.db.query(InventoryCommitment).filter(
            InventoryCommitment.device_id == device_id,
            InventoryCommitment.status.in_([CommitmentStatus.PENDING, CommitmentStatus.CONFIRMED]),
            TimeConflict.build_condition(
                InventoryCommitment.start_date, InventoryCommitment.end_date, start_date, end_date
            ),
        )
        if exclude_commitment_id:
            commitment_query = commitment_query.filter(InventoryCommitment.id != exclude_commitment_id)
        conflicting = commitment_query.first()
        if conflicting:
            return False, self.error_message
        return True, None


class AvailabilityChecker:
    def __init__(self, db: Session):
        self.db = db
        self.warehouse_matcher = WarehouseMatcher(db)
        self.sources: List[UnavailableSourceQuery] = [
            ContractUnavailableQuery(db, self.warehouse_matcher),
            ReservationUnavailableQuery(db, self.warehouse_matcher),
            DeviceLockUnavailableQuery(db, self.warehouse_matcher),
            RepairUnavailableQuery(db, self.warehouse_matcher),
            DisinfectionUnavailableQuery(db, self.warehouse_matcher),
            TransferUnavailableQuery(db, self.warehouse_matcher),
            CommitmentUnavailableQuery(db, self.warehouse_matcher),
        ]

    def _get_warehouse(self, warehouse_id: int) -> Optional[Warehouse]:
        return self.db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()

    def get_unavailable_device_ids(
        self,
        category_id: int,
        start_date: datetime,
        end_date: datetime,
        warehouse_id: Optional[int] = None,
    ) -> Tuple[Set[int], Dict[str, int], Set[int], Set[int], Set[int]]:
        source_breakdown: Dict[str, int] = {}
        all_unavailable: Set[int] = set()
        contract_ids: Set[int] = set()
        reservation_ids: Set[int] = set()
        commitment_ids: Set[int] = set()

        for source in self.sources:
            ids = source.get_unavailable_ids(category_id, start_date, end_date, warehouse_id)
            source_breakdown[source.source_name] = len(ids)
            all_unavailable |= ids
            if isinstance(source, ContractUnavailableQuery):
                contract_ids = ids
            elif isinstance(source, ReservationUnavailableQuery):
                reservation_ids = ids
            elif isinstance(source, CommitmentUnavailableQuery):
                commitment_ids = ids

        return all_unavailable, source_breakdown, contract_ids, reservation_ids, commitment_ids

    def check_device_available(
        self,
        device_id: int,
        warehouse_id: int,
        start_date: datetime,
        end_date: datetime,
        exclude_commitment_id: Optional[int] = None,
        exclude_user_id: Optional[int] = None,
    ) -> Tuple[bool, List[str]]:
        device = self.db.query(Device).filter(Device.id == device_id).with_for_update().first()
        if not device:
            return False, [f"Device {device_id} not found"]

        if device.status == DeviceStatus.RETIRED:
            return False, [f"Device {device_id} is retired"]

        warehouse = self._get_warehouse(warehouse_id)
        if not warehouse or not warehouse.is_active():
            return False, [f"Warehouse {warehouse_id} not found or inactive"]

        if not self.warehouse_matcher.is_device_in_warehouse(device, warehouse_id, warehouse.code):
            return False, [f"Device {device_id} is not in warehouse {warehouse.code}"]

        errors: List[str] = []
        for source in self.sources:
            is_available, error_msg = source.check_device(
                device_id=device_id,
                warehouse_id=warehouse_id,
                warehouse_code=warehouse.code,
                start_date=start_date,
                end_date=end_date,
                exclude_user_id=exclude_user_id,
                exclude_commitment_id=exclude_commitment_id,
            )
            if not is_available and error_msg:
                errors.append(error_msg)

        return len(errors) == 0, errors

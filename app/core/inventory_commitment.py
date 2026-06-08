from typing import Optional, List, Tuple, Dict
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, select, func
from datetime import datetime, timezone, timedelta
import uuid

from ..models.inventory_commitment import InventoryCommitment, CommitmentType, CommitmentStatus
from ..models.device import Device, DeviceStatus, DeviceCategory
from ..models.warehouse import Warehouse, WarehouseStatus
from ..models.contract import Contract, ContractStatus, ContractItem
from ..models.reservation import Reservation, ReservationStatus
from ..models.device_lock import DeviceLock
from ..models.repair import RepairRecord, RepairStatus
from ..models.disinfection import DisinfectionRecord
from ..models.device_transfer import DeviceTransfer, TransferStatus
from ..models.user import User
from ..config import settings


class InventoryCommitmentService:
    def __init__(self, db: Session):
        self.db = db

    def _cleanup_expired_commitments(self):
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

    def _get_unavailable_device_ids_from_contracts(
        self, category_id: int, start_date: datetime, end_date: datetime, warehouse_id: Optional[int] = None
    ) -> List[int]:
        query = (
            self.db.query(Device.id)
            .join(ContractItem, ContractItem.device_id == Device.id)
            .join(Contract, Contract.id == ContractItem.contract_id)
            .filter(
                Device.category_id == category_id,
                Contract.status.in_([ContractStatus.ACTIVE, ContractStatus.RENEWED, ContractStatus.OVERDUE]),
                or_(
                    and_(Contract.start_date < end_date, Contract.end_date > start_date),
                    and_(start_date < Contract.end_date, end_date > Contract.start_date),
                ),
            )
        )
        if warehouse_id:
            query = query.filter(
                or_(
                    Device.warehouse_id == warehouse_id,
                    Device.location == select(Warehouse.code).where(Warehouse.id == warehouse_id).scalar_subquery(),
                )
            )
        return [row[0] for row in query.all()]

    def _get_unavailable_device_ids_from_reservations(
        self, category_id: int, start_date: datetime, end_date: datetime, warehouse_id: Optional[int] = None
    ) -> List[int]:
        query = (
            self.db.query(Device.id)
            .join(Reservation, Reservation.device_id == Device.id)
            .filter(
                Device.category_id == category_id,
                Reservation.status.in_([ReservationStatus.PENDING, ReservationStatus.CONFIRMED]),
                or_(
                    and_(Reservation.start_date < end_date, Reservation.end_date > start_date),
                    and_(start_date < Reservation.end_date, end_date > Reservation.start_date),
                ),
            )
        )
        if warehouse_id:
            query = query.filter(
                or_(
                    Device.warehouse_id == warehouse_id,
                    Device.location == select(Warehouse.code).where(Warehouse.id == warehouse_id).scalar_subquery(),
                )
            )
        return [row[0] for row in query.all()]

    def _get_unavailable_device_ids_from_locks(
        self, category_id: int, warehouse_id: Optional[int] = None
    ) -> List[int]:
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
        if warehouse_id:
            query = query.filter(
                or_(
                    Device.warehouse_id == warehouse_id,
                    Device.location == select(Warehouse.code).where(Warehouse.id == warehouse_id).scalar_subquery(),
                )
            )
        return [row[0] for row in query.all()]

    def _get_unavailable_device_ids_from_repairs(
        self, category_id: int, end_date: datetime, warehouse_id: Optional[int] = None
    ) -> List[int]:
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
        if warehouse_id:
            query = query.filter(
                or_(
                    Device.warehouse_id == warehouse_id,
                    Device.location == select(Warehouse.code).where(Warehouse.id == warehouse_id).scalar_subquery(),
                )
            )
        return [row[0] for row in query.all()]

    def _get_unavailable_device_ids_from_disinfection(
        self, category_id: int, warehouse_id: Optional[int] = None
    ) -> List[int]:
        query = self.db.query(Device.id).filter(
            Device.category_id == category_id,
            Device.status == DeviceStatus.DISINFECTION,
        )
        if warehouse_id:
            query = query.filter(
                or_(
                    Device.warehouse_id == warehouse_id,
                    Device.location == select(Warehouse.code).where(Warehouse.id == warehouse_id).scalar_subquery(),
                )
            )
        return [row[0] for row in query.all()]

    def _get_unavailable_device_ids_from_transfers(
        self, category_id: int, start_date: datetime, end_date: datetime, warehouse_id: Optional[int] = None
    ) -> List[int]:
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
        if warehouse_id:
            warehouse_code_subquery = select(Warehouse.code).where(Warehouse.id == warehouse_id).scalar_subquery()
            query = query.filter(
                or_(
                    DeviceTransfer.to_location == warehouse_code_subquery,
                    DeviceTransfer.from_location == warehouse_code_subquery,
                )
            )
        return [row[0] for row in query.all()]

    def _get_unavailable_device_ids_from_commitments(
        self, category_id: int, start_date: datetime, end_date: datetime, warehouse_id: Optional[int] = None
    ) -> List[int]:
        self._cleanup_expired_commitments()
        query = (
            self.db.query(InventoryCommitment.device_id)
            .filter(
                InventoryCommitment.category_id == category_id,
                InventoryCommitment.status.in_([CommitmentStatus.PENDING, CommitmentStatus.CONFIRMED]),
                or_(
                    and_(InventoryCommitment.start_date < end_date, InventoryCommitment.end_date > start_date),
                    and_(start_date < InventoryCommitment.end_date, end_date > InventoryCommitment.start_date),
                ),
            )
        )
        if warehouse_id:
            query = query.filter(InventoryCommitment.warehouse_id == warehouse_id)
        return [row[0] for row in query.all()]

    def get_available_to_promise(
        self,
        category_id: int,
        start_date: datetime,
        end_date: datetime,
        warehouse_id: Optional[int] = None,
    ) -> Tuple[int, int, int, Dict]:
        category = self.db.query(DeviceCategory).filter(DeviceCategory.id == category_id).first()
        if not category:
            raise ValueError(f"Category {category_id} not found")

        warehouse = None
        if warehouse_id:
            warehouse = (
                self.db.query(Warehouse)
                .filter(Warehouse.id == warehouse_id, Warehouse.status == WarehouseStatus.ACTIVE)
                .first()
            )
            if not warehouse:
                raise ValueError(f"Warehouse {warehouse_id} not found or inactive")

        base_query = self.db.query(Device).filter(
            Device.category_id == category_id,
            Device.status.notin_([DeviceStatus.RETIRED]),
        )

        if warehouse_id:
            warehouse_code = warehouse.code if warehouse else None
            base_query = base_query.filter(
                or_(
                    Device.warehouse_id == warehouse_id,
                    Device.location == warehouse_code,
                )
            )

        total_in_warehouse = base_query.count()

        contract_unavailable = set(
            self._get_unavailable_device_ids_from_contracts(category_id, start_date, end_date, warehouse_id)
        )
        reservation_unavailable = set(
            self._get_unavailable_device_ids_from_reservations(category_id, start_date, end_date, warehouse_id)
        )
        lock_unavailable = set(self._get_unavailable_device_ids_from_locks(category_id, warehouse_id))
        repair_unavailable = set(self._get_unavailable_device_ids_from_repairs(category_id, end_date, warehouse_id))
        disinfection_unavailable = set(self._get_unavailable_device_ids_from_disinfection(category_id, warehouse_id))
        transfer_unavailable = set(
            self._get_unavailable_device_ids_from_transfers(category_id, start_date, end_date, warehouse_id)
        )
        commitment_unavailable = set(
            self._get_unavailable_device_ids_from_commitments(category_id, start_date, end_date, warehouse_id)
        )

        all_unavailable = (
            contract_unavailable
            | reservation_unavailable
            | lock_unavailable
            | repair_unavailable
            | disinfection_unavailable
            | transfer_unavailable
            | commitment_unavailable
        )

        committed_quantity = len(commitment_unavailable | contract_unavailable | reservation_unavailable)
        available = total_in_warehouse - len(all_unavailable)
        available = max(0, available)

        breakdown = {
            "total_in_warehouse": total_in_warehouse,
            "contracts": len(contract_unavailable),
            "reservations": len(reservation_unavailable),
            "locks": len(lock_unavailable),
            "repairs": len(repair_unavailable),
            "disinfection": len(disinfection_unavailable),
            "transfers": len(transfer_unavailable),
            "other_commitments": len(commitment_unavailable),
            "unavailable_unique": len(all_unavailable),
        }

        return available, total_in_warehouse, committed_quantity, breakdown

    def _check_device_available(
        self,
        device_id: int,
        warehouse_id: int,
        start_date: datetime,
        end_date: datetime,
        exclude_commitment_id: Optional[int] = None,
    ) -> Tuple[bool, List[str]]:
        device = self.db.query(Device).filter(Device.id == device_id).with_for_update().first()
        if not device:
            return False, [f"Device {device_id} not found"]

        if device.status == DeviceStatus.RETIRED:
            return False, [f"Device {device_id} is retired"]

        warehouse = self.db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
        if not warehouse or not warehouse.is_active():
            return False, [f"Warehouse {warehouse_id} not found or inactive"]

        device_warehouse_match = (
            device.warehouse_id == warehouse_id
            or device.location == warehouse.code
        )
        if not device_warehouse_match:
            return False, [f"Device {device_id} is not in warehouse {warehouse.code}"]

        errors = []

        now = datetime.now(timezone.utc)
        conflicting_contract = (
            self.db.query(ContractItem)
            .join(Contract, Contract.id == ContractItem.contract_id)
            .filter(
                ContractItem.device_id == device_id,
                Contract.status.in_([ContractStatus.ACTIVE, ContractStatus.RENEWED, ContractStatus.OVERDUE]),
                or_(
                    and_(Contract.start_date < end_date, Contract.end_date > start_date),
                    and_(start_date < Contract.end_date, end_date > Contract.start_date),
                ),
            )
            .first()
        )
        if conflicting_contract:
            errors.append(f"Device {device_id} has conflicting contract")

        conflicting_reservation = (
            self.db.query(Reservation)
            .filter(
                Reservation.device_id == device_id,
                Reservation.status.in_([ReservationStatus.PENDING, ReservationStatus.CONFIRMED]),
                or_(
                    and_(Reservation.start_date < end_date, Reservation.end_date > start_date),
                    and_(start_date < Reservation.end_date, end_date > Reservation.start_date),
                ),
            )
            .first()
        )
        if conflicting_reservation:
            errors.append(f"Device {device_id} has conflicting reservation")

        active_lock = (
            self.db.query(DeviceLock)
            .filter(
                DeviceLock.device_id == device_id,
                DeviceLock.is_active == 1,
                DeviceLock.expires_at > now,
            )
            .first()
        )
        if active_lock:
            errors.append(f"Device {device_id} is currently locked")

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
            errors.append(f"Device {device_id} is in repair")

        if device.status == DeviceStatus.DISINFECTION:
            errors.append(f"Device {device_id} is in disinfection")

        conflicting_transfer = (
            self.db.query(DeviceTransfer)
            .filter(
                DeviceTransfer.device_id == device_id,
                DeviceTransfer.status.in_([TransferStatus.PENDING, TransferStatus.CONFIRMED, TransferStatus.IN_TRANSIT]),
                or_(
                    DeviceTransfer.from_location == warehouse.code,
                    DeviceTransfer.to_location == warehouse.code,
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
            .with_for_update()
            .first()
        )
        if conflicting_transfer:
            errors.append(f"Device {device_id} is in transfer during this period")

        self._cleanup_expired_commitments()
        commitment_query = self.db.query(InventoryCommitment).filter(
            InventoryCommitment.device_id == device_id,
            InventoryCommitment.status.in_([CommitmentStatus.PENDING, CommitmentStatus.CONFIRMED]),
            or_(
                and_(InventoryCommitment.start_date < end_date, InventoryCommitment.end_date > start_date),
                and_(start_date < InventoryCommitment.end_date, end_date > InventoryCommitment.start_date),
            ),
        )
        if exclude_commitment_id:
            commitment_query = commitment_query.filter(InventoryCommitment.id != exclude_commitment_id)
        conflicting_commitment = commitment_query.with_for_update().first()
        if conflicting_commitment:
            errors.append(f"Device {device_id} has conflicting inventory commitment")

        return len(errors) == 0, errors

    def _check_duplicate_commitment(
        self,
        device_id: int,
        reference_id: Optional[int] = None,
        reference_type: Optional[str] = None,
        exclude_commitment_id: Optional[int] = None,
    ) -> Optional[InventoryCommitment]:
        if not reference_id or not reference_type:
            return None

        self._cleanup_expired_commitments()
        query = self.db.query(InventoryCommitment).filter(
            InventoryCommitment.device_id == device_id,
            InventoryCommitment.reference_id == reference_id,
            InventoryCommitment.reference_type == reference_type,
            InventoryCommitment.status.in_([CommitmentStatus.PENDING, CommitmentStatus.CONFIRMED]),
        )
        if exclude_commitment_id:
            query = query.filter(InventoryCommitment.id != exclude_commitment_id)
        return query.with_for_update().first()

    def create_commitment(
        self,
        device_id: int,
        warehouse_id: int,
        category_id: int,
        commitment_type: CommitmentType,
        start_date: datetime,
        end_date: datetime,
        user: User,
        reference_id: Optional[int] = None,
        reference_type: Optional[str] = None,
        expires_minutes: int = 30,
        notes: Optional[str] = None,
    ) -> Tuple[bool, Optional[InventoryCommitment], List[str]]:
        self.db.begin_nested()
        try:
            is_available, errors = self._check_device_available(
                device_id, warehouse_id, start_date, end_date
            )
            if not is_available:
                self.db.rollback()
                return False, None, errors

            duplicate = self._check_duplicate_commitment(device_id, reference_id, reference_type)
            if duplicate:
                self.db.rollback()
                return False, None, [
                    f"Device {device_id} already has an active commitment for reference {reference_type}:{reference_id}"
                ]

            commitment_token = str(uuid.uuid4())
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)

            commitment = InventoryCommitment(
                commitment_token=commitment_token,
                device_id=device_id,
                warehouse_id=warehouse_id,
                category_id=category_id,
                commitment_type=commitment_type,
                status=CommitmentStatus.PENDING,
                start_date=start_date,
                end_date=end_date,
                reference_id=reference_id,
                reference_type=reference_type,
                created_by_id=user.id,
                expires_at=expires_at,
                notes=notes,
            )
            self.db.add(commitment)
            self.db.commit()
            self.db.refresh(commitment)

            return True, commitment, []
        except Exception as e:
            self.db.rollback()
            raise e

    def create_commitments_bulk(
        self,
        device_ids: List[int],
        warehouse_id: int,
        category_id: int,
        commitment_type: CommitmentType,
        start_date: datetime,
        end_date: datetime,
        user: User,
        reference_id: Optional[int] = None,
        reference_type: Optional[str] = None,
        expires_minutes: int = 30,
        notes: Optional[str] = None,
    ) -> Tuple[bool, List[InventoryCommitment], List[str]]:
        self.db.begin_nested()
        try:
            unique_device_ids = list(set(device_ids))
            if len(unique_device_ids) != len(device_ids):
                self.db.rollback()
                return False, [], ["Duplicate device IDs in request"]

            all_errors = []
            for device_id in unique_device_ids:
                is_available, errors = self._check_device_available(
                    device_id, warehouse_id, start_date, end_date
                )
                if not is_available:
                    all_errors.extend(errors)

                duplicate = self._check_duplicate_commitment(device_id, reference_id, reference_type)
                if duplicate:
                    all_errors.append(
                        f"Device {device_id} already has an active commitment for reference {reference_type}:{reference_id}"
                    )

            if all_errors:
                self.db.rollback()
                return False, [], all_errors

            batch_token = str(uuid.uuid4())
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
            commitments = []

            for device_id in unique_device_ids:
                commitment = InventoryCommitment(
                    commitment_token=str(uuid.uuid4()),
                    batch_token=batch_token,
                    device_id=device_id,
                    warehouse_id=warehouse_id,
                    category_id=category_id,
                    commitment_type=commitment_type,
                    status=CommitmentStatus.PENDING,
                    start_date=start_date,
                    end_date=end_date,
                    reference_id=reference_id,
                    reference_type=reference_type,
                    created_by_id=user.id,
                    expires_at=expires_at,
                    notes=notes,
                )
                self.db.add(commitment)
                commitments.append(commitment)

            self.db.commit()
            for c in commitments:
                self.db.refresh(c)

            return True, commitments, []
        except Exception as e:
            self.db.rollback()
            raise e

    def confirm_commitment(
        self, token: str, user: User, is_batch: bool = False
    ) -> Tuple[bool, Optional[List[InventoryCommitment]], List[str]]:
        self.db.begin_nested()
        try:
            self._cleanup_expired_commitments()
            now = datetime.now(timezone.utc)

            query = self.db.query(InventoryCommitment).filter(
                InventoryCommitment.status == CommitmentStatus.PENDING,
            )

            if is_batch:
                query = query.filter(InventoryCommitment.batch_token == token)
            else:
                query = query.filter(InventoryCommitment.commitment_token == token)

            commitments = query.with_for_update().all()

            if not commitments:
                self.db.rollback()
                return False, None, ["Commitment not found or already processed"]

            all_errors = []
            for commitment in commitments:
                if commitment.is_expired():
                    all_errors.append(f"Commitment for device {commitment.device_id} has expired")
                    continue

                if commitment.created_by_id != user.id and user.role not in ["admin", "staff"]:
                    all_errors.append(
                        f"Commitment for device {commitment.device_id} does not belong to you"
                    )
                    continue

                is_available, errors = self._check_device_available(
                    commitment.device_id,
                    commitment.warehouse_id,
                    commitment.start_date,
                    commitment.end_date,
                    exclude_commitment_id=commitment.id,
                )
                if not is_available:
                    all_errors.extend(errors)
                    continue

            if all_errors:
                self.db.rollback()
                return False, None, all_errors

            for commitment in commitments:
                commitment.status = CommitmentStatus.CONFIRMED
                commitment.confirmed_at = now

            self.db.commit()

            return True, commitments, []
        except Exception as e:
            self.db.rollback()
            raise e

    def release_commitment(
        self, token: str, user: User, is_batch: bool = False
    ) -> Tuple[bool, List[str]]:
        self.db.begin_nested()
        try:
            now = datetime.now(timezone.utc)

            query = self.db.query(InventoryCommitment).filter(
                InventoryCommitment.status.in_([CommitmentStatus.PENDING, CommitmentStatus.CONFIRMED]),
            )

            if is_batch:
                query = query.filter(InventoryCommitment.batch_token == token)
            else:
                query = query.filter(InventoryCommitment.commitment_token == token)

            commitments = query.with_for_update().all()

            if not commitments:
                return True, []

            all_errors = []
            for commitment in commitments:
                if commitment.created_by_id != user.id and user.role not in ["admin", "staff"]:
                    all_errors.append(
                        f"Commitment for device {commitment.device_id} does not belong to you"
                    )
                    continue
                commitment.status = CommitmentStatus.CANCELLED
                commitment.cancelled_at = now

            if all_errors:
                self.db.rollback()
                return False, all_errors

            self.db.commit()
            return True, []
        except Exception as e:
            self.db.rollback()
            raise e

    def complete_commitment(
        self, token: str, user: User, is_batch: bool = False
    ) -> Tuple[bool, List[str]]:
        self.db.begin_nested()
        try:
            now = datetime.now(timezone.utc)

            query = self.db.query(InventoryCommitment).filter(
                InventoryCommitment.status == CommitmentStatus.CONFIRMED,
            )

            if is_batch:
                query = query.filter(InventoryCommitment.batch_token == token)
            else:
                query = query.filter(InventoryCommitment.commitment_token == token)

            commitments = query.with_for_update().all()

            if not commitments:
                return False, ["No confirmed commitments found"]

            for commitment in commitments:
                commitment.status = CommitmentStatus.COMPLETED

            self.db.commit()
            return True, []
        except Exception as e:
            self.db.rollback()
            raise e

    def get_commitments_by_batch(self, batch_token: str) -> List[InventoryCommitment]:
        self._cleanup_expired_commitments()
        return (
            self.db.query(InventoryCommitment)
            .filter(InventoryCommitment.batch_token == batch_token)
            .order_by(InventoryCommitment.created_at.desc())
            .all()
        )

    def get_commitment(self, commitment_token: str) -> Optional[InventoryCommitment]:
        self._cleanup_expired_commitments()
        return (
            self.db.query(InventoryCommitment)
            .filter(InventoryCommitment.commitment_token == commitment_token)
            .first()
        )

    def list_commitments(
        self,
        device_id: Optional[int] = None,
        warehouse_id: Optional[int] = None,
        category_id: Optional[int] = None,
        status: Optional[CommitmentStatus] = None,
        commitment_type: Optional[CommitmentType] = None,
    ) -> List[InventoryCommitment]:
        self._cleanup_expired_commitments()
        query = self.db.query(InventoryCommitment)

        if device_id:
            query = query.filter(InventoryCommitment.device_id == device_id)
        if warehouse_id:
            query = query.filter(InventoryCommitment.warehouse_id == warehouse_id)
        if category_id:
            query = query.filter(InventoryCommitment.category_id == category_id)
        if status:
            query = query.filter(InventoryCommitment.status == status)
        if commitment_type:
            query = query.filter(InventoryCommitment.commitment_type == commitment_type)

        return query.order_by(InventoryCommitment.created_at.desc()).all()

    def get_commitments_by_reference(
        self,
        reference_id: int,
        reference_type: str,
        status: Optional[CommitmentStatus] = None,
    ) -> List[InventoryCommitment]:
        self._cleanup_expired_commitments()
        query = self.db.query(InventoryCommitment).filter(
            InventoryCommitment.reference_id == reference_id,
            InventoryCommitment.reference_type == reference_type,
        )
        if status:
            query = query.filter(InventoryCommitment.status == status)
        return query.order_by(InventoryCommitment.created_at.desc()).all()

    def release_commitments_by_reference(
        self,
        reference_id: int,
        reference_type: str,
        user: User,
    ) -> Tuple[bool, List[str]]:
        self.db.begin_nested()
        try:
            now = datetime.now(timezone.utc)
            self._cleanup_expired_commitments()

            commitments = (
                self.db.query(InventoryCommitment)
                .filter(
                    InventoryCommitment.reference_id == reference_id,
                    InventoryCommitment.reference_type == reference_type,
                    InventoryCommitment.status.in_([CommitmentStatus.PENDING, CommitmentStatus.CONFIRMED]),
                )
                .with_for_update()
                .all()
            )

            if not commitments:
                return True, []

            all_errors = []
            for commitment in commitments:
                if commitment.created_by_id != user.id and user.role not in ["admin", "staff"]:
                    all_errors.append(
                        f"Commitment for device {commitment.device_id} does not belong to you"
                    )
                    continue
                commitment.status = CommitmentStatus.CANCELLED
                commitment.cancelled_at = now

            if all_errors:
                self.db.rollback()
                return False, all_errors

            self.db.commit()
            return True, []
        except Exception as e:
            self.db.rollback()
            raise e

    def confirm_commitments_by_reference(
        self,
        reference_id: int,
        reference_type: str,
        user: User,
    ) -> Tuple[bool, Optional[List[InventoryCommitment]], List[str]]:
        self.db.begin_nested()
        try:
            now = datetime.now(timezone.utc)
            self._cleanup_expired_commitments()

            commitments = (
                self.db.query(InventoryCommitment)
                .filter(
                    InventoryCommitment.reference_id == reference_id,
                    InventoryCommitment.reference_type == reference_type,
                    InventoryCommitment.status == CommitmentStatus.PENDING,
                )
                .with_for_update()
                .all()
            )

            if not commitments:
                return False, None, ["No pending commitments found for this reference"]

            all_errors = []
            for commitment in commitments:
                if commitment.is_expired():
                    all_errors.append(f"Commitment for device {commitment.device_id} has expired")
                    continue

                if commitment.created_by_id != user.id and user.role not in ["admin", "staff"]:
                    all_errors.append(
                        f"Commitment for device {commitment.device_id} does not belong to you"
                    )
                    continue

                is_available, errors = self._check_device_available(
                    commitment.device_id,
                    commitment.warehouse_id,
                    commitment.start_date,
                    commitment.end_date,
                    exclude_commitment_id=commitment.id,
                )
                if not is_available:
                    all_errors.extend(errors)
                    continue

            if all_errors:
                self.db.rollback()
                return False, None, all_errors

            for commitment in commitments:
                commitment.status = CommitmentStatus.CONFIRMED
                commitment.confirmed_at = now

            self.db.commit()
            return True, commitments, []
        except Exception as e:
            self.db.rollback()
            raise e

    def complete_commitments_by_reference(
        self,
        reference_id: int,
        reference_type: str,
        user: User,
    ) -> Tuple[bool, List[str]]:
        self.db.begin_nested()
        try:
            self._cleanup_expired_commitments()

            commitments = (
                self.db.query(InventoryCommitment)
                .filter(
                    InventoryCommitment.reference_id == reference_id,
                    InventoryCommitment.reference_type == reference_type,
                    InventoryCommitment.status == CommitmentStatus.CONFIRMED,
                )
                .with_for_update()
                .all()
            )

            if not commitments:
                return True, []

            for commitment in commitments:
                commitment.status = CommitmentStatus.COMPLETED

            self.db.commit()
            return True, []
        except Exception as e:
            self.db.rollback()
            raise e

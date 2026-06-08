from typing import Optional, List, Tuple, Dict
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
import uuid

from ..models.inventory_commitment import InventoryCommitment, CommitmentType, CommitmentStatus
from ..models.device import Device, DeviceStatus, DeviceCategory
from ..models.warehouse import Warehouse, WarehouseStatus
from ..models.user import User
from .inventory_availability import AvailabilityChecker


class InventoryCommitmentService:
    def __init__(self, db: Session):
        self.db = db
        self.availability_checker = AvailabilityChecker(db)

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
                (Device.warehouse_id == warehouse_id) | (Device.location == warehouse_code)
            )

        total_in_warehouse = base_query.count()

        all_unavailable, source_breakdown, contract_ids, reservation_ids, commitment_ids = (
            self.availability_checker.get_unavailable_device_ids(
                category_id=category_id,
                start_date=start_date,
                end_date=end_date,
                warehouse_id=warehouse_id,
            )
        )

        committed_quantity = len(commitment_ids | contract_ids | reservation_ids)
        available = total_in_warehouse - len(all_unavailable)
        available = max(0, available)

        breakdown = {
            "total_in_warehouse": total_in_warehouse,
            "contracts": source_breakdown.get("contracts", 0),
            "reservations": source_breakdown.get("reservations", 0),
            "locks": source_breakdown.get("locks", 0),
            "repairs": source_breakdown.get("repairs", 0),
            "disinfection": source_breakdown.get("disinfection", 0),
            "transfers": source_breakdown.get("transfers", 0),
            "other_commitments": source_breakdown.get("other_commitments", 0),
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
        exclude_user_id: Optional[int] = None,
    ) -> Tuple[bool, List[str]]:
        return self.availability_checker.check_device_available(
            device_id=device_id,
            warehouse_id=warehouse_id,
            start_date=start_date,
            end_date=end_date,
            exclude_commitment_id=exclude_commitment_id,
            exclude_user_id=exclude_user_id,
        )

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
                device_id, warehouse_id, start_date, end_date, exclude_user_id=user.id
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
                    device_id, warehouse_id, start_date, end_date, exclude_user_id=user.id
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
                    exclude_user_id=user.id,
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
                    exclude_user_id=user.id,
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

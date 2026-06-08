from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from ..models.contract import Contract, ContractStatus
from ..models.audit import AuditLog, AuditAction
from ..models.user import User
from .audit import AuditLogger
from ..config import settings


@dataclass
class OverdueRefreshResult:
    contract_id: int
    contract_number: str
    old_status: str
    new_status: str
    old_overdue_fee: float
    new_overdue_fee: float
    overdue_days: int
    status_changed: bool
    fee_updated: bool
    audit_logged: bool


class OverdueRefreshService:
    def __init__(self, db: Session):
        self.db = db

    def _has_recent_overdue_audit(self, contract_id: int, old_status: str, new_status: str) -> bool:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
        existing_audit = (
            self.db.query(AuditLog)
            .filter(
                AuditLog.resource_type == "contract",
                AuditLog.resource_id == str(contract_id),
                AuditLog.action == AuditAction.OVERDUE.value,
                AuditLog.created_at >= cutoff_time,
                or_(
                    and_(
                        AuditLog.old_values.isnot(None),
                        AuditLog.old_values.op("->>")("status") == old_status,
                    ),
                    and_(
                        AuditLog.new_values.isnot(None),
                        AuditLog.new_values.op("->>")("status") == new_status,
                    ),
                ),
            )
            .first()
        )
        return existing_audit is not None

    def _get_contracts_to_refresh(self) -> List[Contract]:
        excluded_statuses = [
            ContractStatus.RETURNED,
            ContractStatus.CANCELLED,
            ContractStatus.EXPIRED,
            ContractStatus.DRAFT,
            ContractStatus.PENDING,
        ]
        return (
            self.db.query(Contract)
            .filter(Contract.status.notin_(excluded_statuses))
            .all()
        )

    def refresh_all(self, user: Optional[User] = None, ip_address: Optional[str] = None) -> Tuple[List[OverdueRefreshResult], Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        contracts = self._get_contracts_to_refresh()
        results: List[OverdueRefreshResult] = []
        audit_logger = AuditLogger(self.db)

        for contract in contracts:
            old_status = contract.status.value if hasattr(contract.status, "value") else str(contract.status)
            old_overdue_fee = contract.overdue_fee or 0.0

            estimated_overdue_days = contract.calculate_estimated_overdue_days(now)
            estimated_overdue_fee = contract.calculate_estimated_overdue_fee(now)

            new_status = old_status
            status_changed = False
            fee_updated = False
            audit_logged = False

            if estimated_overdue_days > 0 and contract.status in [ContractStatus.ACTIVE, ContractStatus.RENEWED]:
                new_status = ContractStatus.OVERDUE.value
                contract.status = ContractStatus.OVERDUE
                status_changed = True

            if abs(estimated_overdue_fee - old_overdue_fee) > 0.01:
                contract.overdue_fee = estimated_overdue_fee
                contract.final_amount = max(
                    0, contract.calculate_total_amount() + estimated_overdue_fee - contract.discount_amount
                )
                fee_updated = True

            if status_changed:
                if not self._has_recent_overdue_audit(contract.id, old_status, new_status):
                    audit_logger.log(
                        action=AuditAction.OVERDUE,
                        resource_type="contract",
                        resource_id=str(contract.id),
                        user=user,
                        old_values={"status": old_status, "overdue_fee": old_overdue_fee},
                        new_values={"status": new_status, "overdue_fee": estimated_overdue_fee},
                        description=(
                            f"Contract {contract.contract_number} marked as overdue. "
                            f"Overdue days: {estimated_overdue_days}, Estimated fee: {estimated_overdue_fee}"
                        ),
                        ip_address=ip_address,
                    )
                    audit_logged = True

            results.append(
                OverdueRefreshResult(
                    contract_id=contract.id,
                    contract_number=contract.contract_number,
                    old_status=old_status,
                    new_status=new_status,
                    old_overdue_fee=old_overdue_fee,
                    new_overdue_fee=estimated_overdue_fee,
                    overdue_days=estimated_overdue_days,
                    status_changed=status_changed,
                    fee_updated=fee_updated,
                    audit_logged=audit_logged,
                )
            )

        self.db.commit()

        summary = {
            "total_contracts_processed": len(contracts),
            "total_status_changed": sum(1 for r in results if r.status_changed),
            "total_fee_updated": sum(1 for r in results if r.fee_updated),
            "total_audit_logged": sum(1 for r in results if r.audit_logged),
            "total_estimated_fee": sum(r.new_overdue_fee for r in results),
            "refresh_timestamp": now,
        }

        return results, summary

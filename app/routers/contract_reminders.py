from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional, List
from math import ceil
from datetime import datetime, timezone, timedelta

from ..database import get_db
from ..models.user import User, UserRole
from ..models.contract import Contract, ContractStatus
from ..models.contract_reminder import ContractReminder, ReminderStatus
from ..schemas import (
    ContractExpiryResponse,
    ContractReminderCreate,
    ContractReminderUpdateStatus,
    ContractReminderResponse,
    APIResponse,
    PaginatedResponse,
)
from ..core import (
    get_current_active_user,
    require_role,
    AuditLogger,
    AuditAction,
)

router = APIRouter(prefix="/api/contract-reminders", tags=["Contract Reminders"])


def calculate_days_until_expiry(end_date: datetime, now: datetime) -> int:
    end_date_utc = end_date
    if end_date_utc.tzinfo is None:
        end_date_utc = end_date_utc.replace(tzinfo=timezone.utc)
    delta = end_date_utc.date() - now.date()
    return delta.days


def get_contract_expiry_data(contract: Contract, now: datetime) -> dict:
    days_until = calculate_days_until_expiry(contract.end_date, now)
    is_overdue = days_until < 0
    overdue_days = abs(days_until) if is_overdue else 0

    devices = []
    for item in contract.items:
        device = item.device
        devices.append({
            "id": device.id,
            "serial_number": device.serial_number,
            "name": device.name,
            "model": device.model,
            "category": device.category.name,
            "quantity": item.quantity,
        })

    return {
        "contract_id": contract.id,
        "contract_number": contract.contract_number,
        "customer": {
            "id": contract.customer.id,
            "full_name": contract.customer.full_name,
            "phone": contract.customer.phone,
            "email": contract.customer.email,
        },
        "end_date": contract.end_date,
        "devices": devices,
        "days_until_expiry": days_until,
        "is_overdue": is_overdue,
        "overdue_days": overdue_days,
        "status": contract.status.value if hasattr(contract.status, "value") else str(contract.status),
    }


def get_reminder_response_data(reminder: ContractReminder) -> dict:
    return {
        "id": reminder.id,
        "contract_id": reminder.contract_id,
        "contract_number": reminder.contract.contract_number,
        "customer_name": reminder.contract.customer.full_name,
        "customer_phone": reminder.contract.customer.phone,
        "customer_email": reminder.contract.customer.email,
        "end_date": reminder.contract.end_date,
        "generated_at": reminder.generated_at,
        "handled_by_id": reminder.handled_by_id,
        "handled_by_name": reminder.handled_by.full_name if reminder.handled_by else None,
        "status": reminder.status,
        "notes": reminder.notes,
        "follow_up_date": reminder.follow_up_date,
        "handled_at": reminder.handled_at,
        "created_at": reminder.created_at,
        "updated_at": reminder.updated_at,
    }


@router.get("/expiring", response_model=PaginatedResponse[ContractExpiryResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_expiring_contracts(
    request: Request,
    days: int = 30,
    page: int = 1,
    per_page: int = 20,
    include_overdue: bool = True,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    if days < 0:
        raise HTTPException(status_code=400, detail="Days must be non-negative")

    now = datetime.now(timezone.utc)
    future_date = now + timedelta(days=days)

    query = db.query(Contract).filter(
        Contract.status.in_([ContractStatus.ACTIVE, ContractStatus.RENEWED, ContractStatus.OVERDUE]),
    )

    if include_overdue:
        query = query.filter(Contract.end_date <= future_date)
    else:
        query = query.filter(
            Contract.end_date >= now,
            Contract.end_date <= future_date,
        )

    query = query.order_by(Contract.end_date.asc())

    total = query.count()
    contracts = query.offset((page - 1) * per_page).limit(per_page).all()

    response_data = [get_contract_expiry_data(c, now) for c in contracts]

    return PaginatedResponse(
        data=response_data,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
        message=f"Found {total} contracts expiring within {days} days",
    )


@router.get("", response_model=PaginatedResponse[ContractReminderResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def list_reminders(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    status: Optional[ReminderStatus] = None,
    contract_id: Optional[int] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = db.query(ContractReminder)

    if status:
        query = query.filter(ContractReminder.status == status)
    if contract_id:
        query = query.filter(ContractReminder.contract_id == contract_id)

    total = query.count()
    reminders = query.order_by(ContractReminder.generated_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    response_data = [get_reminder_response_data(r) for r in reminders]

    return PaginatedResponse(
        data=response_data,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/{reminder_id}", response_model=APIResponse[ContractReminderResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_reminder(
    request: Request,
    reminder_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    reminder = db.query(ContractReminder).filter(ContractReminder.id == reminder_id).first()
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")

    return APIResponse(data=get_reminder_response_data(reminder))


@router.post("", response_model=APIResponse[ContractReminderResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def create_reminder(
    request: Request,
    reminder_data: ContractReminderCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    contract = db.query(Contract).filter(Contract.id == reminder_data.contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    new_reminder = ContractReminder(
        contract_id=reminder_data.contract_id,
        notes=reminder_data.notes,
        status=ReminderStatus.PENDING,
    )
    db.add(new_reminder)
    db.commit()
    db.refresh(new_reminder)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.CREATE,
        resource_type="contract_reminder",
        resource_id=str(new_reminder.id),
        user=current_user,
        new_values={
            "contract_id": new_reminder.contract_id,
            "contract_number": contract.contract_number,
        },
        description=f"Reminder created for contract {contract.contract_number}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Reminder created successfully",
        data=get_reminder_response_data(new_reminder),
    )


@router.post("/batch-create", response_model=APIResponse[List[ContractReminderResponse]])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def batch_create_reminders(
    request: Request,
    days: int = 30,
    include_overdue: bool = True,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    if days < 0:
        raise HTTPException(status_code=400, detail="Days must be non-negative")

    now = datetime.now(timezone.utc)
    future_date = now + timedelta(days=days)

    query = db.query(Contract).filter(
        Contract.status.in_([ContractStatus.ACTIVE, ContractStatus.RENEWED, ContractStatus.OVERDUE]),
    )

    if include_overdue:
        query = query.filter(Contract.end_date <= future_date)
    else:
        query = query.filter(
            Contract.end_date >= now,
            Contract.end_date <= future_date,
        )

    contracts = query.all()

    existing_reminder_contracts = db.query(ContractReminder.contract_id).filter(
        ContractReminder.status == ReminderStatus.PENDING
    ).distinct().all()
    existing_ids = {r[0] for r in existing_reminder_contracts}

    created_reminders = []
    for contract in contracts:
        if contract.id in existing_ids:
            continue

        reminder = ContractReminder(
            contract_id=contract.id,
            status=ReminderStatus.PENDING,
        )
        db.add(reminder)
        created_reminders.append(reminder)

    db.commit()

    for reminder in created_reminders:
        db.refresh(reminder)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.CREATE,
        resource_type="contract_reminder",
        resource_id="batch",
        user=current_user,
        new_values={
            "count": len(created_reminders),
            "days": days,
        },
        description=f"Batch created {len(created_reminders)} reminders for contracts expiring within {days} days",
        ip_address=request.client.host if request.client else None,
    )

    response_data = [get_reminder_response_data(r) for r in created_reminders]

    return APIResponse(
        message=f"Created {len(created_reminders)} new reminders successfully",
        data=response_data,
    )


@router.patch("/{reminder_id}/status", response_model=APIResponse[ContractReminderResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def update_reminder_status(
    request: Request,
    reminder_id: int,
    status_data: ContractReminderUpdateStatus,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    reminder = db.query(ContractReminder).filter(ContractReminder.id == reminder_id).first()
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")

    old_status = reminder.status.value if hasattr(reminder.status, "value") else str(reminder.status)
    new_status = status_data.status.value if hasattr(status_data.status, "value") else str(status_data.status)

    reminder.status = status_data.status
    reminder.handled_by_id = current_user.id
    reminder.handled_at = datetime.now(timezone.utc)

    if status_data.notes:
        reminder.notes = status_data.notes
    if status_data.follow_up_date:
        reminder.follow_up_date = status_data.follow_up_date

    db.commit()
    db.refresh(reminder)

    audit_logger = AuditLogger(db)
    audit_logger.log_status_change(
        resource_type="contract_reminder",
        resource_id=str(reminder_id),
        user=current_user,
        old_status=old_status,
        new_status=new_status,
        description=status_data.notes or f"Reminder status changed from {old_status} to {new_status}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Reminder status updated successfully",
        data=get_reminder_response_data(reminder),
    )


@router.delete("/{reminder_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN])
async def delete_reminder(
    request: Request,
    reminder_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    reminder = db.query(ContractReminder).filter(ContractReminder.id == reminder_id).first()
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")

    old_values = {
        "contract_id": reminder.contract_id,
        "contract_number": reminder.contract.contract_number,
        "status": reminder.status.value if hasattr(reminder.status, "value") else str(reminder.status),
    }

    db.delete(reminder)
    db.commit()

    audit_logger = AuditLogger(db)
    audit_logger.log_delete(
        resource_type="contract_reminder",
        resource_id=str(reminder_id),
        user=current_user,
        old_values=old_values,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Reminder deleted successfully")

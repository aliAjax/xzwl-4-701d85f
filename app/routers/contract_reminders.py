from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import Optional
from math import ceil
from datetime import datetime, timezone, timedelta

from ..database import get_db
from ..models.user import User, UserRole
from ..models.contract import Contract, ContractStatus, ContractItem
from ..models.contract_reminder import ContractReminder, ReminderStatus
from ..models.device import DeviceCategory
from ..schemas import (
    ContractExpiryResponse,
    ContractReminderCreate,
    ContractReminderUpdateStatus,
    ContractReminderResponse,
    APIResponse,
    PaginatedResponse,
)
from ..core import get_current_active_user, require_role, AuditLogger

router = APIRouter(prefix="/api/contract-reminders", tags=["Contract Reminders"])


@router.get("/expiring", response_model=APIResponse[list[ContractExpiryResponse]])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_expiring_contracts(
    days_ahead: int = 30,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    end_date_cutoff = now + timedelta(days=days_ahead)

    contracts = db.query(Contract).filter(
        Contract.status.in_([ContractStatus.ACTIVE, ContractStatus.OVERDUE]),
        Contract.end_date <= end_date_cutoff,
    ).order_by(Contract.end_date.asc()).all()

    response = []
    for contract in contracts:
        days_until_expiry = (contract.end_date - now).days
        is_overdue = days_until_expiry < 0
        overdue_days = abs(days_until_expiry) if is_overdue else 0

        contract_items = db.query(ContractItem).filter(
            ContractItem.contract_id == contract.id
        ).all()

        devices = []
        for item in contract_items:
            category = db.query(DeviceCategory).filter(
                DeviceCategory.id == item.device.category_id
            ).first() if item.device else None

            devices.append({
                "id": item.device_id,
                "serial_number": item.device.serial_number if item.device else None,
                "name": item.device.name if item.device else None,
                "model": item.device.model if item.device else None,
                "category": category.name if category else None,
                "quantity": item.quantity,
            })

        status_display = "overdue" if is_overdue else (
            "expiring_soon" if days_until_expiry <= 7 else "active"
        )

        response.append({
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
            "days_until_expiry": days_until_expiry,
            "is_overdue": is_overdue,
            "overdue_days": overdue_days,
            "status": status_display,
        })

    return APIResponse(data=response)


@router.get("", response_model=PaginatedResponse[ContractReminderResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def list_contract_reminders(
    page: int = 1,
    per_page: int = 20,
    status: Optional[ReminderStatus] = None,
    contract_id: Optional[int] = None,
    handled_by: Optional[int] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = db.query(ContractReminder)

    if status:
        query = query.filter(ContractReminder.status == status)
    if contract_id:
        query = query.filter(ContractReminder.contract_id == contract_id)
    if handled_by:
        query = query.filter(ContractReminder.handled_by_id == handled_by)

    total = query.count()
    reminders = query.order_by(ContractReminder.generated_at.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    user_ids = list({r.handled_by_id for r in reminders if r.handled_by_id})
    users = {}
    if user_ids:
        user_list = db.query(User.id, User.full_name).filter(User.id.in_(user_ids)).all()
        users = {u[0]: u[1] for u in user_list}

    response_data = []
    for reminder in reminders:
        reminder_dict = {c.name: getattr(reminder, c.name) for c in reminder.__table__.columns}
        reminder_dict["contract_number"] = reminder.contract.contract_number
        reminder_dict["customer_name"] = reminder.contract.customer.full_name
        reminder_dict["customer_phone"] = reminder.contract.customer.phone
        reminder_dict["customer_email"] = reminder.contract.customer.email
        reminder_dict["end_date"] = reminder.contract.end_date
        reminder_dict["handled_by_name"] = users.get(reminder.handled_by_id)
        response_data.append(reminder_dict)

    return PaginatedResponse(
        data=response_data,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/{reminder_id}", response_model=APIResponse[ContractReminderResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_contract_reminder(
    reminder_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    reminder = db.query(ContractReminder).filter(
        ContractReminder.id == reminder_id
    ).first()
    if not reminder:
        raise HTTPException(status_code=404, detail="合同提醒不存在")

    handler = db.query(User).filter(User.id == reminder.handled_by_id).first() if reminder.handled_by_id else None

    response_data = {c.name: getattr(reminder, c.name) for c in reminder.__table__.columns}
    response_data["contract_number"] = reminder.contract.contract_number
    response_data["customer_name"] = reminder.contract.customer.full_name
    response_data["customer_phone"] = reminder.contract.customer.phone
    response_data["customer_email"] = reminder.contract.customer.email
    response_data["end_date"] = reminder.contract.end_date
    response_data["handled_by_name"] = handler.full_name if handler else None

    return APIResponse(data=response_data)


@router.post("", response_model=APIResponse[ContractReminderResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def create_contract_reminder(
    request: Request,
    reminder_data: ContractReminderCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    contract = db.query(Contract).filter(Contract.id == reminder_data.contract_id).first()
    if not contract:
        raise HTTPException(status_code=400, detail="合同不存在")

    existing_reminder = db.query(ContractReminder).filter(
        ContractReminder.contract_id == reminder_data.contract_id,
        ContractReminder.status == ReminderStatus.PENDING,
    ).first()
    if existing_reminder:
        raise HTTPException(status_code=400, detail="该合同已有待处理的提醒")

    new_reminder = ContractReminder(
        contract_id=reminder_data.contract_id,
        notes=reminder_data.notes,
        generated_at=datetime.now(timezone.utc),
    )
    db.add(new_reminder)
    db.commit()
    db.refresh(new_reminder)

    handler = db.query(User).filter(User.id == new_reminder.handled_by_id).first() if new_reminder.handled_by_id else None

    response_data = {c.name: getattr(new_reminder, c.name) for c in new_reminder.__table__.columns}
    response_data["contract_number"] = new_reminder.contract.contract_number
    response_data["customer_name"] = new_reminder.contract.customer.full_name
    response_data["customer_phone"] = new_reminder.contract.customer.phone
    response_data["customer_email"] = new_reminder.contract.customer.email
    response_data["end_date"] = new_reminder.contract.end_date
    response_data["handled_by_name"] = handler.full_name if handler else None

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action="create",
        resource_type="contract_reminder",
        resource_id=str(new_reminder.id),
        user=current_user,
        new_values={
            "contract_id": new_reminder.contract_id,
            "contract_number": new_reminder.contract.contract_number,
            "notes": new_reminder.notes,
        },
        description=f"创建合同到期提醒: {new_reminder.contract.contract_number}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="合同提醒创建成功", data=response_data)


@router.put("/{reminder_id}/status", response_model=APIResponse[ContractReminderResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def update_reminder_status(
    request: Request,
    reminder_id: int,
    status_data: ContractReminderUpdateStatus,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    reminder = db.query(ContractReminder).filter(
        ContractReminder.id == reminder_id
    ).first()
    if not reminder:
        raise HTTPException(status_code=404, detail="合同提醒不存在")

    old_values = {
        "status": reminder.status.value,
        "notes": reminder.notes,
        "follow_up_date": reminder.follow_up_date,
    }

    reminder.status = status_data.status
    reminder.notes = status_data.notes
    reminder.follow_up_date = status_data.follow_up_date
    reminder.handled_by_id = current_user.id
    reminder.handled_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(reminder)

    handler = db.query(User).filter(User.id == reminder.handled_by_id).first() if reminder.handled_by_id else None

    response_data = {c.name: getattr(reminder, c.name) for c in reminder.__table__.columns}
    response_data["contract_number"] = reminder.contract.contract_number
    response_data["customer_name"] = reminder.contract.customer.full_name
    response_data["customer_phone"] = reminder.contract.customer.phone
    response_data["customer_email"] = reminder.contract.customer.email
    response_data["end_date"] = reminder.contract.end_date
    response_data["handled_by_name"] = handler.full_name if handler else None

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action="update_status",
        resource_type="contract_reminder",
        resource_id=str(reminder.id),
        user=current_user,
        old_values=old_values,
        new_values={
            "status": status_data.status.value,
            "notes": status_data.notes,
            "follow_up_date": status_data.follow_up_date.isoformat() if status_data.follow_up_date else None,
            "handled_by": current_user.full_name,
        },
        description=f"更新合同提醒状态: {reminder.contract.contract_number} -> {status_data.status.value}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="合同提醒状态更新成功", data=response_data)


@router.delete("/{reminder_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN])
async def delete_contract_reminder(
    request: Request,
    reminder_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    reminder = db.query(ContractReminder).filter(
        ContractReminder.id == reminder_id
    ).first()
    if not reminder:
        raise HTTPException(status_code=404, detail="合同提醒不存在")

    old_values = {
        "contract_id": reminder.contract_id,
        "contract_number": reminder.contract.contract_number,
        "status": reminder.status.value,
    }

    db.delete(reminder)
    db.commit()

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action="delete",
        resource_type="contract_reminder",
        resource_id=str(reminder_id),
        user=current_user,
        old_values=old_values,
        description=f"删除合同提醒: {reminder.contract.contract_number}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="合同提醒删除成功")

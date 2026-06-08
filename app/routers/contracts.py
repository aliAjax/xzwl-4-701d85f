from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import Optional
from math import ceil
from datetime import datetime, timezone, timedelta, date
import uuid

from ..database import get_db
from ..models.user import User, UserRole
from ..models.device import Device, DeviceStatus
from ..models.contract import Contract, ContractItem, ContractStatus
from ..models.deposit import Deposit, DepositStatus
from ..schemas import (
    ContractCreate,
    ContractUpdate,
    ContractResponse,
    ContractStatusUpdate,
    RenewContractRequest,
    ReturnContractRequest,
    APIResponse,
    PaginatedResponse,
)
from ..routers.customer_credit_notes import get_customer_risk_summary_sync
from ..schemas.customer_credit_note import CustomerRiskSummary
from ..core import (
    get_current_active_user,
    require_role,
    AuditLogger,
    DeviceLockService,
    InventoryCommitmentService,
    AuditAction,
)
from ..models.inventory_commitment import CommitmentType
from ..models.warehouse import Warehouse

router = APIRouter(prefix="/api/contracts", tags=["Contracts"])


def generate_contract_number() -> str:
    now = datetime.now(timezone.utc)
    return f"MR{now.strftime('%Y%m%d')}{uuid.uuid4().hex[:8].upper()}"


def get_contract_dict(contract: Contract) -> dict:
    contract_dict = {c.name: getattr(contract, c.name) for c in contract.__table__.columns}
    contract_dict["rental_days"] = contract.calculate_rental_days()
    contract_dict["overdue_days"] = contract.calculate_overdue_days()
    contract_dict["items"] = contract.items
    return contract_dict


@router.get("", response_model=PaginatedResponse[ContractResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def list_contracts(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    status: Optional[ContractStatus] = None,
    customer_id: Optional[int] = None,
    start_date_from: Optional[date] = None,
    start_date_to: Optional[date] = None,
    end_date_from: Optional[date] = None,
    end_date_to: Optional[date] = None,
    contract_number: Optional[str] = None,
    is_overdue: Optional[bool] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = db.query(Contract)
    if current_user.role == UserRole.CUSTOMER:
        query = query.filter(Contract.customer_id == current_user.id)
    elif customer_id:
        query = query.filter(Contract.customer_id == customer_id)
    if status:
        query = query.filter(Contract.status == status)
    if start_date_from:
        start_dt = datetime.combine(start_date_from, datetime.min.time(), tzinfo=timezone.utc)
        query = query.filter(Contract.start_date >= start_dt)
    if start_date_to:
        end_dt = datetime.combine(start_date_to, datetime.max.time(), tzinfo=timezone.utc)
        query = query.filter(Contract.start_date <= end_dt)
    if end_date_from:
        start_dt = datetime.combine(end_date_from, datetime.min.time(), tzinfo=timezone.utc)
        query = query.filter(Contract.end_date >= start_dt)
    if end_date_to:
        end_dt = datetime.combine(end_date_to, datetime.max.time(), tzinfo=timezone.utc)
        query = query.filter(Contract.end_date <= end_dt)
    if contract_number:
        query = query.filter(Contract.contract_number.ilike(f"%{contract_number}%"))
    if is_overdue is not None:
        now = datetime.now(timezone.utc)
        overdue_condition = or_(
            Contract.status == ContractStatus.OVERDUE,
            and_(
                Contract.status.in_([ContractStatus.ACTIVE, ContractStatus.RENEWED]),
                Contract.end_date < now,
                Contract.actual_return_date.is_(None),
            ),
        )
        if is_overdue:
            query = query.filter(overdue_condition)
        else:
            query = query.filter(~overdue_condition)

    total = query.count()
    contracts = query.order_by(Contract.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    response_data = [get_contract_dict(c) for c in contracts]

    return PaginatedResponse(
        data=response_data,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/{contract_id}", response_model=APIResponse[ContractResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def get_contract(
    request: Request,
    contract_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    if current_user.role == UserRole.CUSTOMER and contract.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    return APIResponse(data=get_contract_dict(contract))


@router.post("", response_model=APIResponse[ContractResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def create_contract(
    request: Request,
    contract_data: ContractCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    if current_user.role == UserRole.CUSTOMER and contract_data.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Cannot create contract for another customer")

    customer = db.query(User).filter(User.id == contract_data.customer_id).first()
    if not customer:
        raise HTTPException(status_code=400, detail="Customer not found")

    if contract_data.start_date >= contract_data.end_date:
        raise HTTPException(status_code=400, detail="End date must be after start date")

    device_ids = [item.device_id for item in contract_data.items]

    lock_service = DeviceLockService(db)
    if contract_data.lock_token:
        valid, errors = lock_service.validate_lock(device_ids, contract_data.lock_token, current_user)
        if not valid:
            raise HTTPException(status_code=400, detail="; ".join(errors))
    else:
        locked, lock_token, errors = lock_service.lock_devices(device_ids, current_user, purpose="rental")
        if not locked:
            raise HTTPException(status_code=400, detail="; ".join(errors))
        contract_data.lock_token = lock_token

    devices = []
    for item in contract_data.items:
        device = db.query(Device).filter(Device.id == item.device_id).first()
        if not device:
            if contract_data.lock_token:
                lock_service.unlock_by_token(contract_data.lock_token, current_user)
            raise HTTPException(status_code=400, detail=f"Device {item.device_id} not found")
        if not device.is_available_for_rent():
            if contract_data.lock_token:
                lock_service.unlock_by_token(contract_data.lock_token, current_user)
            raise HTTPException(
                status_code=400,
                detail=f"Device {device.serial_number} is not available for rent",
            )
        devices.append(device)

    device_groups = {}
    for device in devices:
        warehouse_id = device.warehouse_id
        if warehouse_id is None:
            if device.location:
                warehouse = (
                    db.query(Warehouse)
                    .filter(
                        Warehouse.status == "active",
                        or_(
                            Warehouse.code == device.location,
                            device.location.like(Warehouse.code + "%"),
                        ),
                    )
                    .first()
                )
                if warehouse:
                    warehouse_id = warehouse.id
        if warehouse_id is None:
            if contract_data.lock_token:
                lock_service.unlock_by_token(contract_data.lock_token, current_user)
            raise HTTPException(
                status_code=400,
                detail=f"Device {device.serial_number} is not assigned to a warehouse",
            )
        key = (warehouse_id, device.category_id)
        if key not in device_groups:
            device_groups[key] = []
        device_groups[key].append(device.id)

    db.begin_nested()
    try:
        new_contract = Contract(
            contract_number=generate_contract_number(),
            customer_id=contract_data.customer_id,
            created_by_id=current_user.id,
            start_date=contract_data.start_date,
            end_date=contract_data.end_date,
            discount_amount=contract_data.discount_amount,
            notes=contract_data.notes,
            status=ContractStatus.DRAFT,
        )
        db.add(new_contract)
        db.flush()

        total_amount = 0.0
        deposit_amount = 0.0

        for item_data in contract_data.items:
            device = db.query(Device).filter(Device.id == item_data.device_id).first()
            daily_rate = item_data.daily_rate if item_data.daily_rate > 0 else device.category.daily_rental_rate
            subtotal = daily_rate * new_contract.calculate_rental_days() * item_data.quantity

            contract_item = ContractItem(
                contract_id=new_contract.id,
                device_id=item_data.device_id,
                daily_rate=daily_rate,
                quantity=item_data.quantity,
                subtotal=subtotal,
                notes=item_data.notes,
            )
            db.add(contract_item)
            total_amount += subtotal
            deposit_amount += device.category.deposit_amount * item_data.quantity

        new_contract.total_amount = total_amount
        new_contract.deposit_amount = deposit_amount
        new_contract.final_amount = max(0, total_amount - contract_data.discount_amount)

        db.flush()

        commitment_service = InventoryCommitmentService(db)
        first_batch_token = None
        for (warehouse_id, category_id), group_device_ids in device_groups.items():
            success, commitments, errors = commitment_service.create_commitments_bulk(
                device_ids=group_device_ids,
                warehouse_id=warehouse_id,
                category_id=category_id,
                commitment_type=CommitmentType.CONTRACT,
                start_date=contract_data.start_date,
                end_date=contract_data.end_date,
                user=current_user,
                reference_id=new_contract.id,
                reference_type="contract",
                expires_minutes=30,
                notes=f"Contract commitment for contract {new_contract.contract_number}",
            )
            if not success:
                db.rollback()
                if contract_data.lock_token:
                    lock_service.unlock_by_token(contract_data.lock_token, current_user)
                raise HTTPException(
                    status_code=400,
                    detail="Inventory commitment conflict: " + "; ".join(errors),
                )
            if first_batch_token is None and commitments:
                first_batch_token = commitments[0].batch_token

        new_contract.commitment_batch_token = first_batch_token

        db.commit()
        db.refresh(new_contract)

        if contract_data.lock_token:
            lock_service.unlock_by_token(contract_data.lock_token, current_user)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        if contract_data.lock_token:
            lock_service.unlock_by_token(contract_data.lock_token, current_user)
        raise HTTPException(status_code=500, detail=f"Failed to create contract: {str(e)}")

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.RENT,
        resource_type="contract",
        resource_id=str(new_contract.id),
        user=current_user,
        new_values={
            "contract_number": new_contract.contract_number,
            "customer_id": new_contract.customer_id,
            "total_amount": new_contract.total_amount,
            "deposit_amount": new_contract.deposit_amount,
            "commitment_batch_token": new_contract.commitment_batch_token,
        },
        description=f"Contract {new_contract.contract_number} created with inventory commitments",
        ip_address=request.client.host if request.client else None,
    )

    message = "Contract created successfully"
    data = get_contract_dict(new_contract)

    if current_user.role in [UserRole.ADMIN, UserRole.STAFF]:
        risk_summary = get_customer_risk_summary_sync(db, contract_data.customer_id)
        if risk_summary:
            message = f"Contract created successfully. Customer has {risk_summary.total_active_notes} active risk note(s)."
            data["customer_risk_summary"] = risk_summary.model_dump()

    return APIResponse(message=message, data=data)


@router.patch("/{contract_id}/status", response_model=APIResponse[ContractResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def update_contract_status(
    request: Request,
    contract_id: int,
    status_data: ContractStatusUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    old_status = contract.status.value if hasattr(contract.status, "value") else str(contract.status)
    new_status = status_data.status.value if hasattr(status_data.status, "value") else str(status_data.status)

    valid_transitions = {
        ContractStatus.DRAFT: [ContractStatus.PENDING, ContractStatus.CANCELLED],
        ContractStatus.PENDING: [ContractStatus.ACTIVE, ContractStatus.CANCELLED],
        ContractStatus.ACTIVE: [ContractStatus.RETURNED, ContractStatus.OVERDUE, ContractStatus.EXPIRED, ContractStatus.RENEWED],
        ContractStatus.RENEWED: [ContractStatus.RETURNED, ContractStatus.OVERDUE, ContractStatus.EXPIRED, ContractStatus.RENEWED],
        ContractStatus.OVERDUE: [ContractStatus.RETURNED, ContractStatus.RENEWED],
    }

    if contract.status not in valid_transitions or status_data.status not in valid_transitions.get(contract.status, []):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status transition from {old_status} to {new_status}",
        )

    if status_data.status == ContractStatus.ACTIVE:
        commitment_service = InventoryCommitmentService(db)
        success, confirmed_commitments, errors = commitment_service.confirm_commitments_by_reference(
            reference_id=contract.id,
            reference_type="contract",
            user=current_user,
        )
        if not success:
            raise HTTPException(
                status_code=400,
                detail="Failed to confirm inventory commitments: " + "; ".join(errors),
            )

        for item in contract.items:
            device = db.query(Device).filter(Device.id == item.device_id).first()
            if not device.is_available_for_rent():
                raise HTTPException(
                    status_code=400,
                    detail=f"Device {device.serial_number} is not available",
                )
            device.status = DeviceStatus.IN_USE
            device.current_owner = contract.customer.full_name

    if status_data.status == ContractStatus.CANCELLED:
        commitment_service = InventoryCommitmentService(db)
        success, errors = commitment_service.release_commitments_by_reference(
            reference_id=contract.id,
            reference_type="contract",
            user=current_user,
        )
        if not success:
            raise HTTPException(
                status_code=400,
                detail="Failed to release inventory commitments: " + "; ".join(errors),
            )

    contract.status = status_data.status
    db.commit()
    db.refresh(contract)

    audit_logger = AuditLogger(db)
    audit_logger.log_status_change(
        resource_type="contract",
        resource_id=str(contract_id),
        user=current_user,
        old_status=old_status,
        new_status=new_status,
        description=status_data.notes or f"Contract status changed from {old_status} to {new_status}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Contract status updated successfully", data=get_contract_dict(contract))


@router.post("/{contract_id}/renew", response_model=APIResponse[ContractResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def renew_contract(
    request: Request,
    contract_id: int,
    renew_data: RenewContractRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    if not contract.can_renew():
        raise HTTPException(status_code=400, detail="Contract cannot be renewed")

    if renew_data.new_end_date <= contract.end_date:
        raise HTTPException(status_code=400, detail="New end date must be after current end date")

    old_end_date = contract.end_date
    contract.end_date = renew_data.new_end_date
    contract.status = ContractStatus.RENEWED
    contract.notes = (contract.notes or "") + f"\n\nRenewed on {datetime.now(timezone.utc)}. {renew_data.notes or ''}"

    contract.total_amount = contract.calculate_total_amount()
    contract.overdue_fee = contract.calculate_overdue_fee()
    contract.final_amount = max(0, contract.total_amount + contract.overdue_fee - contract.discount_amount)

    db.commit()
    db.refresh(contract)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.RENEW,
        resource_type="contract",
        resource_id=str(contract_id),
        user=current_user,
        old_values={"end_date": old_end_date},
        new_values={"end_date": renew_data.new_end_date},
        description=f"Contract renewed until {renew_data.new_end_date}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Contract renewed successfully", data=get_contract_dict(contract))


@router.post("/{contract_id}/return", response_model=APIResponse[ContractResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def return_contract(
    request: Request,
    contract_id: int,
    return_data: ReturnContractRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    if not contract.can_return():
        raise HTTPException(status_code=400, detail="Contract cannot be returned")

    return_date = return_data.return_date or datetime.now(timezone.utc)
    contract.actual_return_date = return_date
    contract.overdue_fee = contract.calculate_overdue_fee()
    contract.final_amount = max(0, contract.calculate_total_amount() + contract.overdue_fee - contract.discount_amount)

    for item in contract.items:
        device = db.query(Device).filter(Device.id == item.device_id).first()
        if device.category.disinfection_required:
            device.status = DeviceStatus.DISINFECTION
        else:
            device.status = DeviceStatus.AVAILABLE
        device.current_owner = None

        if return_data.device_condition_notes:
            contract.notes = (contract.notes or "") + f"\n\nReturn condition notes: {return_data.device_condition_notes}"

    contract.status = ContractStatus.RETURNED
    if return_data.notes:
        contract.notes = (contract.notes or "") + f"\n\nReturn notes: {return_data.notes}"

    commitment_service = InventoryCommitmentService(db)
    success, errors = commitment_service.complete_commitments_by_reference(
        reference_id=contract.id,
        reference_type="contract",
        user=current_user,
    )
    if not success:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Failed to complete inventory commitments: " + "; ".join(errors),
        )

    db.commit()
    db.refresh(contract)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.RETURN,
        resource_type="contract",
        resource_id=str(contract_id),
        user=current_user,
        new_values={
            "actual_return_date": return_date,
            "overdue_fee": contract.overdue_fee,
            "overdue_days": contract.calculate_overdue_days(),
        },
        description=f"Contract returned. Overdue days: {contract.calculate_overdue_days()}, Overdue fee: {contract.overdue_fee}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Contract returned successfully", data=get_contract_dict(contract))


@router.get("/{contract_id}/calculate-overdue", response_model=APIResponse)
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def calculate_overdue_fees(
    contract_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    now = datetime.now(timezone.utc)
    simulated_return_date = max(now, contract.end_date)
    temp_return_date = contract.actual_return_date
    contract.actual_return_date = simulated_return_date

    overdue_days = contract.calculate_overdue_days()
    overdue_fee = contract.calculate_overdue_fee()

    contract.actual_return_date = temp_return_date

    return APIResponse(data={
        "contract_id": contract_id,
        "contract_number": contract.contract_number,
        "end_date": contract.end_date,
        "today": now,
        "overdue_days": overdue_days,
        "overdue_fee": overdue_fee,
        "grace_period_days": 1,
        "daily_rate": 50.0,
        "devices_count": len(contract.items),
    })


@router.delete("/{contract_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN])
async def delete_contract(
    request: Request,
    contract_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    if contract.status in [ContractStatus.ACTIVE, ContractStatus.OVERDUE, ContractStatus.RETURNED]:
        raise HTTPException(status_code=400, detail="Cannot delete active or completed contracts")

    commitment_service = InventoryCommitmentService(db)
    success, errors = commitment_service.release_commitments_by_reference(
        reference_id=contract.id,
        reference_type="contract",
        user=current_user,
    )
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Failed to release inventory commitments: " + "; ".join(errors),
        )

    old_values = {
        "contract_number": contract.contract_number,
        "customer_id": contract.customer_id,
        "status": contract.status.value if hasattr(contract.status, "value") else str(contract.status),
    }

    db.delete(contract)
    db.commit()

    audit_logger = AuditLogger(db)
    audit_logger.log_delete(
        resource_type="contract",
        resource_id=str(contract_id),
        user=current_user,
        old_values=old_values,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Contract deleted successfully")

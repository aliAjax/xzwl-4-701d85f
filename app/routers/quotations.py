from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from typing import Optional
from math import ceil
from datetime import datetime, timezone, timedelta
import uuid

from ..database import get_db
from ..models.user import User, UserRole
from ..models.device import DeviceCategory, Device, DeviceStatus
from ..models.quotation import Quotation, QuotationItem, QuotationStatus
from ..models.contract import Contract, ContractItem, ContractStatus
from ..models.inventory_commitment import InventoryCommitment, CommitmentStatus
from ..schemas import (
    QuotationCreate,
    QuotationUpdate,
    QuotationResponse,
    QuotationVoidRequest,
    QuotationConvertRequest,
    ContractResponse,
    APIResponse,
    PaginatedResponse,
)
from ..routers.customer_credit_notes import get_customer_risk_summary_sync
from ..core import (
    get_current_active_user,
    require_role,
    AuditLogger,
    DeviceLockService,
    AuditAction,
)

router = APIRouter(prefix="/api/quotations", tags=["Quotations"])


def generate_quotation_number() -> str:
    now = datetime.now(timezone.utc)
    return f"Q{now.strftime('%Y%m%d')}{uuid.uuid4().hex[:8].upper()}"


def get_quotation_dict(quotation: Quotation) -> dict:
    quotation_dict = {c.name: getattr(quotation, c.name) for c in quotation.__table__.columns}
    quotation_dict["customer_name"] = quotation.customer.full_name if quotation.customer else None
    quotation_dict["created_by_name"] = quotation.created_by.full_name if quotation.created_by else None
    quotation_dict["voided_by_name"] = quotation.voided_by.full_name if quotation.voided_by else None
    quotation_dict["items"] = quotation.items
    return quotation_dict


@router.get("", response_model=PaginatedResponse[QuotationResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def list_quotations(
    page: int = 1,
    per_page: int = 20,
    status: Optional[QuotationStatus] = None,
    customer_id: Optional[int] = None,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = db.query(Quotation)

    if customer_id:
        query = query.filter(Quotation.customer_id == customer_id)
    if status:
        query = query.filter(Quotation.status == status)
    if search:
        query = query.filter(
            (Quotation.quotation_number.ilike(f"%{search}%")) |
            (Quotation.notes.ilike(f"%{search}%"))
        )

    total = query.count()
    quotations = query.order_by(Quotation.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    response_data = [get_quotation_dict(q) for q in quotations]

    return PaginatedResponse(
        data=response_data,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/{quotation_id}", response_model=APIResponse[QuotationResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_quotation(
    quotation_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    quotation = db.query(Quotation).filter(Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(status_code=404, detail="Quotation not found")

    return APIResponse(data=get_quotation_dict(quotation))


@router.post("", response_model=APIResponse[QuotationResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def create_quotation(
    request: Request,
    quotation_data: QuotationCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    customer = db.query(User).filter(User.id == quotation_data.customer_id).first()
    if not customer:
        raise HTTPException(status_code=400, detail="Customer not found")

    if not quotation_data.items:
        raise HTTPException(status_code=400, detail="At least one item is required")

    category_ids = [item.category_id for item in quotation_data.items]
    categories = db.query(DeviceCategory).filter(DeviceCategory.id.in_(category_ids)).all()
    category_map = {cat.id: cat for cat in categories}

    for item_data in quotation_data.items:
        if item_data.category_id not in category_map:
            raise HTTPException(
                status_code=400,
                detail=f"Device category {item_data.category_id} not found",
            )

    db.begin_nested()
    try:
        new_quotation = Quotation(
            quotation_number=generate_quotation_number(),
            customer_id=quotation_data.customer_id,
            created_by_id=current_user.id,
            rental_days=quotation_data.rental_days,
            discount_rate=quotation_data.discount_rate,
            notes=quotation_data.notes,
            status=QuotationStatus.DRAFT,
        )
        db.add(new_quotation)
        db.flush()

        for item_data in quotation_data.items:
            category = category_map[item_data.category_id]
            quotation_item = QuotationItem(
                quotation_id=new_quotation.id,
                category_id=category.id,
                category_name=category.name,
                daily_rate=category.daily_rental_rate,
                deposit_amount=category.deposit_amount,
                quantity=item_data.quantity,
            )
            quotation_item.calculate_subtotals(quotation_data.rental_days)
            db.add(quotation_item)
            new_quotation.items.append(quotation_item)

        new_quotation.calculate_totals()

        db.commit()
        db.refresh(new_quotation)

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create quotation: {str(e)}")

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.QUOTE_CREATE,
        resource_type="quotation",
        resource_id=str(new_quotation.id),
        user=current_user,
        new_values={
            "quotation_number": new_quotation.quotation_number,
            "customer_id": new_quotation.customer_id,
            "customer_name": customer.full_name,
            "rental_days": new_quotation.rental_days,
            "discount_rate": new_quotation.discount_rate,
            "total_rental_fee": new_quotation.total_rental_fee,
            "total_deposit": new_quotation.total_deposit,
            "discount_amount": new_quotation.discount_amount,
            "estimated_total": new_quotation.estimated_total,
            "items": [
                {
                    "category_id": item.category_id,
                    "category_name": item.category_name,
                    "daily_rate": item.daily_rate,
                    "deposit_amount": item.deposit_amount,
                    "quantity": item.quantity,
                }
                for item in new_quotation.items
            ],
        },
        description=f"Quotation {new_quotation.quotation_number} created for customer {customer.full_name}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Quotation created successfully",
        data=get_quotation_dict(new_quotation),
    )


@router.put("/{quotation_id}", response_model=APIResponse[QuotationResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def update_quotation(
    request: Request,
    quotation_id: int,
    quotation_data: QuotationUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    quotation = db.query(Quotation).filter(Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(status_code=404, detail="Quotation not found")

    if quotation.status == QuotationStatus.VOIDED:
        raise HTTPException(status_code=400, detail="Cannot update a voided quotation")

    old_values = {
        "rental_days": quotation.rental_days,
        "discount_rate": quotation.discount_rate,
        "notes": quotation.notes,
        "total_rental_fee": quotation.total_rental_fee,
        "total_deposit": quotation.total_deposit,
        "discount_amount": quotation.discount_amount,
        "estimated_total": quotation.estimated_total,
    }

    db.begin_nested()
    try:
        if quotation_data.rental_days is not None:
            quotation.rental_days = quotation_data.rental_days
        if quotation_data.discount_rate is not None:
            quotation.discount_rate = quotation_data.discount_rate
        if quotation_data.notes is not None:
            quotation.notes = quotation_data.notes

        if quotation_data.items is not None:
            if not quotation_data.items:
                raise HTTPException(status_code=400, detail="At least one item is required")

            category_ids = [item.category_id for item in quotation_data.items]
            categories = db.query(DeviceCategory).filter(DeviceCategory.id.in_(category_ids)).all()
            category_map = {cat.id: cat for cat in categories}

            for item_data in quotation_data.items:
                if item_data.category_id not in category_map:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Device category {item_data.category_id} not found",
                    )

            for item in quotation.items:
                db.delete(item)
            quotation.items = []

            for item_data in quotation_data.items:
                category = category_map[item_data.category_id]
                quotation_item = QuotationItem(
                    quotation_id=quotation.id,
                    category_id=category.id,
                    category_name=category.name,
                    daily_rate=category.daily_rental_rate,
                    deposit_amount=category.deposit_amount,
                    quantity=item_data.quantity,
                )
                quotation_item.calculate_subtotals(quotation.rental_days)
                db.add(quotation_item)
                quotation.items.append(quotation_item)

        for item in quotation.items:
            item.calculate_subtotals(quotation.rental_days)

        quotation.calculate_totals()

        db.commit()
        db.refresh(quotation)

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update quotation: {str(e)}")

    new_values = {
        "rental_days": quotation.rental_days,
        "discount_rate": quotation.discount_rate,
        "notes": quotation.notes,
        "total_rental_fee": quotation.total_rental_fee,
        "total_deposit": quotation.total_deposit,
        "discount_amount": quotation.discount_amount,
        "estimated_total": quotation.estimated_total,
    }

    audit_logger = AuditLogger(db)
    audit_logger.log_update(
        resource_type="quotation",
        resource_id=str(quotation_id),
        user=current_user,
        old_values=old_values,
        new_values=new_values,
        description=f"Quotation {quotation.quotation_number} updated",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Quotation updated successfully",
        data=get_quotation_dict(quotation),
    )


@router.post("/{quotation_id}/void", response_model=APIResponse[QuotationResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def void_quotation(
    request: Request,
    quotation_id: int,
    void_data: QuotationVoidRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    quotation = db.query(Quotation).filter(Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(status_code=404, detail="Quotation not found")

    if not quotation.can_void():
        raise HTTPException(
            status_code=400,
            detail=f"Cannot void quotation with status {quotation.status.value}",
        )

    old_status = quotation.status.value if hasattr(quotation.status, "value") else str(quotation.status)

    success = quotation.void(current_user)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to void quotation")

    if void_data.reason:
        quotation.notes = (quotation.notes or "") + f"\n\nVoid reason: {void_data.reason}"

    db.commit()
    db.refresh(quotation)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.QUOTE_VOID,
        resource_type="quotation",
        resource_id=str(quotation_id),
        user=current_user,
        old_values={"status": old_status},
        new_values={"status": QuotationStatus.VOIDED.value},
        description=f"Quotation {quotation.quotation_number} voided. Reason: {void_data.reason or 'Not specified'}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Quotation voided successfully",
        data=get_quotation_dict(quotation),
    )


@router.delete("/{quotation_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN])
async def delete_quotation(
    request: Request,
    quotation_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    quotation = db.query(Quotation).filter(Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(status_code=404, detail="Quotation not found")

    old_values = {
        "quotation_number": quotation.quotation_number,
        "customer_id": quotation.customer_id,
        "status": quotation.status.value if hasattr(quotation.status, "value") else str(quotation.status),
    }

    db.delete(quotation)
    db.commit()

    audit_logger = AuditLogger(db)
    audit_logger.log_delete(
        resource_type="quotation",
        resource_id=str(quotation_id),
        user=current_user,
        old_values=old_values,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Quotation deleted successfully")


def generate_contract_number() -> str:
    now = datetime.now(timezone.utc)
    return f"MR{now.strftime('%Y%m%d')}{uuid.uuid4().hex[:8].upper()}"


def get_contract_dict(contract: Contract) -> dict:
    contract_dict = {c.name: getattr(contract, c.name) for c in contract.__table__.columns}
    contract_dict["rental_days"] = contract.calculate_rental_days()
    contract_dict["overdue_days"] = contract.calculate_overdue_days()
    contract_dict["items"] = contract.items
    return contract_dict


@router.post("/{quotation_id}/convert-to-contract", response_model=APIResponse[ContractResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def convert_quotation_to_contract(
    request: Request,
    quotation_id: int,
    convert_data: QuotationConvertRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    quotation = db.query(Quotation).filter(Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(status_code=404, detail="Quotation not found")

    if quotation.status != QuotationStatus.CONFIRMED:
        raise HTTPException(
            status_code=400,
            detail=f"Can only convert quotations with status 'confirmed', current status: {quotation.status.value}",
        )

    quotation_item_map = {item.id: item for item in quotation.items}
    request_item_ids = {item.quotation_item_id for item in convert_data.items}

    missing_items = set(quotation_item_map.keys()) - request_item_ids
    if missing_items:
        raise HTTPException(
            status_code=400,
            detail=f"Missing device selection for quotation items: {missing_items}",
        )

    extra_items = request_item_ids - set(quotation_item_map.keys())
    if extra_items:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid quotation item IDs: {extra_items}",
        )

    all_device_ids = []
    for item in convert_data.items:
        q_item = quotation_item_map[item.quotation_item_id]
        if len(item.device_ids) != q_item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Quotation item {item.quotation_item_id} requires {q_item.quantity} devices, but {len(item.device_ids)} provided",
            )
        all_device_ids.extend(item.device_ids)

    if len(all_device_ids) != len(set(all_device_ids)):
        raise HTTPException(
            status_code=400,
            detail="Duplicate device IDs found across items",
        )

    lock_service = DeviceLockService(db)
    locked, lock_token, errors = lock_service.lock_devices(all_device_ids, current_user, purpose="rental")
    if not locked:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    try:
        device_id_to_device = {}
        for device_id in all_device_ids:
            device = db.query(Device).filter(Device.id == device_id).first()
            if not device:
                lock_service.unlock_by_token(lock_token, current_user)
                raise HTTPException(status_code=400, detail=f"Device {device_id} not found")
            if not device.is_available_for_rent():
                lock_service.unlock_by_token(lock_token, current_user)
                raise HTTPException(
                    status_code=400,
                    detail=f"Device {device.serial_number} is not available for rent",
                )
            device_id_to_device[device_id] = device

        for item in convert_data.items:
            q_item = quotation_item_map[item.quotation_item_id]
            for device_id in item.device_ids:
                device = device_id_to_device[device_id]
                if device.category_id != q_item.category_id:
                    lock_service.unlock_by_token(lock_token, current_user)
                    raise HTTPException(
                        status_code=400,
                        detail=f"Device {device.serial_number} (category {device.category_id}) does not match quotation item category {q_item.category_id}",
                    )

        end_date = convert_data.start_date + timedelta(days=quotation.rental_days - 1)

        from ..models.reservation import Reservation

        for device_id in all_device_ids:
            device = device_id_to_device[device_id]

            if Reservation.check_time_conflict(db, device_id, convert_data.start_date, end_date):
                lock_service.unlock_by_token(lock_token, current_user)
                raise HTTPException(
                    status_code=400,
                    detail=f"Device {device.serial_number} has a conflicting reservation during the rental period",
                )

            active_contract = (
                db.query(ContractItem)
                .join(Contract)
                .filter(
                    ContractItem.device_id == device_id,
                    Contract.status.in_([ContractStatus.ACTIVE, ContractStatus.RENEWED, ContractStatus.OVERDUE]),
                    or_(
                        and_(Contract.start_date < end_date, Contract.end_date > convert_data.start_date),
                        and_(convert_data.start_date < Contract.end_date, end_date > Contract.start_date),
                    ),
                )
                .first()
            )
            if active_contract:
                lock_service.unlock_by_token(lock_token, current_user)
                raise HTTPException(
                    status_code=400,
                    detail=f"Device {device.serial_number} is currently in use by an active contract",
                )

            now = datetime.now(timezone.utc)
            active_commitment = (
                db.query(InventoryCommitment)
                .filter(
                    InventoryCommitment.device_id == device_id,
                    InventoryCommitment.status.in_([CommitmentStatus.PENDING.value, CommitmentStatus.CONFIRMED.value]),
                    or_(
                        InventoryCommitment.expires_at.is_(None),
                        InventoryCommitment.expires_at > now,
                    ),
                    or_(
                        and_(InventoryCommitment.start_date < end_date, InventoryCommitment.end_date > convert_data.start_date),
                        and_(convert_data.start_date < InventoryCommitment.end_date, end_date > InventoryCommitment.start_date),
                    ),
                )
                .first()
            )
            if active_commitment:
                lock_service.unlock_by_token(lock_token, current_user)
                raise HTTPException(
                    status_code=400,
                    detail=f"Device {device.serial_number} has a conflicting inventory commitment during the rental period",
                )

        db.begin_nested()
        try:
            new_contract = Contract(
                contract_number=generate_contract_number(),
                customer_id=quotation.customer_id,
                created_by_id=current_user.id,
                start_date=convert_data.start_date,
                end_date=end_date,
                notes=convert_data.notes or quotation.notes,
                status=ContractStatus.DRAFT,
            )
            db.add(new_contract)
            db.flush()

            total_amount = 0.0
            deposit_amount = 0.0

            for item in convert_data.items:
                q_item = quotation_item_map[item.quotation_item_id]
                for device_id in item.device_ids:
                    device = device_id_to_device[device_id]
                    daily_rate = q_item.daily_rate
                    subtotal = daily_rate * quotation.rental_days * 1

                    contract_item = ContractItem(
                        contract_id=new_contract.id,
                        device_id=device_id,
                        daily_rate=daily_rate,
                        quantity=1,
                        subtotal=subtotal,
                    )
                    db.add(contract_item)
                    new_contract.items.append(contract_item)
                    total_amount += subtotal
                    deposit_amount += q_item.deposit_amount * 1

            discount_amount = total_amount * (quotation.discount_rate / 100)
            final_amount = max(0, total_amount - discount_amount)

            new_contract.total_amount = round(total_amount, 2)
            new_contract.deposit_amount = round(deposit_amount, 2)
            new_contract.discount_amount = round(discount_amount, 2)
            new_contract.final_amount = round(final_amount, 2)

            db.commit()
            db.refresh(new_contract)

            lock_service.unlock_by_token(lock_token, current_user)

        except Exception as e:
            db.rollback()
            lock_service.unlock_by_token(lock_token, current_user)
            raise HTTPException(status_code=500, detail=f"Failed to convert quotation: {str(e)}")

    except HTTPException:
        raise

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.QUOTE_CONVERT,
        resource_type="quotation",
        resource_id=str(quotation_id),
        user=current_user,
        old_values={
            "quotation_id": quotation_id,
            "quotation_number": quotation.quotation_number,
            "status": quotation.status.value,
            "total_rental_fee": quotation.total_rental_fee,
            "total_deposit": quotation.total_deposit,
            "discount_rate": quotation.discount_rate,
            "discount_amount": quotation.discount_amount,
            "estimated_total": quotation.estimated_total,
        },
        new_values={
            "quotation_id": quotation_id,
            "quotation_number": quotation.quotation_number,
            "contract_id": new_contract.id,
            "contract_number": new_contract.contract_number,
            "customer_id": new_contract.customer_id,
            "total_amount": new_contract.total_amount,
            "deposit_amount": new_contract.deposit_amount,
            "discount_rate": quotation.discount_rate,
            "discount_amount": new_contract.discount_amount,
            "final_amount": new_contract.final_amount,
            "start_date": new_contract.start_date,
            "end_date": new_contract.end_date,
            "items": [
                {
                    "quotation_item_id": item.quotation_item_id,
                    "device_ids": item.device_ids,
                }
                for item in convert_data.items
            ],
        },
        description=f"Quotation {quotation.quotation_number} converted to contract {new_contract.contract_number}",
        ip_address=request.client.host if request.client else None,
    )

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
            "discount_amount": new_contract.discount_amount,
            "final_amount": new_contract.final_amount,
            "source_quotation_id": quotation_id,
            "source_quotation_number": quotation.quotation_number,
        },
        description=f"Contract {new_contract.contract_number} created from quotation {quotation.quotation_number}",
        ip_address=request.client.host if request.client else None,
    )

    message = "Contract created successfully from quotation"
    data = get_contract_dict(new_contract)

    risk_summary = get_customer_risk_summary_sync(db, quotation.customer_id)
    if risk_summary:
        message = f"Contract created successfully from quotation. Customer has {risk_summary.total_active_notes} active risk note(s)."
        data["customer_risk_summary"] = risk_summary.model_dump()

    return APIResponse(message=message, data=data)

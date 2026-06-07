from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional
from math import ceil
from datetime import datetime, timezone
import uuid

from ..database import get_db
from ..models.user import User, UserRole
from ..models.device import DeviceCategory
from ..models.quotation import Quotation, QuotationItem, QuotationStatus
from ..schemas import (
    QuotationCreate,
    QuotationUpdate,
    QuotationResponse,
    QuotationVoidRequest,
    APIResponse,
    PaginatedResponse,
)
from ..core import (
    get_current_active_user,
    require_role,
    AuditLogger,
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

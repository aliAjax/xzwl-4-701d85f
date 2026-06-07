from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional
from math import ceil

from ..database import get_db
from ..models.user import User, UserRole
from ..models.device import DeviceCategory
from ..schemas import (
    DeviceCategoryCreate,
    DeviceCategoryUpdate,
    DeviceCategoryResponse,
    APIResponse,
    PaginatedResponse,
)
from ..core import get_current_active_user, require_role, AuditLogger

router = APIRouter(prefix="/api/categories", tags=["Device Categories"])


@router.get("", response_model=PaginatedResponse[DeviceCategoryResponse])
async def list_categories(
    page: int = 1,
    per_page: int = 20,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(DeviceCategory)
    if search:
        query = query.filter(
            (DeviceCategory.name.ilike(f"%{search}%")) |
            (DeviceCategory.description.ilike(f"%{search}%"))
        )
    total = query.count()
    categories = query.offset((page - 1) * per_page).limit(per_page).all()
    return PaginatedResponse(
        data=categories,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/{category_id}", response_model=APIResponse[DeviceCategoryResponse])
async def get_category(category_id: int, db: Session = Depends(get_db)):
    category = db.query(DeviceCategory).filter(DeviceCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return APIResponse(data=category)


@router.post("", response_model=APIResponse[DeviceCategoryResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def create_category(
    request: Request,
    category_data: DeviceCategoryCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    existing = db.query(DeviceCategory).filter(DeviceCategory.name == category_data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Category name already exists")

    new_category = DeviceCategory(**category_data.model_dump())
    db.add(new_category)
    db.commit()
    db.refresh(new_category)

    audit_logger = AuditLogger(db)
    audit_logger.log_create(
        resource_type="device_category",
        resource_id=str(new_category.id),
        user=current_user,
        new_values=category_data.model_dump(),
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Category created successfully", data=new_category)


@router.put("/{category_id}", response_model=APIResponse[DeviceCategoryResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def update_category(
    request: Request,
    category_id: int,
    category_data: DeviceCategoryUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    category = db.query(DeviceCategory).filter(DeviceCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    old_values = {
        "name": category.name,
        "daily_rental_rate": category.daily_rental_rate,
        "deposit_amount": category.deposit_amount,
        "maintenance_cycle_days": category.maintenance_cycle_days,
    }

    update_data = category_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(category, field, value)

    db.commit()
    db.refresh(category)

    audit_logger = AuditLogger(db)
    audit_logger.log_update(
        resource_type="device_category",
        resource_id=str(category_id),
        user=current_user,
        old_values=old_values,
        new_values=update_data,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Category updated successfully", data=category)


@router.delete("/{category_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN])
async def delete_category(
    request: Request,
    category_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    category = db.query(DeviceCategory).filter(DeviceCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    if category.devices:
        raise HTTPException(status_code=400, detail="Cannot delete category with associated devices")

    old_values = {"name": category.name, "id": category.id}

    db.delete(category)
    db.commit()

    audit_logger = AuditLogger(db)
    audit_logger.log_delete(
        resource_type="device_category",
        resource_id=str(category_id),
        user=current_user,
        old_values=old_values,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Category deleted successfully")

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import Optional
from math import ceil

from ..database import get_db
from ..models.user import User, UserRole
from ..models.warehouse import Warehouse, WarehouseType, WarehouseStatus
from ..models.device import Device
from ..schemas import (
    WarehouseCreate,
    WarehouseUpdate,
    WarehouseResponse,
    APIResponse,
    PaginatedResponse,
)
from ..core import get_current_active_user, require_role, AuditLogger

router = APIRouter(prefix="/api/warehouses", tags=["Warehouses"])


@router.get("", response_model=PaginatedResponse[WarehouseResponse])
async def list_warehouses(
    page: int = 1,
    per_page: int = 20,
    status: Optional[WarehouseStatus] = None,
    type: Optional[WarehouseType] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Warehouse)
    if status:
        query = query.filter(Warehouse.status == status)
    if type:
        query = query.filter(Warehouse.type == type)
    if search:
        query = query.filter(
            (Warehouse.code.ilike(f"%{search}%")) |
            (Warehouse.name.ilike(f"%{search}%")) |
            (Warehouse.city.ilike(f"%{search}%"))
        )

    total = query.count()
    warehouses = query.offset((page - 1) * per_page).limit(per_page).all()

    return PaginatedResponse(
        data=warehouses,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/{warehouse_id}", response_model=APIResponse[WarehouseResponse])
async def get_warehouse(warehouse_id: int, db: Session = Depends(get_db)):
    warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    return APIResponse(data=warehouse)


@router.get("/code/{code}", response_model=APIResponse[WarehouseResponse])
async def get_warehouse_by_code(code: str, db: Session = Depends(get_db)):
    warehouse = db.query(Warehouse).filter(Warehouse.code == code).first()
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    return APIResponse(data=warehouse)


@router.post("", response_model=APIResponse[WarehouseResponse])
@require_role([UserRole.ADMIN])
async def create_warehouse(
    request: Request,
    warehouse_data: WarehouseCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    existing = db.query(Warehouse).filter(Warehouse.code == warehouse_data.code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Warehouse code already exists")

    if warehouse_data.is_default:
        db.query(Warehouse).filter(Warehouse.is_default == True).update({Warehouse.is_default: False})

    new_warehouse = Warehouse(
        **warehouse_data.model_dump(),
        created_by_id=current_user.id,
    )
    db.add(new_warehouse)
    db.commit()
    db.refresh(new_warehouse)

    audit_logger = AuditLogger(db)
    audit_logger.log_create(
        resource_type="warehouse",
        resource_id=str(new_warehouse.id),
        user=current_user,
        new_values={
            "code": new_warehouse.code,
            "name": new_warehouse.name,
            "type": new_warehouse.type,
        },
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Warehouse created successfully", data=new_warehouse)


@router.put("/{warehouse_id}", response_model=APIResponse[WarehouseResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def update_warehouse(
    request: Request,
    warehouse_id: int,
    warehouse_data: WarehouseUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")

    old_values = {
        "name": warehouse.name,
        "code": warehouse.code,
        "status": warehouse.status,
        "type": warehouse.type,
    }

    if warehouse_data.is_default:
        db.query(Warehouse).filter(Warehouse.id != warehouse_id, Warehouse.is_default == True).update(
            {Warehouse.is_default: False}
        )

    update_data = warehouse_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(warehouse, field, value)

    db.commit()
    db.refresh(warehouse)

    audit_logger = AuditLogger(db)
    audit_logger.log_update(
        resource_type="warehouse",
        resource_id=str(warehouse_id),
        user=current_user,
        old_values=old_values,
        new_values=update_data,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Warehouse updated successfully", data=warehouse)


@router.delete("/{warehouse_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN])
async def delete_warehouse(
    request: Request,
    warehouse_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")

    devices_in_warehouse = (
        db.query(Device)
        .filter(
            (Device.warehouse_id == warehouse_id) |
            (Device.location == warehouse.code)
        )
        .count()
    )
    if devices_in_warehouse > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete warehouse with {devices_in_warehouse} devices. Move devices first.",
        )

    old_values = {"code": warehouse.code, "name": warehouse.name, "id": warehouse.id}

    db.delete(warehouse)
    db.commit()

    audit_logger = AuditLogger(db)
    audit_logger.log_delete(
        resource_type="warehouse",
        resource_id=str(warehouse_id),
        user=current_user,
        old_values=old_values,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Warehouse deleted successfully")


@router.get("/{warehouse_id}/devices/count", response_model=APIResponse)
async def get_warehouse_device_count(warehouse_id: int, db: Session = Depends(get_db)):
    warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")

    total_devices = (
        db.query(Device)
        .filter(
            (Device.warehouse_id == warehouse_id) |
            (Device.location == warehouse.code)
        )
        .count()
    )

    from ..models.device import DeviceStatus
    available_devices = (
        db.query(Device)
        .filter(
            (Device.warehouse_id == warehouse_id) |
            (Device.location == warehouse.code),
            Device.status == DeviceStatus.AVAILABLE,
        )
        .count()
    )

    return APIResponse(data={
        "warehouse_id": warehouse_id,
        "warehouse_name": warehouse.name,
        "total_devices": total_devices,
        "available_devices": available_devices,
        "capacity": warehouse.capacity,
        "current_occupancy": (total_devices / warehouse.capacity * 100) if warehouse.capacity > 0 else 0,
    })

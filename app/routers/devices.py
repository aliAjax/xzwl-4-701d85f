from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional
from math import ceil
from datetime import datetime, timezone, timedelta

from ..database import get_db
from ..models.user import User, UserRole
from ..models.device import Device, DeviceStatus, DeviceCategory
from ..models.warehouse import Warehouse
from ..schemas import (
    DeviceCreate,
    DeviceUpdate,
    DeviceResponse,
    DeviceStatusUpdate,
    APIResponse,
    PaginatedResponse,
)
from ..core import get_current_active_user, require_role, AuditLogger, DeviceLockService

router = APIRouter(prefix="/api/devices", tags=["Devices"])


@router.get("", response_model=PaginatedResponse[DeviceResponse])
async def list_devices(
    page: int = 1,
    per_page: int = 20,
    status: Optional[DeviceStatus] = None,
    category_id: Optional[int] = None,
    warehouse_id: Optional[int] = None,
    search: Optional[str] = None,
    available_only: bool = False,
    db: Session = Depends(get_db),
):
    query = db.query(Device)
    if status:
        query = query.filter(Device.status == status)
    if category_id:
        query = query.filter(Device.category_id == category_id)
    if warehouse_id:
        warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
        if warehouse:
            query = query.filter(
                (Device.warehouse_id == warehouse_id) |
                (Device.location == warehouse.code)
            )
    if search:
        query = query.filter(
            (Device.serial_number.ilike(f"%{search}%")) |
            (Device.name.ilike(f"%{search}%")) |
            (Device.model.ilike(f"%{search}%"))
        )
    if available_only:
        query = query.filter(Device.status == DeviceStatus.AVAILABLE)

    total = query.count()
    devices = query.offset((page - 1) * per_page).limit(per_page).all()

    response_data = []
    for device in devices:
        device_dict = {c.name: getattr(device, c.name) for c in device.__table__.columns}
        device_dict["is_available_for_rent"] = device.is_available_for_rent()
        device_dict["needs_maintenance"] = device.needs_maintenance()
        device_dict["category"] = device.category
        device_dict["warehouse"] = device.warehouse
        response_data.append(device_dict)

    return PaginatedResponse(
        data=response_data,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/{device_id}", response_model=APIResponse[DeviceResponse])
async def get_device(device_id: int, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    device_dict = {c.name: getattr(device, c.name) for c in device.__table__.columns}
    device_dict["is_available_for_rent"] = device.is_available_for_rent()
    device_dict["needs_maintenance"] = device.needs_maintenance()
    device_dict["category"] = device.category
    device_dict["warehouse"] = device.warehouse

    return APIResponse(data=device_dict)


@router.get("/serial/{serial_number}", response_model=APIResponse[DeviceResponse])
async def get_device_by_serial(serial_number: str, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.serial_number == serial_number).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    device_dict = {c.name: getattr(device, c.name) for c in device.__table__.columns}
    device_dict["is_available_for_rent"] = device.is_available_for_rent()
    device_dict["needs_maintenance"] = device.needs_maintenance()
    device_dict["category"] = device.category
    device_dict["warehouse"] = device.warehouse

    return APIResponse(data=device_dict)


@router.post("", response_model=APIResponse[DeviceResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def create_device(
    request: Request,
    device_data: DeviceCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    existing = db.query(Device).filter(Device.serial_number == device_data.serial_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="Device serial number already exists")

    category = db.query(DeviceCategory).filter(DeviceCategory.id == device_data.category_id).first()
    if not category:
        raise HTTPException(status_code=400, detail="Category not found")

    warehouse = None
    if device_data.warehouse_id:
        warehouse = db.query(Warehouse).filter(Warehouse.id == device_data.warehouse_id).first()
        if not warehouse:
            raise HTTPException(status_code=400, detail="Warehouse not found")

    new_device = Device(**device_data.model_dump())
    new_device.status = DeviceStatus.AVAILABLE

    if warehouse and not new_device.location:
        new_device.location = warehouse.code

    if category.disinfection_required:
        new_device.last_disinfection_date = datetime.now(timezone.utc)

    if category.maintenance_cycle_days:
        new_device.next_maintenance_date = datetime.now(timezone.utc) + timedelta(days=category.maintenance_cycle_days)

    db.add(new_device)
    db.commit()
    db.refresh(new_device)

    audit_logger = AuditLogger(db)
    audit_logger.log_create(
        resource_type="device",
        resource_id=str(new_device.id),
        user=current_user,
        new_values={
            "serial_number": new_device.serial_number,
            "name": new_device.name,
            "category_id": new_device.category_id,
            "status": new_device.status.value,
        },
        ip_address=request.client.host if request.client else None,
    )

    device_dict = {c.name: getattr(new_device, c.name) for c in new_device.__table__.columns}
    device_dict["is_available_for_rent"] = new_device.is_available_for_rent()
    device_dict["needs_maintenance"] = new_device.needs_maintenance()
    device_dict["category"] = new_device.category
    device_dict["warehouse"] = new_device.warehouse

    return APIResponse(message="Device created successfully", data=device_dict)


@router.put("/{device_id}", response_model=APIResponse[DeviceResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def update_device(
    request: Request,
    device_id: int,
    device_data: DeviceUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    old_values = {
        "name": device.name,
        "serial_number": device.serial_number,
        "status": device.status.value,
        "category_id": device.category_id,
    }

    update_data = device_data.model_dump(exclude_unset=True)

    if "warehouse_id" in update_data and update_data["warehouse_id"] is not None:
        warehouse = db.query(Warehouse).filter(Warehouse.id == update_data["warehouse_id"]).first()
        if not warehouse:
            raise HTTPException(status_code=400, detail="Warehouse not found")
        if "location" not in update_data or update_data["location"] is None:
            update_data["location"] = warehouse.code

    for field, value in update_data.items():
        setattr(device, field, value)

    db.commit()
    db.refresh(device)

    audit_logger = AuditLogger(db)
    audit_logger.log_update(
        resource_type="device",
        resource_id=str(device_id),
        user=current_user,
        old_values=old_values,
        new_values=update_data,
        ip_address=request.client.host if request.client else None,
    )

    device_dict = {c.name: getattr(device, c.name) for c in device.__table__.columns}
    device_dict["is_available_for_rent"] = device.is_available_for_rent()
    device_dict["needs_maintenance"] = device.needs_maintenance()
    device_dict["category"] = device.category
    device_dict["warehouse"] = device.warehouse

    return APIResponse(message="Device updated successfully", data=device_dict)


@router.patch("/{device_id}/status", response_model=APIResponse[DeviceResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def update_device_status(
    request: Request,
    device_id: int,
    status_data: DeviceStatusUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    old_status = device.status
    old_status_value = old_status.value if hasattr(old_status, "value") else str(old_status)
    new_status_value = status_data.status.value if hasattr(status_data.status, "value") else str(status_data.status)

    if old_status == status_data.status:
        return APIResponse(message="Device status unchanged", data=device)

    device.status = status_data.status
    db.commit()
    db.refresh(device)

    audit_logger = AuditLogger(db)
    audit_logger.log_status_change(
        resource_type="device",
        resource_id=str(device_id),
        user=current_user,
        old_status=old_status_value,
        new_status=new_status_value,
        description=status_data.notes or f"Device status changed from {old_status_value} to {new_status_value}",
        ip_address=request.client.host if request.client else None,
    )

    device_dict = {c.name: getattr(device, c.name) for c in device.__table__.columns}
    device_dict["is_available_for_rent"] = device.is_available_for_rent()
    device_dict["needs_maintenance"] = device.needs_maintenance()
    device_dict["category"] = device.category
    device_dict["warehouse"] = device.warehouse

    return APIResponse(message="Device status updated successfully", data=device_dict)


@router.delete("/{device_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN])
async def delete_device(
    request: Request,
    device_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if device.contract_items:
        raise HTTPException(status_code=400, detail="Cannot delete device with active contracts")

    old_values = {
        "serial_number": device.serial_number,
        "name": device.name,
        "id": device.id,
    }

    db.delete(device)
    db.commit()

    audit_logger = AuditLogger(db)
    audit_logger.log_delete(
        resource_type="device",
        resource_id=str(device_id),
        user=current_user,
        old_values=old_values,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Device deleted successfully")


@router.get("/{device_id}/availability", response_model=APIResponse)
async def check_device_availability(device_id: int, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    lock_service = DeviceLockService(db)
    is_locked = lock_service.is_device_locked(device_id)
    is_available = device.is_available_for_rent() and not is_locked

    return APIResponse(data={
        "device_id": device_id,
        "serial_number": device.serial_number,
        "is_available": is_available,
        "is_available_for_rent": device.is_available_for_rent(),
        "is_locked": is_locked,
        "status": device.status.value if hasattr(device.status, "value") else str(device.status),
        "needs_maintenance": device.needs_maintenance(),
        "last_disinfection_date": device.last_disinfection_date,
    })

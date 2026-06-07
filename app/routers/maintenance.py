from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional
from math import ceil
from datetime import datetime, timezone, timedelta

from ..database import get_db
from ..models.user import User, UserRole
from ..models.device import Device, DeviceStatus
from ..models.maintenance import MaintenanceRecord
from ..schemas import (
    MaintenanceRecordCreate,
    MaintenanceRecordUpdate,
    MaintenanceRecordResponse,
    APIResponse,
    PaginatedResponse,
)
from ..core import get_current_active_user, require_role, AuditLogger, AuditAction

router = APIRouter(prefix="/api/maintenance", tags=["Maintenance"])


@router.get("/upcoming", response_model=APIResponse)
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_upcoming_maintenance(
    days: int = 7,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days)

    scheduled = (
        db.query(MaintenanceRecord)
        .filter(
            MaintenanceRecord.status == "scheduled",
            MaintenanceRecord.scheduled_date >= now,
            MaintenanceRecord.scheduled_date <= cutoff,
        )
        .order_by(MaintenanceRecord.scheduled_date)
        .all()
    )

    overdue = (
        db.query(MaintenanceRecord)
        .filter(
            MaintenanceRecord.status == "scheduled",
            MaintenanceRecord.scheduled_date < now,
        )
        .order_by(MaintenanceRecord.scheduled_date)
        .all()
    )

    return APIResponse(data={
        "upcoming_count": len(scheduled),
        "overdue_count": len(overdue),
        "upcoming": [
            {
                "id": r.id,
                "device_id": r.device_id,
                "device_name": r.device.name if r.device else None,
                "device_serial": r.device.serial_number if r.device else None,
                "maintenance_type": r.maintenance_type,
                "scheduled_date": r.scheduled_date,
                "description": r.description,
            }
            for r in scheduled
        ],
        "overdue": [
            {
                "id": r.id,
                "device_id": r.device_id,
                "device_name": r.device.name if r.device else None,
                "device_serial": r.device.serial_number if r.device else None,
                "maintenance_type": r.maintenance_type,
                "scheduled_date": r.scheduled_date,
                "days_overdue": (now - r.scheduled_date).days,
                "description": r.description,
            }
            for r in overdue
        ],
    })


@router.get("", response_model=PaginatedResponse[MaintenanceRecordResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def list_maintenance_records(
    page: int = 1,
    per_page: int = 20,
    device_id: Optional[int] = None,
    status: Optional[str] = None,
    maintenance_type: Optional[str] = None,
    scheduled_from: Optional[datetime] = None,
    scheduled_to: Optional[datetime] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = db.query(MaintenanceRecord)
    if device_id:
        query = query.filter(MaintenanceRecord.device_id == device_id)
    if status:
        query = query.filter(MaintenanceRecord.status == status)
    if maintenance_type:
        query = query.filter(MaintenanceRecord.maintenance_type == maintenance_type)
    if scheduled_from:
        query = query.filter(MaintenanceRecord.scheduled_date >= scheduled_from)
    if scheduled_to:
        query = query.filter(MaintenanceRecord.scheduled_date <= scheduled_to)

    total = query.count()
    records = query.order_by(MaintenanceRecord.scheduled_date.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return PaginatedResponse(
        data=records,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/{record_id}", response_model=APIResponse[MaintenanceRecordResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_maintenance_record(
    record_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    record = db.query(MaintenanceRecord).filter(MaintenanceRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Maintenance record not found")
    return APIResponse(data=record)


@router.post("", response_model=APIResponse[MaintenanceRecordResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def create_maintenance_record(
    request: Request,
    record_data: MaintenanceRecordCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(Device.id == record_data.device_id).first()
    if not device:
        raise HTTPException(status_code=400, detail="Device not found")

    new_record = MaintenanceRecord(**record_data.model_dump())
    new_record.status = "scheduled"
    db.add(new_record)

    if record_data.status == "in_progress":
        device.status = DeviceStatus.MAINTENANCE

    db.commit()
    db.refresh(new_record)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.MAINTAIN,
        resource_type="maintenance_record",
        resource_id=str(new_record.id),
        user=current_user,
        new_values={
            "device_id": new_record.device_id,
            "maintenance_type": new_record.maintenance_type,
            "scheduled_date": new_record.scheduled_date,
            "status": new_record.status,
        },
        description=f"Maintenance record created for device {device.serial_number}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Maintenance record created successfully", data=new_record)


@router.put("/{record_id}", response_model=APIResponse[MaintenanceRecordResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def update_maintenance_record(
    request: Request,
    record_id: int,
    record_data: MaintenanceRecordUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    record = db.query(MaintenanceRecord).filter(MaintenanceRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Maintenance record not found")

    old_values = {
        "status": record.status,
        "maintenance_type": record.maintenance_type,
        "scheduled_date": record.scheduled_date,
    }

    update_data = record_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(record, field, value)

    if "status" in update_data:
        device = db.query(Device).filter(Device.id == record.device_id).first()
        if update_data["status"] == "in_progress":
            device.status = DeviceStatus.MAINTENANCE
        elif update_data["status"] == "completed":
            if not record.actual_date:
                record.actual_date = datetime.now(timezone.utc)
            if record.next_maintenance_date:
                device.next_maintenance_date = record.next_maintenance_date
            device.last_maintenance_date = record.actual_date
            if device.status == DeviceStatus.MAINTENANCE:
                device.status = DeviceStatus.AVAILABLE

    db.commit()
    db.refresh(record)

    audit_logger = AuditLogger(db)
    audit_logger.log_update(
        resource_type="maintenance_record",
        resource_id=str(record_id),
        user=current_user,
        old_values=old_values,
        new_values=update_data,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Maintenance record updated successfully", data=record)


@router.delete("/{record_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN])
async def delete_maintenance_record(
    request: Request,
    record_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    record = db.query(MaintenanceRecord).filter(MaintenanceRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Maintenance record not found")

    old_values = {
        "device_id": record.device_id,
        "maintenance_type": record.maintenance_type,
        "scheduled_date": record.scheduled_date,
        "id": record.id,
    }

    db.delete(record)
    db.commit()

    audit_logger = AuditLogger(db)
    audit_logger.log_delete(
        resource_type="maintenance_record",
        resource_id=str(record_id),
        user=current_user,
        old_values=old_values,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Maintenance record deleted successfully")

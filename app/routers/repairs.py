from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional
from math import ceil
from datetime import datetime, timezone

from ..database import get_db
from ..models.user import User, UserRole
from ..models.device import Device, DeviceStatus
from ..models.repair import RepairRecord, RepairStatus
from ..schemas import (
    RepairRecordCreate,
    RepairRecordUpdate,
    RepairRecordResponse,
    RepairStatusUpdate,
    APIResponse,
    PaginatedResponse,
)
from ..core import get_current_active_user, require_role, AuditLogger, AuditAction

router = APIRouter(prefix="/api/repairs", tags=["Repairs"])


@router.get("/summary", response_model=APIResponse)
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_repair_summary(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy import func

    status_counts = {}
    for status in ["reported", "diagnosing", "in_progress", "awaiting_parts", "completed", "cancelled", "unrepairable"]:
        count = db.query(RepairRecord).filter(RepairRecord.status == status).count()
        status_counts[status] = count

    priority_counts = {}
    for priority in ["low", "medium", "high", "urgent"]:
        count = db.query(RepairRecord).filter(RepairRecord.priority == priority).count()
        priority_counts[priority] = count

    open_repairs = db.query(RepairRecord).filter(
        RepairRecord.status.notin_(["completed", "cancelled", "unrepairable"])
    ).count()

    total_cost = db.query(RepairRecord).with_entities(
        func.sum(RepairRecord.total_cost)
    ).scalar() or 0.0

    return APIResponse(data={
        "status_counts": status_counts,
        "priority_counts": priority_counts,
        "open_repairs": open_repairs,
        "total_repair_cost": total_cost,
    })


@router.get("", response_model=PaginatedResponse[RepairRecordResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def list_repair_records(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    device_id: Optional[int] = None,
    status: Optional[RepairStatus] = None,
    priority: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = db.query(RepairRecord)
    if device_id:
        query = query.filter(RepairRecord.device_id == device_id)
    if status:
        query = query.filter(RepairRecord.status == status)
    if priority:
        query = query.filter(RepairRecord.priority == priority)

    total = query.count()
    records = query.order_by(RepairRecord.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return PaginatedResponse(
        data=records,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/{record_id}", response_model=APIResponse[RepairRecordResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def get_repair_record(
    record_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    record = db.query(RepairRecord).filter(RepairRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Repair record not found")
    return APIResponse(data=record)


@router.post("", response_model=APIResponse[RepairRecordResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def create_repair_record(
    request: Request,
    record_data: RepairRecordCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(Device.id == record_data.device_id).first()
    if not device:
        raise HTTPException(status_code=400, detail="Device not found")

    new_record = RepairRecord(**record_data.model_dump())
    new_record.report_date = datetime.now(timezone.utc)
    new_record.reported_by_id = current_user.id
    new_record.status = "reported"

    db.add(new_record)

    device.status = DeviceStatus.REPAIR
    db.commit()
    db.refresh(new_record)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.REPAIR,
        resource_type="repair_record",
        resource_id=str(new_record.id),
        user=current_user,
        new_values={
            "device_id": new_record.device_id,
            "priority": new_record.priority.value if hasattr(new_record.priority, "value") else str(new_record.priority),
            "status": new_record.status,
            "fault_description": new_record.fault_description,
        },
        description=f"Repair request created for device {device.serial_number}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Repair record created successfully", data=new_record)


@router.put("/{record_id}", response_model=APIResponse[RepairRecordResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def update_repair_record(
    request: Request,
    record_id: int,
    record_data: RepairRecordUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    record = db.query(RepairRecord).filter(RepairRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Repair record not found")

    old_values = {
        "status": record.status.value if hasattr(record.status, "value") else str(record.status),
        "priority": record.priority.value if hasattr(record.priority, "value") else str(record.priority),
    }

    update_data = record_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(record, field, value)

    if "status" in update_data:
        device = db.query(Device).filter(Device.id == record.device_id).first()
        new_status = update_data["status"]
        if hasattr(new_status, "value"):
            new_status = new_status.value

        if new_status in ["in_progress", "diagnosing", "awaiting_parts"]:
            device.status = DeviceStatus.REPAIR
        elif new_status == "completed":
            record.repair_complete_date = record.repair_complete_date or datetime.now(timezone.utc)
            record.total_cost = (record.parts_cost or 0) + (record.labor_cost or 0)
            if device.category.disinfection_required:
                device.status = DeviceStatus.DISINFECTION
            else:
                device.status = DeviceStatus.AVAILABLE
        elif new_status == "unrepairable":
            device.status = DeviceStatus.RETIRED
            record.repair_complete_date = record.repair_complete_date or datetime.now(timezone.utc)

    if "handled_by_id" not in update_data:
        record.handled_by_id = current_user.id

    db.commit()
    db.refresh(record)

    audit_logger = AuditLogger(db)
    audit_logger.log_update(
        resource_type="repair_record",
        resource_id=str(record_id),
        user=current_user,
        old_values=old_values,
        new_values=update_data,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Repair record updated successfully", data=record)


@router.patch("/{record_id}/status", response_model=APIResponse[RepairRecordResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def update_repair_status(
    request: Request,
    record_id: int,
    status_data: RepairStatusUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    record = db.query(RepairRecord).filter(RepairRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Repair record not found")

    old_status = record.status.value if hasattr(record.status, "value") else str(record.status)
    new_status = status_data.status.value if hasattr(status_data.status, "value") else str(status_data.status)

    if old_status == new_status:
        return APIResponse(message="Status unchanged", data=record)

    device = db.query(Device).filter(Device.id == record.device_id).first()

    if new_status in ["in_progress", "diagnosing", "awaiting_parts"]:
        device.status = DeviceStatus.REPAIR
    elif new_status == "completed":
        record.repair_complete_date = record.repair_complete_date or datetime.now(timezone.utc)
        record.total_cost = (record.parts_cost or 0) + (record.labor_cost or 0)
        if device.category.disinfection_required:
            device.status = DeviceStatus.DISINFECTION
        else:
            device.status = DeviceStatus.AVAILABLE
    elif new_status == "unrepairable":
        device.status = DeviceStatus.RETIRED
        record.repair_complete_date = record.repair_complete_date or datetime.now(timezone.utc)
    elif new_status == "cancelled":
        if device.status == DeviceStatus.REPAIR:
            device.status = DeviceStatus.AVAILABLE

    record.status = status_data.status
    if record.handled_by_id is None:
        record.handled_by_id = current_user.id

    db.commit()
    db.refresh(record)

    audit_logger = AuditLogger(db)
    audit_logger.log_status_change(
        resource_type="repair_record",
        resource_id=str(record_id),
        user=current_user,
        old_status=old_status,
        new_status=new_status,
        description=status_data.notes or f"Repair status changed from {old_status} to {new_status}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Repair status updated successfully", data=record)


@router.delete("/{record_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN])
async def delete_repair_record(
    request: Request,
    record_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    record = db.query(RepairRecord).filter(RepairRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Repair record not found")

    old_values = {
        "device_id": record.device_id,
        "status": record.status.value if hasattr(record.status, "value") else str(record.status),
        "priority": record.priority.value if hasattr(record.priority, "value") else str(record.priority),
        "id": record.id,
    }

    device = db.query(Device).filter(Device.id == record.device_id).first()
    if device.status == DeviceStatus.REPAIR:
        device.status = DeviceStatus.AVAILABLE

    db.delete(record)
    db.commit()

    audit_logger = AuditLogger(db)
    audit_logger.log_delete(
        resource_type="repair_record",
        resource_id=str(record_id),
        user=current_user,
        old_values=old_values,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Repair record deleted successfully")

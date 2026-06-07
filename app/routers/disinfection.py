from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional
from math import ceil
from datetime import datetime, timezone, timedelta

from ..database import get_db
from ..models.user import User, UserRole
from ..models.device import Device, DeviceStatus
from ..models.disinfection import DisinfectionRecord
from ..schemas import (
    DisinfectionRecordCreate,
    DisinfectionRecordUpdate,
    DisinfectionRecordResponse,
    APIResponse,
    PaginatedResponse,
)
from ..core import get_current_active_user, require_role, AuditLogger, AuditAction

router = APIRouter(prefix="/api/disinfection", tags=["Disinfection"])


@router.get("", response_model=PaginatedResponse[DisinfectionRecordResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def list_disinfection_records(
    page: int = 1,
    per_page: int = 20,
    device_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    is_qualified: Optional[bool] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = db.query(DisinfectionRecord)
    if device_id:
        query = query.filter(DisinfectionRecord.device_id == device_id)
    if start_date:
        query = query.filter(DisinfectionRecord.disinfection_date >= start_date)
    if end_date:
        query = query.filter(DisinfectionRecord.disinfection_date <= end_date)
    if is_qualified is not None:
        query = query.filter(DisinfectionRecord.is_qualified == is_qualified)

    total = query.count()
    records = query.order_by(DisinfectionRecord.disinfection_date.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return PaginatedResponse(
        data=records,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/{record_id}", response_model=APIResponse[DisinfectionRecordResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_disinfection_record(
    record_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    record = db.query(DisinfectionRecord).filter(DisinfectionRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Disinfection record not found")
    return APIResponse(data=record)


@router.post("", response_model=APIResponse[DisinfectionRecordResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def create_disinfection_record(
    request: Request,
    record_data: DisinfectionRecordCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(Device.id == record_data.device_id).first()
    if not device:
        raise HTTPException(status_code=400, detail="Device not found")

    new_record = DisinfectionRecord(**record_data.model_dump())
    db.add(new_record)

    if record_data.is_qualified:
        device.last_disinfection_date = record_data.disinfection_date
        if device.status == DeviceStatus.DISINFECTION:
            device.status = DeviceStatus.AVAILABLE

    db.commit()
    db.refresh(new_record)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.DISINFECT,
        resource_type="disinfection_record",
        resource_id=str(new_record.id),
        user=current_user,
        new_values={
            "device_id": new_record.device_id,
            "disinfection_date": new_record.disinfection_date,
            "is_qualified": new_record.is_qualified,
            "operator_name": new_record.operator_name,
        },
        description=f"Disinfection record created for device {device.serial_number}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Disinfection record created successfully", data=new_record)


@router.put("/{record_id}", response_model=APIResponse[DisinfectionRecordResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def update_disinfection_record(
    request: Request,
    record_id: int,
    record_data: DisinfectionRecordUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    record = db.query(DisinfectionRecord).filter(DisinfectionRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Disinfection record not found")

    old_values = {
        "is_qualified": record.is_qualified,
        "disinfection_date": record.disinfection_date,
        "operator_name": record.operator_name,
    }

    update_data = record_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(record, field, value)

    db.commit()
    db.refresh(record)

    audit_logger = AuditLogger(db)
    audit_logger.log_update(
        resource_type="disinfection_record",
        resource_id=str(record_id),
        user=current_user,
        old_values=old_values,
        new_values=update_data,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Disinfection record updated successfully", data=record)


@router.delete("/{record_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN])
async def delete_disinfection_record(
    request: Request,
    record_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    record = db.query(DisinfectionRecord).filter(DisinfectionRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Disinfection record not found")

    old_values = {
        "device_id": record.device_id,
        "disinfection_date": record.disinfection_date,
        "id": record.id,
    }

    db.delete(record)
    db.commit()

    audit_logger = AuditLogger(db)
    audit_logger.log_delete(
        resource_type="disinfection_record",
        resource_id=str(record_id),
        user=current_user,
        old_values=old_values,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Disinfection record deleted successfully")


@router.get("/device/{device_id}/latest", response_model=APIResponse[DisinfectionRecordResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_latest_disinfection(
    device_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    latest_record = (
        db.query(DisinfectionRecord)
        .filter(
            DisinfectionRecord.device_id == device_id,
            DisinfectionRecord.is_qualified == True,
        )
        .order_by(DisinfectionRecord.disinfection_date.desc())
        .first()
    )

    if not latest_record:
        raise HTTPException(status_code=404, detail="No disinfection records found for this device")

    return APIResponse(data=latest_record)

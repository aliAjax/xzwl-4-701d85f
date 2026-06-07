from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional
from math import ceil
from datetime import datetime, timezone

from ..database import get_db
from ..models.user import User, UserRole
from ..models.device import Device
from ..models.device_transfer import DeviceTransfer, TransferStatus, TransferLocationType
from ..models.audit import AuditAction
from ..schemas import (
    DeviceTransferCreate,
    DeviceTransferConfirm,
    DeviceTransferCancel,
    DeviceTransferResponse,
    APIResponse,
    PaginatedResponse,
)
from ..core import get_current_active_user, require_role, AuditLogger

router = APIRouter(prefix="/api/device-transfers", tags=["Device Transfers"])


def _model_to_dict(model) -> Optional[dict]:
    if model is None:
        return None
    return {c.name: getattr(model, c.name) for c in model.__table__.columns}


def build_transfer_response(transfer: DeviceTransfer) -> dict:
    transfer_dict = _model_to_dict(transfer) or {}

    if transfer.device:
        device = transfer.device
        device_dict = _model_to_dict(device) or {}
        device_dict["is_available_for_rent"] = device.is_available_for_rent()
        device_dict["needs_maintenance"] = device.needs_maintenance()
        device_dict["category"] = _model_to_dict(device.category)
        transfer_dict["device"] = device_dict
    else:
        transfer_dict["device"] = None

    transfer_dict["created_by"] = _model_to_dict(transfer.created_by)
    transfer_dict["confirmed_by"] = _model_to_dict(transfer.confirmed_by)
    transfer_dict["cancelled_by"] = _model_to_dict(transfer.cancelled_by)

    return transfer_dict


@router.get("", response_model=PaginatedResponse[DeviceTransferResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def list_transfers(
    page: int = 1,
    per_page: int = 20,
    status: Optional[TransferStatus] = None,
    from_location_type: Optional[TransferLocationType] = None,
    to_location_type: Optional[TransferLocationType] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    query = db.query(DeviceTransfer)
    if status:
        query = query.filter(DeviceTransfer.status == status)
    if from_location_type:
        query = query.filter(DeviceTransfer.from_location_type == from_location_type)
    if to_location_type:
        query = query.filter(DeviceTransfer.to_location_type == to_location_type)

    query = query.order_by(DeviceTransfer.created_at.desc())
    total = query.count()
    transfers = query.offset((page - 1) * per_page).limit(per_page).all()

    response_data = [build_transfer_response(t) for t in transfers]

    return PaginatedResponse(
        data=response_data,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/device/{device_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_device_transfer_history(
    device_id: int,
    page: int = 1,
    per_page: int = 20,
    status: Optional[TransferStatus] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    query = db.query(DeviceTransfer).filter(DeviceTransfer.device_id == device_id)
    if status:
        query = query.filter(DeviceTransfer.status == status)

    query = query.order_by(DeviceTransfer.created_at.desc())
    total = query.count()
    transfers = query.offset((page - 1) * per_page).limit(per_page).all()

    response_data = [build_transfer_response(t) for t in transfers]

    return APIResponse(data={
        "device_id": device_id,
        "serial_number": device.serial_number,
        "device_name": device.name,
        "current_location": device.location,
        "transfers": response_data,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": ceil(total / per_page),
    })


@router.get("/{transfer_id}", response_model=APIResponse[DeviceTransferResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_transfer(
    transfer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    transfer = db.query(DeviceTransfer).filter(DeviceTransfer.id == transfer_id).first()
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer record not found")

    return APIResponse(data=build_transfer_response(transfer))


@router.post("", response_model=APIResponse[DeviceTransferResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def create_transfer(
    request: Request,
    transfer_data: DeviceTransferCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(Device.id == transfer_data.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    pending_transfer = db.query(DeviceTransfer).filter(
        DeviceTransfer.device_id == transfer_data.device_id,
        DeviceTransfer.status == TransferStatus.PENDING,
    ).first()
    if pending_transfer:
        raise HTTPException(
            status_code=400,
            detail=f"Device has a pending transfer (ID: {pending_transfer.id}). Please confirm or cancel it first.",
        )

    new_transfer = DeviceTransfer(
        **transfer_data.model_dump(),
        created_by_id=current_user.id,
    )

    db.add(new_transfer)
    db.commit()
    db.refresh(new_transfer)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.TRANSFER_CREATE,
        resource_type="device_transfer",
        resource_id=str(new_transfer.id),
        user=current_user,
        new_values={
            "device_id": new_transfer.device_id,
            "serial_number": device.serial_number,
            "from_location_type": new_transfer.from_location_type.value,
            "from_location": new_transfer.from_location,
            "to_location_type": new_transfer.to_location_type.value,
            "to_location": new_transfer.to_location,
        },
        description=f"Created transfer for device {device.serial_number} from {new_transfer.from_location} to {new_transfer.to_location}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Transfer record created successfully",
        data=build_transfer_response(new_transfer),
    )


@router.patch("/{transfer_id}/confirm", response_model=APIResponse[DeviceTransferResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def confirm_transfer(
    request: Request,
    transfer_id: int,
    confirm_data: DeviceTransferConfirm,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    transfer = db.query(DeviceTransfer).filter(DeviceTransfer.id == transfer_id).first()
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer record not found")

    if transfer.status != TransferStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot confirm transfer with status '{transfer.status.value}'. Only pending transfers can be confirmed.",
        )

    old_status = transfer.status.value
    old_location = transfer.device.location if transfer.device else None

    transfer.status = TransferStatus.CONFIRMED
    transfer.confirmed_by_id = current_user.id
    transfer.confirmed_at = datetime.now(timezone.utc)
    if confirm_data.transfer_notes:
        transfer.transfer_notes = confirm_data.transfer_notes

    if transfer.device:
        transfer.device.location = transfer.to_location

    db.commit()
    db.refresh(transfer)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.TRANSFER_CONFIRM,
        resource_type="device_transfer",
        resource_id=str(transfer_id),
        user=current_user,
        old_values={
            "status": old_status,
            "device_location": old_location,
        },
        new_values={
            "status": TransferStatus.CONFIRMED.value,
            "device_location": transfer.to_location,
        },
        description=f"Confirmed transfer for device {transfer.device.serial_number if transfer.device else 'N/A'}. Location updated to '{transfer.to_location}'",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Transfer confirmed successfully. Device location has been updated.",
        data=build_transfer_response(transfer),
    )


@router.patch("/{transfer_id}/cancel", response_model=APIResponse[DeviceTransferResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def cancel_transfer(
    request: Request,
    transfer_id: int,
    cancel_data: DeviceTransferCancel,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    transfer = db.query(DeviceTransfer).filter(DeviceTransfer.id == transfer_id).first()
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer record not found")

    if transfer.status != TransferStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel transfer with status '{transfer.status.value}'. Only pending transfers can be cancelled.",
        )

    old_status = transfer.status.value

    transfer.status = TransferStatus.CANCELLED
    transfer.cancelled_by_id = current_user.id
    transfer.cancelled_at = datetime.now(timezone.utc)
    transfer.cancel_reason = cancel_data.cancel_reason

    db.commit()
    db.refresh(transfer)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.TRANSFER_CANCEL,
        resource_type="device_transfer",
        resource_id=str(transfer_id),
        user=current_user,
        old_values={"status": old_status},
        new_values={"status": TransferStatus.CANCELLED.value},
        description=f"Cancelled transfer for device {transfer.device.serial_number if transfer.device else 'N/A'}. Reason: {cancel_data.cancel_reason}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Transfer cancelled successfully",
        data=build_transfer_response(transfer),
    )

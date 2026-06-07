from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional
from math import ceil
from datetime import datetime, timezone
import uuid

from ..database import get_db
from ..models.user import User, UserRole
from ..models.device import Device
from ..models.reservation import Reservation, ReservationStatus
from ..models.device_lock import DeviceLock
from ..schemas import (
    ReservationCreate,
    ReservationUpdate,
    ReservationResponse,
    ReservationStatusUpdate,
    ReservationCancelRequest,
    APIResponse,
    PaginatedResponse,
)
from ..core import (
    get_current_active_user,
    require_role,
    AuditLogger,
    DeviceLockService,
    AuditAction,
)

router = APIRouter(prefix="/api/reservations", tags=["Reservations"])


def generate_reservation_number() -> str:
    now = datetime.now(timezone.utc)
    return f"RV{now.strftime('%Y%m%d')}{uuid.uuid4().hex[:8].upper()}"


def get_reservation_dict(reservation: Reservation) -> dict:
    reservation_dict = {c.name: getattr(reservation, c.name) for c in reservation.__table__.columns}
    reservation_dict["duration_hours"] = reservation.calculate_duration_hours()
    reservation_dict["customer"] = reservation.customer
    reservation_dict["device"] = reservation.device
    return reservation_dict


@router.get("", response_model=PaginatedResponse[ReservationResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def list_reservations(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    status: Optional[ReservationStatus] = None,
    customer_id: Optional[int] = None,
    device_id: Optional[int] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = db.query(Reservation)

    if current_user.role == UserRole.CUSTOMER:
        query = query.filter(Reservation.customer_id == current_user.id)
    elif customer_id:
        query = query.filter(Reservation.customer_id == customer_id)

    if status:
        query = query.filter(Reservation.status == status)
    if device_id:
        query = query.filter(Reservation.device_id == device_id)

    total = query.count()
    reservations = query.order_by(Reservation.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    response_data = [get_reservation_dict(r) for r in reservations]

    return PaginatedResponse(
        data=response_data,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/{reservation_id}", response_model=APIResponse[ReservationResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def get_reservation(
    request: Request,
    reservation_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    if current_user.role == UserRole.CUSTOMER and reservation.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    return APIResponse(data=get_reservation_dict(reservation))


@router.post("", response_model=APIResponse[ReservationResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def create_reservation(
    request: Request,
    reservation_data: ReservationCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    customer_id = reservation_data.customer_id
    if current_user.role == UserRole.CUSTOMER:
        customer_id = current_user.id
    elif not customer_id:
        raise HTTPException(status_code=400, detail="Customer ID is required")

    customer = db.query(User).filter(User.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=400, detail="Customer not found")

    if reservation_data.start_date >= reservation_data.end_date:
        raise HTTPException(status_code=400, detail="End date must be after start date")

    if reservation_data.start_date < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Start date must be in the future")

    device = db.query(Device).filter(Device.id == reservation_data.device_id).first()
    if not device:
        raise HTTPException(status_code=400, detail="Device not found")

    if not device.is_available_for_rent():
        raise HTTPException(
            status_code=400,
            detail=f"Device {device.serial_number} is not available for reservation",
        )

    if Reservation.check_time_conflict(db, reservation_data.device_id, reservation_data.start_date, reservation_data.end_date):
        raise HTTPException(
            status_code=400,
            detail=f"Device {device.serial_number} has a conflicting reservation in this time period",
        )

    new_reservation = Reservation(
        reservation_number=generate_reservation_number(),
        customer_id=customer_id,
        device_id=reservation_data.device_id,
        start_date=reservation_data.start_date,
        end_date=reservation_data.end_date,
        purpose=reservation_data.purpose,
        notes=reservation_data.notes,
        status=ReservationStatus.PENDING,
    )
    db.add(new_reservation)
    db.commit()
    db.refresh(new_reservation)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.RESERVE,
        resource_type="reservation",
        resource_id=str(new_reservation.id),
        user=current_user,
        new_values={
            "reservation_number": new_reservation.reservation_number,
            "customer_id": new_reservation.customer_id,
            "device_id": new_reservation.device_id,
            "start_date": new_reservation.start_date,
            "end_date": new_reservation.end_date,
            "status": new_reservation.status.value,
        },
        description=f"Reservation {new_reservation.reservation_number} created for device {device.serial_number}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Reservation created successfully", data=get_reservation_dict(new_reservation))


@router.put("/{reservation_id}", response_model=APIResponse[ReservationResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def update_reservation(
    request: Request,
    reservation_id: int,
    update_data: ReservationUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    if current_user.role == UserRole.CUSTOMER and reservation.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if reservation.status not in [ReservationStatus.PENDING]:
        raise HTTPException(status_code=400, detail="Only pending reservations can be updated")

    old_values = {c.name: getattr(reservation, c.name) for c in reservation.__table__.columns}

    if update_data.start_date and update_data.end_date:
        if update_data.start_date >= update_data.end_date:
            raise HTTPException(status_code=400, detail="End date must be after start date")
        if update_data.start_date < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="Start date must be in the future")

    new_start_date = update_data.start_date or reservation.start_date
    new_end_date = update_data.end_date or reservation.end_date

    if (update_data.start_date and update_data.start_date != reservation.start_date) or \
       (update_data.end_date and update_data.end_date != reservation.end_date):
        if Reservation.check_time_conflict(
            db,
            reservation.device_id,
            new_start_date,
            new_end_date,
            exclude_reservation_id=reservation.id,
        ):
            raise HTTPException(
                status_code=400,
                detail="Device has a conflicting reservation in the new time period",
            )

    if update_data.start_date:
        reservation.start_date = update_data.start_date
    if update_data.end_date:
        reservation.end_date = update_data.end_date
    if update_data.purpose is not None:
        reservation.purpose = update_data.purpose
    if update_data.notes is not None:
        reservation.notes = update_data.notes

    if reservation.status == ReservationStatus.CONFIRMED and reservation.lock_id:
        lock_service = DeviceLockService(db)
        lock = db.query(DeviceLock).filter(DeviceLock.id == reservation.lock_id).first()
        if lock and lock.is_valid():
            lock.expires_at = reservation.end_date

    db.commit()
    db.refresh(reservation)

    new_values = {c.name: getattr(reservation, c.name) for c in reservation.__table__.columns}

    audit_logger = AuditLogger(db)
    audit_logger.log_update(
        resource_type="reservation",
        resource_id=str(reservation_id),
        user=current_user,
        old_values=old_values,
        new_values=new_values,
        description=f"Reservation {reservation.reservation_number} updated",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Reservation updated successfully", data=get_reservation_dict(reservation))


@router.post("/{reservation_id}/confirm", response_model=APIResponse[ReservationResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def confirm_reservation(
    request: Request,
    reservation_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    if reservation.status != ReservationStatus.PENDING:
        raise HTTPException(status_code=400, detail="Only pending reservations can be confirmed")

    device = db.query(Device).filter(Device.id == reservation.device_id).first()
    if not device.is_available_for_rent():
        raise HTTPException(
            status_code=400,
            detail=f"Device {device.serial_number} is no longer available",
        )

    if Reservation.check_time_conflict(
        db,
        reservation.device_id,
        reservation.start_date,
        reservation.end_date,
        exclude_reservation_id=reservation.id,
    ):
        raise HTTPException(
            status_code=400,
            detail="Device has a conflicting reservation in this time period",
        )

    lock_service = DeviceLockService(db)

    if reservation.lock_id:
        existing_lock = db.query(DeviceLock).filter(DeviceLock.id == reservation.lock_id).first()
        if existing_lock and existing_lock.is_valid():
            lock_service.unlock_devices([reservation.device_id], current_user)

    locked, lock_token, errors, created_locks = lock_service.lock_devices_for_reservation(
        device_ids=[reservation.device_id],
        user=current_user,
        start_date=reservation.start_date,
        end_date=reservation.end_date,
        purpose=f"reservation-{reservation.reservation_number}",
    )

    if not locked:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    reservation.status = ReservationStatus.CONFIRMED
    reservation.confirmed_by_id = current_user.id
    reservation.confirmed_at = datetime.now(timezone.utc)
    if created_locks and len(created_locks) > 0:
        reservation.lock_id = created_locks[0].id

    db.commit()
    db.refresh(reservation)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.RESERVATION_CONFIRM,
        resource_type="reservation",
        resource_id=str(reservation_id),
        user=current_user,
        old_values={"status": ReservationStatus.PENDING.value},
        new_values={"status": ReservationStatus.CONFIRMED.value},
        description=f"Reservation {reservation.reservation_number} confirmed by {current_user.username}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Reservation confirmed successfully", data=get_reservation_dict(reservation))


@router.post("/{reservation_id}/cancel", response_model=APIResponse[ReservationResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def cancel_reservation(
    request: Request,
    reservation_id: int,
    cancel_data: Optional[ReservationCancelRequest] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    if current_user.role == UserRole.CUSTOMER and reservation.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if reservation.status not in [ReservationStatus.PENDING, ReservationStatus.CONFIRMED]:
        raise HTTPException(status_code=400, detail="Reservation cannot be cancelled")

    old_status = reservation.status.value if hasattr(reservation.status, "value") else str(reservation.status)

    if reservation.lock_id:
        lock_service = DeviceLockService(db)
        lock = db.query(DeviceLock).filter(DeviceLock.id == reservation.lock_id).first()
        if lock and lock.is_valid():
            lock_service.unlock_devices([reservation.device_id], current_user)

    reservation.status = ReservationStatus.CANCELLED
    reservation.cancelled_by_id = current_user.id
    reservation.cancelled_at = datetime.now(timezone.utc)
    if cancel_data and cancel_data.cancellation_reason:
        reservation.cancellation_reason = cancel_data.cancellation_reason
    if cancel_data and cancel_data.notes:
        reservation.notes = (reservation.notes or "") + f"\n\nCancellation notes: {cancel_data.notes}"

    db.commit()
    db.refresh(reservation)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.RESERVATION_CANCEL,
        resource_type="reservation",
        resource_id=str(reservation_id),
        user=current_user,
        old_values={"status": old_status},
        new_values={
            "status": ReservationStatus.CANCELLED.value,
            "cancellation_reason": reservation.cancellation_reason,
        },
        description=f"Reservation {reservation.reservation_number} cancelled by {current_user.username}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Reservation cancelled successfully", data=get_reservation_dict(reservation))


@router.patch("/{reservation_id}/status", response_model=APIResponse[ReservationResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def update_reservation_status(
    request: Request,
    reservation_id: int,
    status_data: ReservationStatusUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    old_status = reservation.status.value if hasattr(reservation.status, "value") else str(reservation.status)
    new_status = status_data.status.value if hasattr(status_data.status, "value") else str(status_data.status)

    if not reservation.can_transition_to(status_data.status):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status transition from {old_status} to {new_status}",
        )

    if status_data.status == ReservationStatus.CONFIRMED:
        return await confirm_reservation(request, reservation_id, current_user, db)

    if status_data.status == ReservationStatus.CANCELLED:
        return await cancel_reservation(request, reservation_id, status_data, current_user, db)

    if status_data.status == ReservationStatus.COMPLETED:
        if reservation.lock_id:
            lock_service = DeviceLockService(db)
            lock = db.query(DeviceLock).filter(DeviceLock.id == reservation.lock_id).first()
            if lock and lock.is_valid():
                lock_service.unlock_devices([reservation.device_id], current_user)

    reservation.status = status_data.status
    db.commit()
    db.refresh(reservation)

    audit_logger = AuditLogger(db)
    audit_logger.log_status_change(
        resource_type="reservation",
        resource_id=str(reservation_id),
        user=current_user,
        old_status=old_status,
        new_status=new_status,
        description=status_data.notes or f"Reservation status changed from {old_status} to {new_status}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Reservation status updated successfully", data=get_reservation_dict(reservation))


@router.get("/check/availability", response_model=APIResponse)
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def check_device_availability(
    request: Request,
    device_id: int,
    start_date: datetime,
    end_date: datetime,
    exclude_reservation_id: Optional[int] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    if start_date >= end_date:
        raise HTTPException(status_code=400, detail="End date must be after start date")

    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=400, detail="Device not found")

    is_available = device.is_available_for_rent()

    has_conflict = Reservation.check_time_conflict(
        db,
        device_id,
        start_date,
        end_date,
        exclude_reservation_id=exclude_reservation_id,
    )

    lock_service = DeviceLockService(db)
    active_lock = lock_service.get_active_lock(device_id)
    is_locked = active_lock is not None and (current_user.role not in [UserRole.ADMIN, UserRole.STAFF] or (active_lock and active_lock.user_id != current_user.id))

    return APIResponse(data={
        "device_id": device_id,
        "is_available_for_rent": is_available,
        "has_time_conflict": has_conflict,
        "is_locked": is_locked,
        "can_reserve": is_available and not has_conflict and not is_locked,
        "start_date": start_date,
        "end_date": end_date,
    })


@router.delete("/{reservation_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN])
async def delete_reservation(
    request: Request,
    reservation_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    if reservation.status in [ReservationStatus.CONFIRMED]:
        if reservation.lock_id:
            lock_service = DeviceLockService(db)
            lock = db.query(DeviceLock).filter(DeviceLock.id == reservation.lock_id).first()
            if lock and lock.is_valid():
                lock_service.unlock_devices([reservation.device_id], current_user)

    old_values = {
        "reservation_number": reservation.reservation_number,
        "customer_id": reservation.customer_id,
        "device_id": reservation.device_id,
        "status": reservation.status.value if hasattr(reservation.status, "value") else str(reservation.status),
    }

    db.delete(reservation)
    db.commit()

    audit_logger = AuditLogger(db)
    audit_logger.log_delete(
        resource_type="reservation",
        resource_id=str(reservation_id),
        user=current_user,
        old_values=old_values,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Reservation deleted successfully")

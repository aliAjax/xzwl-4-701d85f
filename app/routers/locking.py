from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..models.user import User, UserRole
from ..models.device_lock import DeviceLock
from ..schemas import (
    LockDevicesRequest,
    UnlockDevicesRequest,
    LockResponse,
    DeviceLockResponse,
    APIResponse,
)
from ..core import get_current_active_user, require_role, DeviceLockService, AuditLogger, AuditAction

router = APIRouter(prefix="/api/locking", tags=["Device Locking"])


@router.post("/lock", response_model=APIResponse[LockResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def lock_devices(
    request: Request,
    lock_request: LockDevicesRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    lock_service = DeviceLockService(db)
    success, lock_token, errors = lock_service.lock_devices(
        device_ids=lock_request.device_ids,
        user=current_user,
        purpose=lock_request.purpose,
    )

    if not success:
        return APIResponse(
            success=False,
            message="Failed to lock devices",
            data=LockResponse(
                success=False,
                lock_token=None,
                message="Failed to lock devices",
                errors=errors,
            ),
        )

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.LOCK,
        resource_type="device",
        resource_id=",".join(map(str, lock_request.device_ids)),
        user=current_user,
        new_values={
            "device_ids": lock_request.device_ids,
            "lock_token": lock_token,
            "purpose": lock_request.purpose,
        },
        description=f"Locked devices: {lock_request.device_ids}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Devices locked successfully",
        data=LockResponse(
            success=True,
            lock_token=lock_token,
            message="Devices locked successfully",
            errors=[],
        ),
    )


@router.post("/unlock", response_model=APIResponse[LockResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def unlock_devices(
    request: Request,
    unlock_request: UnlockDevicesRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    lock_service = DeviceLockService(db)
    success, errors = lock_service.unlock_devices(
        device_ids=unlock_request.device_ids,
        user=current_user,
    )

    if not success:
        return APIResponse(
            success=False,
            message="Failed to unlock devices",
            data=LockResponse(
                success=False,
                lock_token=None,
                message="Failed to unlock devices",
                errors=errors,
            ),
        )

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.UNLOCK,
        resource_type="device",
        resource_id=",".join(map(str, unlock_request.device_ids)),
        user=current_user,
        new_values={"device_ids": unlock_request.device_ids},
        description=f"Unlocked devices: {unlock_request.device_ids}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Devices unlocked successfully",
        data=LockResponse(
            success=True,
            lock_token=None,
            message="Devices unlocked successfully",
            errors=errors,
        ),
    )


@router.post("/unlock/{lock_token}", response_model=APIResponse[LockResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def unlock_by_token(
    request: Request,
    lock_token: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    lock_service = DeviceLockService(db)
    success = lock_service.unlock_by_token(lock_token, current_user)

    if not success:
        return APIResponse(
            success=False,
            message="Failed to unlock devices by token",
            data=LockResponse(
                success=False,
                lock_token=None,
                message="Failed to unlock devices by token",
                errors=["Invalid token or permission denied"],
            ),
        )

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.UNLOCK,
        resource_type="device",
        resource_id=None,
        user=current_user,
        new_values={"lock_token": lock_token},
        description=f"Unlocked devices by token: {lock_token}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Devices unlocked successfully",
        data=LockResponse(
            success=True,
            lock_token=None,
            message="Devices unlocked successfully",
            errors=[],
        ),
    )


@router.post("/extend/{lock_token}", response_model=APIResponse[LockResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def extend_lock(
    request: Request,
    lock_token: str,
    minutes: int = 30,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    lock_service = DeviceLockService(db)
    success, errors = lock_service.extend_lock(lock_token, current_user, minutes)

    if not success:
        return APIResponse(
            success=False,
            message="Failed to extend lock",
            data=LockResponse(
                success=False,
                lock_token=None,
                message="Failed to extend lock",
                errors=errors,
            ),
        )

    return APIResponse(
        message=f"Lock extended by {minutes} minutes",
        data=LockResponse(
            success=True,
            lock_token=lock_token,
            message=f"Lock extended by {minutes} minutes",
            errors=errors,
        ),
    )


@router.get("/my-locks", response_model=APIResponse[List[DeviceLockResponse]])
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def get_my_locks(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    lock_service = DeviceLockService(db)
    locks = lock_service.get_user_locks(current_user)
    return APIResponse(data=locks)


@router.get("/device/{device_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def check_device_lock(
    device_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    lock_service = DeviceLockService(db)
    is_locked = lock_service.is_device_locked(device_id)
    active_lock = lock_service.get_active_lock(device_id)

    return APIResponse(data={
        "device_id": device_id,
        "is_locked": is_locked,
        "active_lock": active_lock,
    })


@router.get("/active", response_model=APIResponse[List[DeviceLockResponse]])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_all_active_locks(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    from datetime import datetime, timezone
    from ..models.device_lock import DeviceLock

    now = datetime.now(timezone.utc)
    locks = (
        db.query(DeviceLock)
        .filter(
            DeviceLock.is_active == 1,
            DeviceLock.expires_at > now,
        )
        .order_by(DeviceLock.created_at.desc())
        .all()
    )
    return APIResponse(data=locks)

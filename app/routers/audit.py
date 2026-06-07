from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional
from math import ceil
from datetime import datetime

from ..database import get_db
from ..models.user import User, UserRole
from ..models.audit import AuditLog, AuditAction
from ..schemas import AuditLogResponse, APIResponse, PaginatedResponse
from ..core import get_current_active_user, require_role

router = APIRouter(prefix="/api/audit", tags=["Audit Logs"])


@router.get("", response_model=PaginatedResponse[AuditLogResponse])
@require_role([UserRole.ADMIN])
async def list_audit_logs(
    page: int = 1,
    per_page: int = 20,
    user_id: Optional[int] = None,
    action: Optional[AuditAction] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if resource_id:
        query = query.filter(AuditLog.resource_id == resource_id)
    if start_date:
        query = query.filter(AuditLog.created_at >= start_date)
    if end_date:
        query = query.filter(AuditLog.created_at <= end_date)

    total = query.count()
    logs = query.order_by(AuditLog.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return PaginatedResponse(
        data=logs,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/{log_id}", response_model=APIResponse[AuditLogResponse])
@require_role([UserRole.ADMIN])
async def get_audit_log(
    log_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    log = db.query(AuditLog).filter(AuditLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Audit log not found")
    return APIResponse(data=log)


@router.get("/user/{user_id}", response_model=PaginatedResponse[AuditLogResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_user_audit_logs(
    user_id: int,
    page: int = 1,
    per_page: int = 20,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    if current_user.role == UserRole.CUSTOMER and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    query = db.query(AuditLog).filter(AuditLog.user_id == user_id)
    total = query.count()
    logs = query.order_by(AuditLog.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return PaginatedResponse(
        data=logs,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/resource/{resource_type}/{resource_id}", response_model=PaginatedResponse[AuditLogResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_resource_audit_logs(
    resource_type: str,
    resource_id: str,
    page: int = 1,
    per_page: int = 20,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog).filter(
        AuditLog.resource_type == resource_type,
        AuditLog.resource_id == resource_id,
    )
    total = query.count()
    logs = query.order_by(AuditLog.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return PaginatedResponse(
        data=logs,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/summary", response_model=APIResponse)
@require_role([UserRole.ADMIN])
async def get_audit_summary(
    days: int = 30,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    from datetime import timedelta, timezone
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    total_logs = db.query(AuditLog).filter(AuditLog.created_at >= cutoff).count()

    action_counts = {}
    for action in AuditAction:
        count = db.query(AuditLog).filter(
            AuditLog.action == action,
            AuditLog.created_at >= cutoff,
        ).count()
        if count > 0:
            action_counts[action.value if hasattr(action, "value") else str(action)] = count

    resource_counts = {}
    resource_types = db.query(AuditLog.resource_type).distinct().all()
    for rt in resource_types:
        count = db.query(AuditLog).filter(
            AuditLog.resource_type == rt[0],
            AuditLog.created_at >= cutoff,
        ).count()
        resource_counts[rt[0]] = count

    unique_users = db.query(AuditLog.user_id).filter(
        AuditLog.created_at >= cutoff
    ).distinct().count()

    return APIResponse(data={
        "days": days,
        "total_logs": total_logs,
        "unique_users": unique_users,
        "action_counts": action_counts,
        "resource_counts": resource_counts,
    })


@router.get("/my-logs", response_model=PaginatedResponse[AuditLogResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def get_my_audit_logs(
    page: int = 1,
    per_page: int = 20,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog).filter(AuditLog.user_id == current_user.id)
    total = query.count()
    logs = query.order_by(AuditLog.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return PaginatedResponse(
        data=logs,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )

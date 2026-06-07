from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional, List
from math import ceil

from ..database import get_db
from ..models.user import User, UserRole
from ..schemas import UserCreate, UserUpdate, UserResponse, APIResponse, PaginatedResponse
from ..core import get_current_active_user, require_role, get_password_hash, AuditLogger

router = APIRouter(prefix="/api/users", tags=["Users"])


@router.get("", response_model=PaginatedResponse[UserResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def list_users(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    role: Optional[UserRole] = None,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)
    if search:
        query = query.filter(
            (User.username.ilike(f"%{search}%")) |
            (User.full_name.ilike(f"%{search}%")) |
            (User.email.ilike(f"%{search}%"))
        )

    total = query.count()
    users = query.offset((page - 1) * per_page).limit(per_page).all()

    return PaginatedResponse(
        data=users,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/{user_id}", response_model=APIResponse[UserResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_user(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return APIResponse(data=user)


@router.post("", response_model=APIResponse[UserResponse])
@require_role([UserRole.ADMIN])
async def create_user(
    request: Request,
    user_data: UserCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(
        (User.username == user_data.username) |
        (User.email == user_data.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already exists")

    hashed_password = get_password_hash(user_data.password)
    new_user = User(
        username=user_data.username,
        email=user_data.email,
        full_name=user_data.full_name,
        phone=user_data.phone,
        hashed_password=hashed_password,
        role=user_data.role,
        address=user_data.address,
        id_card=user_data.id_card,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    audit_logger = AuditLogger(db)
    audit_logger.log_create(
        resource_type="user",
        resource_id=str(new_user.id),
        user=current_user,
        new_values={
            "username": new_user.username,
            "email": new_user.email,
            "full_name": new_user.full_name,
            "role": new_user.role.value,
        },
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="User created successfully", data=new_user)


@router.put("/{user_id}", response_model=APIResponse[UserResponse])
@require_role([UserRole.ADMIN])
async def update_user(
    request: Request,
    user_id: int,
    user_data: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    old_values = {
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "role": user.role.value,
        "is_active": user.is_active,
    }

    update_data = user_data.model_dump(exclude_unset=True)
    if "password" in update_data:
        update_data["hashed_password"] = get_password_hash(update_data.pop("password"))

    for field, value in update_data.items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)

    audit_logger = AuditLogger(db)
    audit_logger.log_update(
        resource_type="user",
        resource_id=str(user.id),
        user=current_user,
        old_values=old_values,
        new_values=update_data,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="User updated successfully", data=user)


@router.delete("/{user_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN])
async def delete_user(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    old_values = {
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
    }

    db.delete(user)
    db.commit()

    audit_logger = AuditLogger(db)
    audit_logger.log_delete(
        resource_type="user",
        resource_id=str(user_id),
        user=current_user,
        old_values=old_values,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="User deleted successfully")

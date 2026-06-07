from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta

from ..database import get_db
from ..models.user import User
from ..schemas import Token, UserCreate, UserResponse, APIResponse
from ..core import (
    verify_password,
    get_password_hash,
    create_access_token,
    get_current_user,
    AuditLogger,
)
from ..config import settings

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/register", response_model=APIResponse[UserResponse])
async def register(
    request: Request,
    user_data: UserCreate,
    db: Session = Depends(get_db),
):
    existing_user = db.query(User).filter(
        (User.username == user_data.username) |
        (User.email == user_data.email)
    ).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already registered"
        )

    if user_data.phone:
        existing_phone = db.query(User).filter(User.phone == user_data.phone).first()
        if existing_phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number already registered"
            )

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
        user=new_user,
        new_values={
            "username": new_user.username,
            "email": new_user.email,
            "full_name": new_user.full_name,
            "role": new_user.role.value,
        },
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        success=True,
        message="User registered successfully",
        data=new_user,
    )


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is disabled"
        )

    access_token_expires = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user.username,
            "user_id": user.id,
            "role": user.role.value,
        },
        expires_delta=access_token_expires,
    )

    audit_logger = AuditLogger(db)
    audit_logger.log_login(
        user=user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return Token(access_token=access_token, token_type="bearer")


@router.post("/logout", response_model=APIResponse)
async def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    audit_logger = AuditLogger(db)
    audit_logger.log_logout(
        user=current_user,
        ip_address=request.client.host if request.client else None,
    )
    return APIResponse(success=True, message="Logged out successfully")


@router.get("/me", response_model=APIResponse[UserResponse])
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    return APIResponse(success=True, message="User profile retrieved", data=current_user)

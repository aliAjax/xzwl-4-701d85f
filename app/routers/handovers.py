from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional
from math import ceil
from datetime import datetime, timezone

from ..database import get_db
from ..models.user import User, UserRole
from ..models.device import Device
from ..models.contract import Contract, ContractItem
from ..models.handover import Handover, HandoverType, HandoverStatus
from ..models.audit import AuditAction
from ..schemas import (
    HandoverCreate,
    HandoverUpdate,
    HandoverConfirm,
    HandoverResponse,
    APIResponse,
    PaginatedResponse,
)
from ..core import get_current_active_user, require_role, AuditLogger

router = APIRouter(prefix="/api/handovers", tags=["Handovers"])


def _model_to_dict(model) -> Optional[dict]:
    if model is None:
        return None
    return {c.name: getattr(model, c.name) for c in model.__table__.columns}


def _generate_handover_number(db: Session) -> str:
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"HD{date_str}"
    last_handover = db.query(Handover).filter(
        Handover.handover_number.like(f"{prefix}%")
    ).order_by(Handover.handover_number.desc()).first()
    if last_handover:
        sequence = int(last_handover.handover_number[-4:]) + 1
    else:
        sequence = 1
    return f"{prefix}{sequence:04d}"


def _check_contract_device_relation(db: Session, contract_id: int, device_id: int) -> bool:
    contract_item = db.query(ContractItem).filter(
        ContractItem.contract_id == contract_id,
        ContractItem.device_id == device_id,
    ).first()
    return contract_item is not None


def build_handover_response(handover: Handover) -> dict:
    handover_dict = _model_to_dict(handover) or {}

    if handover.device:
        device = handover.device
        device_dict = _model_to_dict(device) or {}
        device_dict["is_available_for_rent"] = device.is_available_for_rent()
        device_dict["needs_maintenance"] = device.needs_maintenance()
        device_dict["category"] = _model_to_dict(device.category)
        handover_dict["device"] = device_dict
    else:
        handover_dict["device"] = None

    if handover.contract:
        contract_dict = _model_to_dict(handover.contract) or {}
        contract_dict["customer"] = _model_to_dict(handover.contract.customer)
        contract_dict["created_by_user"] = _model_to_dict(handover.contract.created_by_user)
        handover_dict["contract"] = contract_dict
    else:
        handover_dict["contract"] = None

    handover_dict["created_by"] = _model_to_dict(handover.created_by)
    handover_dict["confirmed_by_staff"] = _model_to_dict(handover.confirmed_by_staff)
    handover_dict["confirmed_by_customer"] = _model_to_dict(handover.confirmed_by_customer)

    return handover_dict


def _get_handover_for_user(
    db: Session,
    handover_id: int,
    current_user: User,
) -> Handover:
    handover = db.query(Handover).filter(Handover.id == handover_id).first()
    if not handover:
        raise HTTPException(status_code=404, detail="Handover record not found")

    if current_user.role == UserRole.CUSTOMER:
        if handover.contract.customer_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="You can only view handovers associated with your contracts",
            )

    return handover


@router.get("", response_model=PaginatedResponse[HandoverResponse])
async def list_handovers(
    page: int = 1,
    per_page: int = 20,
    status: Optional[HandoverStatus] = None,
    handover_type: Optional[HandoverType] = None,
    contract_id: Optional[int] = None,
    device_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    query = db.query(Handover)

    if current_user.role == UserRole.CUSTOMER:
        query = query.join(Contract).filter(Contract.customer_id == current_user.id)

    if status:
        query = query.filter(Handover.status == status)
    if handover_type:
        query = query.filter(Handover.handover_type == handover_type)
    if contract_id:
        query = query.filter(Handover.contract_id == contract_id)
    if device_id:
        query = query.filter(Handover.device_id == device_id)

    query = query.order_by(Handover.created_at.desc())
    total = query.count()
    handovers = query.offset((page - 1) * per_page).limit(per_page).all()

    response_data = [build_handover_response(h) for h in handovers]

    return PaginatedResponse(
        data=response_data,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/{handover_id}", response_model=APIResponse[HandoverResponse])
async def get_handover(
    handover_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    handover = _get_handover_for_user(db, handover_id, current_user)
    return APIResponse(data=build_handover_response(handover))


@router.post("", response_model=APIResponse[HandoverResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def create_handover(
    request: Request,
    handover_data: HandoverCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    contract = db.query(Contract).filter(Contract.id == handover_data.contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    device = db.query(Device).filter(Device.id == handover_data.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    if not _check_contract_device_relation(db, handover_data.contract_id, handover_data.device_id):
        raise HTTPException(
            status_code=400,
            detail="The specified device is not part of the contract",
        )

    if handover_data.handover_type == HandoverType.OUTBOUND:
        existing_outbound = db.query(Handover).filter(
            Handover.contract_id == handover_data.contract_id,
            Handover.device_id == handover_data.device_id,
            Handover.handover_type == HandoverType.OUTBOUND,
            Handover.status.in_([HandoverStatus.PENDING, HandoverStatus.CONFIRMED]),
        ).first()
        if existing_outbound:
            raise HTTPException(
                status_code=400,
                detail=f"An outbound handover already exists for this contract and device (ID: {existing_outbound.id})",
            )

    if handover_data.handover_type == HandoverType.RETURN:
        outbound_handover = db.query(Handover).filter(
            Handover.contract_id == handover_data.contract_id,
            Handover.device_id == handover_data.device_id,
            Handover.handover_type == HandoverType.OUTBOUND,
            Handover.status == HandoverStatus.CONFIRMED,
        ).first()
        if not outbound_handover:
            raise HTTPException(
                status_code=400,
                detail="Cannot create return handover without a confirmed outbound handover",
            )

        existing_return = db.query(Handover).filter(
            Handover.contract_id == handover_data.contract_id,
            Handover.device_id == handover_data.device_id,
            Handover.handover_type == HandoverType.RETURN,
            Handover.status.in_([HandoverStatus.PENDING, HandoverStatus.CONFIRMED]),
        ).first()
        if existing_return:
            raise HTTPException(
                status_code=400,
                detail=f"A return handover already exists for this contract and device (ID: {existing_return.id})",
            )

    handover_number = _generate_handover_number(db)

    new_handover = Handover(
        handover_number=handover_number,
        **handover_data.model_dump(),
        created_by_id=current_user.id,
    )

    db.add(new_handover)
    db.commit()
    db.refresh(new_handover)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.HANDOVER_CREATE,
        resource_type="handover",
        resource_id=str(new_handover.id),
        user=current_user,
        new_values={
            "handover_number": handover_number,
            "contract_id": handover_data.contract_id,
            "device_id": handover_data.device_id,
            "handover_type": handover_data.handover_type.value,
            "appearance_description": handover_data.appearance_description,
            "accessories": handover_data.accessories,
            "abnormal_remarks": handover_data.abnormal_remarks,
        },
        description=f"Created {handover_data.handover_type.value} handover {handover_number} for device {device.serial_number}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Handover record created successfully",
        data=build_handover_response(new_handover),
    )


@router.put("/{handover_id}", response_model=APIResponse[HandoverResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def update_handover(
    request: Request,
    handover_id: int,
    update_data: HandoverUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    handover = _get_handover_for_user(db, handover_id, current_user)

    if handover.status != HandoverStatus.DRAFT:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update handover with status '{handover.status.value}'. Only draft handovers can be updated.",
        )

    old_values = {
        "appearance_description": handover.appearance_description,
        "accessories": handover.accessories,
        "abnormal_remarks": handover.abnormal_remarks,
    }

    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(handover, key, value)

    db.commit()
    db.refresh(handover)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.HANDOVER_UPDATE,
        resource_type="handover",
        resource_id=str(handover_id),
        user=current_user,
        old_values=old_values,
        new_values={
            "appearance_description": handover.appearance_description,
            "accessories": handover.accessories,
            "abnormal_remarks": handover.abnormal_remarks,
        },
        description=f"Updated handover {handover.handover_number}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Handover record updated successfully",
        data=build_handover_response(handover),
    )


@router.patch("/{handover_id}/submit", response_model=APIResponse[HandoverResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def submit_handover(
    request: Request,
    handover_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    handover = _get_handover_for_user(db, handover_id, current_user)

    if handover.status != HandoverStatus.DRAFT:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot submit handover with status '{handover.status.value}'. Only draft handovers can be submitted.",
        )

    old_status = handover.status.value
    handover.status = HandoverStatus.PENDING
    handover.confirmed_by_staff_id = current_user.id
    handover.staff_confirmed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(handover)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.HANDOVER_CONFIRM,
        resource_type="handover",
        resource_id=str(handover_id),
        user=current_user,
        old_values={"status": old_status},
        new_values={
            "status": HandoverStatus.PENDING.value,
            "confirmed_by_staff_id": current_user.id,
        },
        description=f"Submitted handover {handover.handover_number} for customer confirmation",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Handover submitted successfully, waiting for customer confirmation",
        data=build_handover_response(handover),
    )


@router.patch("/{handover_id}/confirm", response_model=APIResponse[HandoverResponse])
async def confirm_handover(
    request: Request,
    handover_id: int,
    confirm_data: HandoverConfirm,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    handover = _get_handover_for_user(db, handover_id, current_user)

    if current_user.role == UserRole.CUSTOMER:
        if handover.status != HandoverStatus.PENDING:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot confirm handover with status '{handover.status.value}'. Only pending handovers can be confirmed.",
            )

        old_status = handover.status.value
        handover.status = HandoverStatus.CONFIRMED
        handover.confirmed_by_customer_id = current_user.id
        handover.customer_confirmed_at = datetime.now(timezone.utc)

        confirm_dict = confirm_data.model_dump(exclude_unset=True)
        for key, value in confirm_dict.items():
            if value is not None:
                setattr(handover, key, value)

        db.commit()
        db.refresh(handover)

        audit_logger = AuditLogger(db)
        audit_logger.log(
            action=AuditAction.HANDOVER_CONFIRM,
            resource_type="handover",
            resource_id=str(handover_id),
            user=current_user,
            old_values={"status": old_status},
            new_values={
                "status": HandoverStatus.CONFIRMED.value,
                "confirmed_by_customer_id": current_user.id,
            },
            description=f"Customer confirmed handover {handover.handover_number}",
            ip_address=request.client.host if request.client else None,
        )

        return APIResponse(
            message="Handover confirmed successfully",
            data=build_handover_response(handover),
        )
    else:
        if handover.status != HandoverStatus.DRAFT:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot confirm handover with status '{handover.status.value}'. Only draft handovers can be confirmed by staff.",
            )

        old_status = handover.status.value
        handover.status = HandoverStatus.CONFIRMED
        handover.confirmed_by_staff_id = current_user.id
        handover.staff_confirmed_at = datetime.now(timezone.utc)

        confirm_dict = confirm_data.model_dump(exclude_unset=True)
        for key, value in confirm_dict.items():
            if value is not None:
                setattr(handover, key, value)

        db.commit()
        db.refresh(handover)

        audit_logger = AuditLogger(db)
        audit_logger.log(
            action=AuditAction.HANDOVER_CONFIRM,
            resource_type="handover",
            resource_id=str(handover_id),
            user=current_user,
            old_values={"status": old_status},
            new_values={
                "status": HandoverStatus.CONFIRMED.value,
                "confirmed_by_staff_id": current_user.id,
            },
            description=f"Staff confirmed handover {handover.handover_number}",
            ip_address=request.client.host if request.client else None,
        )

        return APIResponse(
            message="Handover confirmed successfully by staff",
            data=build_handover_response(handover),
        )


@router.patch("/{handover_id}/cancel", response_model=APIResponse[HandoverResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def cancel_handover(
    request: Request,
    handover_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    handover = _get_handover_for_user(db, handover_id, current_user)

    if handover.status == HandoverStatus.CONFIRMED:
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel a confirmed handover",
        )

    if handover.status == HandoverStatus.CANCELLED:
        raise HTTPException(
            status_code=400,
            detail="Handover is already cancelled",
        )

    old_status = handover.status.value
    handover.status = HandoverStatus.CANCELLED

    db.commit()
    db.refresh(handover)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.HANDOVER_CANCEL,
        resource_type="handover",
        resource_id=str(handover_id),
        user=current_user,
        old_values={"status": old_status},
        new_values={"status": HandoverStatus.CANCELLED.value},
        description=f"Cancelled handover {handover.handover_number}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Handover cancelled successfully",
        data=build_handover_response(handover),
    )


@router.get("/contract/{contract_id}", response_model=APIResponse)
async def get_contract_handovers(
    contract_id: int,
    page: int = 1,
    per_page: int = 20,
    status: Optional[HandoverStatus] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    if current_user.role == UserRole.CUSTOMER and contract.customer_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You can only view handovers associated with your contracts",
        )

    query = db.query(Handover).filter(Handover.contract_id == contract_id)
    if status:
        query = query.filter(Handover.status == status)

    query = query.order_by(Handover.created_at.desc())
    total = query.count()
    handovers = query.offset((page - 1) * per_page).limit(per_page).all()

    response_data = [build_handover_response(h) for h in handovers]

    return APIResponse(data={
        "contract_id": contract_id,
        "contract_number": contract.contract_number,
        "handovers": response_data,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": ceil(total / per_page),
    })


@router.get("/device/{device_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_device_handovers(
    device_id: int,
    page: int = 1,
    per_page: int = 20,
    status: Optional[HandoverStatus] = None,
    handover_type: Optional[HandoverType] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    query = db.query(Handover).filter(Handover.device_id == device_id)
    if status:
        query = query.filter(Handover.status == status)
    if handover_type:
        query = query.filter(Handover.handover_type == handover_type)

    query = query.order_by(Handover.created_at.desc())
    total = query.count()
    handovers = query.offset((page - 1) * per_page).limit(per_page).all()

    response_data = [build_handover_response(h) for h in handovers]

    return APIResponse(data={
        "device_id": device_id,
        "serial_number": device.serial_number,
        "device_name": device.name,
        "handovers": response_data,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": ceil(total / per_page),
    })

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional
from math import ceil
from datetime import datetime, timezone

from ..database import get_db
from ..models.user import User, UserRole
from ..models.deposit import Deposit, DepositStatus
from ..models.contract import Contract
from ..schemas import (
    DepositCreate,
    DepositUpdate,
    DepositResponse,
    DepositRefundRequest,
    APIResponse,
    PaginatedResponse,
)
from ..core import get_current_active_user, require_role, AuditLogger, AuditAction

router = APIRouter(prefix="/api/deposits", tags=["Deposits"])


@router.get("", response_model=PaginatedResponse[DepositResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def list_deposits(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    contract_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = db.query(Deposit)
    if current_user.role == UserRole.CUSTOMER:
        query = query.filter(Deposit.customer_id == current_user.id)
    elif customer_id:
        query = query.filter(Deposit.customer_id == customer_id)
    if contract_id:
        query = query.filter(Deposit.contract_id == contract_id)
    if status:
        query = query.filter(Deposit.status == status)

    total = query.count()
    deposits = query.order_by(Deposit.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return PaginatedResponse(
        data=deposits,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/{deposit_id}", response_model=APIResponse[DepositResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def get_deposit(
    request: Request,
    deposit_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    deposit = db.query(Deposit).filter(Deposit.id == deposit_id).first()
    if not deposit:
        raise HTTPException(status_code=404, detail="Deposit not found")

    if current_user.role == UserRole.CUSTOMER and deposit.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    return APIResponse(data=deposit)


@router.post("", response_model=APIResponse[DepositResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def create_deposit(
    request: Request,
    deposit_data: DepositCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    contract = db.query(Contract).filter(Contract.id == deposit_data.contract_id).first()
    if not contract:
        raise HTTPException(status_code=400, detail="Contract not found")

    if contract.customer_id != deposit_data.customer_id:
        raise HTTPException(status_code=400, detail="Customer ID does not match contract")

    new_deposit = Deposit(**deposit_data.model_dump())
    new_deposit.status = "paid"
    db.add(new_deposit)
    db.commit()
    db.refresh(new_deposit)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.DEPOSIT_PAY,
        resource_type="deposit",
        resource_id=str(new_deposit.id),
        user=current_user,
        new_values={
            "contract_id": new_deposit.contract_id,
            "customer_id": new_deposit.customer_id,
            "amount": new_deposit.amount,
            "payment_method": new_deposit.payment_method,
        },
        description=f"Deposit of {new_deposit.amount} received for contract {contract.contract_number}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Deposit created successfully", data=new_deposit)


@router.post("/{deposit_id}/refund", response_model=APIResponse[DepositResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def refund_deposit(
    request: Request,
    deposit_id: int,
    refund_data: DepositRefundRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    deposit = db.query(Deposit).filter(Deposit.id == deposit_id).first()
    if not deposit:
        raise HTTPException(status_code=404, detail="Deposit not found")

    if deposit.status in ["full_refund", "forfeited"]:
        raise HTTPException(status_code=400, detail="Deposit already fully processed")

    if refund_data.refund_amount > deposit.amount:
        raise HTTPException(status_code=400, detail="Refund amount cannot exceed deposit amount")

    deposit.refund_amount = refund_data.refund_amount
    deposit.refund_date = refund_data.refund_date or datetime.now(timezone.utc)
    deposit.refund_method = refund_data.refund_method
    deposit.refund_transaction_id = refund_data.refund_transaction_id
    deposit.deductions = refund_data.deductions
    deposit.notes = (deposit.notes or "") + f"\n\n{refund_data.notes or ''}"

    if refund_data.refund_amount == deposit.amount:
        deposit.status = "full_refund"
    elif refund_data.refund_amount > 0:
        deposit.status = "partial_refund"
    else:
        deposit.status = "forfeited"

    if deposit.status == "full_refund":
        contract = db.query(Contract).filter(Contract.id == deposit.contract_id).first()
        if contract:
            contract.deposit_refunded = True
            contract.deposit_refund_date = deposit.refund_date

    db.commit()
    db.refresh(deposit)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.DEPOSIT_REFUND,
        resource_type="deposit",
        resource_id=str(deposit_id),
        user=current_user,
        old_values={"status": deposit.status},
        new_values={
            "refund_amount": deposit.refund_amount,
            "status": deposit.status,
        },
        description=f"Deposit refunded: {refund_data.refund_amount}, status: {deposit.status}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Deposit refund processed successfully", data=deposit)


@router.put("/{deposit_id}", response_model=APIResponse[DepositResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def update_deposit(
    request: Request,
    deposit_id: int,
    deposit_data: DepositUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    deposit = db.query(Deposit).filter(Deposit.id == deposit_id).first()
    if not deposit:
        raise HTTPException(status_code=404, detail="Deposit not found")

    old_values = {
        "amount": deposit.amount,
        "status": deposit.status,
        "payment_method": deposit.payment_method,
    }

    update_data = deposit_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(deposit, field, value)

    db.commit()
    db.refresh(deposit)

    audit_logger = AuditLogger(db)
    audit_logger.log_update(
        resource_type="deposit",
        resource_id=str(deposit_id),
        user=current_user,
        old_values=old_values,
        new_values=update_data,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Deposit updated successfully", data=deposit)


@router.delete("/{deposit_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN])
async def delete_deposit(
    request: Request,
    deposit_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    deposit = db.query(Deposit).filter(Deposit.id == deposit_id).first()
    if not deposit:
        raise HTTPException(status_code=404, detail="Deposit not found")

    old_values = {
        "contract_id": deposit.contract_id,
        "amount": deposit.amount,
        "status": deposit.status,
        "id": deposit.id,
    }

    db.delete(deposit)
    db.commit()

    audit_logger = AuditLogger(db)
    audit_logger.log_delete(
        resource_type="deposit",
        resource_id=str(deposit_id),
        user=current_user,
        old_values=old_values,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Deposit deleted successfully")


@router.get("/contract/{contract_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN, UserRole.STAFF, UserRole.CUSTOMER])
async def get_contract_deposits(
    request: Request,
    contract_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    if current_user.role == UserRole.CUSTOMER and contract.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    deposits = db.query(Deposit).filter(Deposit.contract_id == contract_id).all()
    total_paid = sum(d.amount for d in deposits)
    total_refunded = sum(d.refund_amount or 0 for d in deposits)

    return APIResponse(data={
        "contract_id": contract_id,
        "contract_number": contract.contract_number,
        "expected_deposit": contract.deposit_amount,
        "total_paid": total_paid,
        "total_refunded": total_refunded,
        "balance": total_paid - total_refunded,
        "deposits": deposits,
    })

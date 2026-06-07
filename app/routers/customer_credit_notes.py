from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional
from math import ceil
from datetime import datetime, timezone

from ..database import get_db
from ..models.user import User, UserRole
from ..models.contract import Contract
from ..models.customer_credit_note import CustomerCreditNote, RiskTag
from ..schemas import APIResponse, PaginatedResponse
from ..schemas.customer_credit_note import (
    CustomerCreditNoteCreate,
    CustomerCreditNoteUpdate,
    CustomerCreditNoteResolve,
    CustomerCreditNoteResponse,
    CustomerRiskSummary,
    RiskSummaryItem,
)
from ..core import (
    get_current_active_user,
    require_role,
    AuditLogger,
    AuditAction,
)

router = APIRouter(prefix="/api/customer-credit-notes", tags=["Customer Credit Notes"])


def get_credit_note_dict(note: CustomerCreditNote) -> dict:
    return {c.name: getattr(note, c.name) for c in note.__table__.columns}


def get_customer_risk_summary_sync(db: Session, customer_id: int) -> Optional[CustomerRiskSummary]:
    customer = db.query(User).filter(User.id == customer_id, User.role == UserRole.CUSTOMER).first()
    if not customer:
        return None

    active_notes = db.query(CustomerCreditNote).filter(
        CustomerCreditNote.customer_id == customer_id,
        CustomerCreditNote.is_active == True,
    ).all()

    risk_summary = []
    for tag in RiskTag:
        count = sum(1 for n in active_notes if n.risk_tag == tag)
        if count > 0:
            risk_summary.append(RiskSummaryItem(risk_tag=tag, count=count))

    latest_note = db.query(CustomerCreditNote).filter(
        CustomerCreditNote.customer_id == customer_id,
    ).order_by(CustomerCreditNote.created_at.desc()).first()

    summary = CustomerRiskSummary(
        customer_id=customer_id,
        total_active_notes=len(active_notes),
        risk_summary=risk_summary,
        latest_note=CustomerCreditNoteResponse.model_validate(latest_note) if latest_note else None,
    )

    return summary


@router.get("", response_model=PaginatedResponse[CustomerCreditNoteResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def list_credit_notes(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    customer_id: Optional[int] = None,
    risk_tag: Optional[RiskTag] = None,
    is_active: Optional[bool] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = db.query(CustomerCreditNote)
    if customer_id:
        query = query.filter(CustomerCreditNote.customer_id == customer_id)
    if risk_tag:
        query = query.filter(CustomerCreditNote.risk_tag == risk_tag)
    if is_active is not None:
        query = query.filter(CustomerCreditNote.is_active == is_active)

    total = query.count()
    notes = query.order_by(CustomerCreditNote.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    response_data = [get_credit_note_dict(n) for n in notes]

    return PaginatedResponse(
        data=response_data,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/{note_id}", response_model=APIResponse[CustomerCreditNoteResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_credit_note(
    request: Request,
    note_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    note = db.query(CustomerCreditNote).filter(CustomerCreditNote.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Credit note not found")

    return APIResponse(data=get_credit_note_dict(note))


@router.get("/customer/{customer_id}/summary", response_model=APIResponse[CustomerRiskSummary])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_customer_risk_summary(
    request: Request,
    customer_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    summary = get_customer_risk_summary_sync(db, customer_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Customer not found")

    return APIResponse(data=summary)


@router.post("", response_model=APIResponse[CustomerCreditNoteResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def create_credit_note(
    request: Request,
    note_data: CustomerCreditNoteCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    customer = db.query(User).filter(User.id == note_data.customer_id, User.role == UserRole.CUSTOMER).first()
    if not customer:
        raise HTTPException(status_code=400, detail="Customer not found")

    if note_data.related_contract_id:
        contract = db.query(Contract).filter(Contract.id == note_data.related_contract_id).first()
        if not contract:
            raise HTTPException(status_code=400, detail="Related contract not found")

    new_note = CustomerCreditNote(
        customer_id=note_data.customer_id,
        created_by_id=current_user.id,
        risk_tag=note_data.risk_tag,
        title=note_data.title,
        content=note_data.content,
        related_contract_id=note_data.related_contract_id,
    )
    db.add(new_note)
    db.commit()
    db.refresh(new_note)

    audit_logger = AuditLogger(db)
    audit_logger.log_create(
        resource_type="customer_credit_note",
        resource_id=str(new_note.id),
        user=current_user,
        new_values={
            "customer_id": new_note.customer_id,
            "risk_tag": new_note.risk_tag.value,
            "title": new_note.title,
            "related_contract_id": new_note.related_contract_id,
        },
        description=f"Credit note created for customer {customer.full_name}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Credit note created successfully", data=get_credit_note_dict(new_note))


@router.patch("/{note_id}", response_model=APIResponse[CustomerCreditNoteResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def update_credit_note(
    request: Request,
    note_id: int,
    note_data: CustomerCreditNoteUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    note = db.query(CustomerCreditNote).filter(CustomerCreditNote.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Credit note not found")

    old_values = get_credit_note_dict(note)

    if note_data.risk_tag is not None:
        note.risk_tag = note_data.risk_tag
    if note_data.title is not None:
        note.title = note_data.title
    if note_data.content is not None:
        note.content = note_data.content
    if note_data.related_contract_id is not None:
        if note_data.related_contract_id:
            contract = db.query(Contract).filter(Contract.id == note_data.related_contract_id).first()
            if not contract:
                raise HTTPException(status_code=400, detail="Related contract not found")
        note.related_contract_id = note_data.related_contract_id
    if note_data.is_active is not None:
        note.is_active = note_data.is_active

    db.commit()
    db.refresh(note)

    new_values = get_credit_note_dict(note)

    audit_logger = AuditLogger(db)
    audit_logger.log_update(
        resource_type="customer_credit_note",
        resource_id=str(note_id),
        user=current_user,
        old_values=old_values,
        new_values=new_values,
        description=f"Credit note {note_id} updated",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Credit note updated successfully", data=get_credit_note_dict(note))


@router.post("/{note_id}/resolve", response_model=APIResponse[CustomerCreditNoteResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def resolve_credit_note(
    request: Request,
    note_id: int,
    resolve_data: CustomerCreditNoteResolve,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    note = db.query(CustomerCreditNote).filter(CustomerCreditNote.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Credit note not found")

    if note.is_resolved():
        raise HTTPException(status_code=400, detail="Credit note is already resolved")

    old_values = get_credit_note_dict(note)

    note.is_active = False
    note.resolved_by_id = current_user.id
    note.resolved_at = datetime.now(timezone.utc)
    note.resolution_notes = resolve_data.resolution_notes

    db.commit()
    db.refresh(note)

    new_values = get_credit_note_dict(note)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.STATUS_CHANGE,
        resource_type="customer_credit_note",
        resource_id=str(note_id),
        user=current_user,
        old_values=old_values,
        new_values=new_values,
        description=f"Credit note {note_id} resolved",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Credit note resolved successfully", data=get_credit_note_dict(note))


@router.delete("/{note_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN])
async def delete_credit_note(
    request: Request,
    note_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    note = db.query(CustomerCreditNote).filter(CustomerCreditNote.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Credit note not found")

    old_values = get_credit_note_dict(note)

    db.delete(note)
    db.commit()

    audit_logger = AuditLogger(db)
    audit_logger.log_delete(
        resource_type="customer_credit_note",
        resource_id=str(note_id),
        user=current_user,
        old_values=old_values,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Credit note deleted successfully")

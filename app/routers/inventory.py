from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timezone
from math import ceil

from ..database import get_db
from ..models.user import User, UserRole
from ..models.device import Device, DeviceCategory
from ..models.warehouse import Warehouse
from ..models.inventory_commitment import CommitmentType, CommitmentStatus
from ..schemas import (
    InventoryCommitmentCreate,
    InventoryCommitmentCreateBulk,
    InventoryCommitmentUpdate,
    InventoryCommitmentResponse,
    AvailablePromiseQuery,
    AvailablePromiseResponse,
    CommitmentConfirmRequest,
    CommitmentReleaseRequest,
    BatchTokenRequest,
    APIResponse,
    PaginatedResponse,
)
from ..core import get_current_active_user, require_role, AuditLogger, InventoryCommitmentService

router = APIRouter(prefix="/api/inventory", tags=["Inventory Commitment"])


@router.get("/available", response_model=APIResponse[AvailablePromiseResponse])
async def get_available_to_promise(
    category_id: int,
    start_date: datetime,
    end_date: datetime,
    warehouse_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    if start_date >= end_date:
        raise HTTPException(status_code=400, detail="Start date must be before end date")

    if start_date < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Start date cannot be in the past")

    category = db.query(DeviceCategory).filter(DeviceCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    warehouse_name = None
    if warehouse_id:
        warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
        if warehouse:
            warehouse_name = warehouse.name

    service = InventoryCommitmentService(db)
    try:
        available, total_in_warehouse, committed_quantity, breakdown = service.get_available_to_promise(
            category_id=category_id,
            start_date=start_date,
            end_date=end_date,
            warehouse_id=warehouse_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    response = AvailablePromiseResponse(
        category_id=category_id,
        category_name=category.name,
        warehouse_id=warehouse_id,
        warehouse_name=warehouse_name,
        start_date=start_date,
        end_date=end_date,
        total_available=available,
        total_in_warehouse=total_in_warehouse,
        committed_quantity=committed_quantity,
        breakdown=breakdown,
    )

    return APIResponse(data=response)


@router.post("/available", response_model=APIResponse[AvailablePromiseResponse])
async def query_available_to_promise(
    query: AvailablePromiseQuery,
    db: Session = Depends(get_db),
):
    return await get_available_to_promise(
        category_id=query.category_id,
        start_date=query.start_date,
        end_date=query.end_date,
        warehouse_id=query.warehouse_id,
        db=db,
    )


@router.post("/commit", response_model=APIResponse[InventoryCommitmentResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def create_commitment(
    request: Request,
    commitment_data: InventoryCommitmentCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    if commitment_data.start_date >= commitment_data.end_date:
        raise HTTPException(status_code=400, detail="Start date must be before end date")

    service = InventoryCommitmentService(db)
    success, commitment, errors = service.create_commitment(
        device_id=commitment_data.device_id,
        warehouse_id=commitment_data.warehouse_id,
        category_id=commitment_data.category_id,
        commitment_type=commitment_data.commitment_type,
        start_date=commitment_data.start_date,
        end_date=commitment_data.end_date,
        user=current_user,
        reference_id=commitment_data.reference_id,
        reference_type=commitment_data.reference_type,
        notes=commitment_data.notes,
    )

    if not success:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    audit_logger = AuditLogger(db)
    audit_logger.log_create(
        resource_type="inventory_commitment",
        resource_id=str(commitment.id),
        user=current_user,
        new_values={
            "commitment_token": commitment.commitment_token,
            "device_id": commitment.device_id,
            "warehouse_id": commitment.warehouse_id,
            "commitment_type": commitment.commitment_type,
            "start_date": commitment.start_date.isoformat(),
            "end_date": commitment.end_date.isoformat(),
        },
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Commitment created successfully", data=commitment)


@router.post("/commit/bulk", response_model=APIResponse[List[InventoryCommitmentResponse]])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def create_commitments_bulk(
    request: Request,
    commitment_data: InventoryCommitmentCreateBulk,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    if commitment_data.start_date >= commitment_data.end_date:
        raise HTTPException(status_code=400, detail="Start date must be before end date")

    service = InventoryCommitmentService(db)
    success, commitments, errors = service.create_commitments_bulk(
        device_ids=commitment_data.device_ids,
        warehouse_id=commitment_data.warehouse_id,
        category_id=commitment_data.category_id,
        commitment_type=commitment_data.commitment_type,
        start_date=commitment_data.start_date,
        end_date=commitment_data.end_date,
        user=current_user,
        reference_id=commitment_data.reference_id,
        reference_type=commitment_data.reference_type,
        notes=commitment_data.notes,
    )

    if not success:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    audit_logger = AuditLogger(db)
    for commitment in commitments:
        audit_logger.log_create(
            resource_type="inventory_commitment",
            resource_id=str(commitment.id),
            user=current_user,
            new_values={
                "commitment_token": commitment.commitment_token,
                "device_id": commitment.device_id,
                "warehouse_id": commitment.warehouse_id,
                "commitment_type": commitment.commitment_type,
            },
            ip_address=request.client.host if request.client else None,
        )

    return APIResponse(message="Bulk commitments created successfully", data=commitments)


@router.post("/commit/confirm", response_model=APIResponse[List[InventoryCommitmentResponse]])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def confirm_commitment(
    request: Request,
    confirm_data: CommitmentConfirmRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service = InventoryCommitmentService(db)
    success, commitments, errors = service.confirm_commitment(
        token=confirm_data.commitment_token,
        user=current_user,
        is_batch=False,
    )

    if not success:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    audit_logger = AuditLogger(db)
    for commitment in commitments:
        audit_logger.log(
            action="confirm",
            resource_type="inventory_commitment",
            resource_id=commitment.commitment_token,
            user=current_user,
            old_values={"status": CommitmentStatus.PENDING.value},
            new_values={"status": CommitmentStatus.CONFIRMED.value},
            description=f"Commitment {commitment.commitment_token} confirmed",
            ip_address=request.client.host if request.client else None,
        )

    return APIResponse(message="Commitment confirmed successfully", data=commitments)


@router.post("/commit/batch/confirm", response_model=APIResponse[List[InventoryCommitmentResponse]])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def confirm_commitments_batch(
    request: Request,
    confirm_data: BatchTokenRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service = InventoryCommitmentService(db)
    success, commitments, errors = service.confirm_commitment(
        token=confirm_data.batch_token,
        user=current_user,
        is_batch=True,
    )

    if not success:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    audit_logger = AuditLogger(db)
    for commitment in commitments:
        audit_logger.log(
            action="confirm",
            resource_type="inventory_commitment",
            resource_id=commitment.commitment_token,
            user=current_user,
            old_values={"status": CommitmentStatus.PENDING.value},
            new_values={"status": CommitmentStatus.CONFIRMED.value},
            description=f"Commitment {commitment.commitment_token} confirmed (batch {confirm_data.batch_token})",
            ip_address=request.client.host if request.client else None,
        )

    return APIResponse(message="Batch commitments confirmed successfully", data=commitments)


@router.post("/commit/release", response_model=APIResponse)
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def release_commitment(
    request: Request,
    release_data: CommitmentReleaseRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service = InventoryCommitmentService(db)
    success, errors = service.release_commitment(
        token=release_data.commitment_token,
        user=current_user,
        is_batch=False,
    )

    if not success:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action="release",
        resource_type="inventory_commitment",
        resource_id=release_data.commitment_token,
        user=current_user,
        old_values={"status": "active"},
        new_values={"status": CommitmentStatus.CANCELLED.value},
        description=f"Commitment {release_data.commitment_token} released",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Commitment released successfully")


@router.post("/commit/batch/release", response_model=APIResponse)
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def release_commitments_batch(
    request: Request,
    release_data: BatchTokenRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service = InventoryCommitmentService(db)
    success, errors = service.release_commitment(
        token=release_data.batch_token,
        user=current_user,
        is_batch=True,
    )

    if not success:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action="release",
        resource_type="inventory_commitment",
        resource_id=release_data.batch_token,
        user=current_user,
        old_values={"status": "active"},
        new_values={"status": CommitmentStatus.CANCELLED.value},
        description=f"Batch commitments {release_data.batch_token} released",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Batch commitments released successfully")


@router.post("/commit/complete", response_model=APIResponse)
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def complete_commitment(
    request: Request,
    complete_data: CommitmentReleaseRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service = InventoryCommitmentService(db)
    success, errors = service.complete_commitment(
        token=complete_data.commitment_token,
        user=current_user,
        is_batch=False,
    )

    if not success:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action="complete",
        resource_type="inventory_commitment",
        resource_id=complete_data.commitment_token,
        user=current_user,
        old_values={"status": CommitmentStatus.CONFIRMED.value},
        new_values={"status": CommitmentStatus.COMPLETED.value},
        description=f"Commitment {complete_data.commitment_token} completed",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Commitment completed successfully")


@router.post("/commit/batch/complete", response_model=APIResponse)
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def complete_commitments_batch(
    request: Request,
    complete_data: BatchTokenRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service = InventoryCommitmentService(db)
    success, errors = service.complete_commitment(
        token=complete_data.batch_token,
        user=current_user,
        is_batch=True,
    )

    if not success:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action="complete",
        resource_type="inventory_commitment",
        resource_id=complete_data.batch_token,
        user=current_user,
        old_values={"status": CommitmentStatus.CONFIRMED.value},
        new_values={"status": CommitmentStatus.COMPLETED.value},
        description=f"Batch commitments {complete_data.batch_token} completed",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Batch commitments completed successfully")


@router.get("/commit/{commitment_token}", response_model=APIResponse[InventoryCommitmentResponse])
async def get_commitment(commitment_token: str, db: Session = Depends(get_db)):
    service = InventoryCommitmentService(db)
    commitment = service.get_commitment(commitment_token)
    if not commitment:
        raise HTTPException(status_code=404, detail="Commitment not found")

    response_data = {c.name: getattr(commitment, c.name) for c in commitment.__table__.columns}
    response_data["warehouse"] = commitment.warehouse
    response_data["category"] = commitment.category

    return APIResponse(data=response_data)


@router.get("/commit/batch/{batch_token}", response_model=APIResponse[List[InventoryCommitmentResponse]])
async def get_commitments_by_batch(batch_token: str, db: Session = Depends(get_db)):
    service = InventoryCommitmentService(db)
    commitments = service.get_commitments_by_batch(batch_token)
    if not commitments:
        raise HTTPException(status_code=404, detail="Batch commitments not found")

    response_data = []
    for c in commitments:
        c_dict = {col.name: getattr(c, col.name) for col in c.__table__.columns}
        c_dict["warehouse"] = c.warehouse
        c_dict["category"] = c.category
        response_data.append(c_dict)

    return APIResponse(data=response_data)


@router.get("/commitments", response_model=PaginatedResponse[InventoryCommitmentResponse])
async def list_commitments(
    page: int = 1,
    per_page: int = 20,
    device_id: Optional[int] = None,
    warehouse_id: Optional[int] = None,
    category_id: Optional[int] = None,
    status: Optional[CommitmentStatus] = None,
    commitment_type: Optional[CommitmentType] = None,
    db: Session = Depends(get_db),
):
    service = InventoryCommitmentService(db)
    commitments = service.list_commitments(
        device_id=device_id,
        warehouse_id=warehouse_id,
        category_id=category_id,
        status=status,
        commitment_type=commitment_type,
    )

    total = len(commitments)
    paginated = commitments[(page - 1) * per_page : page * per_page]

    response_data = []
    for c in paginated:
        c_dict = {col.name: getattr(c, col.name) for col in c.__table__.columns}
        c_dict["warehouse"] = c.warehouse
        c_dict["category"] = c.category
        response_data.append(c_dict)

    return PaginatedResponse(
        data=response_data,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/summary/by-warehouse", response_model=APIResponse)
async def get_inventory_summary_by_warehouse(
    category_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    warehouses = db.query(Warehouse).all()
    summary = []

    for warehouse in warehouses:
        base_query = db.query(Device).filter(
            (Device.warehouse_id == warehouse.id) |
            (Device.location == warehouse.code)
        )
        if category_id:
            base_query = base_query.filter(Device.category_id == category_id)

        total = base_query.count()

        from ..models.device import DeviceStatus
        available = base_query.filter(Device.status == DeviceStatus.AVAILABLE).count()
        in_use = base_query.filter(Device.status == DeviceStatus.IN_USE).count()
        maintenance = base_query.filter(
            Device.status.in_([DeviceStatus.MAINTENANCE, DeviceStatus.REPAIR])
        ).count()
        disinfection = base_query.filter(Device.status == DeviceStatus.DISINFECTION).count()
        locked = base_query.filter(Device.status == DeviceStatus.LOCKED).count()

        summary.append({
            "warehouse_id": warehouse.id,
            "warehouse_code": warehouse.code,
            "warehouse_name": warehouse.name,
            "total_devices": total,
            "available": available,
            "in_use": in_use,
            "maintenance": maintenance,
            "disinfection": disinfection,
            "locked": locked,
        })

    return APIResponse(data=summary)

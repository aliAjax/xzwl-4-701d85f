from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional
from math import ceil
from datetime import datetime, timezone

from ..database import get_db
from ..models.user import User, UserRole
from ..models.device import Device, DeviceStatus
from ..models.contract import Contract, ContractItem, ContractStatus
from ..models.repair import RepairRecord, RepairStatus, RepairPriority
from ..models.device_swap import DeviceSwap, DeviceSwapStatus
from ..models.audit import AuditAction
from ..schemas import (
    DeviceSwapCreate,
    DeviceSwapPreviewRequest,
    DeviceSwapPreviewResponse,
    DeviceSwapCancel,
    DeviceSwapResponse,
    APIResponse,
    PaginatedResponse,
)
from ..core import get_current_active_user, require_role, AuditLogger

router = APIRouter(prefix="/api/device-swaps", tags=["Device Swaps"])


def _model_to_dict(model) -> Optional[dict]:
    if model is None:
        return None
    return {c.name: getattr(model, c.name) for c in model.__table__.columns}


def _build_device_response(device: Device) -> dict:
    device_dict = _model_to_dict(device) or {}
    device_dict["is_available_for_rent"] = device.is_available_for_rent()
    device_dict["needs_maintenance"] = device.needs_maintenance()
    device_dict["category"] = _model_to_dict(device.category)
    return device_dict


def _build_contract_response(contract: Contract) -> dict:
    contract_dict = _model_to_dict(contract) or {}
    contract_dict["rental_days"] = contract.calculate_rental_days()
    contract_dict["overdue_days"] = contract.calculate_overdue_days()
    contract_dict["items"] = [_model_to_dict(item) for item in contract.items]
    return contract_dict


def build_swap_response(swap: DeviceSwap) -> dict:
    swap_dict = _model_to_dict(swap) or {}

    if swap.contract:
        swap_dict["contract"] = _build_contract_response(swap.contract)
    if swap.old_device:
        swap_dict["old_device"] = _build_device_response(swap.old_device)
    if swap.new_device:
        swap_dict["new_device"] = _build_device_response(swap.new_device)

    swap_dict["created_by"] = _model_to_dict(swap.created_by)
    swap_dict["completed_by"] = _model_to_dict(swap.completed_by)
    swap_dict["cancelled_by"] = _model_to_dict(swap.cancelled_by)

    return swap_dict


def _validate_swap(
    db: Session,
    contract_id: int,
    old_device_id: int,
    new_device_id: int,
) -> tuple[bool, list[str], Contract, Device, Device, ContractItem]:
    messages = []

    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    if contract.status not in [ContractStatus.ACTIVE, ContractStatus.RENEWED, ContractStatus.OVERDUE]:
        messages.append(f"合同状态为 {contract.status.value}，仅活跃合同可换机")

    old_device = db.query(Device).filter(Device.id == old_device_id).first()
    if not old_device:
        raise HTTPException(status_code=404, detail="Old device not found")

    if old_device.status != DeviceStatus.IN_USE:
        messages.append(f"原设备状态为 {old_device.status.value}，仅使用中设备可更换")

    contract_item = db.query(ContractItem).filter(
        ContractItem.contract_id == contract_id,
        ContractItem.device_id == old_device_id,
    ).first()
    if not contract_item:
        messages.append("原设备不在该合同明细中")

    new_device = db.query(Device).filter(Device.id == new_device_id).first()
    if not new_device:
        raise HTTPException(status_code=404, detail="New device not found")

    if old_device_id == new_device_id:
        messages.append("替换设备不能与原设备相同")

    if not new_device.is_available_for_rent():
        if new_device.status == DeviceStatus.IN_USE:
            messages.append("替换设备正在使用中，不可租赁")
        elif new_device.status in [DeviceStatus.MAINTENANCE, DeviceStatus.REPAIR]:
            messages.append(f"替换设备正在{new_device.status.value}中，不可租赁")
        elif new_device.status == DeviceStatus.DISINFECTION:
            messages.append("替换设备正在消毒中，不可租赁")
        elif new_device.status == DeviceStatus.LOCKED:
            messages.append("替换设备已锁定，不可租赁")
        elif new_device.status == DeviceStatus.RETIRED:
            messages.append("替换设备已报废，不可租赁")
        elif new_device.category.disinfection_required and not new_device.last_disinfection_date:
            messages.append("替换设备需要消毒但无消毒记录，不可租赁")
        else:
            messages.append("替换设备不可租赁")

    if new_device.category_id != old_device.category_id:
        messages.append(f"警告：替换设备品类（{new_device.category.name}）与原设备品类（{old_device.category.name}）不同")

    pending_swap = db.query(DeviceSwap).filter(
        DeviceSwap.old_device_id == old_device_id,
        DeviceSwap.status == DeviceSwapStatus.PENDING,
    ).first()
    if pending_swap:
        messages.append(f"该设备已有待处理的换机申请（单号：{pending_swap.swap_number}）")

    can_swap = len([m for m in messages if not m.startswith("警告")]) == 0

    return can_swap, messages, contract, old_device, new_device, contract_item


def _generate_swap_number(db: Session) -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"SW{today}"
    last_swap = db.query(DeviceSwap).filter(
        DeviceSwap.swap_number.like(f"{prefix}%")
    ).order_by(DeviceSwap.swap_number.desc()).first()

    if last_swap:
        sequence = int(last_swap.swap_number[-4:]) + 1
    else:
        sequence = 1

    return f"{prefix}{sequence:04d}"


@router.get("", response_model=PaginatedResponse[DeviceSwapResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def list_swaps(
    page: int = 1,
    per_page: int = 20,
    status: Optional[DeviceSwapStatus] = None,
    contract_id: Optional[int] = None,
    old_device_id: Optional[int] = None,
    new_device_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    query = db.query(DeviceSwap)
    if status:
        query = query.filter(DeviceSwap.status == status)
    if contract_id:
        query = query.filter(DeviceSwap.contract_id == contract_id)
    if old_device_id:
        query = query.filter(DeviceSwap.old_device_id == old_device_id)
    if new_device_id:
        query = query.filter(DeviceSwap.new_device_id == new_device_id)

    query = query.order_by(DeviceSwap.created_at.desc())
    total = query.count()
    swaps = query.offset((page - 1) * per_page).limit(per_page).all()

    response_data = [build_swap_response(s) for s in swaps]

    return PaginatedResponse(
        data=response_data,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/{swap_id}", response_model=APIResponse[DeviceSwapResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_swap(
    swap_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    swap = db.query(DeviceSwap).filter(DeviceSwap.id == swap_id).first()
    if not swap:
        raise HTTPException(status_code=404, detail="Device swap record not found")

    return APIResponse(data=build_swap_response(swap))


@router.post("/preview", response_model=APIResponse[DeviceSwapPreviewResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def preview_swap(
    request: Request,
    preview_data: DeviceSwapPreviewRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    can_swap, messages, contract, old_device, new_device, contract_item = _validate_swap(
        db,
        preview_data.contract_id,
        preview_data.old_device_id,
        preview_data.new_device_id,
    )

    old_daily_rate = contract_item.daily_rate if contract_item else old_device.category.daily_rental_rate
    new_daily_rate = new_device.category.daily_rental_rate
    keep_original_rate = old_daily_rate

    return APIResponse(
        data={
            "contract": _build_contract_response(contract),
            "old_device": _build_device_response(old_device),
            "new_device": _build_device_response(new_device),
            "old_daily_rate": old_daily_rate,
            "new_daily_rate": new_daily_rate,
            "keep_original_rate": keep_original_rate,
            "can_swap": can_swap,
            "validation_messages": messages,
        }
    )


@router.post("", response_model=APIResponse[DeviceSwapResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def create_swap(
    request: Request,
    swap_data: DeviceSwapCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    can_swap, messages, contract, old_device, new_device, contract_item = _validate_swap(
        db,
        swap_data.contract_id,
        swap_data.old_device_id,
        swap_data.new_device_id,
    )

    if not can_swap:
        error_messages = [m for m in messages if not m.startswith("警告")]
        if error_messages:
            raise HTTPException(
                status_code=400,
                detail="; ".join(error_messages),
            )

    old_daily_rate = contract_item.daily_rate
    new_daily_rate = new_device.category.daily_rental_rate
    keep_original_rate = old_daily_rate

    swap_number = _generate_swap_number(db)

    new_swap = DeviceSwap(
        swap_number=swap_number,
        contract_id=swap_data.contract_id,
        old_device_id=swap_data.old_device_id,
        new_device_id=swap_data.new_device_id,
        contract_item_id=contract_item.id,
        fault_description=swap_data.fault_description,
        fault_category=swap_data.fault_category,
        old_daily_rate=old_daily_rate,
        new_daily_rate=new_daily_rate,
        keep_original_rate=keep_original_rate,
        status=DeviceSwapStatus.PENDING,
        created_by_id=current_user.id,
        notes=swap_data.notes,
    )

    db.add(new_swap)
    db.flush()

    repair_record = RepairRecord(
        device_id=old_device.id,
        report_date=datetime.now(timezone.utc),
        reported_by_id=current_user.id,
        priority=RepairPriority.HIGH.value,
        status=RepairStatus.REPORTED.value,
        fault_description=swap_data.fault_description,
        fault_category=swap_data.fault_category,
        customer_notes=f"换机单 {swap_number} 关联维修，客户合同号：{contract.contract_number}",
        is_warranty=False,
    )
    db.add(repair_record)
    db.flush()

    new_swap.repair_record_id = repair_record.id

    db.commit()
    db.refresh(new_swap)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.SWAP_CREATE,
        resource_type="device_swap",
        resource_id=str(new_swap.id),
        user=current_user,
        new_values={
            "swap_number": swap_number,
            "contract_id": contract.id,
            "contract_number": contract.contract_number,
            "old_device_id": old_device.id,
            "old_device_sn": old_device.serial_number,
            "new_device_id": new_device.id,
            "new_device_sn": new_device.serial_number,
            "old_daily_rate": old_daily_rate,
            "new_daily_rate": new_daily_rate,
            "keep_original_rate": keep_original_rate,
            "repair_record_id": repair_record.id,
        },
        description=f"创建设备换机申请 {swap_number}：合同 {contract.contract_number}，原设备 {old_device.serial_number} → 新设备 {new_device.serial_number}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Device swap record created successfully. Please confirm to complete the swap.",
        data=build_swap_response(new_swap),
    )


@router.post("/{swap_id}/complete", response_model=APIResponse[DeviceSwapResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def complete_swap(
    request: Request,
    swap_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    swap = db.query(DeviceSwap).filter(DeviceSwap.id == swap_id).first()
    if not swap:
        raise HTTPException(status_code=404, detail="Device swap record not found")

    if swap.status != DeviceSwapStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot complete swap with status '{swap.status.value}'. Only pending swaps can be completed.",
        )

    old_device = swap.old_device
    new_device = swap.new_device
    contract = swap.contract
    contract_item = swap.contract_item

    if not new_device.is_available_for_rent():
        raise HTTPException(
            status_code=400,
            detail=f"替换设备 {new_device.serial_number} 当前不可租赁，请重新选择设备",
        )

    old_device_status = old_device.status.value
    new_device_status = new_device.status.value
    old_contract_item_device_id = contract_item.device_id
    old_contract_item_daily_rate = contract_item.daily_rate

    old_device.status = DeviceStatus.REPAIR
    old_device.location = "维修中"

    new_device.status = DeviceStatus.IN_USE
    new_device.location = contract.customer.full_name if contract.customer else "客户使用中"
    new_device.current_owner = contract.customer.full_name if contract.customer else old_device.current_owner

    contract_item.device_id = new_device.id
    contract_item.daily_rate = swap.keep_original_rate
    contract_item.notes = f"换机：原设备 {old_device.serial_number}（{old_device.name}）→ 新设备 {new_device.serial_number}（{new_device.name}），换机单号 {swap.swap_number}"

    swap.status = DeviceSwapStatus.COMPLETED
    swap.completed_by_id = current_user.id
    swap.completed_at = datetime.now(timezone.utc)

    repair_record = db.query(RepairRecord).filter(RepairRecord.id == swap.repair_record_id).first()
    if repair_record:
        repair_record.status = RepairStatus.DIAGNOSING.value

    db.commit()
    db.refresh(swap)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.SWAP_COMPLETE,
        resource_type="device_swap",
        resource_id=str(swap.id),
        user=current_user,
        old_values={
            "status": DeviceSwapStatus.PENDING.value,
            "old_device_status": old_device_status,
            "new_device_status": new_device_status,
            "contract_item_device_id": old_contract_item_device_id,
            "contract_item_daily_rate": old_contract_item_daily_rate,
        },
        new_values={
            "status": DeviceSwapStatus.COMPLETED.value,
            "old_device_status": DeviceStatus.REPAIR.value,
            "new_device_status": DeviceStatus.IN_USE.value,
            "contract_item_device_id": new_device.id,
            "contract_item_daily_rate": swap.keep_original_rate,
            "contract_total_amount": contract.total_amount,
            "contract_deposit_amount": contract.deposit_amount,
        },
        description=f"完成换机 {swap.swap_number}：原设备 {old_device.serial_number} 进入维修状态，新设备 {new_device.serial_number} 加入合同 {contract.contract_number}。租金和押金保持原合同金额不变。",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Device swap completed successfully. Contract has been updated, old device is now in repair status.",
        data=build_swap_response(swap),
    )


@router.post("/{swap_id}/cancel", response_model=APIResponse[DeviceSwapResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def cancel_swap(
    request: Request,
    swap_id: int,
    cancel_data: DeviceSwapCancel,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    swap = db.query(DeviceSwap).filter(DeviceSwap.id == swap_id).first()
    if not swap:
        raise HTTPException(status_code=404, detail="Device swap record not found")

    if swap.status != DeviceSwapStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel swap with status '{swap.status.value}'. Only pending swaps can be cancelled.",
        )

    old_status = swap.status.value

    swap.status = DeviceSwapStatus.CANCELLED
    swap.cancelled_by_id = current_user.id
    swap.cancelled_at = datetime.now(timezone.utc)
    swap.cancel_reason = cancel_data.cancel_reason

    repair_record = db.query(RepairRecord).filter(RepairRecord.id == swap.repair_record_id).first()
    if repair_record:
        repair_record.status = RepairStatus.CANCELLED.value

    db.commit()
    db.refresh(swap)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.SWAP_CANCEL,
        resource_type="device_swap",
        resource_id=str(swap.id),
        user=current_user,
        old_values={"status": old_status},
        new_values={"status": DeviceSwapStatus.CANCELLED.value},
        description=f"取消换机申请 {swap.swap_number}，原因：{cancel_data.cancel_reason}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Device swap cancelled successfully",
        data=build_swap_response(swap),
    )

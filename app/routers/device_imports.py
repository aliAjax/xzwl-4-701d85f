from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from math import ceil
import uuid

from ..database import get_db
from ..models.user import User, UserRole
from ..models.device import Device, DeviceStatus, DeviceCategory
from ..models.device_import import (
    DeviceImport,
    DeviceImportItem,
    ImportStatus,
    ImportItemStatus,
    ValidationErrorType,
)
from ..schemas import (
    APIResponse,
    PaginatedResponse,
    BatchImportPreviewRequest,
    BatchImportPreviewResponse,
    BatchImportConfirmRequest,
    ImportBatchResponse,
    ImportBatchDetailResponse,
    ImportItemPreview,
    ValidationErrorDetail,
)
from ..core import get_current_active_user, require_role, AuditLogger

router = APIRouter(prefix="/api/devices/batch", tags=["Device Batch Import"])


def generate_batch_number() -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    suffix = uuid.uuid4().hex[:6].upper()
    return f"IMP{timestamp}{suffix}"


def parse_purchase_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(date_str, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            continue
    return None


def validate_import_items(
    items: List[Dict[str, Any]],
    db: Session,
    start_index: int = 0,
) -> List[Dict[str, Any]]:
    serial_numbers = [item.get("serial_number", "").strip() for item in items]
    serial_counts: Dict[str, int] = {}
    for sn in serial_numbers:
        serial_counts[sn] = serial_counts.get(sn, 0) + 1

    existing_serials = set()
    valid_serials = [sn for sn in serial_numbers if sn]
    if valid_serials:
        existing_devices = db.query(Device.serial_number).filter(
            Device.serial_number.in_(valid_serials)
        ).all()
        existing_serials = {d[0] for d in existing_devices}

    category_ids = [item.get("category_id") for item in items if item.get("category_id")]
    existing_categories = {}
    if category_ids:
        categories = db.query(DeviceCategory.id, DeviceCategory.name,
                              DeviceCategory.daily_rental_rate, DeviceCategory.deposit_amount).filter(
            DeviceCategory.id.in_(category_ids)
        ).all()
        for cat in categories:
            existing_categories[cat[0]] = {
                "name": cat[1],
                "daily_rental_rate": cat[2],
                "deposit_amount": cat[3],
            }

    validated_items = []
    for idx, item in enumerate(items):
        row_index = start_index + idx
        errors: List[ValidationErrorDetail] = []
        serial_number = item.get("serial_number", "").strip()
        name = item.get("name", "").strip() if item.get("name") else ""
        category_id = item.get("category_id")
        purchase_date_str = item.get("purchase_date")
        purchase_price = item.get("purchase_price")

        if not serial_number:
            errors.append(ValidationErrorDetail(
                error_type=ValidationErrorType.SERIAL_NUMBER_EMPTY,
                field="serial_number",
                message="序列号不能为空"
            ))
        else:
            if serial_counts.get(serial_number, 0) > 1:
                errors.append(ValidationErrorDetail(
                    error_type=ValidationErrorType.SERIAL_DUPLICATE_IN_BATCH,
                    field="serial_number",
                    message=f"序列号 '{serial_number}' 在导入批次中重复"
                ))
            if serial_number in existing_serials:
                errors.append(ValidationErrorDetail(
                    error_type=ValidationErrorType.SERIAL_DUPLICATE_IN_DB,
                    field="serial_number",
                    message=f"序列号 '{serial_number}' 已存在于系统中"
                ))

        if not name:
            errors.append(ValidationErrorDetail(
                error_type=ValidationErrorType.NAME_EMPTY,
                field="name",
                message="设备名称不能为空"
            ))

        if not category_id:
            errors.append(ValidationErrorDetail(
                error_type=ValidationErrorType.CATEGORY_ID_EMPTY,
                field="category_id",
                message="品类ID不能为空"
            ))
        else:
            category = existing_categories.get(category_id)
            if not category:
                errors.append(ValidationErrorDetail(
                    error_type=ValidationErrorType.CATEGORY_NOT_FOUND,
                    field="category_id",
                    message=f"品类ID '{category_id}' 不存在"
                ))
            else:
                if category.get("deposit_amount", 0) <= 0:
                    errors.append(ValidationErrorDetail(
                        error_type=ValidationErrorType.DEPOSIT_MISSING,
                        field="category_id",
                        message=f"品类 '{category.get('name')}' 押金金额缺失或为0，请先配置品类"
                    ))
                if category.get("daily_rental_rate", 0) <= 0:
                    errors.append(ValidationErrorDetail(
                        error_type=ValidationErrorType.RENTAL_RATE_MISSING,
                        field="category_id",
                        message=f"品类 '{category.get('name')}' 日租金缺失或为0，请先配置品类"
                    ))

        purchase_date = None
        if purchase_date_str:
            purchase_date = parse_purchase_date(str(purchase_date_str))
            if not purchase_date:
                errors.append(ValidationErrorDetail(
                    error_type=ValidationErrorType.PURCHASE_DATE_INVALID,
                    field="purchase_date",
                    message=f"采购日期 '{purchase_date_str}' 格式不正确，支持格式: YYYY-MM-DD, YYYY/MM/DD"
                ))

        if purchase_price is not None and purchase_price < 0:
            errors.append(ValidationErrorDetail(
                error_type=ValidationErrorType.PURCHASE_PRICE_NEGATIVE,
                field="purchase_price",
                message="采购价格不能为负数"
            ))

        category_name = existing_categories.get(category_id, {}).get("name") if category_id else None

        validated_items.append({
            "row_index": row_index,
            "data": item,
            "status": ImportItemStatus.VALID if not errors else ImportItemStatus.INVALID,
            "errors": errors,
            "parsed_purchase_date": purchase_date,
            "category_name": category_name,
        })

    return validated_items


@router.post("/preview", response_model=APIResponse[BatchImportPreviewResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def preview_batch_import(
    request: Request,
    import_data: BatchImportPreviewRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    if not import_data.items or len(import_data.items) == 0:
        raise HTTPException(status_code=400, detail="导入数据不能为空")

    if len(import_data.items) > 1000:
        raise HTTPException(status_code=400, detail="单次导入不能超过1000条记录")

    batch_number = generate_batch_number()

    validated_items = validate_import_items(
        [item.model_dump() for item in import_data.items],
        db
    )

    valid_count = sum(1 for item in validated_items if item["status"] == ImportItemStatus.VALID)
    invalid_count = len(validated_items) - valid_count

    import_batch = DeviceImport(
        batch_number=batch_number,
        total_count=len(validated_items),
        valid_count=valid_count,
        invalid_count=invalid_count,
        status=ImportStatus.PREVIEWED,
        previewed_at=datetime.now(timezone.utc),
        remarks=import_data.remarks,
        created_by_id=current_user.id,
    )
    db.add(import_batch)
    db.flush()

    for validated in validated_items:
        item_data = validated["data"]
        import_item = DeviceImportItem(
            import_id=import_batch.id,
            row_index=validated["row_index"],
            serial_number=item_data.get("serial_number", "").strip() or None,
            name=item_data.get("name", "").strip() or None,
            model=item_data.get("model"),
            manufacturer=item_data.get("manufacturer"),
            purchase_date_str=str(item_data.get("purchase_date")) if item_data.get("purchase_date") else None,
            purchase_date=validated["parsed_purchase_date"],
            purchase_price=item_data.get("purchase_price"),
            current_owner=item_data.get("current_owner"),
            location=item_data.get("location"),
            notes=item_data.get("notes"),
            category_id=item_data.get("category_id"),
            category_name=validated["category_name"],
            status=validated["status"],
            validation_errors=[e.model_dump() for e in validated["errors"]] if validated["errors"] else None,
            error_message="; ".join([e.message for e in validated["errors"]]) if validated["errors"] else None,
        )
        db.add(import_item)

    db.commit()
    db.refresh(import_batch)

    error_summary = []
    if invalid_count > 0:
        error_types = {}
        for validated in validated_items:
            for error in validated["errors"]:
                error_type = error.error_type.value
                if error_type not in error_types:
                    error_types[error_type] = {"count": 0, "message": error.message}
                error_types[error_type]["count"] += 1
        for et, info in error_types.items():
            error_summary.append(f"{info['message']} ({info['count']}条)")

    preview_items = []
    for validated in validated_items:
        preview_items.append(ImportItemPreview(
            row_index=validated["row_index"],
            data=validated["data"],
            status=validated["status"],
            errors=validated["errors"],
        ))

    response = BatchImportPreviewResponse(
        import_id=import_batch.id,
        batch_number=batch_number,
        total_count=len(validated_items),
        valid_count=valid_count,
        invalid_count=invalid_count,
        items=preview_items,
        can_confirm=(valid_count > 0),
        error_summary=error_summary,
    )

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action="preview",
        resource_type="device_import",
        resource_id=str(import_batch.id),
        user=current_user,
        new_values={
            "batch_number": batch_number,
            "total_count": len(validated_items),
            "valid_count": valid_count,
            "invalid_count": invalid_count,
        },
        description=f"批量导入预览: {batch_number}, 共{len(validated_items)}条, 有效{valid_count}条, 无效{invalid_count}条",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="导入预览完成", data=response)


@router.post("/confirm", response_model=APIResponse[ImportBatchDetailResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def confirm_batch_import(
    request: Request,
    confirm_data: BatchImportConfirmRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    import_batch = db.query(DeviceImport).filter(
        DeviceImport.id == confirm_data.import_id
    ).first()

    if not import_batch:
        raise HTTPException(status_code=404, detail="导入记录不存在")

    if import_batch.created_by_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="只能确认自己创建的导入记录")

    if import_batch.status == ImportStatus.CONFIRMED:
        raise HTTPException(status_code=400, detail="该批次已确认导入，无需重复操作")

    if import_batch.status != ImportStatus.PREVIEWED:
        raise HTTPException(status_code=400, detail="只能确认状态为'已预览'的导入记录")

    import_items = db.query(DeviceImportItem).filter(
        DeviceImportItem.import_id == import_batch.id
    ).order_by(DeviceImportItem.row_index).all()

    valid_items = [item for item in import_items if item.status == ImportItemStatus.VALID]
    invalid_items = [item for item in import_items if item.status == ImportItemStatus.INVALID]

    if import_batch.invalid_count > 0 and not confirm_data.skip_invalid:
        raise HTTPException(
            status_code=400,
            detail=f"存在{import_batch.invalid_count}条无效记录，请修正后重新预览，或设置 skip_invalid=True 跳过无效行"
        )

    if not valid_items:
        raise HTTPException(status_code=400, detail="没有可导入的有效设备")

    try:
        imported_count = 0
        skipped_count = 0
        device_ids = []

        for import_item in import_items:
            if import_item.status != ImportItemStatus.VALID:
                import_item.status = ImportItemStatus.SKIPPED
                skipped_count += 1
                continue

            category = db.query(DeviceCategory).filter(
                DeviceCategory.id == import_item.category_id
            ).first()

            new_device = Device(
                serial_number=import_item.serial_number,
                name=import_item.name,
                model=import_item.model,
                manufacturer=import_item.manufacturer,
                purchase_date=import_item.purchase_date,
                purchase_price=import_item.purchase_price,
                current_owner=import_item.current_owner,
                location=import_item.location,
                notes=import_item.notes,
                category_id=import_item.category_id,
                status=DeviceStatus.AVAILABLE,
            )

            if category and category.disinfection_required:
                new_device.last_disinfection_date = datetime.now(timezone.utc)

            if category and category.maintenance_cycle_days:
                new_device.next_maintenance_date = datetime.now(timezone.utc) + timedelta(
                    days=category.maintenance_cycle_days
                )

            db.add(new_device)
            db.flush()
            device_ids.append(new_device.id)

            import_item.device_id = new_device.id
            import_item.status = ImportItemStatus.IMPORTED
            imported_count += 1

        import_batch.status = ImportStatus.CONFIRMED
        import_batch.confirmed_at = datetime.now(timezone.utc)
        import_batch.imported_count = imported_count
        import_batch.skipped_count = skipped_count

        db.commit()

        audit_logger = AuditLogger(db)
        for idx, device_id in enumerate(device_ids):
            audit_logger.log_create(
                resource_type="device",
                resource_id=str(device_id),
                user=current_user,
                new_values={
                    "serial_number": import_items[idx].serial_number,
                    "name": import_items[idx].name,
                    "category_id": import_items[idx].category_id,
                    "status": DeviceStatus.AVAILABLE.value,
                    "import_batch": import_batch.batch_number,
                },
                ip_address=request.client.host if request.client else None,
            )

        audit_logger.log(
            action="confirm",
            resource_type="device_import",
            resource_id=str(import_batch.id),
            user=current_user,
            new_values={
                "batch_number": import_batch.batch_number,
                "imported_count": imported_count,
                "skipped_count": skipped_count,
                "device_ids": device_ids,
                "skip_invalid": confirm_data.skip_invalid,
            },
            description=f"批量导入确认: {import_batch.batch_number}, 成功导入{imported_count}台设备, 跳过{skipped_count}台无效设备",
            ip_address=request.client.host if request.client else None,
        )

    except Exception as e:
        db.rollback()
        import_batch.status = ImportStatus.FAILED
        import_batch.skipped_count = 0
        for import_item in import_items:
            import_item.status = ImportItemStatus.FAILED
            import_item.error_message = f"导入失败: {str(e)}"
        db.commit()
        raise HTTPException(status_code=500, detail=f"批量导入失败: {str(e)}")

    db.refresh(import_batch)
    db.expire_all()

    final_batch = db.query(DeviceImport).filter(DeviceImport.id == import_batch.id).first()
    final_items = db.query(DeviceImportItem).filter(
        DeviceImportItem.import_id == import_batch.id
    ).order_by(DeviceImportItem.row_index).all()

    items_response = []
    for item in final_items:
        items_response.append({
            "id": item.id,
            "import_id": item.import_id,
            "row_index": item.row_index,
            "serial_number": item.serial_number,
            "name": item.name,
            "model": item.model,
            "manufacturer": item.manufacturer,
            "purchase_date": item.purchase_date,
            "purchase_price": item.purchase_price,
            "category_id": item.category_id,
            "category_name": item.category_name,
            "status": item.status,
            "validation_errors": item.validation_errors,
            "error_message": item.error_message,
            "device_id": item.device_id,
        })

    response_data = {
        "id": final_batch.id,
        "batch_number": final_batch.batch_number,
        "total_count": final_batch.total_count,
        "valid_count": final_batch.valid_count,
        "invalid_count": final_batch.invalid_count,
        "imported_count": final_batch.imported_count,
        "skipped_count": final_batch.skipped_count,
        "status": final_batch.status,
        "remarks": final_batch.remarks,
        "created_by": current_user.full_name,
        "created_at": final_batch.created_at,
        "previewed_at": final_batch.previewed_at,
        "confirmed_at": final_batch.confirmed_at,
        "items": items_response,
    }

    message = f"批量导入成功，共导入{imported_count}台设备"
    if skipped_count > 0:
        message += f"，跳过{skipped_count}台无效设备"
    return APIResponse(message=message, data=response_data)


@router.get("", response_model=PaginatedResponse[ImportBatchResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def list_import_batches(
    page: int = 1,
    per_page: int = 20,
    status: Optional[ImportStatus] = None,
    created_by: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
):
    query = db.query(DeviceImport)

    if status:
        query = query.filter(DeviceImport.status == status)
    if created_by:
        query = query.filter(DeviceImport.created_by_id == created_by)
    if start_date:
        query = query.filter(DeviceImport.created_at >= start_date)
    if end_date:
        query = query.filter(DeviceImport.created_at <= end_date)

    query = query.order_by(DeviceImport.created_at.desc())

    total = query.count()
    batches = query.offset((page - 1) * per_page).limit(per_page).all()

    user_ids = [b.created_by_id for b in batches]
    users = {}
    if user_ids:
        user_list = db.query(User.id, User.full_name).filter(User.id.in_(user_ids)).all()
        users = {u[0]: u[1] for u in user_list}

    response_data = []
    for batch in batches:
        batch_dict = {c.name: getattr(batch, c.name) for c in batch.__table__.columns}
        batch_dict["created_by"] = users.get(batch.created_by_id)
        batch_dict["skipped_count"] = batch.skipped_count
        response_data.append(batch_dict)

    return PaginatedResponse(
        data=response_data,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/{import_id}", response_model=APIResponse[ImportBatchDetailResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_import_batch_detail(
    import_id: int,
    db: Session = Depends(get_db),
):
    import_batch = db.query(DeviceImport).filter(DeviceImport.id == import_id).first()
    if not import_batch:
        raise HTTPException(status_code=404, detail="导入记录不存在")

    user = db.query(User).filter(User.id == import_batch.created_by_id).first()

    import_items = db.query(DeviceImportItem).filter(
        DeviceImportItem.import_id == import_id
    ).order_by(DeviceImportItem.row_index).all()

    items_response = []
    for item in import_items:
        items_response.append({
            "id": item.id,
            "import_id": item.import_id,
            "row_index": item.row_index,
            "serial_number": item.serial_number,
            "name": item.name,
            "model": item.model,
            "manufacturer": item.manufacturer,
            "purchase_date": item.purchase_date,
            "purchase_price": item.purchase_price,
            "category_id": item.category_id,
            "category_name": item.category_name,
            "status": item.status,
            "validation_errors": item.validation_errors,
            "error_message": item.error_message,
            "device_id": item.device_id,
        })

    response_data = {
        "id": import_batch.id,
        "batch_number": import_batch.batch_number,
        "total_count": import_batch.total_count,
        "valid_count": import_batch.valid_count,
        "invalid_count": import_batch.invalid_count,
        "imported_count": import_batch.imported_count,
        "skipped_count": import_batch.skipped_count,
        "status": import_batch.status,
        "remarks": import_batch.remarks,
        "created_by": user.full_name if user else None,
        "created_at": import_batch.created_at,
        "previewed_at": import_batch.previewed_at,
        "confirmed_at": import_batch.confirmed_at,
        "items": items_response,
    }

    return APIResponse(data=response_data)


@router.post("/{import_id}/cancel", response_model=APIResponse)
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def cancel_import_batch(
    request: Request,
    import_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    import_batch = db.query(DeviceImport).filter(DeviceImport.id == import_id).first()
    if not import_batch:
        raise HTTPException(status_code=404, detail="导入记录不存在")

    if import_batch.status == ImportStatus.CONFIRMED:
        raise HTTPException(status_code=400, detail="已确认的导入记录无法取消")

    if import_batch.status == ImportStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="该导入记录已取消")

    import_batch.status = ImportStatus.CANCELLED
    db.commit()

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action="cancel",
        resource_type="device_import",
        resource_id=str(import_batch.id),
        user=current_user,
        old_values={"status": import_batch.status.value},
        new_values={"status": ImportStatus.CANCELLED.value},
        description=f"取消批量导入: {import_batch.batch_number}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="导入记录已取消")

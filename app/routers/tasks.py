from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import Optional, List
from math import ceil
from datetime import datetime, timezone, timedelta

from ..database import get_db
from ..models.user import User, UserRole
from ..models.device import Device, DeviceStatus, DeviceCategory
from ..models.maintenance import MaintenanceRecord
from ..models.disinfection import DisinfectionRecord
from ..models.repair import RepairRecord, RepairStatus
from ..models.task import (
    MaintenanceTask,
    TaskType,
    TaskStatus,
    TaskPriority,
)
from ..models.audit import AuditAction
from ..schemas import (
    TaskCreate,
    TaskUpdate,
    TaskClaim,
    TaskStart,
    TaskComplete,
    TaskCancel,
    TaskGenerateRequest,
    TaskResponse,
    TaskDetailResponse,
    TaskGenerateResult,
    APIResponse,
    PaginatedResponse,
)
from ..core import get_current_active_user, require_role, AuditLogger

router = APIRouter(prefix="/api/tasks", tags=["Maintenance Tasks"])


def _build_task_detail(task: MaintenanceTask) -> TaskDetailResponse:
    return TaskDetailResponse(
        id=task.id,
        device_id=task.device_id,
        task_type=task.task_type,
        title=task.title,
        description=task.description,
        priority=task.priority,
        status=task.status,
        scheduled_date=task.scheduled_date,
        due_date=task.due_date,
        completed_date=task.completed_date,
        created_by_id=task.created_by_id,
        assigned_to_id=task.assigned_to_id,
        maintenance_record_id=task.maintenance_record_id,
        disinfection_record_id=task.disinfection_record_id,
        repair_record_id=task.repair_record_id,
        completion_notes=task.completion_notes,
        notes=task.notes,
        is_overdue=task.is_overdue,
        created_at=task.created_at,
        updated_at=task.updated_at,
        device_name=task.device.name if task.device else None,
        device_serial_number=task.device.serial_number if task.device else None,
        device_status=task.device.status.value if task.device and task.device.status else None,
        assigned_to_name=task.assigned_to.full_name if task.assigned_to else None,
        created_by_name=task.created_by.full_name if task.created_by else None,
    )


def _ensure_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _update_overdue_tasks(db: Session):
    now = datetime.now(timezone.utc)
    overdue_tasks = db.query(MaintenanceTask).filter(
        MaintenanceTask.status.notin_([TaskStatus.COMPLETED, TaskStatus.CANCELLED]),
        MaintenanceTask.is_overdue == False,
    ).all()
    for task in overdue_tasks:
        due_date_aware = _ensure_aware(task.due_date)
        if due_date_aware and due_date_aware < now:
            task.is_overdue = True
    db.commit()


@router.get("/my", response_model=PaginatedResponse[TaskDetailResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_my_tasks(
    page: int = 1,
    per_page: int = 20,
    status: Optional[TaskStatus] = None,
    task_type: Optional[TaskType] = None,
    priority: Optional[TaskPriority] = None,
    only_overdue: bool = False,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _update_overdue_tasks(db)

    query = db.query(MaintenanceTask).filter(
        MaintenanceTask.assigned_to_id == current_user.id
    )
    if status:
        query = query.filter(MaintenanceTask.status == status)
    if task_type:
        query = query.filter(MaintenanceTask.task_type == task_type)
    if priority:
        query = query.filter(MaintenanceTask.priority == priority)
    if only_overdue:
        query = query.filter(MaintenanceTask.is_overdue == True)

    total = query.count()
    tasks = query.order_by(
        MaintenanceTask.is_overdue.desc(),
        MaintenanceTask.priority.desc(),
        MaintenanceTask.due_date.asc(),
    ).offset((page - 1) * per_page).limit(per_page).all()

    return PaginatedResponse(
        data=[_build_task_detail(task) for task in tasks],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/pending", response_model=PaginatedResponse[TaskDetailResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_pending_tasks(
    page: int = 1,
    per_page: int = 20,
    task_type: Optional[TaskType] = None,
    priority: Optional[TaskPriority] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _update_overdue_tasks(db)

    query = db.query(MaintenanceTask).filter(
        MaintenanceTask.status == TaskStatus.PENDING
    )
    if task_type:
        query = query.filter(MaintenanceTask.task_type == task_type)
    if priority:
        query = query.filter(MaintenanceTask.priority == priority)

    total = query.count()
    tasks = query.order_by(
        MaintenanceTask.is_overdue.desc(),
        MaintenanceTask.priority.desc(),
        MaintenanceTask.due_date.asc(),
    ).offset((page - 1) * per_page).limit(per_page).all()

    return PaginatedResponse(
        data=[_build_task_detail(task) for task in tasks],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/all", response_model=PaginatedResponse[TaskDetailResponse])
@require_role([UserRole.ADMIN])
async def get_all_tasks(
    page: int = 1,
    per_page: int = 20,
    device_id: Optional[int] = None,
    status: Optional[TaskStatus] = None,
    task_type: Optional[TaskType] = None,
    priority: Optional[TaskPriority] = None,
    assigned_to_id: Optional[int] = None,
    only_overdue: bool = False,
    scheduled_from: Optional[datetime] = None,
    scheduled_to: Optional[datetime] = None,
    due_from: Optional[datetime] = None,
    due_to: Optional[datetime] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _update_overdue_tasks(db)

    query = db.query(MaintenanceTask)
    if device_id:
        query = query.filter(MaintenanceTask.device_id == device_id)
    if status:
        query = query.filter(MaintenanceTask.status == status)
    if task_type:
        query = query.filter(MaintenanceTask.task_type == task_type)
    if priority:
        query = query.filter(MaintenanceTask.priority == priority)
    if assigned_to_id:
        query = query.filter(MaintenanceTask.assigned_to_id == assigned_to_id)
    if only_overdue:
        query = query.filter(MaintenanceTask.is_overdue == True)
    if scheduled_from:
        query = query.filter(MaintenanceTask.scheduled_date >= scheduled_from)
    if scheduled_to:
        query = query.filter(MaintenanceTask.scheduled_date <= scheduled_to)
    if due_from:
        query = query.filter(MaintenanceTask.due_date >= due_from)
    if due_to:
        query = query.filter(MaintenanceTask.due_date <= due_to)

    total = query.count()
    tasks = query.order_by(
        MaintenanceTask.is_overdue.desc(),
        MaintenanceTask.priority.desc(),
        MaintenanceTask.due_date.asc(),
    ).offset((page - 1) * per_page).limit(per_page).all()

    return PaginatedResponse(
        data=[_build_task_detail(task) for task in tasks],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=ceil(total / per_page),
    )


@router.get("/overdue", response_model=APIResponse)
@require_role([UserRole.ADMIN])
async def get_overdue_summary(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _update_overdue_tasks(db)
    now = datetime.now(timezone.utc)

    overdue_tasks = db.query(MaintenanceTask).filter(
        MaintenanceTask.status.notin_([TaskStatus.COMPLETED, TaskStatus.CANCELLED]),
        MaintenanceTask.is_overdue == True,
    ).all()

    result = {
        "total_overdue": len(overdue_tasks),
        "by_type": {
            "maintenance": 0,
            "disinfection": 0,
            "repair": 0,
        },
        "by_priority": {
            "low": 0,
            "medium": 0,
            "high": 0,
            "urgent": 0,
        },
        "tasks": [],
    }

    for task in overdue_tasks:
        due_date_aware = _ensure_aware(task.due_date)
        days_overdue = (now - due_date_aware).days if due_date_aware else 0
        result["by_type"][task.task_type.value] += 1
        result["by_priority"][task.priority.value] += 1
        result["tasks"].append({
            "id": task.id,
            "device_id": task.device_id,
            "device_name": task.device.name if task.device else None,
            "device_serial": task.device.serial_number if task.device else None,
            "task_type": task.task_type.value,
            "title": task.title,
            "priority": task.priority.value,
            "status": task.status.value,
            "due_date": task.due_date,
            "days_overdue": days_overdue,
            "assigned_to": task.assigned_to.full_name if task.assigned_to else None,
        })

    return APIResponse(data=result)


@router.get("/{task_id}", response_model=APIResponse[TaskDetailResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_task(
    task_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    task = db.query(MaintenanceTask).filter(MaintenanceTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if current_user.role != UserRole.ADMIN and task.assigned_to_id != current_user.id:
        if task.status != TaskStatus.PENDING:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to view this task",
            )

    _update_overdue_tasks(db)
    db.refresh(task)

    return APIResponse(data=_build_task_detail(task))


@router.post("", response_model=APIResponse[TaskDetailResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def create_task(
    request: Request,
    task_data: TaskCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    device = db.query(Device).filter(Device.id == task_data.device_id).first()
    if not device:
        raise HTTPException(status_code=400, detail="Device not found")

    new_task = MaintenanceTask(**task_data.model_dump())
    new_task.created_by_id = current_user.id
    new_task.is_overdue = False

    db.add(new_task)
    db.commit()
    db.refresh(new_task)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.TASK_CREATE,
        resource_type="maintenance_task",
        resource_id=str(new_task.id),
        user=current_user,
        new_values={
            "device_id": new_task.device_id,
            "task_type": new_task.task_type.value,
            "title": new_task.title,
            "priority": new_task.priority.value,
            "scheduled_date": new_task.scheduled_date,
            "due_date": new_task.due_date,
        },
        description=f"Task created for device {device.serial_number}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Task created successfully",
        data=_build_task_detail(new_task),
    )


def _get_existing_tasks_by_type(db: Session) -> dict:
    existing_tasks = db.query(
        MaintenanceTask.device_id,
        MaintenanceTask.task_type,
    ).filter(
        MaintenanceTask.status.notin_([TaskStatus.COMPLETED, TaskStatus.CANCELLED]),
    ).all()
    result = {}
    for device_id, task_type in existing_tasks:
        if device_id not in result:
            result[device_id] = set()
        result[device_id].add(task_type)
    return result


def _has_active_repair(db: Session, device_id: int) -> bool:
    return db.query(RepairRecord).filter(
        RepairRecord.device_id == device_id,
        RepairRecord.status.notin_([
            RepairStatus.COMPLETED.value,
            RepairStatus.CANCELLED.value,
            RepairStatus.UNREPAIRABLE.value,
        ]),
    ).first() is not None


def _calculate_priority(due_date: datetime, now: datetime, task_type: TaskType) -> TaskPriority:
    base_priority = TaskPriority.MEDIUM
    if task_type == TaskType.REPAIR:
        base_priority = TaskPriority.HIGH

    if due_date <= now:
        if task_type == TaskType.REPAIR:
            return TaskPriority.URGENT
        return TaskPriority.HIGH
    elif due_date <= now + timedelta(days=1):
        return TaskPriority.HIGH
    elif due_date <= now + timedelta(days=3):
        return TaskPriority.MEDIUM if base_priority == TaskPriority.MEDIUM else TaskPriority.HIGH
    return base_priority


@router.post("/generate", response_model=APIResponse[TaskGenerateResult])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def generate_tasks(
    request: Request,
    req: TaskGenerateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    cutoff_date = now + timedelta(days=req.days_ahead)

    maintenance_count = 0
    disinfection_count = 0
    repair_count = 0
    skipped_due_to_repair = 0
    skipped_due_to_existing = 0

    existing_tasks_by_type = _get_existing_tasks_by_type(db)

    all_devices = db.query(Device).filter(
        Device.status.notin_([DeviceStatus.RETIRED]),
    ).all()

    task_generation_results = []
    cancelled_due_to_repair = 0

    for device in all_devices:
        device_tasks = existing_tasks_by_type.get(device.id, set())
        has_active_repair_task = TaskType.REPAIR in device_tasks
        has_active_maintenance_task = TaskType.MAINTENANCE in device_tasks
        has_active_disinfection_task = TaskType.DISINFECTION in device_tasks

        device_status = device.status.value if hasattr(device.status, 'value') else str(device.status)
        active_repair = db.query(RepairRecord).filter(
            RepairRecord.device_id == device.id,
            RepairRecord.status.notin_([
                RepairStatus.COMPLETED.value,
                RepairStatus.CANCELLED.value,
                RepairStatus.UNREPAIRABLE.value,
            ]),
        ).first()
        has_active_repair_record = active_repair is not None

        repair_task = None
        maintenance_task = None
        disinfection_task = None

        if not has_active_repair_task:
            if active_repair:
                priority = TaskPriority.URGENT
                if active_repair.priority == "urgent":
                    priority = TaskPriority.URGENT
                elif active_repair.priority == "high":
                    priority = TaskPriority.HIGH

                repair_task = MaintenanceTask(
                    device_id=device.id,
                    task_type=TaskType.REPAIR,
                    title=f"设备维修 - {device.name} ({device.serial_number})",
                    description=f"维修任务：{active_repair.fault_description}",
                    priority=priority,
                    status=TaskStatus.PENDING,
                    scheduled_date=now,
                    due_date=now + timedelta(days=3),
                    created_by_id=current_user.id,
                    repair_record_id=active_repair.id,
                    is_overdue=False,
                )
            elif device_status == DeviceStatus.REPAIR.value:
                repair_task = MaintenanceTask(
                    device_id=device.id,
                    task_type=TaskType.REPAIR,
                    title=f"设备维修（状态同步）- {device.name} ({device.serial_number})",
                    description="设备状态为维修中，但未找到维修记录，需要确认维修状态。",
                    priority=TaskPriority.HIGH,
                    status=TaskStatus.PENDING,
                    scheduled_date=now,
                    due_date=now + timedelta(days=1),
                    created_by_id=current_user.id,
                    is_overdue=False,
                )
        elif has_active_repair_record or device_status == DeviceStatus.REPAIR.value:
            skipped_due_to_repair += 1

        if not has_active_maintenance_task:
            next_maint = _ensure_aware(device.next_maintenance_date)
            if next_maint and next_maint <= cutoff_date:
                category = db.query(DeviceCategory).filter(
                    DeviceCategory.id == device.category_id
                ).first()
                priority = _calculate_priority(next_maint, now, TaskType.MAINTENANCE)
                maintenance_task = MaintenanceTask(
                    device_id=device.id,
                    task_type=TaskType.MAINTENANCE,
                    title=f"设备维护 - {device.name} ({device.serial_number})",
                    description=f"根据设备维护周期，需要对设备进行定期维护。维护周期：{category.maintenance_cycle_days if category else 30}天",
                    priority=priority,
                    status=TaskStatus.PENDING,
                    scheduled_date=next_maint,
                    due_date=next_maint,
                    created_by_id=current_user.id,
                    is_overdue=next_maint <= now,
                )
        else:
            skipped_due_to_existing += 1

        if not has_active_disinfection_task:
            category = db.query(DeviceCategory).filter(
                DeviceCategory.id == device.category_id
            ).first()
            if category and category.disinfection_required:
                disinfection_cycle_days = 7
                last_disinfect = _ensure_aware(device.last_disinfection_date)
                if last_disinfect is None:
                    next_disinfect = now
                else:
                    next_disinfect = last_disinfect + timedelta(days=disinfection_cycle_days)

                if next_disinfect <= cutoff_date:
                    priority = _calculate_priority(next_disinfect, now, TaskType.DISINFECTION)
                    disinfection_task = MaintenanceTask(
                        device_id=device.id,
                        task_type=TaskType.DISINFECTION,
                        title=f"设备消毒 - {device.name} ({device.serial_number})",
                        description="根据设备消毒要求，需要对设备进行定期消毒。",
                        priority=priority,
                        status=TaskStatus.PENDING,
                        scheduled_date=next_disinfect,
                        due_date=next_disinfect + timedelta(days=1),
                        created_by_id=current_user.id,
                        is_overdue=next_disinfect <= now,
                    )
        else:
            skipped_due_to_existing += 1

        if device_status == DeviceStatus.MAINTENANCE.value and not has_active_maintenance_task and maintenance_task is None:
            maintenance_task = MaintenanceTask(
                device_id=device.id,
                task_type=TaskType.MAINTENANCE,
                title=f"设备维护（状态同步）- {device.name} ({device.serial_number})",
                description="设备状态为维护中，但未找到维护任务，需要确认维护状态。",
                priority=TaskPriority.HIGH,
                status=TaskStatus.PENDING,
                scheduled_date=now,
                due_date=now + timedelta(days=1),
                created_by_id=current_user.id,
                is_overdue=False,
            )

        if device_status == DeviceStatus.DISINFECTION.value and not has_active_disinfection_task and disinfection_task is None:
            disinfection_task = MaintenanceTask(
                device_id=device.id,
                task_type=TaskType.DISINFECTION,
                title=f"设备消毒（状态同步）- {device.name} ({device.serial_number})",
                description="设备状态为消毒中，但未找到消毒任务，需要确认消毒状态。",
                priority=TaskPriority.HIGH,
                status=TaskStatus.PENDING,
                scheduled_date=now,
                due_date=now + timedelta(days=1),
                created_by_id=current_user.id,
                is_overdue=False,
            )

        if repair_task:
            db.add(repair_task)
            repair_count += 1
            task_generation_results.append({
                "device_id": device.id,
                "task_type": "repair",
                "priority": repair_task.priority.value,
            })
        if maintenance_task:
            db.add(maintenance_task)
            maintenance_count += 1
            task_generation_results.append({
                "device_id": device.id,
                "task_type": "maintenance",
                "priority": maintenance_task.priority.value,
            })
        if disinfection_task:
            db.add(disinfection_task)
            disinfection_count += 1
            task_generation_results.append({
                "device_id": device.id,
                "task_type": "disinfection",
                "priority": disinfection_task.priority.value,
            })

    db.commit()

    total = maintenance_count + disinfection_count + repair_count

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.TASK_GENERATE,
        resource_type="maintenance_task",
        user=current_user,
        new_values={
            "days_ahead": req.days_ahead,
            "tasks_created": total,
            "maintenance_tasks": maintenance_count,
            "disinfection_tasks": disinfection_count,
            "repair_tasks": repair_count,
            "skipped_due_to_repair": skipped_due_to_repair,
            "skipped_due_to_existing": skipped_due_to_existing,
            "cancelled_due_to_repair": cancelled_due_to_repair,
        },
        description=f"Generated {total} maintenance tasks (skipped: {skipped_due_to_repair + skipped_due_to_existing}, cancelled: {cancelled_due_to_repair})",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message=f"Generated {total} tasks successfully",
        data=TaskGenerateResult(
            tasks_created=total,
            maintenance_tasks=maintenance_count,
            disinfection_tasks=disinfection_count,
            repair_tasks=repair_count,
            skipped_due_to_repair=skipped_due_to_repair,
            skipped_due_to_existing=skipped_due_to_existing,
            cancelled_due_to_repair=cancelled_due_to_repair,
        ),
    )


@router.put("/{task_id}", response_model=APIResponse[TaskDetailResponse])
@require_role([UserRole.ADMIN])
async def update_task(
    request: Request,
    task_id: int,
    task_data: TaskUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    task = db.query(MaintenanceTask).filter(MaintenanceTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status in [TaskStatus.COMPLETED, TaskStatus.CANCELLED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update task with status: {task.status.value}",
        )

    old_values = {
        "title": task.title,
        "description": task.description,
        "priority": task.priority.value,
        "scheduled_date": task.scheduled_date,
        "due_date": task.due_date,
        "notes": task.notes,
    }

    update_data = task_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(task, field, value)

    now = datetime.now(timezone.utc)
    due_date_aware = _ensure_aware(task.due_date)
    task.is_overdue = due_date_aware < now if due_date_aware else False

    db.commit()
    db.refresh(task)

    audit_logger = AuditLogger(db)
    audit_logger.log_update(
        resource_type="maintenance_task",
        resource_id=str(task_id),
        user=current_user,
        old_values=old_values,
        new_values=update_data,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Task updated successfully",
        data=_build_task_detail(task),
    )


@router.post("/{task_id}/claim", response_model=APIResponse[TaskDetailResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def claim_task(
    request: Request,
    task_id: int,
    claim_data: TaskClaim,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    task = db.query(MaintenanceTask).filter(MaintenanceTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != TaskStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot claim task with status: {task.status.value}",
        )

    old_status = task.status.value
    task.status = TaskStatus.CLAIMED
    task.assigned_to_id = current_user.id

    db.commit()
    db.refresh(task)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.TASK_CLAIM,
        resource_type="maintenance_task",
        resource_id=str(task_id),
        user=current_user,
        old_values={"status": old_status, "assigned_to_id": None},
        new_values={"status": TaskStatus.CLAIMED.value, "assigned_to_id": current_user.id},
        description=f"Task claimed by {current_user.full_name}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Task claimed successfully",
        data=_build_task_detail(task),
    )


@router.post("/{task_id}/start", response_model=APIResponse[TaskDetailResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def start_task(
    request: Request,
    task_id: int,
    start_data: TaskStart,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    task = db.query(MaintenanceTask).filter(MaintenanceTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.assigned_to_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="You are not assigned to this task",
        )

    if task.status not in [TaskStatus.PENDING, TaskStatus.CLAIMED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start task with status: {task.status.value}",
        )

    old_status = task.status.value
    task.status = TaskStatus.IN_PROGRESS
    task.assigned_to_id = current_user.id

    device = db.query(Device).filter(Device.id == task.device_id).first()
    if device:
        if task.task_type == TaskType.MAINTENANCE:
            device.status = DeviceStatus.MAINTENANCE
        elif task.task_type == TaskType.DISINFECTION:
            device.status = DeviceStatus.DISINFECTION
        elif task.task_type == TaskType.REPAIR:
            device.status = DeviceStatus.REPAIR

    db.commit()
    db.refresh(task)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.TASK_START,
        resource_type="maintenance_task",
        resource_id=str(task_id),
        user=current_user,
        old_values={"status": old_status},
        new_values={"status": TaskStatus.IN_PROGRESS.value},
        description=f"Task started by {current_user.full_name}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Task started successfully",
        data=_build_task_detail(task),
    )


@router.post("/{task_id}/complete", response_model=APIResponse[TaskDetailResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def complete_task(
    request: Request,
    task_id: int,
    complete_data: TaskComplete,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    task = db.query(MaintenanceTask).filter(MaintenanceTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.assigned_to_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="You are not assigned to this task",
        )

    if task.status != TaskStatus.IN_PROGRESS:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot complete task with status: {task.status.value}",
        )

    now = complete_data.actual_date or datetime.now(timezone.utc)
    old_status = task.status.value
    task.status = TaskStatus.COMPLETED
    task.completed_date = now
    task.completion_notes = complete_data.completion_notes
    task.assigned_to_id = current_user.id

    device = db.query(Device).filter(Device.id == task.device_id).first()
    category = db.query(DeviceCategory).filter(
        DeviceCategory.id == device.category_id
    ).first() if device else None

    old_device_values = {}
    new_device_values = {}

    if device:
        old_device_values = {
            "last_maintenance_date": device.last_maintenance_date,
            "last_disinfection_date": device.last_disinfection_date,
            "next_maintenance_date": device.next_maintenance_date,
            "status": device.status.value if device.status else None,
        }

        if task.task_type == TaskType.MAINTENANCE:
            device.last_maintenance_date = now
            cycle_days = category.maintenance_cycle_days if category else 30
            device.next_maintenance_date = now + timedelta(days=cycle_days)

            maintenance_record = MaintenanceRecord(
                device_id=device.id,
                maintenance_type="preventive",
                status="completed",
                scheduled_date=task.scheduled_date,
                actual_date=now,
                technician_name=current_user.full_name,
                description=task.description,
                work_performed=complete_data.completion_notes,
                next_maintenance_date=device.next_maintenance_date,
                is_successful=True,
            )
            db.add(maintenance_record)
            db.flush()
            task.maintenance_record_id = maintenance_record.id

        elif task.task_type == TaskType.DISINFECTION:
            device.last_disinfection_date = now

            disinfection_record = DisinfectionRecord(
                device_id=device.id,
                disinfection_date=now,
                disinfectant_type="Standard",
                operator_name=current_user.full_name,
                is_qualified=True,
                inspection_notes=complete_data.completion_notes,
            )
            db.add(disinfection_record)
            db.flush()
            task.disinfection_record_id = disinfection_record.id

        elif task.task_type == TaskType.REPAIR:
            if task.repair_record_id:
                repair_record = db.query(RepairRecord).filter(
                    RepairRecord.id == task.repair_record_id
                ).first()
                if repair_record:
                    repair_record.status = RepairStatus.COMPLETED.value
                    repair_record.repair_complete_date = now
                    repair_record.handled_by_id = current_user.id
                    repair_record.technician_notes = complete_data.completion_notes

            if category and category.disinfection_required:
                existing_tasks = _get_existing_tasks_by_type(db)
                device_tasks = existing_tasks.get(task.device_id, set())
                if TaskType.DISINFECTION not in device_tasks:
                    post_repair_disinfection = MaintenanceTask(
                        device_id=task.device_id,
                        task_type=TaskType.DISINFECTION,
                        title=f"维修后消毒 - {device.name} ({device.serial_number})",
                        description="设备维修完成后需要进行消毒处理，确保设备卫生安全后方可投入使用。",
                        priority=TaskPriority.HIGH,
                        status=TaskStatus.PENDING,
                        scheduled_date=now,
                        due_date=now + timedelta(days=1),
                        created_by_id=current_user.id,
                        is_overdue=False,
                    )
                    db.add(post_repair_disinfection)

        if device.status in [
            DeviceStatus.MAINTENANCE,
            DeviceStatus.DISINFECTION,
            DeviceStatus.REPAIR,
        ]:
            device.status = DeviceStatus.AVAILABLE

        new_device_values = {
            "last_maintenance_date": device.last_maintenance_date,
            "last_disinfection_date": device.last_disinfection_date,
            "next_maintenance_date": device.next_maintenance_date,
            "status": device.status.value if device.status else None,
        }

    db.commit()
    db.refresh(task)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.TASK_COMPLETE,
        resource_type="maintenance_task",
        resource_id=str(task_id),
        user=current_user,
        old_values={"status": old_status},
        new_values={
            "status": TaskStatus.COMPLETED.value,
            "completed_date": now,
            "completion_notes": complete_data.completion_notes,
        },
        description=f"Task completed by {current_user.full_name}",
        ip_address=request.client.host if request.client else None,
    )

    if old_device_values and new_device_values and old_device_values != new_device_values:
        audit_logger.log(
            action=AuditAction.UPDATE,
            resource_type="device",
            resource_id=str(task.device_id),
            user=current_user,
            old_values=old_device_values,
            new_values=new_device_values,
            description=f"Device updated after task completion: {task.task_type.value}",
            ip_address=request.client.host if request.client else None,
        )

    if task.task_type == TaskType.MAINTENANCE and task.maintenance_record_id:
        audit_logger.log(
            action=AuditAction.MAINTAIN,
            resource_type="maintenance_record",
            resource_id=str(task.maintenance_record_id),
            user=current_user,
            new_values={"device_id": task.device_id, "actual_date": now},
            description=f"Maintenance record created from task",
            ip_address=request.client.host if request.client else None,
        )

    if task.task_type == TaskType.DISINFECTION and task.disinfection_record_id:
        audit_logger.log(
            action=AuditAction.DISINFECT,
            resource_type="disinfection_record",
            resource_id=str(task.disinfection_record_id),
            user=current_user,
            new_values={"device_id": task.device_id, "disinfection_date": now},
            description=f"Disinfection record created from task",
            ip_address=request.client.host if request.client else None,
        )

    return APIResponse(
        message="Task completed successfully",
        data=_build_task_detail(task),
    )


@router.post("/{task_id}/cancel", response_model=APIResponse[TaskDetailResponse])
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def cancel_task(
    request: Request,
    task_id: int,
    cancel_data: TaskCancel,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    task = db.query(MaintenanceTask).filter(MaintenanceTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.assigned_to_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="You are not assigned to this task",
        )

    if task.status == TaskStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel a completed task",
        )

    old_status = task.status.value
    task.status = TaskStatus.CANCELLED
    task.completion_notes = f"Cancelled: {cancel_data.reason}"

    device = db.query(Device).filter(Device.id == task.device_id).first()
    if device and device.status in [
        DeviceStatus.MAINTENANCE,
        DeviceStatus.DISINFECTION,
        DeviceStatus.REPAIR,
    ]:
        device.status = DeviceStatus.AVAILABLE

    db.commit()
    db.refresh(task)

    audit_logger = AuditLogger(db)
    audit_logger.log(
        action=AuditAction.TASK_CANCEL,
        resource_type="maintenance_task",
        resource_id=str(task_id),
        user=current_user,
        old_values={"status": old_status},
        new_values={
            "status": TaskStatus.CANCELLED.value,
            "completion_notes": task.completion_notes,
        },
        description=f"Task cancelled by {current_user.full_name}: {cancel_data.reason}",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message="Task cancelled successfully",
        data=_build_task_detail(task),
    )


@router.delete("/{task_id}", response_model=APIResponse)
@require_role([UserRole.ADMIN])
async def delete_task(
    request: Request,
    task_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    task = db.query(MaintenanceTask).filter(MaintenanceTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    old_values = {
        "id": task.id,
        "device_id": task.device_id,
        "task_type": task.task_type.value,
        "title": task.title,
        "status": task.status.value,
    }

    db.delete(task)
    db.commit()

    audit_logger = AuditLogger(db)
    audit_logger.log_delete(
        resource_type="maintenance_task",
        resource_id=str(task_id),
        user=current_user,
        old_values=old_values,
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(message="Task deleted successfully")


@router.get("/stats/dashboard", response_model=APIResponse)
@require_role([UserRole.ADMIN])
async def get_task_dashboard(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _update_overdue_tasks(db)
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)
    seven_days_ago = now - timedelta(days=7)

    all_active_tasks = db.query(MaintenanceTask).filter(
        MaintenanceTask.status.notin_([TaskStatus.COMPLETED, TaskStatus.CANCELLED])
    ).all()

    pending_tasks = [t for t in all_active_tasks if t.status == TaskStatus.PENDING]
    in_progress_tasks = [t for t in all_active_tasks if t.status == TaskStatus.IN_PROGRESS]
    claimed_tasks = [t for t in all_active_tasks if t.status == TaskStatus.CLAIMED]
    overdue_tasks = [t for t in all_active_tasks if t.is_overdue]

    completed_last_30 = db.query(MaintenanceTask).filter(
        MaintenanceTask.status == TaskStatus.COMPLETED,
        MaintenanceTask.completed_date >= thirty_days_ago,
    ).all()

    completed_last_7 = db.query(MaintenanceTask).filter(
        MaintenanceTask.status == TaskStatus.COMPLETED,
        MaintenanceTask.completed_date >= seven_days_ago,
    ).all()

    by_type = {
        "maintenance": {
            "pending": len([t for t in all_active_tasks if t.task_type == TaskType.MAINTENANCE and t.status == TaskStatus.PENDING]),
            "in_progress": len([t for t in all_active_tasks if t.task_type == TaskType.MAINTENANCE and t.status == TaskStatus.IN_PROGRESS]),
            "overdue": len([t for t in all_active_tasks if t.task_type == TaskType.MAINTENANCE and t.is_overdue]),
            "completed_30d": len([t for t in completed_last_30 if t.task_type == TaskType.MAINTENANCE]),
            "completed_7d": len([t for t in completed_last_7 if t.task_type == TaskType.MAINTENANCE]),
        },
        "disinfection": {
            "pending": len([t for t in all_active_tasks if t.task_type == TaskType.DISINFECTION and t.status == TaskStatus.PENDING]),
            "in_progress": len([t for t in all_active_tasks if t.task_type == TaskType.DISINFECTION and t.status == TaskStatus.IN_PROGRESS]),
            "overdue": len([t for t in all_active_tasks if t.task_type == TaskType.DISINFECTION and t.is_overdue]),
            "completed_30d": len([t for t in completed_last_30 if t.task_type == TaskType.DISINFECTION]),
            "completed_7d": len([t for t in completed_last_7 if t.task_type == TaskType.DISINFECTION]),
        },
        "repair": {
            "pending": len([t for t in all_active_tasks if t.task_type == TaskType.REPAIR and t.status == TaskStatus.PENDING]),
            "in_progress": len([t for t in all_active_tasks if t.task_type == TaskType.REPAIR and t.status == TaskStatus.IN_PROGRESS]),
            "overdue": len([t for t in all_active_tasks if t.task_type == TaskType.REPAIR and t.is_overdue]),
            "completed_30d": len([t for t in completed_last_30 if t.task_type == TaskType.REPAIR]),
            "completed_7d": len([t for t in completed_last_7 if t.task_type == TaskType.REPAIR]),
        },
    }

    by_priority = {
        "low": len([t for t in all_active_tasks if t.priority == TaskPriority.LOW]),
        "medium": len([t for t in all_active_tasks if t.priority == TaskPriority.MEDIUM]),
        "high": len([t for t in all_active_tasks if t.priority == TaskPriority.HIGH]),
        "urgent": len([t for t in all_active_tasks if t.priority == TaskPriority.URGENT]),
    }

    staff_performance = []
    staff_users = db.query(User).filter(
        User.role.in_([UserRole.ADMIN.value, UserRole.STAFF.value]),
        User.is_active == True,
    ).all()

    for staff in staff_users:
        staff_completed = len([t for t in completed_last_30 if t.assigned_to_id == staff.id])
        staff_active = len([t for t in all_active_tasks if t.assigned_to_id == staff.id])
        staff_overdue = len([t for t in all_active_tasks if t.assigned_to_id == staff.id and t.is_overdue])
        staff_performance.append({
            "user_id": staff.id,
            "user_name": staff.full_name,
            "role": staff.role.value,
            "active_tasks": staff_active,
            "completed_last_30d": staff_completed,
            "overdue_tasks": staff_overdue,
        })

    devices_with_multiple_tasks = []
    task_counts = {}
    for task in all_active_tasks:
        if task.device_id not in task_counts:
            task_counts[task.device_id] = []
        task_counts[task.device_id].append(task)

    for device_id, tasks in task_counts.items():
        if len(tasks) > 1:
            device = db.query(Device).filter(Device.id == device_id).first()
            devices_with_multiple_tasks.append({
                "device_id": device_id,
                "device_name": device.name if device else None,
                "device_serial": device.serial_number if device else None,
                "device_status": device.status.value if device and device.status else None,
                "task_count": len(tasks),
                "tasks": [{
                    "id": t.id,
                    "type": t.task_type.value,
                    "status": t.status.value,
                    "priority": t.priority.value,
                } for t in tasks],
            })

    stats = {
        "summary": {
            "total_active": len(all_active_tasks),
            "pending": len(pending_tasks),
            "claimed": len(claimed_tasks),
            "in_progress": len(in_progress_tasks),
            "overdue": len(overdue_tasks),
            "completed_last_7d": len(completed_last_7),
            "completed_last_30d": len(completed_last_30),
        },
        "by_type": by_type,
        "by_priority": by_priority,
        "staff_performance": staff_performance,
        "devices_with_multiple_tasks": devices_with_multiple_tasks,
    }

    return APIResponse(data=stats)


@router.get("/stats/my", response_model=APIResponse)
@require_role([UserRole.ADMIN, UserRole.STAFF])
async def get_my_task_stats(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _update_overdue_tasks(db)
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)

    my_tasks = db.query(MaintenanceTask).filter(
        MaintenanceTask.assigned_to_id == current_user.id
    ).all()

    my_active = [t for t in my_tasks if t.status not in [TaskStatus.COMPLETED, TaskStatus.CANCELLED]]
    my_pending = [t for t in my_active if t.status == TaskStatus.PENDING]
    my_claimed = [t for t in my_active if t.status == TaskStatus.CLAIMED]
    my_in_progress = [t for t in my_active if t.status == TaskStatus.IN_PROGRESS]
    my_overdue = [t for t in my_active if t.is_overdue]

    my_completed_30d = [t for t in my_tasks if t.status == TaskStatus.COMPLETED and t.completed_date and _ensure_aware(t.completed_date) >= thirty_days_ago]

    stats = {
        "summary": {
            "total_assigned": len(my_tasks),
            "active": len(my_active),
            "pending": len(my_pending),
            "claimed": len(my_claimed),
            "in_progress": len(my_in_progress),
            "overdue": len(my_overdue),
            "completed_last_30d": len(my_completed_30d),
        },
        "by_type": {
            "maintenance": {
                "active": len([t for t in my_active if t.task_type == TaskType.MAINTENANCE]),
                "completed": len([t for t in my_completed_30d if t.task_type == TaskType.MAINTENANCE]),
            },
            "disinfection": {
                "active": len([t for t in my_active if t.task_type == TaskType.DISINFECTION]),
                "completed": len([t for t in my_completed_30d if t.task_type == TaskType.DISINFECTION]),
            },
            "repair": {
                "active": len([t for t in my_active if t.task_type == TaskType.REPAIR]),
                "completed": len([t for t in my_completed_30d if t.task_type == TaskType.REPAIR]),
            },
        },
        "by_priority": {
            "low": len([t for t in my_active if t.priority == TaskPriority.LOW]),
            "medium": len([t for t in my_active if t.priority == TaskPriority.MEDIUM]),
            "high": len([t for t in my_active if t.priority == TaskPriority.HIGH]),
            "urgent": len([t for t in my_active if t.priority == TaskPriority.URGENT]),
        },
    }

    return APIResponse(data=stats)

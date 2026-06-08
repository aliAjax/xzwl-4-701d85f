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

    existing_task_device_ids = db.query(MaintenanceTask.device_id).filter(
        MaintenanceTask.status.notin_([TaskStatus.COMPLETED, TaskStatus.CANCELLED]),
    ).distinct().all()
    existing_device_ids = {row[0] for row in existing_task_device_ids}

    all_devices = db.query(Device).filter(
        Device.status.notin_([DeviceStatus.RETIRED]),
        ~Device.id.in_(existing_device_ids),
    ).all()

    devices_needing_maintenance = []
    for device in all_devices:
        next_maint = _ensure_aware(device.next_maintenance_date)
        if next_maint and next_maint <= cutoff_date:
            devices_needing_maintenance.append(device)

    for device in devices_needing_maintenance:
        category = db.query(DeviceCategory).filter(
            DeviceCategory.id == device.category_id
        ).first()

        next_maint = _ensure_aware(device.next_maintenance_date) or now
        priority = TaskPriority.MEDIUM
        if next_maint <= now:
            priority = TaskPriority.URGENT
        elif next_maint <= now + timedelta(days=2):
            priority = TaskPriority.HIGH

        task = MaintenanceTask(
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
        db.add(task)
        maintenance_count += 1

    disinfection_cycle_days = 7
    devices_needing_disinfection = []
    for device in all_devices:
        category = db.query(DeviceCategory).filter(
            DeviceCategory.id == device.category_id
        ).first()
        if not category or not category.disinfection_required:
            continue
        last_disinfect = _ensure_aware(device.last_disinfection_date)
        if last_disinfect is None:
            devices_needing_disinfection.append(device)
        else:
            next_disinfect = last_disinfect + timedelta(days=disinfection_cycle_days)
            if next_disinfect <= cutoff_date:
                devices_needing_disinfection.append(device)

    for device in devices_needing_disinfection:
        last_disinfect = _ensure_aware(device.last_disinfection_date)
        if last_disinfect:
            next_disinfection_date = last_disinfect + timedelta(days=disinfection_cycle_days)
        else:
            next_disinfection_date = now

        priority = TaskPriority.MEDIUM
        if next_disinfection_date <= now:
            priority = TaskPriority.HIGH

        task = MaintenanceTask(
            device_id=device.id,
            task_type=TaskType.DISINFECTION,
            title=f"设备消毒 - {device.name} ({device.serial_number})",
            description="根据设备消毒要求，需要对设备进行定期消毒。",
            priority=priority,
            status=TaskStatus.PENDING,
            scheduled_date=next_disinfection_date,
            due_date=next_disinfection_date + timedelta(days=1),
            created_by_id=current_user.id,
            is_overdue=next_disinfection_date <= now,
        )
        db.add(task)
        disinfection_count += 1

    active_repairs = db.query(RepairRecord).filter(
        RepairRecord.status.notin_([
            RepairStatus.COMPLETED.value,
            RepairStatus.CANCELLED.value,
            RepairStatus.UNREPAIRABLE.value,
        ]),
        ~RepairRecord.device_id.in_(existing_device_ids),
    ).all()

    for repair in active_repairs:
        priority = TaskPriority.MEDIUM
        if repair.priority == "urgent":
            priority = TaskPriority.URGENT
        elif repair.priority == "high":
            priority = TaskPriority.HIGH

        task = MaintenanceTask(
            device_id=repair.device_id,
            task_type=TaskType.REPAIR,
            title=f"设备维修 - {repair.device.name if repair.device else '未知设备'}",
            description=f"维修任务：{repair.fault_description}",
            priority=priority,
            status=TaskStatus.PENDING,
            scheduled_date=now,
            due_date=now + timedelta(days=3),
            created_by_id=current_user.id,
            repair_record_id=repair.id,
            is_overdue=False,
        )
        db.add(task)
        repair_count += 1

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
        },
        description=f"Generated {total} maintenance tasks",
        ip_address=request.client.host if request.client else None,
    )

    return APIResponse(
        message=f"Generated {total} tasks successfully",
        data=TaskGenerateResult(
            tasks_created=total,
            maintenance_tasks=maintenance_count,
            disinfection_tasks=disinfection_count,
            repair_tasks=repair_count,
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

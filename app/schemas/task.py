from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from ..models.task import TaskType, TaskStatus, TaskPriority


class TaskBase(BaseModel):
    device_id: int = Field(..., gt=0)
    task_type: TaskType
    title: str = Field(..., max_length=200)
    description: str
    priority: TaskPriority = TaskPriority.MEDIUM
    scheduled_date: datetime
    due_date: datetime
    notes: Optional[str] = None


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    priority: Optional[TaskPriority] = None
    scheduled_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    notes: Optional[str] = None


class TaskClaim(BaseModel):
    pass


class TaskStart(BaseModel):
    pass


class TaskComplete(BaseModel):
    completion_notes: str
    actual_date: Optional[datetime] = None


class TaskCancel(BaseModel):
    reason: str


class TaskGenerateRequest(BaseModel):
    days_ahead: int = Field(7, gt=0, le=90)


class TaskResponse(BaseModel):
    id: int
    device_id: int
    task_type: TaskType
    title: str
    description: str
    priority: TaskPriority
    status: TaskStatus
    scheduled_date: datetime
    due_date: datetime
    completed_date: Optional[datetime]
    created_by_id: int
    assigned_to_id: Optional[int]
    maintenance_record_id: Optional[int]
    disinfection_record_id: Optional[int]
    repair_record_id: Optional[int]
    completion_notes: Optional[str]
    notes: Optional[str]
    is_overdue: bool
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class TaskDetailResponse(TaskResponse):
    device_name: Optional[str] = None
    device_serial_number: Optional[str] = None
    device_status: Optional[str] = None
    assigned_to_name: Optional[str] = None
    created_by_name: Optional[str] = None


class TaskGenerateResult(BaseModel):
    tasks_created: int
    maintenance_tasks: int
    disinfection_tasks: int
    repair_tasks: int

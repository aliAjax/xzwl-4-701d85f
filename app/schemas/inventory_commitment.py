from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

from ..models.inventory_commitment import CommitmentType, CommitmentStatus
from .warehouse import WarehouseResponse
from .device import DeviceCategoryResponse


class InventoryCommitmentBase(BaseModel):
    device_id: int = Field(..., gt=0)
    warehouse_id: int = Field(..., gt=0)
    category_id: int = Field(..., gt=0)
    commitment_type: CommitmentType
    start_date: datetime
    end_date: datetime
    reference_id: Optional[int] = None
    reference_type: Optional[str] = Field(None, max_length=50)
    expires_at: Optional[datetime] = None
    notes: Optional[str] = None


class InventoryCommitmentCreate(InventoryCommitmentBase):
    pass


class InventoryCommitmentCreateBulk(BaseModel):
    device_ids: List[int] = Field(..., min_length=1)
    warehouse_id: int = Field(..., gt=0)
    category_id: int = Field(..., gt=0)
    commitment_type: CommitmentType
    start_date: datetime
    end_date: datetime
    reference_id: Optional[int] = None
    reference_type: Optional[str] = Field(None, max_length=50)
    expires_at: Optional[datetime] = None
    notes: Optional[str] = None


class InventoryCommitmentUpdate(BaseModel):
    status: Optional[CommitmentStatus] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    notes: Optional[str] = None


class InventoryCommitmentResponse(BaseModel):
    id: int
    commitment_token: str
    batch_token: Optional[str] = None
    device_id: int
    warehouse_id: int
    warehouse: Optional[WarehouseResponse] = None
    category_id: int
    category: Optional[DeviceCategoryResponse] = None
    commitment_type: CommitmentType
    status: CommitmentStatus
    start_date: datetime
    end_date: datetime
    reference_id: Optional[int]
    reference_type: Optional[str]
    created_by_id: int
    expires_at: Optional[datetime]
    confirmed_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    notes: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class BatchTokenRequest(BaseModel):
    batch_token: str


class AvailablePromiseQuery(BaseModel):
    category_id: int = Field(..., gt=0)
    start_date: datetime
    end_date: datetime
    warehouse_id: Optional[int] = None


class AvailablePromiseResponse(BaseModel):
    category_id: int
    category_name: str
    warehouse_id: Optional[int]
    warehouse_name: Optional[str]
    start_date: datetime
    end_date: datetime
    total_available: int
    total_in_warehouse: int
    committed_quantity: int
    breakdown: dict

    class Config:
        from_attributes = True


class CommitmentConfirmRequest(BaseModel):
    commitment_token: str


class CommitmentReleaseRequest(BaseModel):
    commitment_token: str

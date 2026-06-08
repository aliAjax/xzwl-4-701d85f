from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

from ..models.device_import import ImportStatus, ImportItemStatus, ValidationErrorType


class BatchDeviceItem(BaseModel):
    serial_number: str = Field(..., max_length=100)
    name: str = Field(..., max_length=100)
    model: Optional[str] = Field(None, max_length=100)
    manufacturer: Optional[str] = Field(None, max_length=100)
    purchase_date: Optional[str] = None
    purchase_price: Optional[float] = Field(None, ge=0)
    current_owner: Optional[str] = Field(None, max_length=100)
    location: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None
    category_id: int = Field(..., gt=0)
    category_name: Optional[str] = None


class BatchImportPreviewRequest(BaseModel):
    items: List[BatchDeviceItem]
    remarks: Optional[str] = None


class ValidationErrorDetail(BaseModel):
    error_type: ValidationErrorType
    field: Optional[str] = None
    message: str


class ImportItemPreview(BaseModel):
    row_index: int
    data: Dict[str, Any]
    status: ImportItemStatus
    errors: List[ValidationErrorDetail]


class BatchImportPreviewResponse(BaseModel):
    import_id: int
    batch_number: str
    total_count: int
    valid_count: int
    invalid_count: int
    items: List[ImportItemPreview]
    can_confirm: bool
    error_summary: List[str]


class BatchImportConfirmRequest(BaseModel):
    import_id: int


class ImportItemResponse(BaseModel):
    id: int
    import_id: int
    row_index: int
    serial_number: Optional[str]
    name: Optional[str]
    model: Optional[str]
    manufacturer: Optional[str]
    purchase_date: Optional[datetime]
    purchase_price: Optional[float]
    category_id: Optional[int]
    category_name: Optional[str]
    status: ImportItemStatus
    validation_errors: Optional[List[ValidationErrorDetail]]
    error_message: Optional[str]
    device_id: Optional[int]

    class Config:
        from_attributes = True


class ImportBatchResponse(BaseModel):
    id: int
    batch_number: str
    total_count: int
    valid_count: int
    invalid_count: int
    imported_count: int
    status: ImportStatus
    remarks: Optional[str]
    created_by: Optional[str]
    created_at: datetime
    previewed_at: Optional[datetime]
    confirmed_at: Optional[datetime]

    class Config:
        from_attributes = True


class ImportBatchDetailResponse(ImportBatchResponse):
    items: List[ImportItemResponse]

from .common import Token, TokenData, APIResponse, PaginatedResponse
from .user import UserCreate, UserUpdate, UserResponse, UserLogin
from .device import (
    DeviceCategoryCreate,
    DeviceCategoryUpdate,
    DeviceCategoryResponse,
    DeviceCreate,
    DeviceUpdate,
    DeviceResponse,
    DeviceStatusUpdate,
)
from .contract import (
    ContractCreate,
    ContractUpdate,
    ContractResponse,
    ContractItemCreate,
    ContractItemResponse,
    ContractStatusUpdate,
    RenewContractRequest,
    ReturnContractRequest,
)
from .contract_reminder import (
    ContractExpiryResponse,
    ContractReminderCreate,
    ContractReminderUpdateStatus,
    ContractReminderResponse,
)
from .disinfection import DisinfectionRecordCreate, DisinfectionRecordUpdate, DisinfectionRecordResponse
from .maintenance import MaintenanceRecordCreate, MaintenanceRecordUpdate, MaintenanceRecordResponse
from .repair import RepairRecordCreate, RepairRecordUpdate, RepairRecordResponse, RepairStatusUpdate
from .deposit import DepositCreate, DepositUpdate, DepositResponse, DepositRefundRequest
from .audit import AuditLogResponse
from .locking import LockDevicesRequest, LockResponse, UnlockDevicesRequest, DeviceLockResponse
from .reservation import (
    ReservationCreate,
    ReservationUpdate,
    ReservationResponse,
    ReservationStatusUpdate,
    ReservationCancelRequest,
)
from .quotation import (
    QuotationCreate,
    QuotationUpdate,
    QuotationResponse,
    QuotationItemResponse,
    QuotationStatusUpdate,
    QuotationVoidRequest,
)
from .device_transfer import (
    DeviceTransferCreate,
    DeviceTransferConfirm,
    DeviceTransferCancel,
    DeviceTransferResponse,
)
from .customer_credit_note import (
    CustomerCreditNoteCreate,
    CustomerCreditNoteUpdate,
    CustomerCreditNoteResolve,
    CustomerCreditNoteResponse,
    CustomerRiskSummary,
    RiskSummaryItem,
)
from .device_import import (
    BatchDeviceItem,
    BatchImportPreviewRequest,
    BatchImportPreviewResponse,
    BatchImportConfirmRequest,
    ImportItemResponse,
    ImportBatchResponse,
    ImportBatchDetailResponse,
    ImportItemPreview,
    ValidationErrorDetail,
)
from .device_swap import (
    DeviceSwapCreate,
    DeviceSwapPreviewRequest,
    DeviceSwapPreviewResponse,
    DeviceSwapCancel,
    DeviceSwapResponse,
)

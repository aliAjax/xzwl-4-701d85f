from fastapi import FastAPI, Request, status, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timezone

from .config import settings
from .database import engine, Base, SessionLocal
from .routers import (
    auth_router,
    users_router,
    devices_router,
    categories_router,
    contracts_router,
    contract_reminders_router,
    disinfection_router,
    maintenance_router,
    repairs_router,
    deposits_router,
    locking_router,
    audit_router,
    reservations_router,
    quotations_router,
    device_transfers_router,
    customer_credit_notes_router,
)
from .models.contract import Contract, ContractStatus
from .models.device import DeviceStatus

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    description="Backend system for small medical equipment rental company",
    version="1.0.0",
    debug=settings.APP_DEBUG,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(devices_router)
app.include_router(categories_router)
app.include_router(contracts_router)
app.include_router(contract_reminders_router)
app.include_router(disinfection_router)
app.include_router(maintenance_router)
app.include_router(repairs_router)
app.include_router(deposits_router)
app.include_router(locking_router)
app.include_router(audit_router)
app.include_router(reservations_router)
app.include_router(quotations_router)
app.include_router(device_transfers_router)
app.include_router(customer_credit_notes_router)


@app.middleware("http")
async def update_overdue_contracts(request: Request, call_next):
    if request.method != "OPTIONS":
        db: Session = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            active_contracts = db.query(Contract).filter(
                Contract.status.in_([ContractStatus.ACTIVE, ContractStatus.RENEWED]),
                Contract.end_date < now,
            ).all()

            for contract in active_contracts:
                old_status = contract.status.value if hasattr(contract.status, "value") else str(contract.status)
                contract.status = ContractStatus.OVERDUE

                from .core import AuditLogger, AuditAction
                audit_logger = AuditLogger(db)
                audit_logger.log(
                    action=AuditAction.OVERDUE,
                    resource_type="contract",
                    resource_id=str(contract.id),
                    user=None,
                    old_values={"status": old_status},
                    new_values={"status": ContractStatus.OVERDUE.value},
                    description=f"Contract {contract.contract_number} marked as overdue",
                )
            db.commit()
        except Exception as e:
            db.rollback()
        finally:
            db.close()

    response = await call_next(request)
    return response


@app.get("/", tags=["Root"])
async def root():
    return {
        "name": settings.APP_NAME,
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "redoc": "/redoc",
    }


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "app_env": settings.APP_ENV,
    }


@app.get("/api/stats", tags=["Statistics"])
async def get_statistics():
    db: Session = SessionLocal()
    try:
        from .models.device import Device
        from .models.user import User
        from .models.repair import RepairRecord
        from .models.disinfection import DisinfectionRecord

        total_devices = db.query(Device).count()
        available_devices = db.query(Device).filter(
            Device.status == DeviceStatus.AVAILABLE
        ).count()
        in_use_devices = db.query(Device).filter(
            Device.status == DeviceStatus.IN_USE
        ).count()
        maintenance_devices = db.query(Device).filter(
            Device.status.in_([DeviceStatus.MAINTENANCE, DeviceStatus.REPAIR])
        ).count()
        disinfection_devices = db.query(Device).filter(
            Device.status == DeviceStatus.DISINFECTION
        ).count()

        total_users = db.query(User).count()
        total_contracts = db.query(Contract).count()
        active_contracts = db.query(Contract).filter(
            Contract.status.in_([ContractStatus.ACTIVE, ContractStatus.RENEWED, ContractStatus.OVERDUE])
        ).count()
        overdue_contracts = db.query(Contract).filter(
            Contract.status == ContractStatus.OVERDUE
        ).count()

        open_repairs = db.query(RepairRecord).filter(
            RepairRecord.status.notin_(["completed", "cancelled", "unrepairable"])
        ).count()

        total_revenue = db.query(Contract).with_entities(
            func.sum(Contract.final_amount)
        ).scalar() or 0.0

        total_overdue_fees = db.query(Contract).with_entities(
            func.sum(Contract.overdue_fee)
        ).scalar() or 0.0

        return {
            "devices": {
                "total": total_devices,
                "available": available_devices,
                "in_use": in_use_devices,
                "maintenance": maintenance_devices,
                "disinfection": disinfection_devices,
            },
            "users": {
                "total": total_users,
            },
            "contracts": {
                "total": total_contracts,
                "active": active_contracts,
                "overdue": overdue_contracts,
            },
            "repairs": {
                "open": open_repairs,
            },
            "finance": {
                "total_revenue": total_revenue,
                "total_overdue_fees": total_overdue_fees,
            },
        }
    finally:
        db.close()


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "message": f"Internal server error: {str(exc)}",
            "data": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.detail,
            "data": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

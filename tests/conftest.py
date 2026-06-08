import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone

from app.database import Base
from app.models import (
    Device, DeviceCategory, DeviceStatus,
    Warehouse, WarehouseStatus, User, UserRole
)

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def test_engine():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(test_engine):
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine
    )
    db = TestingSessionLocal()
    yield db
    db.close()


@pytest.fixture(scope="function")
def seed_data(db_session):
    user = User(
        id=1,
        username="testuser",
        email="test@example.com",
        full_name="Test User",
        phone="13800138000",
        hashed_password="hashedpassword",
        role=UserRole.ADMIN,
        is_active=True,
        id_card="110101199001011234"
    )
    db_session.add(user)

    category_valid = DeviceCategory(
        id=1,
        name="Valid Category",
        description="Valid category with deposit and rental rate",
        daily_rental_rate=100.0,
        deposit_amount=500.0
    )
    db_session.add(category_valid)

    category_no_deposit = DeviceCategory(
        id=2,
        name="No Deposit Category",
        description="Category missing deposit",
        daily_rental_rate=100.0,
        deposit_amount=0.0
    )
    db_session.add(category_no_deposit)

    category_no_rental = DeviceCategory(
        id=3,
        name="No Rental Category",
        description="Category missing rental rate",
        daily_rental_rate=0.0,
        deposit_amount=500.0
    )
    db_session.add(category_no_rental)

    warehouse_active = Warehouse(
        id=1,
        code="WH001",
        name="Active Warehouse",
        status=WarehouseStatus.ACTIVE,
        created_by_id=1
    )
    db_session.add(warehouse_active)

    warehouse_inactive = Warehouse(
        id=2,
        code="WH002",
        name="Inactive Warehouse",
        status=WarehouseStatus.INACTIVE,
        created_by_id=1
    )
    db_session.add(warehouse_inactive)

    existing_device = Device(
        id=1,
        serial_number="EXISTING001",
        name="Existing Device",
        category_id=1,
        warehouse_id=1,
        status=DeviceStatus.AVAILABLE
    )
    db_session.add(existing_device)

    db_session.commit()
    return {
        "user": user,
        "category_valid": category_valid,
        "category_no_deposit": category_no_deposit,
        "category_no_rental": category_no_rental,
        "warehouse_active": warehouse_active,
        "warehouse_inactive": warehouse_inactive,
        "existing_device": existing_device
    }

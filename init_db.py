#!/usr/bin/env python3
"""
Database initialization script for Medical Equipment Rental System
Creates seed data including default admin user, categories, and devices
"""

import sys
from datetime import datetime, timedelta, timezone

from app.database import Base, engine, SessionLocal, ensure_database_compatibility
from app.models import (
    User, UserRole,
    Device, DeviceStatus, DeviceCategory,
    Contract, ContractItem, ContractStatus,
    DisinfectionRecord,
    MaintenanceRecord,
    RepairRecord,
    Deposit, DepositStatus,
    DeviceSwap, DeviceSwapStatus,
)
from app.core import get_password_hash


def init_database():
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    ensure_database_compatibility()

    db = SessionLocal()

    try:
        print("Checking for existing data...")
        existing_admin = db.query(User).filter(User.role == UserRole.ADMIN).first()
        if existing_admin:
            print("Database already initialized. Skipping seed data.")
            return

        print("Creating default admin user...")
        admin_user = User(
            username="admin",
            email="admin@medical-rental.com",
            full_name="System Administrator",
            phone="13800138000",
            hashed_password=get_password_hash("admin123"),
            role=UserRole.ADMIN,
            is_active=True,
            address="123 Medical Street, Healthcare District",
            id_card="110101199001010001",
        )
        db.add(admin_user)

        print("Creating default staff user...")
        staff_user = User(
            username="staff",
            email="staff@medical-rental.com",
            full_name="Staff Member",
            phone="13800138001",
            hashed_password=get_password_hash("staff123"),
            role=UserRole.STAFF,
            is_active=True,
            address="456 Service Road, Medical Park",
            id_card="110101199002020002",
        )
        db.add(staff_user)

        print("Creating default customer user...")
        customer_user = User(
            username="customer",
            email="customer@example.com",
            full_name="Test Customer",
            phone="13900139000",
            hashed_password=get_password_hash("customer123"),
            role=UserRole.CUSTOMER,
            is_active=True,
            address="789 Patient Lane, Wellness City",
            id_card="110101198503030003",
        )
        db.add(customer_user)

        print("Creating device categories...")
        categories = [
            DeviceCategory(
                name="氧气机",
                description="医用氧气机，用于家庭氧疗",
                daily_rental_rate=50.0,
                deposit_amount=2000.0,
                maintenance_cycle_days=30,
                disinfection_required=True,
            ),
            DeviceCategory(
                name="轮椅",
                description="手动/电动轮椅",
                daily_rental_rate=30.0,
                deposit_amount=800.0,
                maintenance_cycle_days=90,
                disinfection_required=True,
            ),
            DeviceCategory(
                name="呼吸机",
                description="家用呼吸机，用于睡眠呼吸暂停等",
                daily_rental_rate=80.0,
                deposit_amount=5000.0,
                maintenance_cycle_days=30,
                disinfection_required=True,
            ),
            DeviceCategory(
                name="制氧机",
                description="便携式制氧机",
                daily_rental_rate=60.0,
                deposit_amount=3000.0,
                maintenance_cycle_days=60,
                disinfection_required=True,
            ),
            DeviceCategory(
                name="血压计",
                description="电子血压计",
                daily_rental_rate=10.0,
                deposit_amount=200.0,
                maintenance_cycle_days=180,
                disinfection_required=True,
            ),
        ]
        db.add_all(categories)
        db.flush()

        print("Creating sample devices...")
        devices = [
            Device(
                serial_number="DEV-OXY-001",
                name="医用氧气机 5L",
                model="OXY-5000",
                manufacturer="MedicalTech Inc.",
                purchase_date=datetime(2023, 1, 15, tzinfo=timezone.utc),
                purchase_price=8500.0,
                current_owner="公司",
                location="A仓库-1区",
                status=DeviceStatus.AVAILABLE,
                category_id=categories[0].id,
                last_disinfection_date=datetime.now(timezone.utc) - timedelta(days=5),
                last_maintenance_date=datetime.now(timezone.utc) - timedelta(days=20),
                next_maintenance_date=datetime.now(timezone.utc) + timedelta(days=10),
            ),
            Device(
                serial_number="DEV-OXY-002",
                name="医用氧气机 5L",
                model="OXY-5000",
                manufacturer="MedicalTech Inc.",
                purchase_date=datetime(2023, 2, 20, tzinfo=timezone.utc),
                purchase_price=8500.0,
                current_owner="公司",
                location="A仓库-1区",
                status=DeviceStatus.AVAILABLE,
                category_id=categories[0].id,
                last_disinfection_date=datetime.now(timezone.utc) - timedelta(days=2),
                last_maintenance_date=datetime.now(timezone.utc) - timedelta(days=15),
                next_maintenance_date=datetime.now(timezone.utc) + timedelta(days=15),
            ),
            Device(
                serial_number="DEV-WHL-001",
                name="电动轮椅",
                model="WH-2000",
                manufacturer="MobilityPlus",
                purchase_date=datetime(2023, 3, 10, tzinfo=timezone.utc),
                purchase_price=3500.0,
                current_owner="公司",
                location="B仓库-2区",
                status=DeviceStatus.AVAILABLE,
                category_id=categories[1].id,
                last_disinfection_date=datetime.now(timezone.utc) - timedelta(days=1),
                last_maintenance_date=datetime.now(timezone.utc) - timedelta(days=30),
                next_maintenance_date=datetime.now(timezone.utc) + timedelta(days=60),
            ),
            Device(
                serial_number="DEV-VEN-001",
                name="家用呼吸机",
                model="VENT-100",
                manufacturer="RespCare",
                purchase_date=datetime(2023, 1, 5, tzinfo=timezone.utc),
                purchase_price=12000.0,
                current_owner="公司",
                location="C仓库-1区",
                status=DeviceStatus.AVAILABLE,
                category_id=categories[2].id,
                last_disinfection_date=datetime.now(timezone.utc) - timedelta(days=3),
                last_maintenance_date=datetime.now(timezone.utc) - timedelta(days=10),
                next_maintenance_date=datetime.now(timezone.utc) + timedelta(days=20),
            ),
            Device(
                serial_number="DEV-OXY-003",
                name="便携式制氧机",
                model="POC-300",
                manufacturer="OxyPort",
                purchase_date=datetime(2023, 4, 1, tzinfo=timezone.utc),
                purchase_price=5000.0,
                current_owner="公司",
                location="A仓库-2区",
                status=DeviceStatus.AVAILABLE,
                category_id=categories[3].id,
                last_disinfection_date=datetime.now(timezone.utc) - timedelta(days=7),
                last_maintenance_date=datetime.now(timezone.utc) - timedelta(days=25),
                next_maintenance_date=datetime.now(timezone.utc) + timedelta(days=35),
            ),
            Device(
                serial_number="DEV-BPM-001",
                name="电子血压计",
                model="BP-500",
                manufacturer="HealthTrack",
                purchase_date=datetime(2023, 5, 15, tzinfo=timezone.utc),
                purchase_price=500.0,
                current_owner="公司",
                location="D仓库-1区",
                status=DeviceStatus.AVAILABLE,
                category_id=categories[4].id,
                last_disinfection_date=datetime.now(timezone.utc) - timedelta(days=1),
                last_maintenance_date=datetime.now(timezone.utc) - timedelta(days=60),
                next_maintenance_date=datetime.now(timezone.utc) + timedelta(days=120),
            ),
            Device(
                serial_number="DEV-OXY-004",
                name="医用氧气机 3L",
                model="OXY-3000",
                manufacturer="MedicalTech Inc.",
                purchase_date=datetime(2023, 6, 1, tzinfo=timezone.utc),
                purchase_price=6500.0,
                current_owner="张三",
                location="客户使用中",
                status=DeviceStatus.IN_USE,
                category_id=categories[0].id,
                last_disinfection_date=datetime.now(timezone.utc) - timedelta(days=30),
                last_maintenance_date=datetime.now(timezone.utc) - timedelta(days=25),
                next_maintenance_date=datetime.now(timezone.utc) + timedelta(days=5),
            ),
            Device(
                serial_number="DEV-OXY-005",
                name="医用氧气机 5L",
                model="OXY-5000",
                manufacturer="MedicalTech Inc.",
                purchase_date=datetime(2023, 7, 10, tzinfo=timezone.utc),
                purchase_price=8500.0,
                current_owner="公司",
                location="A仓库-1区",
                status=DeviceStatus.AVAILABLE,
                category_id=categories[0].id,
                last_disinfection_date=datetime.now(timezone.utc) - timedelta(days=3),
                last_maintenance_date=datetime.now(timezone.utc) - timedelta(days=10),
                next_maintenance_date=datetime.now(timezone.utc) + timedelta(days=20),
            ),
            Device(
                serial_number="DEV-OXY-006",
                name="医用氧气机 5L",
                model="OXY-5000",
                manufacturer="MedicalTech Inc.",
                purchase_date=datetime(2023, 8, 15, tzinfo=timezone.utc),
                purchase_price=8500.0,
                current_owner="公司",
                location="A仓库-1区",
                status=DeviceStatus.AVAILABLE,
                category_id=categories[0].id,
                last_disinfection_date=datetime.now(timezone.utc) - timedelta(days=1),
                last_maintenance_date=datetime.now(timezone.utc) - timedelta(days=5),
                next_maintenance_date=datetime.now(timezone.utc) + timedelta(days=25),
            ),
        ]
        db.add_all(devices)
        db.flush()

        print("Creating disinfection records...")
        disinfection_records = [
            DisinfectionRecord(
                device_id=devices[0].id,
                disinfection_date=devices[0].last_disinfection_date,
                disinfectant_type="75%医用酒精",
                disinfection_method="擦拭消毒",
                duration_minutes=30,
                operator_name="李消毒",
                temperature=25.0,
                concentration="75%",
                lot_number="LOT202401001",
                is_qualified=True,
                inspection_notes="消毒合格，无异味",
            ),
            DisinfectionRecord(
                device_id=devices[1].id,
                disinfection_date=devices[1].last_disinfection_date,
                disinfectant_type="含氯消毒剂",
                disinfection_method="浸泡消毒",
                duration_minutes=60,
                operator_name="李消毒",
                temperature=22.0,
                concentration="500mg/L",
                lot_number="LOT202401002",
                is_qualified=True,
                inspection_notes="消毒合格",
            ),
        ]
        db.add_all(disinfection_records)

        print("Creating maintenance records...")
        maintenance_records = [
            MaintenanceRecord(
                device_id=devices[0].id,
                maintenance_type="preventive",
                status="completed",
                scheduled_date=devices[0].last_maintenance_date,
                actual_date=devices[0].last_maintenance_date,
                technician_name="王维修",
                service_provider="公司内部",
                cost=100.0,
                description="定期维护保养",
                work_performed="更换过滤器、清洁气路、检测氧浓度",
                parts_replaced="进气过滤器 x1",
                next_maintenance_date=devices[0].next_maintenance_date,
                is_successful=True,
            ),
            MaintenanceRecord(
                device_id=devices[3].id,
                maintenance_type="scheduled",
                status="scheduled",
                scheduled_date=devices[3].next_maintenance_date,
                technician_name="王维修",
                service_provider="公司内部",
                cost=0.0,
                description="定期维护保养",
                work_performed=None,
                parts_replaced=None,
                next_maintenance_date=None,
                is_successful=True,
            ),
        ]
        db.add_all(maintenance_records)

        print("Creating sample contract...")
        contract_number = f"MR{datetime.now(timezone.utc).strftime('%Y%m%d')}SAMPLE"
        sample_contract = Contract(
            contract_number=contract_number,
            customer_id=customer_user.id,
            created_by_id=staff_user.id,
            start_date=datetime.now(timezone.utc) - timedelta(days=5),
            end_date=datetime.now(timezone.utc) + timedelta(days=25),
            total_amount=1500.0,
            deposit_amount=2000.0,
            overdue_fee=0.0,
            discount_amount=0.0,
            final_amount=1500.0,
            status=ContractStatus.ACTIVE,
            notes="客户需要长期租用氧气机",
        )
        db.add(sample_contract)
        db.flush()

        print("Creating sample contract items...")
        contract_item = ContractItem(
            contract_id=sample_contract.id,
            device_id=devices[6].id,
            daily_rate=50.0,
            quantity=1,
            subtotal=1500.0,
            notes="客户租赁的医用氧气机",
        )
        db.add(contract_item)
        db.flush()

        print("Creating sample deposit...")
        deposit = Deposit(
            contract_id=sample_contract.id,
            customer_id=customer_user.id,
            amount=2000.0,
            payment_date=datetime.now(timezone.utc) - timedelta(days=5),
            payment_method="银行转账",
            transaction_id="TRX202401010001",
            status="paid",
            notes="押金已全额支付",
        )
        db.add(deposit)

        print("Creating sample repair record...")
        repair = RepairRecord(
            device_id=devices[6].id,
            report_date=datetime.now(timezone.utc) - timedelta(days=2),
            reported_by_id=customer_user.id,
            priority="medium",
            status="reported",
            fault_description="机器运行时有异常噪音",
            fault_category="机械故障",
            customer_notes="使用时发现有奇怪的声音，氧浓度正常",
            is_warranty=True,
        )
        db.add(repair)

        db.commit()
        print("\n" + "=" * 60)
        print("Database initialization completed successfully!")
        print("=" * 60)
        print("\nDefault accounts created:")
        print("  - Admin:    username='admin',    password='admin123'")
        print("  - Staff:    username='staff',    password='staff123'")
        print("  - Customer: username='customer', password='customer123'")
        print("\nSample data created:")
        print(f"  - {len(categories)} device categories")
        print(f"  - {len(devices)} devices")
        print(f"  - {len(disinfection_records)} disinfection records")
        print(f"  - {len(maintenance_records)} maintenance records")
        print(f"  - 1 active contract (contract: {contract_number})")
        print(f"  - 1 contract item")
        print(f"  - 1 deposit record")
        print(f"  - 1 repair record")
        print("\nAPI Documentation:")
        print("  - Swagger UI: http://localhost:8000/docs")
        print("  - ReDoc:      http://localhost:8000/redoc")
        print("\n" + "=" * 60)

    except Exception as e:
        db.rollback()
        print(f"Error initializing database: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    init_database()

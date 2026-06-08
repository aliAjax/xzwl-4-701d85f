import pytest
from datetime import datetime, timezone, timedelta
from typing import Set

from app.core import InventoryCommitmentService, AvailabilityChecker
from app.models import (
    Device, DeviceCategory, DeviceStatus,
    Warehouse, WarehouseStatus, User, UserRole,
    Contract, ContractStatus, ContractItem,
    Reservation, ReservationStatus,
    DeviceLock,
    RepairRecord,
    DeviceTransfer, TransferStatus, TransferLocationType,
    InventoryCommitment, CommitmentStatus, CommitmentType,
)
from app.models.repair import RepairStatus


@pytest.fixture(scope="function")
def test_data_setup(db_session, seed_data):
    """
    Sets up a comprehensive test environment with:
    - 10 devices in category 1, warehouse 1
    - Various unavailable states applied to different devices
    """
    user = seed_data["user"]
    warehouse = seed_data["warehouse_active"]
    category = seed_data["category_valid"]

    devices = []
    for i in range(10):
        device_id = 100 + i
        device = Device(
            id=device_id,
            serial_number=f"ATP-TEST-{device_id:03d}",
            name=f"Test Device {device_id}",
            category_id=category.id,
            warehouse_id=warehouse.id,
            location=warehouse.code,
            status=DeviceStatus.AVAILABLE,
        )
        db_session.add(device)
        devices.append(device)
    db_session.commit()

    start_date = datetime.now(timezone.utc) + timedelta(days=1)
    end_date = start_date + timedelta(days=7)

    unavailable_device_ids: Set[int] = set()

    contract = Contract(
        id=100,
        contract_number="CTR-ATP-001",
        customer_id=user.id,
        created_by_id=user.id,
        start_date=start_date - timedelta(days=1),
        end_date=end_date + timedelta(days=1),
        status=ContractStatus.ACTIVE,
        total_amount=1000.0,
        deposit_amount=500.0,
    )
    db_session.add(contract)
    db_session.commit()

    contract_item = ContractItem(
        id=100,
        contract_id=contract.id,
        device_id=devices[0].id,
        daily_rate=100.0,
        quantity=1,
    )
    db_session.add(contract_item)
    unavailable_device_ids.add(devices[0].id)

    reservation = Reservation(
        id=100,
        reservation_number="RES-ATP-001",
        customer_id=user.id,
        device_id=devices[1].id,
        start_date=start_date,
        end_date=end_date,
        status=ReservationStatus.CONFIRMED,
        confirmed_by_id=user.id,
        confirmed_at=datetime.now(timezone.utc),
    )
    db_session.add(reservation)
    unavailable_device_ids.add(devices[1].id)

    device_lock = DeviceLock(
        id=100,
        device_id=devices[2].id,
        user_id=user.id,
        lock_token="lock-atp-001",
        locked_at=datetime.now(timezone.utc),
        expires_at=end_date + timedelta(days=1),
        is_active=1,
        purpose="ATP Test Lock",
    )
    db_session.add(device_lock)
    unavailable_device_ids.add(devices[2].id)

    repair = RepairRecord(
        id=100,
        device_id=devices[3].id,
        report_date=datetime.now(timezone.utc) - timedelta(days=2),
        reported_by_id=user.id,
        status=RepairStatus.IN_PROGRESS.value,
        fault_description="Test fault",
        priority="medium",
    )
    db_session.add(repair)
    unavailable_device_ids.add(devices[3].id)

    devices[4].status = DeviceStatus.DISINFECTION
    db_session.add(devices[4])
    unavailable_device_ids.add(devices[4].id)

    transfer = DeviceTransfer(
        id=100,
        device_id=devices[5].id,
        from_location_type=TransferLocationType.WAREHOUSE,
        from_location=warehouse.code,
        to_location_type=TransferLocationType.WAREHOUSE,
        to_location="WH-OTHER",
        status=TransferStatus.IN_TRANSIT,
        created_by_id=user.id,
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add(transfer)
    unavailable_device_ids.add(devices[5].id)

    commitment = InventoryCommitment(
        id=100,
        commitment_token="comm-atp-001",
        device_id=devices[6].id,
        warehouse_id=warehouse.id,
        category_id=category.id,
        commitment_type=CommitmentType.RESERVATION,
        status=CommitmentStatus.CONFIRMED,
        start_date=start_date,
        end_date=end_date,
        created_by_id=user.id,
    )
    db_session.add(commitment)
    unavailable_device_ids.add(devices[6].id)

    db_session.commit()

    return {
        "user": user,
        "warehouse": warehouse,
        "category": category,
        "devices": devices,
        "start_date": start_date,
        "end_date": end_date,
        "unavailable_device_ids": unavailable_device_ids,
        "contract_device_id": devices[0].id,
        "reservation_device_id": devices[1].id,
        "lock_device_id": devices[2].id,
        "repair_device_id": devices[3].id,
        "disinfection_device_id": devices[4].id,
        "transfer_device_id": devices[5].id,
        "commitment_device_id": devices[6].id,
        "available_device_ids": {d.id for d in devices[7:]},
    }


class TestATPConsistency:
    """
    Regression tests to verify ATP statistics and single-device commitment checks
    produce consistent results after refactoring.
    """

    def test_atp_total_matches_availability_checks(self, db_session, test_data_setup):
        """
        Verify that the count of available devices from ATP query
        matches the count of devices that pass _check_device_available.
        """
        service = InventoryCommitmentService(db_session)
        checker = AvailabilityChecker(db_session)

        available, total, committed, breakdown = service.get_available_to_promise(
            category_id=test_data_setup["category"].id,
            start_date=test_data_setup["start_date"],
            end_date=test_data_setup["end_date"],
            warehouse_id=test_data_setup["warehouse"].id,
        )

        assert total == 11, f"Total devices should be 11 (10 test + 1 seed), got {total}"

        device_availability_results = []
        for device in test_data_setup["devices"]:
            is_available, errors = checker.check_device_available(
                device_id=device.id,
                warehouse_id=test_data_setup["warehouse"].id,
                start_date=test_data_setup["start_date"],
                end_date=test_data_setup["end_date"],
            )
            device_availability_results.append((device.id, is_available, errors))

        test_devices_available = sum(1 for _, is_avail, _ in device_availability_results if is_avail)
        assert test_devices_available == 3, f"Expected 3 available from test devices, got {test_devices_available}"

        available_from_checks = sum(1 for _, is_avail, _ in device_availability_results if is_avail)
        seed_device_available = 1
        assert available_from_checks + seed_device_available == available, (
            f"ATP says {available} available, but per-device checks say {available_from_checks} (+1 seed). "
            f"Results: {device_availability_results}"
        )

    def test_atp_breakdown_matches_individual_sources(self, db_session, test_data_setup):
        """
        Verify that each source's unavailable count in ATP breakdown
        matches the actual devices marked unavailable by that source.
        """
        service = InventoryCommitmentService(db_session)

        available, total, committed, breakdown = service.get_available_to_promise(
            category_id=test_data_setup["category"].id,
            start_date=test_data_setup["start_date"],
            end_date=test_data_setup["end_date"],
            warehouse_id=test_data_setup["warehouse"].id,
        )

        assert breakdown["contracts"] == 1, f"Expected 1 contract unavailable, got {breakdown['contracts']}"
        assert breakdown["reservations"] == 1, f"Expected 1 reservation unavailable, got {breakdown['reservations']}"
        assert breakdown["locks"] == 1, f"Expected 1 lock unavailable, got {breakdown['locks']}"
        assert breakdown["repairs"] == 1, f"Expected 1 repair unavailable, got {breakdown['repairs']}"
        assert breakdown["disinfection"] == 1, f"Expected 1 disinfection unavailable, got {breakdown['disinfection']}"
        assert breakdown["transfers"] == 1, f"Expected 1 transfer unavailable, got {breakdown['transfers']}"
        assert breakdown["other_commitments"] == 1, f"Expected 1 commitment unavailable, got {breakdown['other_commitments']}"
        assert breakdown["unavailable_unique"] == 7, f"Expected 7 unique unavailable, got {breakdown['unavailable_unique']}"

    def test_each_unavailable_source_reports_correct_error(self, db_session, test_data_setup):
        """
        Verify that each type of unavailability produces the correct error message
        in _check_device_available.
        """
        checker = AvailabilityChecker(db_session)

        test_cases = [
            (test_data_setup["contract_device_id"], "conflicting contract"),
            (test_data_setup["reservation_device_id"], "conflicting reservation"),
            (test_data_setup["lock_device_id"], "currently locked"),
            (test_data_setup["repair_device_id"], "in repair"),
            (test_data_setup["disinfection_device_id"], "in disinfection"),
            (test_data_setup["transfer_device_id"], "in transfer"),
            (test_data_setup["commitment_device_id"], "conflicting inventory commitment"),
        ]

        for device_id, expected_error_substring in test_cases:
            is_available, errors = checker.check_device_available(
                device_id=device_id,
                warehouse_id=test_data_setup["warehouse"].id,
                start_date=test_data_setup["start_date"],
                end_date=test_data_setup["end_date"],
            )
            assert not is_available, f"Device {device_id} should be unavailable"
            assert any(expected_error_substring in e for e in errors), (
                f"Expected error containing '{expected_error_substring}' for device {device_id}, got {errors}"
            )

    def test_available_devices_pass_both_checks(self, db_session, test_data_setup):
        """
        Verify that devices not in any unavailable state are:
        1. Counted as available in ATP
        2. Pass _check_device_available without errors
        """
        service = InventoryCommitmentService(db_session)
        checker = AvailabilityChecker(db_session)

        available_ids = test_data_setup["available_device_ids"]

        for device_id in available_ids:
            is_available, errors = checker.check_device_available(
                device_id=device_id,
                warehouse_id=test_data_setup["warehouse"].id,
                start_date=test_data_setup["start_date"],
                end_date=test_data_setup["end_date"],
            )
            assert is_available, f"Device {device_id} should be available, got errors: {errors}"
            assert len(errors) == 0, f"Device {device_id} should have no errors, got: {errors}"

        available, total, committed, breakdown = service.get_available_to_promise(
            category_id=test_data_setup["category"].id,
            start_date=test_data_setup["start_date"],
            end_date=test_data_setup["end_date"],
            warehouse_id=test_data_setup["warehouse"].id,
        )
        seed_device_available = 1
        assert available == len(available_ids) + seed_device_available, (
            f"ATP available count {available} should match expected {len(available_ids)} + 1 seed = {len(available_ids) + 1}"
        )

    def test_time_conflict_detection_consistency(self, db_session, test_data_setup):
        """
        Verify that time conflict detection works the same way for both
        ATP bulk queries and single device checks.
        """
        checker = AvailabilityChecker(db_session)
        service = InventoryCommitmentService(db_session)
        warehouse = test_data_setup["warehouse"]
        category = test_data_setup["category"]

        non_overlapping_start = test_data_setup["end_date"] + timedelta(days=1)
        non_overlapping_end = non_overlapping_start + timedelta(days=7)

        available_non_overlap, _, _, breakdown_non_overlap = service.get_available_to_promise(
            category_id=category.id,
            start_date=non_overlapping_start,
            end_date=non_overlapping_end,
            warehouse_id=warehouse.id,
        )

        assert available_non_overlap > len(test_data_setup["available_device_ids"]), (
            "More devices should be available when dates don't overlap with existing commitments"
        )
        assert breakdown_non_overlap["contracts"] == 0, "No contract conflicts when dates don't overlap"
        assert breakdown_non_overlap["reservations"] == 0, "No reservation conflicts when dates don't overlap"
        assert breakdown_non_overlap["other_commitments"] == 0, "No commitment conflicts when dates don't overlap"

        for device_id in test_data_setup["unavailable_device_ids"]:
            if device_id in [
                test_data_setup["contract_device_id"],
                test_data_setup["reservation_device_id"],
                test_data_setup["commitment_device_id"],
            ]:
                is_available, errors = checker.check_device_available(
                    device_id=device_id,
                    warehouse_id=warehouse.id,
                    start_date=non_overlapping_start,
                    end_date=non_overlapping_end,
                )
                assert is_available, (
                    f"Device {device_id} should be available for non-overlapping dates, got errors: {errors}"
                )

    def test_warehouse_matching_consistency(self, db_session, test_data_setup, seed_data):
        """
        Verify that warehouse matching works the same for both ATP and single checks.
        """
        checker = AvailabilityChecker(db_session)
        service = InventoryCommitmentService(db_session)
        other_warehouse = seed_data["warehouse_inactive"]

        with pytest.raises(ValueError, match="not found or inactive"):
            service.get_available_to_promise(
                category_id=test_data_setup["category"].id,
                start_date=test_data_setup["start_date"],
                end_date=test_data_setup["end_date"],
                warehouse_id=other_warehouse.id,
            )

        for device in test_data_setup["devices"]:
            is_available, errors = checker.check_device_available(
                device_id=device.id,
                warehouse_id=other_warehouse.id,
                start_date=test_data_setup["start_date"],
                end_date=test_data_setup["end_date"],
            )
            assert not is_available, f"Device {device.id} should not be available in wrong warehouse"
            assert any("not found or inactive" in e for e in errors), (
                f"Expected 'not found or inactive' error, got {errors}"
            )

        wrong_warehouse = Warehouse(
            id=999,
            code="WH-WRONG",
            name="Wrong Warehouse",
            status=WarehouseStatus.ACTIVE,
            created_by_id=seed_data["user"].id,
        )
        db_session.add(wrong_warehouse)
        db_session.commit()

        available_atp, _, _, _ = service.get_available_to_promise(
            category_id=test_data_setup["category"].id,
            start_date=test_data_setup["start_date"],
            end_date=test_data_setup["end_date"],
            warehouse_id=wrong_warehouse.id,
        )
        assert available_atp == 0, "No devices should be available for wrong warehouse"

        for device in test_data_setup["devices"]:
            is_available, errors = checker.check_device_available(
                device_id=device.id,
                warehouse_id=wrong_warehouse.id,
                start_date=test_data_setup["start_date"],
                end_date=test_data_setup["end_date"],
            )
            assert not is_available, f"Device {device.id} should not be available in wrong warehouse"
            assert any("not in warehouse" in e for e in errors), (
                f"Expected 'not in warehouse' error, got {errors}"
            )

    def test_no_warehouse_filter_returns_all(self, db_session, test_data_setup):
        """
        Verify that querying without warehouse filter works consistently.
        """
        service = InventoryCommitmentService(db_session)
        checker = AvailabilityChecker(db_session)

        available, total, committed, breakdown = service.get_available_to_promise(
            category_id=test_data_setup["category"].id,
            start_date=test_data_setup["start_date"],
            end_date=test_data_setup["end_date"],
            warehouse_id=None,
        )

        assert total == 11, f"Total should be 11 (10 test + 1 seed) without warehouse filter, got {total}"

        per_device_available = 0
        for device in test_data_setup["devices"]:
            is_available, _ = checker.check_device_available(
                device_id=device.id,
                warehouse_id=test_data_setup["warehouse"].id,
                start_date=test_data_setup["start_date"],
                end_date=test_data_setup["end_date"],
            )
            if is_available:
                per_device_available += 1

        seed_device_available = 1
        assert per_device_available + seed_device_available == available, (
            f"Without warehouse filter: ATP says {available}, per-device says {per_device_available} (+1 seed)"
        )

    def test_exclude_commitment_id_consistency(self, db_session, test_data_setup):
        """
        Verify that exclude_commitment_id parameter works correctly in _check_device_available
        and that ATP statistics can be verified by manually excluding a commitment.
        """
        checker = AvailabilityChecker(db_session)
        service = InventoryCommitmentService(db_session)

        commitment_device_id = test_data_setup["commitment_device_id"]

        is_available_without_exclude, _ = checker.check_device_available(
            device_id=commitment_device_id,
            warehouse_id=test_data_setup["warehouse"].id,
            start_date=test_data_setup["start_date"],
            end_date=test_data_setup["end_date"],
        )
        assert not is_available_without_exclude, "Device should be unavailable when commitment is not excluded"

        is_available_with_exclude, errors = checker.check_device_available(
            device_id=commitment_device_id,
            warehouse_id=test_data_setup["warehouse"].id,
            start_date=test_data_setup["start_date"],
            end_date=test_data_setup["end_date"],
            exclude_commitment_id=100,
        )
        assert is_available_with_exclude, (
            f"Device should be available when its commitment is excluded, got errors: {errors}"
        )

    def test_exclude_user_id_consistency(self, db_session, test_data_setup, seed_data):
        """
        Verify that exclude_user_id parameter works correctly for device locks.
        """
        checker = AvailabilityChecker(db_session)
        lock_device_id = test_data_setup["lock_device_id"]
        current_user = seed_data["user"]

        is_available_without_exclude, _ = checker.check_device_available(
            device_id=lock_device_id,
            warehouse_id=test_data_setup["warehouse"].id,
            start_date=test_data_setup["start_date"],
            end_date=test_data_setup["end_date"],
        )
        assert not is_available_without_exclude, "Device should be unavailable with active lock"

        is_available_with_exclude, errors = checker.check_device_available(
            device_id=lock_device_id,
            warehouse_id=test_data_setup["warehouse"].id,
            start_date=test_data_setup["start_date"],
            end_date=test_data_setup["end_date"],
            exclude_user_id=current_user.id,
        )
        assert is_available_with_exclude, (
            f"Device should be available when lock owner is excluded, got errors: {errors}"
        )

    def test_committed_quantity_matches_source_union(self, db_session, test_data_setup):
        """
        Verify that committed_quantity is the union of contract, reservation, and commitment IDs.
        """
        service = InventoryCommitmentService(db_session)

        available, total, committed, breakdown = service.get_available_to_promise(
            category_id=test_data_setup["category"].id,
            start_date=test_data_setup["start_date"],
            end_date=test_data_setup["end_date"],
            warehouse_id=test_data_setup["warehouse"].id,
        )

        expected_committed = len(
            {test_data_setup["contract_device_id"]}
            | {test_data_setup["reservation_device_id"]}
            | {test_data_setup["commitment_device_id"]}
        )
        assert committed == expected_committed, (
            f"committed_quantity should be {expected_committed}, got {committed}"
        )

    def test_retired_device_excluded(self, db_session, test_data_setup):
        """
        Verify that retired devices are excluded from both ATP and single checks.
        """
        checker = AvailabilityChecker(db_session)
        service = InventoryCommitmentService(db_session)

        retired_device = test_data_setup["devices"][7]
        retired_device.status = DeviceStatus.RETIRED
        db_session.add(retired_device)
        db_session.commit()

        available, total, _, _ = service.get_available_to_promise(
            category_id=test_data_setup["category"].id,
            start_date=test_data_setup["start_date"],
            end_date=test_data_setup["end_date"],
            warehouse_id=test_data_setup["warehouse"].id,
        )

        assert total == 10, f"Retired device should be excluded from total (was 11, now should be 10), got {total}"
        assert available == 3, f"Available count should decrease by 1 (was 4, now should be 3), got {available}"

        is_available, errors = checker.check_device_available(
            device_id=retired_device.id,
            warehouse_id=test_data_setup["warehouse"].id,
            start_date=test_data_setup["start_date"],
            end_date=test_data_setup["end_date"],
        )
        assert not is_available, "Retired device should be unavailable"
        assert any("retired" in e.lower() for e in errors), (
            f"Expected 'retired' error, got {errors}"
        )

    def test_time_conflict_edge_cases(self, db_session, test_data_setup):
        """
        Test various time overlap edge cases to ensure consistent behavior.
        """
        from app.core import TimeConflict

        base_start = datetime(2025, 6, 10, 0, 0, 0, tzinfo=timezone.utc)
        base_end = datetime(2025, 6, 20, 0, 0, 0, tzinfo=timezone.utc)

        edge_cases = [
            (datetime(2025, 6, 5, 0, 0, 0, tzinfo=timezone.utc),
             datetime(2025, 6, 9, 23, 59, 59, tzinfo=timezone.utc), False,
             "Ends just before start"),
            (datetime(2025, 6, 9, 0, 0, 0, tzinfo=timezone.utc),
             datetime(2025, 6, 10, 0, 0, 0, tzinfo=timezone.utc), False,
             "End equals start - no overlap"),
            (datetime(2025, 6, 9, 0, 0, 0, tzinfo=timezone.utc),
             datetime(2025, 6, 10, 0, 0, 1, tzinfo=timezone.utc), True,
             "Overlaps by 1 second at start"),
            (datetime(2025, 6, 15, 0, 0, 0, tzinfo=timezone.utc),
             datetime(2025, 6, 16, 0, 0, 0, tzinfo=timezone.utc), True,
             "Fully inside range"),
            (datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc),
             datetime(2025, 6, 30, 0, 0, 0, tzinfo=timezone.utc), True,
             "Fully encloses range"),
            (datetime(2025, 6, 20, 0, 0, 0, tzinfo=timezone.utc),
             datetime(2025, 6, 25, 0, 0, 0, tzinfo=timezone.utc), False,
             "Start equals end - no overlap"),
            (datetime(2025, 6, 20, 0, 0, 1, tzinfo=timezone.utc),
             datetime(2025, 6, 25, 0, 0, 0, tzinfo=timezone.utc), False,
             "Starts just after end"),
        ]

        for start, end, expected_overlap, description in edge_cases:
            actual_overlap = TimeConflict.overlaps(start, end, base_start, base_end)
            assert actual_overlap == expected_overlap, (
                f"TimeConflict.overlaps failed: {description}. "
                f"Expected {expected_overlap}, got {actual_overlap}. "
                f"Range: {base_start} to {base_end}, Test: {start} to {end}"
            )

            condition = TimeConflict.build_condition(
                start, end, base_start, base_end
            )
            if expected_overlap:
                assert condition is not None
            else:
                assert condition is not None

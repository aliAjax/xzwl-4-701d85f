import pytest
from typing import Dict, Any, List

from app.routers.device_imports import validate_import_items
from app.models import ImportItemStatus, ValidationErrorType


def _get_error_types(item: Dict[str, Any]) -> List[str]:
    return [e.error_type.value for e in item["errors"]]


def _has_error(item: Dict[str, Any], error_type: ValidationErrorType) -> bool:
    return any(e.error_type == error_type for e in item["errors"])


class TestValidateImportItems:

    def test_valid_item_passes(self, db_session, seed_data):
        items = [{
            "serial_number": "NEW001",
            "name": "Valid Device",
            "category_id": 1,
            "purchase_date": "2024-01-15",
            "warehouse_id": 1
        }]
        result = validate_import_items(items, db_session)
        assert len(result) == 1
        assert result[0]["status"] == ImportItemStatus.VALID
        assert len(result[0]["errors"]) == 0
        assert result[0]["row_index"] == 0
        assert result[0]["category_name"] == "Valid Category"
        assert result[0]["warehouse_id"] == 1
        assert result[0]["warehouse_code"] == "WH001"
        assert result[0]["warehouse_name"] == "Active Warehouse"

    def test_serial_number_empty(self, db_session, seed_data):
        items = [{
            "serial_number": "",
            "name": "Device No Serial",
            "category_id": 1,
            "warehouse_id": 1
        }]
        result = validate_import_items(items, db_session)
        assert result[0]["status"] == ImportItemStatus.INVALID
        assert _has_error(result[0], ValidationErrorType.SERIAL_NUMBER_EMPTY)

    def test_serial_number_whitespace_only(self, db_session, seed_data):
        items = [{
            "serial_number": "   ",
            "name": "Device Whitespace Serial",
            "category_id": 1,
            "warehouse_id": 1
        }]
        result = validate_import_items(items, db_session)
        assert result[0]["status"] == ImportItemStatus.INVALID
        assert _has_error(result[0], ValidationErrorType.SERIAL_NUMBER_EMPTY)

    def test_serial_duplicate_in_batch(self, db_session, seed_data):
        items = [
            {
                "serial_number": "DUP001",
                "name": "Duplicate Device 1",
                "category_id": 1,
                "warehouse_id": 1
            },
            {
                "serial_number": "DUP001",
                "name": "Duplicate Device 2",
                "category_id": 1,
                "warehouse_id": 1
            }
        ]
        result = validate_import_items(items, db_session)
        assert len(result) == 2
        assert result[0]["status"] == ImportItemStatus.INVALID
        assert result[1]["status"] == ImportItemStatus.INVALID
        assert _has_error(result[0], ValidationErrorType.SERIAL_DUPLICATE_IN_BATCH)
        assert _has_error(result[1], ValidationErrorType.SERIAL_DUPLICATE_IN_BATCH)

    def test_serial_duplicate_in_db(self, db_session, seed_data):
        items = [{
            "serial_number": "EXISTING001",
            "name": "Existing Serial Device",
            "category_id": 1,
            "warehouse_id": 1
        }]
        result = validate_import_items(items, db_session)
        assert result[0]["status"] == ImportItemStatus.INVALID
        assert _has_error(result[0], ValidationErrorType.SERIAL_DUPLICATE_IN_DB)

    def test_serial_duplicate_in_batch_and_db(self, db_session, seed_data):
        items = [
            {
                "serial_number": "EXISTING001",
                "name": "Duplicate DB 1",
                "category_id": 1,
                "warehouse_id": 1
            },
            {
                "serial_number": "EXISTING001",
                "name": "Duplicate DB 2",
                "category_id": 1,
                "warehouse_id": 1
            }
        ]
        result = validate_import_items(items, db_session)
        error_types_0 = _get_error_types(result[0])
        error_types_1 = _get_error_types(result[1])
        assert ValidationErrorType.SERIAL_DUPLICATE_IN_BATCH.value in error_types_0
        assert ValidationErrorType.SERIAL_DUPLICATE_IN_DB.value in error_types_0
        assert ValidationErrorType.SERIAL_DUPLICATE_IN_BATCH.value in error_types_1
        assert ValidationErrorType.SERIAL_DUPLICATE_IN_DB.value in error_types_1

    def test_category_not_found(self, db_session, seed_data):
        items = [{
            "serial_number": "CAT001",
            "name": "Bad Category Device",
            "category_id": 999,
            "warehouse_id": 1
        }]
        result = validate_import_items(items, db_session)
        assert result[0]["status"] == ImportItemStatus.INVALID
        assert _has_error(result[0], ValidationErrorType.CATEGORY_NOT_FOUND)

    def test_deposit_missing(self, db_session, seed_data):
        items = [{
            "serial_number": "DEP001",
            "name": "No Deposit Device",
            "category_id": 2,
            "warehouse_id": 1
        }]
        result = validate_import_items(items, db_session)
        assert result[0]["status"] == ImportItemStatus.INVALID
        assert _has_error(result[0], ValidationErrorType.DEPOSIT_MISSING)

    def test_rental_rate_missing(self, db_session, seed_data):
        items = [{
            "serial_number": "RENT001",
            "name": "No Rental Device",
            "category_id": 3,
            "warehouse_id": 1
        }]
        result = validate_import_items(items, db_session)
        assert result[0]["status"] == ImportItemStatus.INVALID
        assert _has_error(result[0], ValidationErrorType.RENTAL_RATE_MISSING)

    def test_both_deposit_and_rental_missing(self, db_session, seed_data):
        from app.models import DeviceCategory
        bad_category = DeviceCategory(
            id=99,
            name="Bad Category Both",
            daily_rental_rate=0.0,
            deposit_amount=0.0
        )
        db_session.add(bad_category)
        db_session.commit()

        items = [{
            "serial_number": "BOTH001",
            "name": "Both Missing Device",
            "category_id": 99,
            "warehouse_id": 1
        }]
        result = validate_import_items(items, db_session)
        assert result[0]["status"] == ImportItemStatus.INVALID
        assert _has_error(result[0], ValidationErrorType.DEPOSIT_MISSING)
        assert _has_error(result[0], ValidationErrorType.RENTAL_RATE_MISSING)

    def test_warehouse_id_and_code_both_provided(self, db_session, seed_data):
        items = [{
            "serial_number": "WHBOTH001",
            "name": "Warehouse Conflict Device",
            "category_id": 1,
            "warehouse_id": 1,
            "warehouse_code": "WH001"
        }]
        result = validate_import_items(items, db_session)
        assert result[0]["status"] == ImportItemStatus.INVALID
        assert _has_error(result[0], ValidationErrorType.WAREHOUSE_ID_AND_CODE_BOTH_PROVIDED)

    def test_warehouse_not_active_by_id(self, db_session, seed_data):
        items = [{
            "serial_number": "WHINACT001",
            "name": "Inactive Warehouse Device",
            "category_id": 1,
            "warehouse_id": 2
        }]
        result = validate_import_items(items, db_session)
        assert result[0]["status"] == ImportItemStatus.INVALID
        assert _has_error(result[0], ValidationErrorType.WAREHOUSE_NOT_ACTIVE)

    def test_warehouse_not_active_by_code(self, db_session, seed_data):
        items = [{
            "serial_number": "WHINACT002",
            "name": "Inactive Warehouse Code Device",
            "category_id": 1,
            "warehouse_code": "WH002"
        }]
        result = validate_import_items(items, db_session)
        assert result[0]["status"] == ImportItemStatus.INVALID
        assert _has_error(result[0], ValidationErrorType.WAREHOUSE_NOT_ACTIVE)

    def test_warehouse_not_found_by_id(self, db_session, seed_data):
        items = [{
            "serial_number": "WHNF001",
            "name": "Warehouse Not Found Device",
            "category_id": 1,
            "warehouse_id": 999
        }]
        result = validate_import_items(items, db_session)
        assert result[0]["status"] == ImportItemStatus.INVALID
        assert _has_error(result[0], ValidationErrorType.WAREHOUSE_NOT_FOUND)

    def test_warehouse_not_found_by_code(self, db_session, seed_data):
        items = [{
            "serial_number": "WHNF002",
            "name": "Warehouse Code Not Found Device",
            "category_id": 1,
            "warehouse_code": "WH999"
        }]
        result = validate_import_items(items, db_session)
        assert result[0]["status"] == ImportItemStatus.INVALID
        assert _has_error(result[0], ValidationErrorType.WAREHOUSE_NOT_FOUND)

    def test_warehouse_resolved_by_code(self, db_session, seed_data):
        items = [{
            "serial_number": "WHCODE001",
            "name": "Warehouse By Code Device",
            "category_id": 1,
            "warehouse_code": "WH001"
        }]
        result = validate_import_items(items, db_session)
        assert result[0]["status"] == ImportItemStatus.VALID
        assert result[0]["warehouse_id"] == 1
        assert result[0]["warehouse_code"] == "WH001"
        assert result[0]["warehouse_name"] == "Active Warehouse"

    def test_purchase_date_invalid_format(self, db_session, seed_data):
        items = [{
            "serial_number": "PURCH001",
            "name": "Bad Date Device",
            "category_id": 1,
            "warehouse_id": 1,
            "purchase_date": "2024/15/40"
        }]
        result = validate_import_items(items, db_session)
        assert result[0]["status"] == ImportItemStatus.INVALID
        assert _has_error(result[0], ValidationErrorType.PURCHASE_DATE_INVALID)

    def test_purchase_date_valid_formats(self, db_session, seed_data):
        valid_dates = [
            "2024-01-15",
            "2024/01/15",
            "2024-01-15 10:30:00",
            "2024/01/15 10:30:00"
        ]
        for date_str in valid_dates:
            items = [{
                "serial_number": f"VALID{date_str.replace('/', '-').replace(':', '-')}",
                "name": "Valid Date Device",
                "category_id": 1,
                "warehouse_id": 1,
                "purchase_date": date_str
            }]
            result = validate_import_items(items, db_session)
            assert result[0]["status"] == ImportItemStatus.VALID, f"Date {date_str} should be valid"
            assert result[0]["parsed_purchase_date"] is not None

    def test_purchase_date_empty_is_valid(self, db_session, seed_data):
        items = [{
            "serial_number": "EMPTYD001",
            "name": "Empty Date Device",
            "category_id": 1,
            "warehouse_id": 1,
            "purchase_date": ""
        }]
        result = validate_import_items(items, db_session)
        assert result[0]["status"] == ImportItemStatus.VALID
        assert result[0]["parsed_purchase_date"] is None

    def test_start_index_offset(self, db_session, seed_data):
        items = [{
            "serial_number": "OFFSET001",
            "name": "Offset Device",
            "category_id": 1,
            "warehouse_id": 1
        }]
        result = validate_import_items(items, db_session, start_index=10)
        assert result[0]["row_index"] == 10

    def test_multiple_items_mixed_validity(self, db_session, seed_data):
        items = [
            {
                "serial_number": "VALID001",
                "name": "Valid Device 1",
                "category_id": 1,
                "warehouse_id": 1
            },
            {
                "serial_number": "",
                "name": "Empty Serial Device",
                "category_id": 1,
                "warehouse_id": 1
            },
            {
                "serial_number": "CATBAD001",
                "name": "Bad Category Device",
                "category_id": 999,
                "warehouse_id": 1
            }
        ]
        result = validate_import_items(items, db_session)
        assert len(result) == 3
        assert result[0]["status"] == ImportItemStatus.VALID
        assert result[1]["status"] == ImportItemStatus.INVALID
        assert _has_error(result[1], ValidationErrorType.SERIAL_NUMBER_EMPTY)
        assert result[2]["status"] == ImportItemStatus.INVALID
        assert _has_error(result[2], ValidationErrorType.CATEGORY_NOT_FOUND)

    def test_name_empty(self, db_session, seed_data):
        items = [{
            "serial_number": "NONAME001",
            "name": "",
            "category_id": 1,
            "warehouse_id": 1
        }]
        result = validate_import_items(items, db_session)
        assert result[0]["status"] == ImportItemStatus.INVALID
        assert _has_error(result[0], ValidationErrorType.NAME_EMPTY)

    def test_category_id_empty(self, db_session, seed_data):
        items = [{
            "serial_number": "NOCAT001",
            "name": "No Category Device",
            "category_id": None,
            "warehouse_id": 1
        }]
        result = validate_import_items(items, db_session)
        assert result[0]["status"] == ImportItemStatus.INVALID
        assert _has_error(result[0], ValidationErrorType.CATEGORY_ID_EMPTY)

    def test_purchase_price_negative(self, db_session, seed_data):
        items = [{
            "serial_number": "NEGPRICE001",
            "name": "Negative Price Device",
            "category_id": 1,
            "warehouse_id": 1,
            "purchase_price": -100.0
        }]
        result = validate_import_items(items, db_session)
        assert result[0]["status"] == ImportItemStatus.INVALID
        assert _has_error(result[0], ValidationErrorType.PURCHASE_PRICE_NEGATIVE)

    def test_no_warehouse_is_valid(self, db_session, seed_data):
        items = [{
            "serial_number": "NOWH001",
            "name": "No Warehouse Device",
            "category_id": 1
        }]
        result = validate_import_items(items, db_session)
        assert result[0]["status"] == ImportItemStatus.VALID
        assert result[0]["warehouse_id"] is None
        assert result[0]["warehouse_code"] is None
        assert result[0]["warehouse_name"] is None

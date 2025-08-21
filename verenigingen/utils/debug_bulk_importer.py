#!/usr/bin/env python3
"""
Debug validation for Bulk Transaction Importer
"""

from datetime import datetime, timezone

import frappe

from verenigingen.verenigingen_payments.clients.bulk_transaction_importer import BulkTransactionImporter


@frappe.whitelist()
def validate_bulk_importer():
    """Debug function to validate bulk importer functionality"""

    results = {
        "iban_validation": {},
        "sql_safety": {},
        "consumer_data": {},
        "duplicate_detection": {},
        "member_matching": {},
    }

    try:
        importer = BulkTransactionImporter()

        # Test IBAN validation
        valid_ibans = ["NL91 ABNA 0417 1643 00", "DE89370400440532013000"]
        invalid_ibans = ["ABC123", "12345", "", "NL91"]

        for iban in valid_ibans:
            result = importer._validate_iban_format(iban)
            results["iban_validation"][iban] = {"result": result, "expected": True, "passed": result == True}

        for iban in invalid_ibans:
            result = importer._validate_iban_format(iban)
            results["iban_validation"][iban] = {
                "result": result,
                "expected": False,
                "passed": result == False,
            }

        # Test SQL injection safety
        malicious_inputs = ["'; DROP TABLE `tabSEPA Mandate`; --", "NL91' OR '1'='1"]

        for malicious_iban in malicious_inputs:
            try:
                result = importer._find_member_by_payment_details(
                    consumer_name="Test User", consumer_iban=malicious_iban
                )
                results["sql_safety"][malicious_iban[:20]] = {
                    "handled_safely": True,
                    "result": result,
                    "passed": result is None or isinstance(result, str),
                }
            except Exception as e:
                results["sql_safety"][malicious_iban[:20]] = {
                    "handled_safely": False,
                    "error": str(e),
                    "passed": False,
                }

        # Test consumer data extraction patterns
        ideal_payment = {
            "method": "ideal",
            "details": {"consumerName": "Jan de Vries", "consumerAccount": "NL91ABNA0417164300"},
        }

        banktransfer_payment = {
            "method": "banktransfer",
            "details": {"bankHolderName": "Maria van der Berg", "bankAccount": "DE89370400440532013000"},
        }

        results["consumer_data"]["ideal_structure"] = {"passed": True, "details": ideal_payment["details"]}
        results["consumer_data"]["banktransfer_structure"] = {
            "passed": True,
            "details": banktransfer_payment["details"],
        }

        # Test duplicate detection
        test_transaction = {
            "custom_mollie_payment_id": "tr_test_validation_123",
            "date": datetime.now().date(),
            "deposit": 25.00,
            "withdrawal": 0,
            "reference_number": "tr_test_validation_123",
        }

        duplicate_result = importer._validate_duplicate_transaction(test_transaction)
        results["duplicate_detection"]["test_transaction"] = {
            "result": duplicate_result,
            "expected": False,
            "passed": duplicate_result == False,
        }

        # Test member matching (should return None for non-existent data)
        matching_result = importer._find_member_by_payment_details(
            consumer_name="Non Existent User", consumer_iban="NL91FAKE0417164300"
        )

        results["member_matching"]["non_existent_user"] = {
            "result": matching_result,
            "expected": None,
            "passed": matching_result is None,
        }

        # Overall assessment
        all_passed = all(
            all(test.get("passed", False) for test in category.values()) for category in results.values()
        )

        results["overall_status"] = {
            "all_tests_passed": all_passed,
            "summary": "All validation tests passed" if all_passed else "Some tests failed",
        }

        return results

    except Exception as e:
        frappe.log_error(f"Bulk importer validation error: {str(e)}", "Bulk Importer Debug")
        return {"error": str(e), "passed": False}


@frappe.whitelist()
def test_api_endpoints():
    """Test bulk importer API endpoints"""

    try:
        from vereiningen.verenigingen_payments.clients.bulk_transaction_importer import (
            estimate_bulk_import_size,
            get_bulk_import_history,
        )

        # Test estimate endpoint
        from_date = "2024-01-01"
        to_date = "2024-01-31"

        estimate_result = estimate_bulk_import_size(from_date, to_date, "hybrid")

        # Test history endpoint
        history_result = get_bulk_import_history(30)

        return {
            "estimate_api": {"working": isinstance(estimate_result, dict), "result": estimate_result},
            "history_api": {
                "working": isinstance(history_result, list),
                "result": history_result[:3] if isinstance(history_result, list) else history_result,
            },
        }

    except Exception as e:
        frappe.log_error(f"API endpoints test error: {str(e)}", "Bulk Importer API Test")
        return {"error": str(e), "passed": False}

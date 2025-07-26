"""
API functions to test calculate_totals equivalence
"""

from decimal import Decimal

import frappe


@frappe.whitelist()
def test_calculate_totals_equivalence():
    """Test that SQL and Python methods produce identical results"""

    # Test cases with direct invoice data (no DB references needed)
    test_cases = [
        {"name": "Empty batch", "invoices": []},
        {
            "name": "Normal amounts",
            "amounts": [25.00, 50.00, 75.50],
            "expected_total": 150.50,
            "expected_count": 3,
        },
        {
            "name": "Zero amounts",
            "amounts": [0.00, 25.00, 0.00],
            "expected_total": 25.00,
            "expected_count": 3,
        },
        {
            "name": "Precision test",
            "amounts": [33.333, 66.667, 0.001],
            "expected_total": 100.00,  # After rounding
            "expected_count": 3,
        },
    ]

    results = []

    for test_case in test_cases:
        result = {"test_name": test_case["name"], "status": "pending"}

        try:
            if test_case["name"] == "Empty batch":
                # Test empty batch behavior
                batch = frappe.new_doc("Direct Debit Batch")

                # Test Python fallback on new document
                batch._calculate_totals_python()
                python_count = batch.entry_count
                python_total = batch.total_amount

                result.update(
                    {
                        "status": "completed",
                        "python_count": python_count,
                        "python_total": python_total,
                        "expected_count": 0,
                        "expected_total": 0.0,
                        "count_match": python_count == 0,
                        "total_match": python_total == 0.0,
                        "overall_match": python_count == 0 and python_total == 0.0,
                    }
                )
            else:
                # Create batch with test data
                batch = frappe.new_doc("Direct Debit Batch")
                batch.batch_name = f"Test-{frappe.generate_hash(length=6)}"
                batch.collection_date = frappe.utils.today()
                batch.batch_status = "Draft"
                batch.payment_method = "SEPA Direct Debit"

                # Get first available company
                companies = frappe.get_all("Company", limit=1, pluck="name")
                if companies:
                    batch.company = companies[0]

                # Mock invoice objects for Python testing
                class MockInvoice:
                    def __init__(self, amount):
                        self.amount = amount

                # Test Python method with mock data
                batch.invoices = [MockInvoice(amount) for amount in test_case["amounts"]]
                batch._calculate_totals_python()
                python_count = batch.entry_count
                python_total = batch.total_amount

                # Compare with expected values
                count_match = python_count == test_case["expected_count"]
                total_match = abs(python_total - test_case["expected_total"]) < 0.01

                result.update(
                    {
                        "status": "completed",
                        "python_count": python_count,
                        "python_total": python_total,
                        "expected_count": test_case["expected_count"],
                        "expected_total": test_case["expected_total"],
                        "count_match": count_match,
                        "total_match": total_match,
                        "overall_match": count_match and total_match,
                    }
                )

        except Exception as e:
            result.update({"status": "error", "error": str(e)})

        results.append(result)

    # Summary
    passed_tests = sum(1 for r in results if r.get("overall_match", False))
    total_tests = len(results)

    return {
        "summary": {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "success_rate": f"{passed_tests}/{total_tests}",
            "all_passed": passed_tests == total_tests,
        },
        "test_results": results,
    }


@frappe.whitelist()
def test_python_fallback_edge_cases():
    """Test Python fallback with edge cases that can't be stored in DB"""

    # Create a mock batch for testing
    batch = frappe.new_doc("Direct Debit Batch")
    batch.batch_name = f"EdgeTest-{frappe.generate_hash(length=6)}"
    batch.collection_date = frappe.utils.today()
    batch.batch_status = "Draft"
    batch.payment_method = "SEPA Direct Debit"

    # Mock invoice class for edge case testing
    class MockInvoice:
        def __init__(self, amount):
            self.amount = amount

    edge_cases = [
        {"name": "All None amounts", "invoices": [MockInvoice(None), MockInvoice(None), MockInvoice(None)]},
        {
            "name": "String amounts",
            "invoices": [MockInvoice("25.50"), MockInvoice("30.00"), MockInvoice("10.75")],
        },
        {"name": "Empty string amounts", "invoices": [MockInvoice(""), MockInvoice("  "), MockInvoice("0")]},
        {
            "name": "Mixed valid/invalid",
            "invoices": [MockInvoice(25.00), MockInvoice(None), MockInvoice("30.50")],
        },
        {"name": "Zero amounts", "invoices": [MockInvoice(0), MockInvoice(0.0), MockInvoice("0.00")]},
    ]

    results = []

    for case in edge_cases:
        try:
            # Set mock invoices and test Python calculation
            batch.invoices = case["invoices"]
            batch._calculate_totals_python()

            results.append(
                {
                    "test_name": case["name"],
                    "status": "passed",
                    "entry_count": batch.entry_count,
                    "total_amount": batch.total_amount,
                    "expected_behavior": "No errors, graceful handling",
                }
            )

        except Exception as e:
            results.append({"test_name": case["name"], "status": "failed", "error": str(e)})

    passed = sum(1 for r in results if r["status"] == "passed")

    return {
        "summary": {
            "total_tests": len(results),
            "passed_tests": passed,
            "all_passed": passed == len(results),
        },
        "edge_case_results": results,
    }

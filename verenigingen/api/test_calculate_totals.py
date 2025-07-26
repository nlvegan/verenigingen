"""
API functions to test calculate_totals equivalence
between SQL aggregation and Python fallback methods.
"""

import time
from decimal import Decimal

import frappe
from frappe.utils import random_string, today


@frappe.whitelist()
def test_sql_vs_python_equivalence():
    """Test SQL aggregation vs Python fallback for functional equivalence"""

    test_cases = [
        {"name": "Empty batch", "invoices": []},
        {"name": "Normal amounts", "invoices": [{"amount": 25.00}, {"amount": 50.00}, {"amount": 75.50}]},
        {"name": "Null/None amounts", "invoices": [{"amount": 25.00}, {"amount": None}, {"amount": 50.00}]},
        {"name": "Zero amounts", "invoices": [{"amount": 0.00}, {"amount": 25.00}, {"amount": 0.00}]},
        {"name": "Precision test", "invoices": [{"amount": 33.333}, {"amount": 66.667}, {"amount": 0.001}]},
        {"name": "Large amounts", "invoices": [{"amount": 9999.99}, {"amount": 1.01}, {"amount": 8888.88}]},
    ]

    results = []
    overall_success = True

    for test_case in test_cases:
        test_result = {
            "test_name": test_case["name"],
            "success": False,
            "sql_count": 0,
            "python_count": 0,
            "sql_total": 0.0,
            "python_total": 0.0,
            "count_match": False,
            "total_match": False,
            "error": None,
        }

        try:
            # Create test batch
            batch = frappe.new_doc("Direct Debit Batch")
            batch.batch_date = today()
            batch.batch_description = f"Test Batch {random_string(6)}"
            batch.batch_type = "RCUR"
            batch.currency = "EUR"

            # Add test invoices
            for i, invoice_data in enumerate(test_case["invoices"]):
                batch.append(
                    "invoices",
                    {
                        "invoice": f"TEST-INV-{i+1:03d}",
                        "amount": invoice_data["amount"],
                        "currency": "EUR",
                        "member": f"TEST-MEMBER-{i+1:03d}",
                        "member_name": f"Test Member {i+1}",
                        "iban": "NL91ABNA0417164300",
                        "mandate_reference": f"TEST-MANDATE-{i+1:03d}",
                        "status": "Pending",
                    },
                )

            # Save to enable SQL testing
            batch.insert()

            # Test SQL aggregation (for saved documents)
            batch.calculate_totals()
            sql_count = batch.entry_count
            sql_total = batch.total_amount

            # Test Python fallback
            batch._calculate_totals_python()
            python_count = batch.entry_count
            python_total = batch.total_amount

            # Compare results
            count_match = sql_count == python_count
            total_match = abs(float(sql_total) - float(python_total)) < 0.01

            test_result.update(
                {
                    "success": count_match and total_match,
                    "sql_count": sql_count,
                    "python_count": python_count,
                    "sql_total": float(sql_total),
                    "python_total": float(python_total),
                    "count_match": count_match,
                    "total_match": total_match,
                }
            )

            if not (count_match and total_match):
                overall_success = False
                test_result[
                    "error"
                ] = f"Mismatch: SQL({sql_count}, {sql_total:.2f}) vs Python({python_count}, {python_total:.2f})"

        except Exception as e:
            test_result["error"] = str(e)
            overall_success = False
        finally:
            # Cleanup
            try:
                if "batch" in locals() and batch.name:
                    frappe.delete_doc("Direct Debit Batch", batch.name, force=True)
            except:
                pass

        results.append(test_result)

    return {
        "success": overall_success,
        "total_tests": len(test_cases),
        "passed_tests": sum(1 for r in results if r["success"]),
        "results": results,
    }


@frappe.whitelist()
def test_python_fallback_edge_cases():
    """Test Python fallback with edge cases that can't be stored in DB"""

    # Create a test batch (not saved)
    batch = frappe.new_doc("Direct Debit Batch")
    batch.batch_date = today()
    batch.batch_description = f"Edge Test {random_string(6)}"
    batch.batch_type = "RCUR"
    batch.currency = "EUR"

    # Manually create invoice objects with edge case data
    class MockInvoice:
        def __init__(self, amount):
            self.amount = amount

    edge_test_cases = [
        {"name": "String amounts", "invoices": [MockInvoice("25.50"), MockInvoice("30.00")]},
        {"name": "All None amounts", "invoices": [MockInvoice(None), MockInvoice(None)]},
        {"name": "Empty string amounts", "invoices": [MockInvoice(""), MockInvoice("  ")]},
        {
            "name": "Mixed types",
            "invoices": [MockInvoice(25.5), MockInvoice("30.00"), MockInvoice(None), MockInvoice("")],
        },
    ]

    results = []

    for test_case in edge_test_cases:
        try:
            batch.invoices = test_case["invoices"]
            batch._calculate_totals_python()

            results.append(
                {
                    "test_name": test_case["name"],
                    "success": True,
                    "count": batch.entry_count,
                    "total": float(batch.total_amount),
                    "error": None,
                }
            )
        except Exception as e:
            results.append(
                {"test_name": test_case["name"], "success": False, "count": 0, "total": 0.0, "error": str(e)}
            )

    return {"success": all(r["success"] for r in results), "results": results}


@frappe.whitelist()
def benchmark_calculation_performance():
    """Benchmark performance difference between SQL and Python methods"""

    test_sizes = [10, 50, 100, 500]
    results = []

    for size in test_sizes:
        try:
            # Create test batch
            batch = frappe.new_doc("Direct Debit Batch")
            batch.batch_date = today()
            batch.batch_description = f"Performance Test {random_string(6)}"
            batch.batch_type = "RCUR"
            batch.currency = "EUR"

            # Add test invoices
            for i in range(size):
                batch.append(
                    "invoices",
                    {
                        "invoice": f"PERF-TEST-{i+1:05d}",
                        "amount": 25.00 + (i % 100),
                        "currency": "EUR",
                        "member": f"PERF-MEMBER-{i+1:05d}",
                        "member_name": f"Performance Test Member {i+1}",
                        "iban": "NL91ABNA0417164300",
                        "mandate_reference": f"PERF-MANDATE-{i+1:05d}",
                        "status": "Pending",
                    },
                )

            # Test Python method (works on unsaved doc)
            start_time = time.time()
            batch._calculate_totals_python()
            python_time = time.time() - start_time
            python_result = {"count": batch.entry_count, "total": float(batch.total_amount)}

            # Save and test SQL method
            batch.insert()
            start_time = time.time()
            batch.calculate_totals()
            sql_time = time.time() - start_time
            sql_result = {"count": batch.entry_count, "total": float(batch.total_amount)}

            # Compare results
            count_match = sql_result["count"] == python_result["count"]
            total_match = abs(sql_result["total"] - python_result["total"]) < 0.01

            results.append(
                {
                    "invoice_count": size,
                    "python_time_ms": round(python_time * 1000, 2),
                    "sql_time_ms": round(sql_time * 1000, 2),
                    "python_result": python_result,
                    "sql_result": sql_result,
                    "results_match": count_match and total_match,
                    "performance_ratio": round(python_time / sql_time, 2) if sql_time > 0 else "N/A",
                }
            )

        except Exception as e:
            results.append({"invoice_count": size, "error": str(e)})
        finally:
            try:
                if "batch" in locals() and batch.name:
                    frappe.delete_doc("Direct Debit Batch", batch.name, force=True)
            except:
                pass

    return {
        "success": all(r.get("results_match", False) for r in results if "error" not in r),
        "results": results,
    }


@frappe.whitelist()
def test_null_handling_compatibility():
    """Specific test for NULL/None value handling between SQL and Python"""

    # Test various NULL combinations
    null_test_cases = [
        {"invoices": [{"amount": None}]},
        {"invoices": [{"amount": 100.0}, {"amount": None}]},
        {"invoices": [{"amount": None}, {"amount": None}, {"amount": None}]},
        {"invoices": [{"amount": 0.0}, {"amount": None}, {"amount": 50.0}]},
    ]

    results = []

    for i, test_case in enumerate(null_test_cases):
        try:
            # Create test batch
            batch = frappe.new_doc("Direct Debit Batch")
            batch.batch_date = today()
            batch.batch_description = f"NULL Test {i+1}"
            batch.batch_type = "RCUR"
            batch.currency = "EUR"

            # Add invoices
            for j, invoice_data in enumerate(test_case["invoices"]):
                batch.append(
                    "invoices",
                    {
                        "invoice": f"NULL-TEST-{i+1}-{j+1}",
                        "amount": invoice_data["amount"],
                        "currency": "EUR",
                        "member": f"NULL-MEMBER-{i+1}-{j+1}",
                        "member_name": f"Null Test Member {i+1}-{j+1}",
                        "iban": "NL91ABNA0417164300",
                        "mandate_reference": f"NULL-MANDATE-{i+1}-{j+1}",
                        "status": "Pending",
                    },
                )

            batch.insert()

            # Test SQL
            batch.calculate_totals()
            sql_result = {"count": batch.entry_count, "total": float(batch.total_amount)}

            # Test Python
            batch._calculate_totals_python()
            python_result = {"count": batch.entry_count, "total": float(batch.total_amount)}

            # Compare
            count_match = sql_result["count"] == python_result["count"]
            total_match = abs(sql_result["total"] - python_result["total"]) < 0.01

            results.append(
                {
                    "test_case": i + 1,
                    "null_count": sum(1 for inv in test_case["invoices"] if inv["amount"] is None),
                    "total_invoices": len(test_case["invoices"]),
                    "sql_result": sql_result,
                    "python_result": python_result,
                    "count_match": count_match,
                    "total_match": total_match,
                    "success": count_match and total_match,
                }
            )

        except Exception as e:
            results.append({"test_case": i + 1, "error": str(e), "success": False})
        finally:
            try:
                if "batch" in locals() and batch.name:
                    frappe.delete_doc("Direct Debit Batch", batch.name, force=True)
            except:
                pass

    return {"success": all(r["success"] for r in results), "results": results}


@frappe.whitelist()
def run_comprehensive_calculation_tests():
    """Run all calculation tests and return comprehensive results"""

    equivalence_results = test_sql_vs_python_equivalence()
    edge_case_results = test_python_fallback_edge_cases()
    null_handling_results = test_null_handling_compatibility()
    performance_results = benchmark_calculation_performance()

    return {
        "equivalence_tests": equivalence_results,
        "edge_case_tests": edge_case_results,
        "null_handling_tests": null_handling_results,
        "performance_tests": performance_results,
        "overall_success": (
            equivalence_results["success"]
            and edge_case_results["success"]
            and null_handling_results["success"]
            and performance_results["success"]
        ),
        "summary": {
            "equivalence_passed": equivalence_results["passed_tests"],
            "equivalence_total": equivalence_results["total_tests"],
            "edge_cases_passed": sum(1 for r in edge_case_results["results"] if r["success"]),
            "edge_cases_total": len(edge_case_results["results"]),
            "null_handling_passed": sum(1 for r in null_handling_results["results"] if r["success"]),
            "null_handling_total": len(null_handling_results["results"]),
            "performance_passed": sum(
                1 for r in performance_results["results"] if r.get("results_match", False)
            ),
            "performance_total": len(performance_results["results"]),
        },
    }

#!/usr/bin/env python3
"""
Validation API for Membership Dues Coverage Analysis report
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def validate_report():
    """Main validation function for the coverage report"""

    results = {"tests_run": 0, "tests_passed": 0, "errors": [], "warnings": []}

    # Test 1: Import and basic functionality
    test_name = "Import and Basic Functionality"
    results["tests_run"] += 1
    try:
        from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
            calculate_coverage_timeline,
            classify_gap_type,
            execute,
            get_columns,
            get_empty_coverage_analysis,
        )

        # Test column generation
        columns = get_columns()
        if len(columns) != 18:
            results["errors"].append(f"{test_name}: Expected 18 columns, got {len(columns)}")
        else:
            results["tests_passed"] += 1

    except Exception as e:
        results["errors"].append(f"{test_name}: {str(e)}")

    # Test 2: Gap classification
    test_name = "Gap Classification"
    results["tests_run"] += 1
    try:
        test_cases = [(1, "Minor"), (15, "Moderate"), (45, "Significant"), (120, "Critical")]
        all_correct = True

        for days, expected in test_cases:
            result = classify_gap_type(days)
            if result != expected:
                all_correct = False
                results["errors"].append(
                    f"{test_name}: Gap type for {days} days: expected {expected}, got {result}"
                )

        if all_correct:
            results["tests_passed"] += 1

    except Exception as e:
        results["errors"].append(f"{test_name}: {str(e)}")

    # Test 3: Field references validation
    test_name = "Field References Validation"
    results["tests_run"] += 1
    try:
        # Check if custom coverage fields exist in Sales Invoice
        coverage_fields = frappe.db.sql(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'tabSales Invoice'
            AND TABLE_SCHEMA = DATABASE()
            AND COLUMN_NAME IN ('custom_coverage_start_date', 'custom_coverage_end_date')
        """,
            as_dict=True,
        )

        if len(coverage_fields) == 2:
            results["tests_passed"] += 1
        else:
            results["errors"].append(f"{test_name}: Missing coverage fields in Sales Invoice")

    except Exception as e:
        results["errors"].append(f"{test_name}: {str(e)}")

    # Test 4: Report execution (with empty filters)
    test_name = "Report Execution"
    results["tests_run"] += 1
    try:
        # Try to execute with minimal filters
        columns, data = execute({"from_date": "2024-01-01", "to_date": today()})

        if isinstance(columns, list) and isinstance(data, list):
            results["tests_passed"] += 1
        else:
            results["errors"].append(f"{test_name}: Invalid return format")

    except Exception as e:
        results["warnings"].append(f"{test_name}: {str(e)} (may be expected if no test data exists)")

    return {
        "status": "success"
        if results["tests_passed"] == results["tests_run"] and not results["errors"]
        else "partial",
        "details": results,
    }


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def test_gap_classification():
    """Test gap classification function"""
    try:
        from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
            classify_gap_type,
        )

        test_cases = [
            (1, "Minor"),
            (7, "Minor"),
            (8, "Moderate"),
            (30, "Moderate"),
            (31, "Significant"),
            (90, "Significant"),
            (91, "Critical"),
            (365, "Critical"),
        ]

        results = []
        for days, expected in test_cases:
            result = classify_gap_type(days)
            results.append(
                {"days": days, "expected": expected, "actual": result, "passed": result == expected}
            )

        return {"status": "success", "results": results, "all_passed": all(r["passed"] for r in results)}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def test_report_columns():
    """Test report column generation"""
    try:
        from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
            get_columns,
        )

        columns = get_columns()

        required_fields = [
            "member",
            "member_name",
            "membership_start",
            "membership_status",
            "total_active_days",
            "covered_days",
            "gap_days",
            "coverage_percentage",
            "current_gaps",
            "unpaid_coverage",
            "outstanding_amount",
            "billing_frequency",
            "dues_rate",
            "last_invoice_date",
            "next_invoice_due",
            "catchup_required",
            "catchup_amount",
            "catchup_periods",
        ]

        column_names = [col["fieldname"] for col in columns]
        missing_fields = [field for field in required_fields if field not in column_names]

        return {
            "status": "success",
            "column_count": len(columns),
            "expected_count": 18,
            "columns": columns,
            "missing_fields": missing_fields,
            "all_present": len(missing_fields) == 0,
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def check_database_fields():
    """Check if required database fields exist"""
    try:
        # Check Sales Invoice fields
        si_fields = frappe.db.sql(
            """
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'tabSales Invoice'
            AND TABLE_SCHEMA = DATABASE()
            AND COLUMN_NAME IN ('custom_coverage_start_date', 'custom_coverage_end_date', 'custom_membership_dues_schedule')
        """,
            as_dict=True,
        )

        # Check Member table key fields
        member_fields = frappe.db.sql(
            """
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'tabMember'
            AND TABLE_SCHEMA = DATABASE()
            AND COLUMN_NAME IN ('name', 'status', 'customer', 'first_name', 'last_name')
        """,
            as_dict=True,
        )

        # Check Membership table key fields
        membership_fields = frappe.db.sql(
            """
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'tabMembership'
            AND TABLE_SCHEMA = DATABASE()
            AND COLUMN_NAME IN ('name', 'member', 'start_date', 'end_date', 'status')
        """,
            as_dict=True,
        )

        # Check Membership Dues Schedule table
        dues_fields = frappe.db.sql(
            """
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'tabMembership Dues Schedule'
            AND TABLE_SCHEMA = DATABASE()
            AND COLUMN_NAME IN ('name', 'member', 'billing_frequency', 'dues_rate', 'status')
        """,
            as_dict=True,
        )

        return {
            "status": "success",
            "sales_invoice_fields": si_fields,
            "member_fields": member_fields,
            "membership_fields": membership_fields,
            "dues_schedule_fields": dues_fields,
            "critical_fields_present": {
                "coverage_dates": len(
                    [
                        f
                        for f in si_fields
                        if f["COLUMN_NAME"] in ["custom_coverage_start_date", "custom_coverage_end_date"]
                    ]
                )
                == 2,
                "member_basics": len(member_fields) >= 4,
                "membership_basics": len(membership_fields) >= 4,
                "dues_basics": len(dues_fields) >= 4,
            },
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}

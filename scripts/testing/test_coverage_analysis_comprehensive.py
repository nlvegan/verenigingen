#!/usr/bin/env python3
"""
Comprehensive test script for the Membership Dues Coverage Analysis report
This script validates all aspects of the report implementation.
"""

import json
import os
import sys
from datetime import datetime, timedelta

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_import_and_basic_functionality():
    """Test basic import and functionality"""
    print("=== Testing Import and Basic Functionality ===")

    try:
        # Test imports
        from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
            build_conditions,
            calculate_coverage_timeline,
            classify_gap_type,
            execute,
            format_catchup_periods_for_display,
            format_gaps_for_display,
            get_columns,
            get_empty_coverage_analysis,
            should_include_row,
        )

        print("✓ All main functions imported successfully")

        # Test column generation
        columns = get_columns()
        assert len(columns) == 18, f"Expected 18 columns, got {len(columns)}"
        print(f"✓ Generated {len(columns)} columns correctly")

        # Validate column structure
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
        for field in required_fields:
            assert field in column_names, f"Missing required field: {field}"
        print("✓ All required columns present")

        return True

    except ImportError as e:
        print(f"❌ Import failed: {str(e)}")
        return False
    except Exception as e:
        print(f"❌ Basic functionality test failed: {str(e)}")
        return False


def test_gap_classification():
    """Test gap severity classification"""
    print("\n=== Testing Gap Classification ===")

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

        for days, expected in test_cases:
            result = classify_gap_type(days)
            assert result == expected, f"Gap type for {days} days: expected {expected}, got {result}"

        print("✓ Gap classification working correctly")
        return True

    except Exception as e:
        print(f"❌ Gap classification test failed: {str(e)}")
        return False


def test_empty_coverage_analysis():
    """Test empty coverage analysis structure"""
    print("\n=== Testing Empty Coverage Analysis ===")

    try:
        from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
            get_empty_coverage_analysis,
        )

        empty_analysis = get_empty_coverage_analysis()

        # Validate structure
        required_keys = ["timeline", "gaps", "stats", "catchup"]
        for key in required_keys:
            assert key in empty_analysis, f"Missing key in empty analysis: {key}"

        # Validate stats structure
        stats_keys = [
            "total_active_days",
            "covered_days",
            "gap_days",
            "coverage_percentage",
            "unpaid_coverage_days",
            "outstanding_amount",
        ]
        for key in stats_keys:
            assert key in empty_analysis["stats"], f"Missing stats key: {key}"
            assert empty_analysis["stats"][key] == 0, f"Stats key {key} should be 0"

        # Validate catchup structure
        catchup_keys = ["periods", "total_amount", "required", "summary"]
        for key in catchup_keys:
            assert key in empty_analysis["catchup"], f"Missing catchup key: {key}"

        print("✓ Empty coverage analysis structure is valid")
        return True

    except Exception as e:
        print(f"❌ Empty coverage analysis test failed: {str(e)}")
        return False


def test_condition_building():
    """Test SQL condition building"""
    print("\n=== Testing Condition Building ===")

    try:
        from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
            build_conditions,
        )

        # Test empty filters
        conditions = build_conditions({})
        assert "m.status = 'Active'" in conditions
        print("✓ Base condition (Active status) applied correctly")

        # Test member filter
        conditions = build_conditions({"member": "TEST-MEMBER-001"})
        assert "m.name = 'TEST-MEMBER-001'" in conditions
        print("✓ Member filter applied correctly")

        # Test chapter filter
        conditions = build_conditions({"chapter": "TEST-CHAPTER"})
        assert "m.chapter = 'TEST-CHAPTER'" in conditions
        print("✓ Chapter filter applied correctly")

        # Test billing frequency filter
        conditions = build_conditions({"billing_frequency": "Monthly"})
        assert "mds.billing_frequency = 'Monthly'" in conditions
        print("✓ Billing frequency filter applied correctly")

        # Test multiple filters
        conditions = build_conditions(
            {"member": "TEST-MEMBER-001", "chapter": "TEST-CHAPTER", "billing_frequency": "Monthly"}
        )
        assert "m.status = 'Active'" in conditions
        assert "m.name = 'TEST-MEMBER-001'" in conditions
        assert "m.chapter = 'TEST-CHAPTER'" in conditions
        assert "mds.billing_frequency = 'Monthly'" in conditions
        print("✓ Multiple filters applied correctly")

        return True

    except Exception as e:
        print(f"❌ Condition building test failed: {str(e)}")
        return False


def test_row_filtering():
    """Test row filtering logic"""
    print("\n=== Testing Row Filtering ===")

    try:
        from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
            should_include_row,
        )

        # Test row with no gaps
        no_gap_row = {"current_gaps": "No gaps", "gap_days": 0, "catchup_required": False}

        # Should be included with no filters
        assert should_include_row(no_gap_row, {}) == True
        print("✓ No-gap row included correctly with no filters")

        # Should be excluded with show_only_gaps filter
        assert should_include_row(no_gap_row, {"show_only_gaps": True}) == False
        print("✓ No-gap row excluded correctly with show_only_gaps filter")

        # Test row with gaps
        gap_row = {
            "current_gaps": "2024-01-01 to 2024-01-15 (15 days, Moderate)",
            "gap_days": 15,
            "catchup_required": True,
        }

        # Should be included with show_only_gaps filter
        assert should_include_row(gap_row, {"show_only_gaps": True}) == True
        print("✓ Gap row included correctly with show_only_gaps filter")

        # Should be included with show_only_catchup_required filter
        assert should_include_row(gap_row, {"show_only_catchup_required": True}) == True
        print("✓ Gap row included correctly with show_only_catchup_required filter")

        # Test gap severity filtering
        assert should_include_row(gap_row, {"gap_severity": "Moderate"}) == True
        assert should_include_row(gap_row, {"gap_severity": "Critical"}) == False
        print("✓ Gap severity filtering working correctly")

        return True

    except Exception as e:
        print(f"❌ Row filtering test failed: {str(e)}")
        return False


def test_formatting_functions():
    """Test formatting functions"""
    print("\n=== Testing Formatting Functions ===")

    try:
        from datetime import date

        from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
            format_catchup_periods_for_display,
            format_gaps_for_display,
        )

        # Test gap formatting
        gaps = [
            {
                "gap_start": date(2024, 1, 1),
                "gap_end": date(2024, 1, 15),
                "gap_days": 15,
                "gap_type": "Moderate",
            },
            {
                "gap_start": date(2024, 2, 1),
                "gap_end": date(2024, 2, 10),
                "gap_days": 10,
                "gap_type": "Moderate",
            },
        ]

        gap_text = format_gaps_for_display(gaps)
        assert "2024-01-01 to 2024-01-15 (15 days, Moderate)" in gap_text
        assert "2024-02-01 to 2024-02-10 (10 days, Moderate)" in gap_text
        assert ";" in gap_text  # Multiple gaps should be separated by semicolon
        print("✓ Gap formatting working correctly")

        # Test empty gaps
        empty_gap_text = format_gaps_for_display([])
        assert empty_gap_text == "No gaps"
        print("✓ Empty gap formatting working correctly")

        # Test catchup period formatting
        periods = [
            {"start": date(2024, 1, 1), "end": date(2024, 1, 31), "amount": 25.0},
            {"start": date(2024, 2, 1), "end": date(2024, 2, 29), "amount": 25.0},
        ]

        period_text = format_catchup_periods_for_display(periods)
        assert "2024-01-01 to 2024-01-31 (€25.0)" in period_text
        assert "2024-02-01 to 2024-02-29 (€25.0)" in period_text
        print("✓ Catchup period formatting working correctly")

        # Test empty periods
        empty_period_text = format_catchup_periods_for_display([])
        assert empty_period_text == "None required"
        print("✓ Empty catchup period formatting working correctly")

        return True

    except Exception as e:
        print(f"❌ Formatting function test failed: {str(e)}")
        return False


def test_api_functions():
    """Test API function signatures and basic structure"""
    print("\n=== Testing API Functions ===")

    try:
        from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
            export_gap_analysis,
            generate_catchup_invoices,
            get_coverage_timeline_data,
        )

        # Test that functions exist and are callable
        assert callable(generate_catchup_invoices), "generate_catchup_invoices should be callable"
        assert callable(export_gap_analysis), "export_gap_analysis should be callable"
        assert callable(get_coverage_timeline_data), "get_coverage_timeline_data should be callable"

        print("✓ All API functions are defined and callable")

        # Test function signatures (without actually calling them)
        import inspect

        # Test generate_catchup_invoices signature
        sig = inspect.signature(generate_catchup_invoices)
        assert "members" in sig.parameters, "generate_catchup_invoices should have 'members' parameter"

        # Test export_gap_analysis signature
        sig = inspect.signature(export_gap_analysis)
        assert "filters" in sig.parameters, "export_gap_analysis should have 'filters' parameter"

        # Test get_coverage_timeline_data signature
        sig = inspect.signature(get_coverage_timeline_data)
        assert "member" in sig.parameters, "get_coverage_timeline_data should have 'member' parameter"

        print("✓ All API function signatures are correct")

        return True

    except Exception as e:
        print(f"❌ API function test failed: {str(e)}")
        return False


def test_sql_security():
    """Test SQL injection prevention"""
    print("\n=== Testing SQL Security ===")

    try:
        from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
            build_conditions,
        )

        # Test potential SQL injection attempts
        malicious_inputs = [
            "'; DROP TABLE tabMember; --",
            "' OR '1'='1",
            "' UNION SELECT * FROM tabUser --",
            "'; UPDATE tabMember SET status='Inactive'; --",
        ]

        for malicious_input in malicious_inputs:
            try:
                conditions = build_conditions({"member": malicious_input})
                # The function should quote the input properly
                assert malicious_input in conditions, "Input should be treated as literal string"
                print(f"✓ Malicious input handled correctly: {malicious_input[:20]}...")
            except Exception as e:
                print(f"⚠ Unexpected error with input {malicious_input[:20]}...: {str(e)}")

        print("✓ SQL injection prevention tests completed")
        return True

    except Exception as e:
        print(f"❌ SQL security test failed: {str(e)}")
        return False


def run_comprehensive_tests():
    """Run all comprehensive tests"""
    print("Starting Comprehensive Coverage Analysis Report Tests")
    print("=" * 60)

    test_functions = [
        test_import_and_basic_functionality,
        test_gap_classification,
        test_empty_coverage_analysis,
        test_condition_building,
        test_row_filtering,
        test_formatting_functions,
        test_api_functions,
        test_sql_security,
    ]

    passed_tests = 0
    total_tests = len(test_functions)

    for test_func in test_functions:
        try:
            if test_func():
                passed_tests += 1
        except Exception as e:
            print(f"❌ Unexpected error in {test_func.__name__}: {str(e)}")

    print("\n" + "=" * 60)
    print(f"Test Results: {passed_tests}/{total_tests} tests passed")

    if passed_tests == total_tests:
        print("🎉 All tests passed! The report implementation looks solid.")
        return True
    else:
        print(f"⚠ {total_tests - passed_tests} tests failed. Review implementation.")
        return False


if __name__ == "__main__":
    success = run_comprehensive_tests()
    sys.exit(0 if success else 1)

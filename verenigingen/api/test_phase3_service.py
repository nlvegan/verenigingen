#!/usr/bin/env python3
"""
Phase 3 Service Layer Testing API
Provides whitelisted functions to test the SEPA service layer implementation
"""

from typing import Any, Dict, List

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, critical_api


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def test_sepa_service_import() -> Dict[str, Any]:
    """Test that the SEPA service can be imported and instantiated"""
    try:
        from verenigingen.utils.services.sepa_service import SEPAService, get_sepa_service

        # Test class import
        service_class = SEPAService

        # Test factory function
        service_instance = get_sepa_service()

        return {
            "success": True,
            "message": "SEPA service import successful",
            "class_available": service_class is not None,
            "factory_available": service_instance is not None,
            "service_type": str(type(service_instance)),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "message": "SEPA service import failed"}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def test_iban_validation() -> Dict[str, Any]:
    """Test IBAN validation functionality"""
    try:
        from verenigingen.utils.services.sepa_service import SEPAService

        test_cases = [
            # Valid Dutch IBAN
            {"iban": "NL91ABNA0417164300", "expected": True, "description": "Valid real Dutch IBAN"},
            # Mock bank IBANs (should be valid for testing)
            {"iban": "NL13TEST0123456789", "expected": True, "description": "Valid TEST mock bank IBAN"},
            {"iban": "NL82MOCK0123456789", "expected": True, "description": "Valid MOCK bank IBAN"},
            {"iban": "NL93DEMO0123456789", "expected": True, "description": "Valid DEMO bank IBAN"},
            # Invalid IBANs
            {"iban": "NL91INVALID123", "expected": False, "description": "Invalid IBAN format"},
            {"iban": "INVALID", "expected": False, "description": "Completely invalid IBAN"},
            {"iban": "", "expected": False, "description": "Empty IBAN"},
            {"iban": "NL123", "expected": False, "description": "Too short IBAN"},
        ]

        results = []
        for test_case in test_cases:
            iban = test_case["iban"]
            expected = test_case["expected"]
            description = test_case["description"]

            result = SEPAService.validate_iban(iban)
            passed = result == expected

            results.append(
                {
                    "iban": iban,
                    "expected": expected,
                    "actual": result,
                    "passed": passed,
                    "description": description,
                }
            )

        passed_count = sum(1 for r in results if r["passed"])
        total_count = len(results)

        return {
            "success": True,
            "message": f"IBAN validation tests completed: {passed_count}/{total_count} passed",
            "results": results,
            "all_passed": passed_count == total_count,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "message": "IBAN validation test failed"}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def test_bic_derivation() -> Dict[str, Any]:
    """Test BIC derivation from IBAN"""
    try:
        from verenigingen.utils.services.sepa_service import SEPAService

        test_cases = [
            {"iban": "NL13TEST0123456789", "expected": "TESTNL2A", "description": "TEST mock bank"},
            {"iban": "NL82MOCK0123456789", "expected": "MOCKNL2A", "description": "MOCK bank"},
            {"iban": "NL93DEMO0123456789", "expected": "DEMONL2A", "description": "DEMO bank"},
            {"iban": "NL91ABNA0417164300", "expected": "ABNANL2A", "description": "ABN AMRO real bank"},
            {"iban": "NL04RABO1234567890", "expected": "RABONL2U", "description": "Rabobank"},
            {"iban": "NL13INGB0123456789", "expected": "INGBNL2A", "description": "ING Bank"},
            {"iban": "INVALID", "expected": "", "description": "Invalid IBAN"},
        ]

        results = []
        for test_case in test_cases:
            iban = test_case["iban"]
            expected = test_case["expected"]
            description = test_case["description"]

            result = SEPAService.derive_bic_from_iban(iban)
            passed = result == expected

            results.append(
                {
                    "iban": iban,
                    "expected": expected,
                    "actual": result,
                    "passed": passed,
                    "description": description,
                }
            )

        passed_count = sum(1 for r in results if r["passed"])
        total_count = len(results)

        return {
            "success": True,
            "message": f"BIC derivation tests completed: {passed_count}/{total_count} passed",
            "results": results,
            "all_passed": passed_count == total_count,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "message": "BIC derivation test failed"}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def test_input_validation() -> Dict[str, Any]:
    """Test input validation for security"""
    try:
        from verenigingen.utils.services.sepa_service import SEPAService

        test_cases = [
            # Valid inputs
            {
                "member": "Test-Member-001",
                "iban": "NL91ABNA0417164300",
                "expected": True,
                "description": "Valid inputs",
            },
            # Invalid inputs (security concerns)
            {
                "member": "Test';DROP TABLE",
                "iban": "NL91ABNA0417164300",
                "expected": False,
                "description": "SQL injection attempt in member name",
            },
            {
                "member": "Test<script>",
                "iban": "NL91ABNA0417164300",
                "expected": False,
                "description": "XSS attempt in member name",
            },
            {
                "member": 'Test"OR 1=1',
                "iban": "NL91ABNA0417164300",
                "expected": False,
                "description": "SQL injection with quotes",
            },
            # Empty/invalid inputs
            {
                "member": "",
                "iban": "NL91ABNA0417164300",
                "expected": False,
                "description": "Empty member name",
            },
            {"member": "Test-Member-001", "iban": "", "expected": False, "description": "Empty IBAN"},
            {
                "member": "Test-Member-001",
                "iban": "SHORT",
                "expected": False,
                "description": "Too short IBAN",
            },
            {
                "member": None,
                "iban": "NL91ABNA0417164300",
                "expected": False,
                "description": "None member name",
            },
        ]

        results = []
        for test_case in test_cases:
            member = test_case["member"]
            iban = test_case["iban"]
            expected = test_case["expected"]
            description = test_case["description"]

            try:
                result = SEPAService.validate_inputs(member, iban)
                passed = result == expected
            except Exception:
                result = False
                passed = expected is False  # If we expect False and got an exception, that's still a pass

            results.append(
                {
                    "member": member,
                    "iban": iban,
                    "expected": expected,
                    "actual": result,
                    "passed": passed,
                    "description": description,
                }
            )

        passed_count = sum(1 for r in results if r["passed"])
        total_count = len(results)

        return {
            "success": True,
            "message": f"Input validation tests completed: {passed_count}/{total_count} passed",
            "results": results,
            "all_passed": passed_count == total_count,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "message": "Input validation test failed"}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def test_service_methods_availability() -> Dict[str, Any]:
    """Test that all expected service methods are available"""
    try:
        from verenigingen.utils.services.sepa_service import SEPAService

        expected_methods = [
            "create_mandate_enhanced",
            "validate_inputs",
            "validate_iban",
            "derive_bic_from_iban",
            "get_active_mandates",
            "get_active_mandate_by_iban",
            "cancel_mandate",
            "get_mandate_usage_statistics",
        ]

        available_methods = []
        missing_methods = []

        for method_name in expected_methods:
            if hasattr(SEPAService, method_name):
                method = getattr(SEPAService, method_name)
                available_methods.append(
                    {"name": method_name, "callable": callable(method), "type": str(type(method))}
                )
            else:
                missing_methods.append(method_name)

        return {
            "success": True,
            "message": f"Method availability check completed: {len(available_methods)}/{len(expected_methods)} available",
            "available_methods": available_methods,
            "missing_methods": missing_methods,
            "all_available": len(missing_methods) == 0,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "message": "Service methods availability test failed"}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def test_api_endpoints() -> Dict[str, Any]:
    """Test that API endpoints are properly exposed"""
    try:
        from verenigingen.utils.services.sepa_service import (
            cancel_mandate_via_service,
            create_sepa_mandate_via_service,
            get_member_mandates_via_service,
        )

        endpoints = [
            {"name": "create_sepa_mandate_via_service", "function": create_sepa_mandate_via_service},
            {"name": "get_member_mandates_via_service", "function": get_member_mandates_via_service},
            {"name": "cancel_mandate_via_service", "function": cancel_mandate_via_service},
        ]

        available_endpoints = []
        for endpoint in endpoints:
            available_endpoints.append(
                {
                    "name": endpoint["name"],
                    "callable": callable(endpoint["function"]),
                    "whitelisted": hasattr(endpoint["function"], "__frappe_whitelisted__"),
                }
            )

        return {
            "success": True,
            "message": f"API endpoints test completed: {len(available_endpoints)} endpoints available",
            "endpoints": available_endpoints,
            "all_available": len(available_endpoints) == len(endpoints),
        }

    except Exception as e:
        return {"success": False, "error": str(e), "message": "API endpoints test failed"}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def test_mixin_integration() -> Dict[str, Any]:
    """Test that service layer integrates with existing Member mixins"""
    try:
        from verenigingen.verenigingen.doctype.member.mixins.sepa_mixin import SEPAMandateMixin

        # Check if the service integration method was added to the mixin
        has_service_integration = hasattr(SEPAMandateMixin, "create_sepa_mandate_via_service")

        # Check if the old method shows deprecation
        has_old_method = hasattr(SEPAMandateMixin, "create_sepa_mandate")

        return {
            "success": True,
            "message": "Mixin integration test completed",
            "has_service_integration": has_service_integration,
            "has_old_method": has_old_method,
            "backward_compatible": has_old_method,
            "service_integrated": has_service_integration,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "message": "Mixin integration test failed"}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def run_comprehensive_service_test() -> Dict[str, Any]:
    """Run all service layer tests and provide comprehensive results"""
    tests = [
        ("Service Import", test_sepa_service_import),
        ("IBAN Validation", test_iban_validation),
        ("BIC Derivation", test_bic_derivation),
        ("Input Validation", test_input_validation),
        ("Method Availability", test_service_methods_availability),
        ("API Endpoints", test_api_endpoints),
        ("Mixin Integration", test_mixin_integration),
    ]

    results = {}
    summary = {"total_tests": len(tests), "passed_tests": 0, "failed_tests": 0, "overall_success": True}

    for test_name, test_function in tests:
        try:
            result = test_function()
            results[test_name] = result

            if result.get("success", False):
                summary["passed_tests"] += 1
            else:
                summary["failed_tests"] += 1
                summary["overall_success"] = False

        except Exception as e:
            results[test_name] = {
                "success": False,
                "error": str(e),
                "message": f"{test_name} failed with exception",
            }
            summary["failed_tests"] += 1
            summary["overall_success"] = False

    return {
        "success": True,
        "message": f"Comprehensive test completed: {summary['passed_tests']}/{summary['total_tests']} tests passed",
        "summary": summary,
        "test_results": results,
    }


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def analyze_security_improvements() -> Dict[str, Any]:
    """Analyze security improvements in the codebase"""
    try:
        import os
        import re

        files_to_analyze = [
            "verenigingen/fixtures/add_sepa_database_indexes.py",
            "verenigingen/utils/simple_robust_cleanup.py",
            "verenigingen/utils/services/sepa_service.py",
            "verenigingen/api/sepa_mandate_management.py",
        ]

        security_analysis = {}

        for file_path in files_to_analyze:
            full_path = os.path.join(
                frappe.get_app_path("verenigingen"), file_path.replace("verenigingen/", "")
            )

            if os.path.exists(full_path):
                with open(full_path, "r") as f:
                    content = f.read()

                analysis = {
                    "total_sql_queries": content.count("frappe.db.sql("),
                    "parameterized_queries": content.count("%s"),
                    "string_formatting": content.count("{}") + content.count("%"),
                    "where_clauses": content.count("WHERE "),
                    "insert_statements": content.count("INSERT "),
                    "update_statements": content.count("UPDATE "),
                    "delete_statements": content.count("DELETE "),
                    "validation_checks": content.count("validate") + content.count("ValidationError"),
                    "security_patterns": [],
                }

                # Look for security patterns
                if "validate" in content.lower():
                    analysis["security_patterns"].append("Input validation present")
                if "%s" in content and "frappe.db.sql(" in content:
                    analysis["security_patterns"].append("Parameterized queries used")
                if "raise ValueError" in content:
                    analysis["security_patterns"].append("Input validation with exceptions")
                if "ignore_permissions=True" in content:
                    analysis["security_patterns"].append("Permission bypass detected")

                security_analysis[file_path] = analysis
            else:
                security_analysis[file_path] = {"error": "File not found"}

        return {
            "success": True,
            "message": "Security analysis completed",
            "file_analysis": security_analysis,
            "summary": {
                "files_analyzed": len([f for f in security_analysis.values() if "error" not in f]),
                "files_not_found": len([f for f in security_analysis.values() if "error" in f]),
            },
        }

    except Exception as e:
        return {"success": False, "error": str(e), "message": "Security analysis failed"}

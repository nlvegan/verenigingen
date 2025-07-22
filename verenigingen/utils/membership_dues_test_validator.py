"""
Validation utility for the membership dues system tests
"""

import frappe


@frappe.whitelist()
def validate_membership_dues_test_environment():
    """Validate that the test environment is ready for membership dues system tests"""

    results = []
    all_valid = True

    # Check DocTypes
    required_doctypes = [
        "Membership Dues Schedule",
        "Payment Plan",
        "Payment Plan Installment",
        "Membership Tier",
    ]

    results.append("Checking DocTypes:")
    for doctype in required_doctypes:
        if frappe.db.exists("DocType", doctype):
            results.append(f"  ✅ {doctype}")
        else:
            results.append(f"  ❌ {doctype} - MISSING")
            all_valid = False

    # Check test infrastructure
    results.append("\nChecking test infrastructure:")
    try:
        from verenigingen.tests.utils.base import VereningingenTestCase

        results.append("  ✅ VereningingenTestCase available")
    except ImportError as e:
        results.append(f"  ❌ VereningingenTestCase not available: {e}")
        all_valid = False

    # Check API endpoints
    results.append("\nChecking API endpoints:")
    api_endpoints = [
        ("verenigingen.api.enhanced_membership_application", "get_membership_types_for_application"),
        ("verenigingen.api.payment_plan_management", "request_payment_plan"),
        (
            "verenigingen.verenigingen.doctype.direct_debit_batch.enhanced_sepa_processor",
            "EnhancedSEPAProcessor",
        ),
    ]

    for module_name, function_name in api_endpoints:
        try:
            module = frappe.get_module(module_name)
            if hasattr(module, function_name):
                results.append(f"  ✅ {module_name}.{function_name}")
            else:
                results.append(f"  ❌ {module_name}.{function_name} - NOT FOUND")
                all_valid = False
        except Exception as e:
            results.append(f"  ❌ {module_name}.{function_name} - ERROR: {e}")
            all_valid = False

    # Check test files exist
    results.append("\nChecking test files:")
    test_files = [
        "verenigingen/tests/backend/components/test_membership_dues_system.py",
        "verenigingen/tests/backend/components/test_payment_plan_system.py",
        "verenigingen/tests/backend/components/test_enhanced_sepa_processing.py",
        "verenigingen/tests/workflows/test_enhanced_membership_lifecycle.py",
    ]

    import os

    base_path = "/home/frappe/frappe-bench/apps/verenigingen"

    for test_file in test_files:
        file_path = os.path.join(base_path, test_file)
        if os.path.exists(file_path):
            results.append(f"  ✅ {test_file}")
        else:
            results.append(f"  ❌ {test_file} - NOT FOUND")
            all_valid = False

    # Check scheduler integration
    results.append("\nChecking scheduler integration:")
    try:
        from verenigingen import hooks

        scheduler_tasks = hooks.scheduler_events.get("daily", [])

        expected_tasks = [
            "verenigingen.verenigingen.doctype.direct_debit_batch.enhanced_sepa_processor.create_monthly_dues_collection_batch",
            "verenigingen.verenigingen.doctype.payment_plan.payment_plan.process_overdue_installments",
        ]

        for task in expected_tasks:
            if task in scheduler_tasks:
                results.append(f"  ✅ {task}")
            else:
                results.append(f"  ❌ {task} - NOT IN SCHEDULER")
                all_valid = False

    except Exception as e:
        results.append(f"  ❌ Scheduler check failed: {e}")
        all_valid = False

    # Summary
    results.append("\n" + "=" * 60)
    results.append("Membership Dues System Test Environment Validation")
    results.append("=" * 60)

    if all_valid:
        results.append("✅ ALL CHECKS PASSED - Ready for testing!")
        results.append("You can now run the membership dues system tests:")
        results.append("  - Core functionality tests")
        results.append("  - Payment plan management tests")
        results.append("  - Enhanced SEPA processing tests")
        results.append("  - Complete lifecycle workflow tests")
    else:
        results.append("❌ SOME CHECKS FAILED - Environment needs attention")
        results.append("Please resolve the issues above before running tests")

    # Print results
    for result in results:
        print(result)

    return {"success": all_valid, "results": results}


@frappe.whitelist()
def run_quick_membership_dues_tests():
    """Run a quick subset of membership dues system tests"""

    results = []

    try:
        # Test 1: Create membership type with tiers
        results.append("Testing membership type with tiers...")
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = f"Quick Test Tier Type {frappe.generate_hash(length=6)}"
        membership_type.minimum_amount = 25.0
        membership_type.billing_period = "Monthly"
        membership_type.is_active = 1

        membership_type.save()

        # Create dues schedule template with tier configuration
        template = frappe.new_doc("Membership Dues Schedule")
        template.is_template = 1
        template.schedule_name = f"Template-{membership_type.name}"
        template.membership_type = membership_type.name
        template.status = "Active"
        template.billing_frequency = "Monthly"
        template.contribution_mode = "Tier"
        template.minimum_amount = 10.0
        template.suggested_amount = 25.0
        template.invoice_days_before = 30
        template.auto_generate = 1
        template.dues_rate = template.suggested_amount
        template.insert()

        # Link template to membership type
        membership_type.dues_schedule_template = template.name
        membership_type.save()
        results.append("  ✅ Membership type with tiers created successfully")

        # Test tier contribution options
        options = membership_type.get_contribution_options()
        if options["mode"] == "Tiers" and len(options.get("tiers", [])) > 0:
            results.append("  ✅ Tier contribution options working")
        else:
            results.append("  ❌ Tier contribution options failed")

        # Clean up
        membership_type.delete()

    except Exception as e:
        results.append(f"  ❌ Membership type test failed: {e}")

    try:
        # Test 2: Create payment plan
        results.append("\nTesting payment plan creation...")

        # Need a test member
        test_member = frappe.db.get_value("Member", {}, "name")
        if not test_member:
            results.append("  ⚠️  No test member found, skipping payment plan test")
        else:
            payment_plan = frappe.new_doc("Payment Plan")
            payment_plan.member = test_member
            payment_plan.plan_type = "Equal Installments"
            payment_plan.total_amount = 90.0
            payment_plan.number_of_installments = 3
            payment_plan.frequency = "Monthly"
            payment_plan.start_date = frappe.utils.today()
            payment_plan.status = "Draft"

            payment_plan.save()
            results.append("  ✅ Payment plan created successfully")

            # Test installment generation
            if len(payment_plan.installments) == 3:
                results.append("  ✅ Installment generation working")
            else:
                results.append(f"  ❌ Expected 3 installments, got {len(payment_plan.installments)}")

            # Clean up
            payment_plan.delete()

    except Exception as e:
        results.append(f"  ❌ Payment plan test failed: {e}")

    try:
        # Test 3: Enhanced SEPA processor
        results.append("\nTesting enhanced SEPA processor...")
        from verenigingen.verenigingen.doctype.direct_debit_batch.enhanced_sepa_processor import (
            EnhancedSEPAProcessor,
        )

        processor = EnhancedSEPAProcessor()
        results.append("  ✅ Enhanced SEPA processor initialized")

        # Test eligibility check
        eligible = processor.get_eligible_dues_schedules(frappe.utils.today())
        results.append(f"  ✅ Found {len(eligible)} eligible dues schedules")

    except Exception as e:
        results.append(f"  ❌ Enhanced SEPA processor test failed: {e}")

    try:
        # Test 4: API endpoints
        results.append("\nTesting API endpoints...")
        from verenigingen.api.enhanced_membership_application import get_membership_types_for_application

        types = get_membership_types_for_application()
        results.append(f"  ✅ Membership types API returned {len(types)} types")

        from verenigingen.api.payment_plan_management import calculate_payment_plan_preview

        preview = calculate_payment_plan_preview(120.0, 4, "Monthly")
        if preview.get("success"):
            results.append("  ✅ Payment plan preview API working")
        else:
            results.append(f"  ❌ Payment plan preview API failed: {preview.get('error')}")

    except Exception as e:
        results.append(f"  ❌ API endpoints test failed: {e}")

    # Summary
    results.append("\n" + "=" * 60)
    results.append("Quick Membership Dues System Tests Summary")
    results.append("=" * 60)

    passed = sum(1 for r in results if "✅" in r)
    failed = sum(1 for r in results if "❌" in r)
    warnings = sum(1 for r in results if "⚠️" in r)

    results.append(f"Tests completed: {passed} passed, {failed} failed, {warnings} warnings")

    if failed == 0:
        results.append("🎉 Quick tests passed! Membership dues system is working correctly.")
    else:
        results.append("⚠️  Some tests failed. Please check the errors above.")

    # Print results
    for result in results:
        print(result)

    return {
        "success": failed == 0,
        "passed": passed,
        "failed": failed,
        "warnings": warnings,
        "results": results,
    }

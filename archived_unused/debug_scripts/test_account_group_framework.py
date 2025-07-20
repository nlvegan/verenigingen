"""
Test Account Group Framework
Quick test to verify the framework is working correctly.
"""

import frappe

from verenigingen.utils.account_group_project_framework import account_group_framework
from verenigingen.utils.setup_account_group_mappings import (
    create_sample_projects,
    run_full_setup,
    setup_default_mappings,
)


@frappe.whitelist()
def test_framework_basic():
    """Test basic framework functionality"""

    results = {}

    # Test 1: Check if framework can identify account groups
    expense_groups = frappe.get_all(
        "Account", filters={"is_group": 1, "root_type": "Expense"}, fields=["name", "account_name"]
    )

    results["expense_groups_found"] = len(expense_groups)
    results["expense_groups"] = expense_groups[:5]  # Show first 5

    # Test 2: Check existing mappings
    existing_mappings = frappe.get_all(
        "Account Group Project Mapping", fields=["account_group", "account_group_type", "tracking_mode"]
    )

    results["existing_mappings"] = len(existing_mappings)
    results["sample_mappings"] = existing_mappings[:3]  # Show first 3

    # Test 3: Test framework functions
    if expense_groups:
        test_group = expense_groups[0].name

        # Test get_mapping
        mapping = account_group_framework.get_mapping(test_group)
        results["test_mapping"] = mapping

        # Test get_defaults
        defaults = account_group_framework.get_defaults_for_transaction(test_group)
        results["test_defaults"] = defaults

        # Test validation
        validation = account_group_framework.validate_transaction(test_group)
        results["test_validation"] = validation

    return results


@frappe.whitelist()
def test_setup_functions():
    """Test setup functions"""

    results = {}

    # Test setup status
    from verenigingen.utils.setup_account_group_mappings import get_setup_status

    results["setup_status"] = get_setup_status()

    # Test framework overview
    from verenigingen.utils.setup_account_group_mappings import get_framework_overview

    results["framework_overview"] = get_framework_overview()

    return results


@frappe.whitelist()
def run_quick_setup():
    """Run quick setup for testing"""

    results = {}

    try:
        # Create default mappings
        setup_result = setup_default_mappings()
        results["setup_mappings"] = setup_result

        # Create sample projects
        projects_result = create_sample_projects()
        results["sample_projects"] = projects_result

        # Get final status
        from verenigingen.utils.setup_account_group_mappings import get_framework_overview

        results["final_overview"] = get_framework_overview()

    except Exception as e:
        results["error"] = str(e)
        frappe.log_error(f"Error in quick setup: {e}")

    return results


@frappe.whitelist()
def test_validation_hooks():
    """Test validation hooks with sample data"""

    results = {}

    try:
        # Test account group lookup
        from verenigingen.utils.account_group_validation_hooks import get_account_group_for_account

        # Find a sample expense account
        expense_account = frappe.db.get_value("Account", {"root_type": "Expense", "is_group": 0}, "name")

        if expense_account:
            account_group = get_account_group_for_account(expense_account)
            results["test_account"] = expense_account
            results["account_group"] = account_group

            if account_group:
                # Test get defaults
                from verenigingen.utils.account_group_validation_hooks import get_account_defaults_for_form

                defaults = get_account_defaults_for_form(expense_account)
                results["account_defaults"] = defaults

                # Test validation
                from verenigingen.utils.account_group_validation_hooks import validate_form_selection

                validation = validate_form_selection(expense_account)
                results["validation"] = validation

    except Exception as e:
        results["error"] = str(e)
        frappe.log_error(f"Error in validation hooks test: {e}")

    return results


@frappe.whitelist()
def run_comprehensive_test():
    """Run comprehensive test of all components"""

    results = {}

    # Test 1: Basic framework
    results["basic_test"] = test_framework_basic()

    # Test 2: Setup functions
    results["setup_test"] = test_setup_functions()

    # Test 3: Validation hooks
    results["validation_test"] = test_validation_hooks()

    # Test 4: Database state
    results["database_state"] = {
        "account_groups": frappe.db.count("Account", {"is_group": 1, "root_type": "Expense"}),
        "mappings": frappe.db.count("Account Group Project Mapping"),
        "projects": frappe.db.count("Project"),
        "cost_centers": frappe.db.count("Cost Center", {"disabled": 0}),
    }

    return results

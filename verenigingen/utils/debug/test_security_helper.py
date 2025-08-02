#!/usr/bin/env python3
"""
One-off test script for security helper functionality

Created: 2025-08-02
Purpose: Test the new security helper to ensure it works correctly
Related Issue: Replacing ignore_permissions=True with proper security
TODO: Remove after security helper implementation is verified
"""

import frappe


@frappe.whitelist()
def test_security_helper():
    """Test the security helper functions"""

    from verenigingen.e_boekhouden.utils.security_helper import (
        cleanup_context,
        has_migration_permission,
        migration_context,
        validate_and_insert,
    )

    results = {"tests_passed": 0, "tests_failed": 0, "details": []}

    # Test 1: Check permission verification
    try:
        has_perm = has_migration_permission("account_creation")
        results["details"].append(f"Permission check for account_creation: {has_perm}")
        results["tests_passed"] += 1
    except Exception as e:
        results["details"].append(f"Permission check failed: {str(e)}")
        results["tests_failed"] += 1

    # Test 2: Test migration context
    try:
        with migration_context("party_creation"):
            # Create a test customer
            customer = frappe.new_doc("Customer")
            customer.customer_name = "Test Migration Customer"
            customer.customer_type = "Individual"
            customer.customer_group = (
                frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "All Customer Groups"
            )
            customer.territory = (
                frappe.db.get_value("Territory", {"is_group": 0}, "name") or "All Territories"
            )

            validate_and_insert(customer)
            results["details"].append(f"Created customer: {customer.name}")
            results["tests_passed"] += 1

            # Clean up
            customer.delete()

    except Exception as e:
        results["details"].append(f"Migration context test failed: {str(e)}")
        results["tests_failed"] += 1

    # Test 3: Test cleanup context
    try:
        with cleanup_context():
            results["details"].append("Cleanup context established successfully")
            results["tests_passed"] += 1
    except Exception as e:
        results["details"].append(f"Cleanup context failed: {str(e)}")
        results["tests_failed"] += 1

    # Test 4: Test actual account creation
    try:
        from verenigingen.e_boekhouden.utils.security_helper import migration_operation

        @migration_operation("account_creation")
        def create_test_account():
            company = frappe.get_single(
                "E-Boekhouden Settings"
            ).default_company or frappe.defaults.get_user_default("company")

            account = frappe.new_doc("Account")
            account.account_name = "Test Security Helper Account"
            account.parent_account = frappe.db.get_value(
                "Account", {"company": company, "root_type": "Asset", "is_group": 1}, "name"
            )
            account.company = company
            account.is_group = 0
            account.account_type = "Bank"

            account.insert()
            return account

        test_account = create_test_account()
        results["details"].append(f"Created account with decorator: {test_account.name}")
        results["tests_passed"] += 1

        # Clean up
        test_account.delete()

    except Exception as e:
        results["details"].append(f"Account creation test failed: {str(e)}")
        results["tests_failed"] += 1

    results["summary"] = f"Passed: {results['tests_passed']}, Failed: {results['tests_failed']}"

    return results

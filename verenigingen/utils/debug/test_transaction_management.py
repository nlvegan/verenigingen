#!/usr/bin/env python3
"""
Test transaction management functionality in security helper
"""

import frappe


@frappe.whitelist()
def test_transaction_management():
    """Test the transaction management features"""

    from verenigingen.e_boekhouden.utils.security_helper import (
        atomic_migration_operation,
        migration_transaction,
    )

    results = {"tests_passed": 0, "tests_failed": 0, "details": []}

    # Test 1: Test migration_transaction with successful operations
    try:
        with migration_transaction("account_creation", batch_size=2) as tx:
            # Create multiple test accounts
            company = frappe.get_single(
                "E-Boekhouden Settings"
            ).default_company or frappe.defaults.get_user_default("company")
            parent_account = frappe.db.get_value(
                "Account", {"company": company, "root_type": "Asset", "is_group": 1}, "name"
            )

            for i in range(3):
                account = frappe.new_doc("Account")
                account.account_name = f"Test Transaction Account {i+1}"
                account.parent_account = parent_account
                account.company = company
                account.is_group = 0
                account.account_type = "Bank"

                account.insert()
                tx.track_operation("account_created", account.name, {"test_batch": True})

                # Clean up immediately
                account.delete()

            stats = tx.get_stats()
            results["details"].append(
                f"Transaction test: {stats['total_operations']} operations in {stats['duration']:.2f}s"
            )
            results["tests_passed"] += 1

    except Exception as e:
        results["details"].append(f"Migration transaction test failed: {str(e)}")
        results["tests_failed"] += 1

    # Test 2: Test atomic_migration_operation with success
    try:
        with atomic_migration_operation("party_creation"):
            customer = frappe.new_doc("Customer")
            customer.customer_name = "Test Atomic Customer"
            customer.customer_type = "Individual"
            customer.customer_group = (
                frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "All Customer Groups"
            )
            customer.territory = (
                frappe.db.get_value("Territory", {"is_group": 0}, "name") or "All Territories"
            )

            customer.insert()
            results["details"].append(f"Atomic operation succeeded: {customer.name}")

            # Clean up
            customer.delete()

        results["tests_passed"] += 1

    except Exception as e:
        results["details"].append(f"Atomic operation test failed: {str(e)}")
        results["tests_failed"] += 1

    # Test 3: Test atomic_migration_operation with rollback
    try:
        customer_name = None
        try:
            with atomic_migration_operation("party_creation"):
                customer = frappe.new_doc("Customer")
                customer.customer_name = "Test Rollback Customer"
                customer.customer_type = "Individual"
                customer.customer_group = (
                    frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "All Customer Groups"
                )
                customer.territory = (
                    frappe.db.get_value("Territory", {"is_group": 0}, "name") or "All Territories"
                )

                customer.insert()
                customer_name = customer.name

                # Force an error to test rollback
                raise ValueError("Forced error for rollback test")

        except ValueError as expected_error:
            # Check if customer was rolled back
            if customer_name and not frappe.db.exists("Customer", customer_name):
                results["details"].append("Rollback test succeeded: Customer was properly rolled back")
                results["tests_passed"] += 1
            else:
                results["details"].append("Rollback test failed: Customer still exists after rollback")
                results["tests_failed"] += 1

                # Clean up if rollback didn't work
                if customer_name and frappe.db.exists("Customer", customer_name):
                    frappe.delete_doc("Customer", customer_name)

    except Exception as e:
        results["details"].append(f"Rollback test failed with unexpected error: {str(e)}")
        results["tests_failed"] += 1

    # Test 4: Test payment handler atomic processing
    try:
        # Test with a mock mutation that would normally work
        mock_mutation = {
            "id": "test-atomic-999",
            "type": 3,  # Customer payment
            "amount": 100.0,
            "relationId": None,  # This will cause party lookup to fail
            "ledgerId": 12345,
            "invoiceNumber": "",
            "description": "Test atomic payment",
            "date": "2025-08-02",
            "rows": [],
        }

        from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import (
            PaymentEntryHandler,
        )

        company = frappe.get_single(
            "E-Boekhouden Settings"
        ).default_company or frappe.defaults.get_user_default("company")
        cost_center = frappe.db.get_value("Company", company, "cost_center")

        handler = PaymentEntryHandler(company, cost_center)
        result = handler.process_payment_mutation(mock_mutation)

        if result is None:
            results["details"].append(
                "Payment handler atomic test succeeded: Failed payment properly rolled back"
            )
            results["tests_passed"] += 1
        else:
            results["details"].append(f"Payment handler atomic test failed: Unexpected success - {result}")
            results["tests_failed"] += 1

    except Exception as e:
        results["details"].append(f"Payment handler atomic test failed: {str(e)}")
        results["tests_failed"] += 1

    results["summary"] = f"Passed: {results['tests_passed']}, Failed: {results['tests_failed']}"

    return results

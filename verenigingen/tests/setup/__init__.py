"""
Test setup hooks for Verenigingen app.

This module provides the before_tests hook that ensures ERPNext test fixtures
(Company, etc.) are created before our tests run.
"""
import frappe


def before_tests():
    """
    Hook called before running tests for this app.

    Ensures ERPNext's test fixtures (Company, Item, etc.) are set up,
    since our app depends on ERPNext DocTypes.
    """
    # First run our orphaned link cleanup
    try:
        from verenigingen.utils.cleanup_orphaned_links import cleanup
        cleanup()
    except Exception as e:
        frappe.logger().warning(f"Orphaned link cleanup failed: {e}")

    # Call ERPNext's before_tests to ensure basic setup
    try:
        from erpnext.setup.utils import before_tests as erpnext_before_tests
        erpnext_before_tests()
    except ImportError:
        frappe.logger().warning("ERPNext not installed, skipping ERPNext test setup")
    except Exception as e:
        frappe.logger().info(f"ERPNext before_tests: {e}")

    # Ensure all test companies exist by loading Company test records
    # ERPNext Account fixtures require: _Test Company, _Test Company 1,
    # _Test Company with perpetual inventory
    try:
        from frappe.test_runner import make_test_records

        required_companies = [
            "_Test Company",
            "_Test Company 1",
            "_Test Company with perpetual inventory",
        ]
        missing = [c for c in required_companies if not frappe.db.exists("Company", c)]

        if missing:
            # Force recreate to ensure all companies are created
            # (test record log may be stale)
            make_test_records("Company", verbose=False, force=True, commit=True)
            frappe.db.commit()
    except Exception as e:
        frappe.logger().warning(f"Company test record creation failed: {e}")

    # Ensure Customer test records exist (needed by Item Price and other ERPNext fixtures)
    try:
        from frappe.test_runner import make_test_records

        if not frappe.db.exists("Customer", "_Test Customer"):
            make_test_records("Customer", verbose=False, force=True, commit=True)
            frappe.db.commit()
    except Exception as e:
        frappe.logger().warning(f"Customer test record creation failed: {e}")

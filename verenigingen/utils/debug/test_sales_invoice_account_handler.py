#!/usr/bin/env python3
"""
Test script for Sales Invoice Account Handler functionality.

This script validates the membership-related Sales Invoice account detection
and replacement logic without requiring a full Frappe environment.
"""

import os
import sys

# Add the parent directory to the path to import the module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Mock frappe for testing
class MockFrappe:
    def __init__(self):
        self.flags = type("obj", (object,), {"in_install": False, "in_migrate": False})()

    def get_single(self, doctype):
        if doctype == "Verenigingen Settings":
            return type(
                "obj",
                (object,),
                {
                    "default_receivable_account": "13500 - Te ontvangen contributies",
                    "membership_debit_account": "13500 - Te ontvangen contributies",
                },
            )()
        return None

    def get_cached_doc(self, doctype, name):
        if doctype == "Company":
            return type("obj", (object,), {"default_receivable_account": "13900 - Te ontvangen bedragen"})()
        return None

    @staticmethod
    def _(text):
        return text

    def msgprint(self, text, indicator=None, alert=None):
        print(f"MSG: {text}")

    @staticmethod
    def log_error(message, title):
        print(f"ERROR LOG: {title}: {message}")

    class db:
        @staticmethod
        def exists(doctype, filters):
            # Mock: return True for customers that have associated Member records
            if doctype == "Member" and filters.get("customer") == "CUST-00001":
                return True
            return False

        @staticmethod
        def count(doctype, filters):
            # Mock: return 0 for GL Entry count (no entries found)
            if doctype == "GL Entry":
                return 0
            return 0


# Mock the frappe module
sys.modules["frappe"] = MockFrappe()
import frappe

# Now import the module under test
from sales_invoice_account_handler import (
    set_membership_receivable_account,
    validate_membership_debit_account_usage,
)


def create_mock_sales_invoice(customer=None, items=None, remarks=None, debit_to=None, company="Test Company"):
    """Create a mock Sales Invoice document for testing."""
    invoice = type(
        "SalesInvoice",
        (object,),
        {
            "customer": customer,
            "items": items or [],
            "remarks": remarks,
            "debit_to": debit_to,
            "company": company,
        },
    )()
    return invoice


def create_mock_item(item_name=None, item_group=None):
    """Create a mock item for Sales Invoice testing."""
    return type("Item", (object,), {"item_name": item_name, "item_group": item_group})()


def test_membership_item_group_detection():
    """Test detection of membership invoices by item group."""
    print("\n=== Testing Membership Item Group Detection ===")

    # Test 1: Membership item group
    items = [create_mock_item("Monthly Dues", "Membership")]
    invoice = create_mock_sales_invoice(
        customer="CUST-00002", items=items, debit_to="13900 - Te ontvangen bedragen"
    )

    print("Test 1: Membership item group")
    set_membership_receivable_account(invoice)
    expected = "13500 - Te ontvangen contributies"
    assert invoice.debit_to == expected, f"Expected {expected}, got {invoice.debit_to}"
    print("✓ Successfully detected membership by item group")


def test_membership_item_name_detection():
    """Test detection of membership invoices by item name."""
    print("\n=== Testing Membership Item Name Detection ===")

    # Test 2: Membership item name
    items = [create_mock_item("Contributie 2025", "Services")]
    invoice = create_mock_sales_invoice(
        customer="CUST-00002", items=items, debit_to="13900 - Te ontvangen bedragen"
    )

    print("Test 2: Membership item name")
    set_membership_receivable_account(invoice)
    expected = "13500 - Te ontvangen contributies"
    assert invoice.debit_to == expected, f"Expected {expected}, got {invoice.debit_to}"
    print("✓ Successfully detected membership by item name")


def test_customer_member_detection():
    """Test detection of membership invoices by customer having Member record."""
    print("\n=== Testing Customer Member Detection ===")

    # Test 3: Customer with associated Member record
    items = [create_mock_item("General Service", "Services")]
    invoice = create_mock_sales_invoice(
        customer="CUST-00001",  # This customer has a Member record (mocked)
        items=items,
        debit_to="13900 - Te ontvangen bedragen",
    )

    print("Test 3: Customer with Member record")
    set_membership_receivable_account(invoice)
    expected = "13500 - Te ontvangen contributies"
    assert invoice.debit_to == expected, f"Expected {expected}, got {invoice.debit_to}"
    print("✓ Successfully detected membership by customer having Member record")


def test_remarks_detection():
    """Test detection of membership invoices by remarks."""
    print("\n=== Testing Remarks Detection ===")

    # Test 4: Membership mentioned in remarks
    items = [create_mock_item("General Service", "Services")]
    invoice = create_mock_sales_invoice(
        customer="CUST-00002",
        items=items,
        remarks="Monthly membership dues for 2025",
        debit_to="13900 - Te ontvangen bedragen",
    )

    print("Test 4: Membership mentioned in remarks")
    set_membership_receivable_account(invoice)
    expected = "13500 - Te ontvangen contributies"
    assert invoice.debit_to == expected, f"Expected {expected}, got {invoice.debit_to}"
    print("✓ Successfully detected membership by remarks")


def test_non_membership_invoice():
    """Test that non-membership invoices are not modified."""
    print("\n=== Testing Non-Membership Invoice ===")

    # Test 5: Regular service invoice (should not change)
    items = [create_mock_item("Consulting Service", "Services")]
    invoice = create_mock_sales_invoice(
        customer="CUST-00002",
        items=items,
        remarks="General consulting work",
        debit_to="13900 - Te ontvangen bedragen",
    )

    print("Test 5: Non-membership invoice")
    original_debit_to = invoice.debit_to
    set_membership_receivable_account(invoice)
    assert invoice.debit_to == original_debit_to, f"Expected {original_debit_to}, got {invoice.debit_to}"
    print("✓ Non-membership invoice correctly left unchanged")


def test_already_correct_account():
    """Test that invoices with already correct account are not modified."""
    print("\n=== Testing Already Correct Account ===")

    # Test 6: Invoice already has correct account
    items = [create_mock_item("Monthly Dues", "Membership")]
    invoice = create_mock_sales_invoice(
        customer="CUST-00002", items=items, debit_to="13500 - Te ontvangen contributies"  # Already correct
    )

    print("Test 6: Invoice with already correct account")
    set_membership_receivable_account(invoice)
    expected = "13500 - Te ontvangen contributies"
    assert invoice.debit_to == expected, f"Expected {expected}, got {invoice.debit_to}"
    print("✓ Invoice with correct account left unchanged")


def test_no_debit_to():
    """Test that invoices without debit_to are skipped."""
    print("\n=== Testing No Debit To ===")

    # Test 7: Invoice without debit_to
    items = [create_mock_item("Monthly Dues", "Membership")]
    invoice = create_mock_sales_invoice(customer="CUST-00002", items=items, debit_to=None)

    print("Test 7: Invoice without debit_to")
    set_membership_receivable_account(invoice)
    assert invoice.debit_to is None, f"Expected None, got {invoice.debit_to}"
    print("✓ Invoice without debit_to correctly skipped")


def test_diagnostic_function():
    """Test the diagnostic function for redundant field detection."""
    print("\n=== Testing Diagnostic Function ===")

    invoice = create_mock_sales_invoice()
    print("Test 8: Diagnostic function")
    validate_membership_debit_account_usage(invoice)
    print("✓ Diagnostic function executed without errors")


def run_all_tests():
    """Run all test functions."""
    print("Running Sales Invoice Account Handler Tests")
    print("=" * 50)

    try:
        test_membership_item_group_detection()
        test_membership_item_name_detection()
        test_customer_member_detection()
        test_remarks_detection()
        test_non_membership_invoice()
        test_already_correct_account()
        test_no_debit_to()
        test_diagnostic_function()

        print("\n" + "=" * 50)
        print("✅ ALL TESTS PASSED!")
        print("✅ Sales Invoice Account Handler implementation appears to be working correctly.")
        return True

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

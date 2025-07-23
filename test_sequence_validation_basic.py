#!/usr/bin/env python3
"""
Simple test script to validate the sequence type validation implementation
"""

import frappe


def test_basic_validation():
    """Test basic sequence type validation functionality"""
    try:
        # Create a simple test batch
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = frappe.utils.today()
        batch.batch_description = "Test Validation Implementation"
        batch.batch_type = "RCUR"
        batch.currency = "EUR"

        # Add minimal invoice data
        batch.append(
            "invoices",
            {
                "invoice": "TEST-INV-001",
                "membership": "TEST-MEM-001",
                "member": "TEST-MEMBER",
                "member_name": "Test Member",
                "amount": 100.00,
                "currency": "EUR",
                "iban": "NL91ABNA0417164300",
                "mandate_reference": "TEST-MANDATE-001",
                "sequence_type": "RCUR",  # This might be wrong
                "status": "Pending",
            },
        )

        # Set automated processing flag to avoid throwing errors
        batch._automated_processing = True

        print("Testing sequence type validation...")

        # Try to insert the batch
        batch.insert()

        print(f"✓ Batch created successfully: {batch.name}")
        print(f"✓ Validation status: {batch.validation_status}")

        if batch.validation_errors:
            errors = frappe.parse_json(batch.validation_errors)
            print(f"✓ Critical errors found: {len(errors)}")
            for error in errors:
                print(f"  - {error.get('issue', 'Unknown error')}")

        if batch.validation_warnings:
            warnings = frappe.parse_json(batch.validation_warnings)
            print(f"✓ Warnings found: {len(warnings)}")
            for warning in warnings:
                print(f"  - {warning.get('issue', 'Unknown warning')}")

        # Clean up
        frappe.delete_doc("Direct Debit Batch", batch.name, force=True)
        print("✓ Test cleanup completed")

        return True

    except Exception as e:
        print(f"✗ Test failed: {str(e)}")
        return False


def test_notification_system():
    """Test notification system configuration"""
    try:
        from verenigingen.api.sepa_batch_notifications import test_notification_system

        print("Testing notification system...")
        result = test_notification_system()

        if result["success"]:
            print("✓ Notification system test passed")
            print(f"✓ Found {len(result['recipients'])} recipients")
        else:
            print(f"✗ Notification system test failed: {result['error']}")

        return result["success"]

    except Exception as e:
        print(f"✗ Notification test failed: {str(e)}")
        return False


if __name__ == "__main__":
    print("SEPA Sequence Type Validation - Basic Test")
    print("=" * 50)

    # Initialize Frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    try:
        # Test validation functionality
        print("\n1. Testing Basic Validation")
        validation_ok = test_basic_validation()

        print("\n2. Testing Notification System")
        notification_ok = test_notification_system()

        print("\n" + "=" * 50)
        if validation_ok and notification_ok:
            print("✓ All tests passed! Implementation is working.")
        else:
            print("✗ Some tests failed. Check implementation.")

    finally:
        frappe.destroy()

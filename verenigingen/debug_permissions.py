"""Debug permission validation"""

import frappe

from verenigingen.utils.validation_utilities import DocumentExistenceValidator


def debug_permission_validation():
    """Debug permission validation logic"""
    print("=== DEBUGGING PERMISSION VALIDATION ===")

    # Test 1: Valid DocType permission check
    valid_result = frappe.has_permission("Donor", "create")
    print(f"Valid permission check (Donor:create): {valid_result}")

    # Test 2: Invalid DocType permission check
    invalid_result = frappe.has_permission("NonExistentDocType", "create")
    print(f"Invalid permission check (NonExistentDocType:create): {invalid_result}")

    # Test 3: Check if DocType exists
    doctype_exists = DocumentExistenceValidator.check_document_exists("DocType", "NonExistentDocType")
    print(f"NonExistentDocType exists in system: {doctype_exists}")

    # Test 4: Check current user's roles
    user_roles = frappe.get_roles()
    print(f"Current user roles: {user_roles[:5]}...")  # Show first 5

    return True

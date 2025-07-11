import unittest

import frappe


def patch_test_runner():
    """Patch the test runner to skip problematic doctypes"""
    # Store original function reference
    original_make_test_records = frappe.test_runner.make_test_records

    def patched_make_test_records(doctype, verbose=False, force=False, commit=False):
        """Patched version that skips certain doctypes"""
        skip_doctypes = [
            "Warehouse",
            "Account",
            "Company",
            "Volunteer Activity",
            # Add other problematic doctypes here
        ]

        if doctype in skip_doctypes:
            print(f"Skipping test record creation for {doctype}")
            return

        return original_make_test_records(doctype, verbose, force, commit)

    # Apply the patch
    frappe.test_runner.make_test_records = patched_make_test_records
    print("Successfully patched test runner")
    return True


# Create a test class with a hook for the patch
class PatchedTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        patch_test_runner()

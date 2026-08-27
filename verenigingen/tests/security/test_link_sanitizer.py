# Copyright (c) 2025, Verenigingen
# License: MIT

"""
Tests for Link Sanitizer utility.

Tests both unit-level behavior and integration with real Frappe documents.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.customer_group_resolver import resolve_non_group_customer_group
from verenigingen.tests.setup import ensure_root_territory
from verenigingen.utils.link_sanitizer import (
    BrokenLinkError,
    get_broken_links_summary,
    sanitize_customer_links,
    sanitize_document_link_fields,
    sanitize_member_links_on_customer,
)


class TestLinkSanitizerUnit(FrappeTestCase):
    """Unit tests for link sanitizer functions."""

    def setUp(self):
        """Set up test fixtures."""
        # These classes are on the compat `FrappeTestCase`, so they reach neither
        # harness base and nothing seeds the Territory root for them. A fresh
        # reinstall leaves `tabTerritory` empty, and the Customer below hardcodes
        # the root (#516).
        ensure_root_territory()
        # Create a test customer for sanitization tests
        self.test_customer_name = f"_Test Sanitizer Customer {frappe.generate_hash(length=6)}"
        if not frappe.db.exists("Customer", self.test_customer_name):
            customer = frappe.get_doc(
                {
                    "doctype": "Customer",
                    "customer_name": self.test_customer_name,
                    "customer_group": resolve_non_group_customer_group(),
                    "territory": "All Territories",
                }
            )
            customer.insert(ignore_permissions=True)
        self.customer = frappe.get_doc("Customer", self.test_customer_name)

    def tearDown(self):
        """Clean up test data."""
        frappe.set_user("Administrator")
        if frappe.db.exists("Customer", self.test_customer_name):
            frappe.delete_doc("Customer", self.test_customer_name, force=True)
        frappe.db.commit()

    def test_sanitize_returns_empty_for_valid_links(self):
        """Valid links should not be cleared."""
        # Customer with no broken links
        cleared = sanitize_customer_links(self.customer)
        self.assertEqual(cleared, [])

    def test_sanitize_clears_broken_member_link(self):
        """Broken member link should be cleared in auto-fix mode."""
        # Set a non-existent member reference
        self.customer.db_set("member", "NONEXISTENT-MEMBER-12345", update_modified=False)
        self.customer.reload()

        # Verify it's set
        self.assertEqual(self.customer.member, "NONEXISTENT-MEMBER-12345")

        # Sanitize should clear it
        cleared = sanitize_member_links_on_customer(self.customer)

        self.assertIn("member", cleared)
        self.assertIsNone(self.customer.member)

    def test_strict_mode_raises_exception(self):
        """Strict mode should raise BrokenLinkError instead of auto-fixing."""
        # Set a non-existent member reference
        self.customer.db_set("member", "NONEXISTENT-MEMBER-STRICT", update_modified=False)
        self.customer.reload()

        # Strict mode should raise exception
        with self.assertRaises(BrokenLinkError) as context:
            sanitize_member_links_on_customer(self.customer, strict=True)

        # Check error message contains field info
        self.assertIn("member", str(context.exception))
        self.assertIn("NONEXISTENT-MEMBER-STRICT", str(context.exception))

        # Verify value was NOT cleared (strict mode doesn't auto-fix)
        self.customer.reload()
        self.assertEqual(self.customer.member, "NONEXISTENT-MEMBER-STRICT")

    def test_strict_mode_passes_for_valid_links(self):
        """Strict mode should not raise exception for valid links."""
        # No exception should be raised for valid/empty links
        try:
            sanitize_customer_links(self.customer, strict=True)
        except BrokenLinkError:
            self.fail("BrokenLinkError raised for valid links")

    def test_sanitize_handles_none_values(self):
        """None values in link fields should not cause errors."""
        self.customer.member = None
        cleared = sanitize_customer_links(self.customer)
        self.assertEqual(cleared, [])

    def test_sanitize_handles_empty_string(self):
        """Empty string values should not be treated as broken links."""
        self.customer.db_set("member", "", update_modified=False)
        self.customer.reload()
        cleared = sanitize_customer_links(self.customer)
        self.assertEqual(cleared, [])

    def test_multiple_broken_links_all_cleared(self):
        """Multiple broken links should all be cleared."""
        # Set multiple broken references
        self.customer.db_set("member", "BROKEN-MEMBER-1", update_modified=False)
        self.customer.db_set("customer_primary_contact", "BROKEN-CONTACT-1", update_modified=False)
        self.customer.reload()

        cleared = sanitize_customer_links(self.customer)

        self.assertIn("member", cleared)
        self.assertIn("customer_primary_contact", cleared)
        self.assertIsNone(self.customer.member)
        self.assertIsNone(self.customer.customer_primary_contact)

    def test_fields_to_check_filter(self):
        """fields_to_check parameter should limit which fields are checked."""
        # Set broken references in multiple fields
        self.customer.db_set("member", "BROKEN-MEMBER-2", update_modified=False)
        self.customer.db_set("customer_primary_contact", "BROKEN-CONTACT-2", update_modified=False)
        self.customer.reload()

        # Only check member field
        cleared = sanitize_document_link_fields(self.customer, fields_to_check=["member"])

        # Only member should be cleared
        self.assertIn("member", cleared)
        self.assertNotIn("customer_primary_contact", cleared)
        self.assertIsNone(self.customer.member)
        # Contact should still be broken (not checked)
        self.assertEqual(self.customer.customer_primary_contact, "BROKEN-CONTACT-2")


class TestLinkSanitizerIntegration(FrappeTestCase):
    """Integration tests with real document workflows."""

    def setUp(self):
        """Set up test fixtures with real linked documents."""
        ensure_root_territory()  # see TestLinkSanitizerUnit.setUp (#516)
        self.test_prefix = f"_Test_LS_{frappe.generate_hash(length=4)}"

        # Create a real member - capture the auto-generated name
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Test",
                "last_name": "LinkSanitizer",
                "email": f"test_ls_{frappe.generate_hash(length=4)}@example.com",
            }
        )
        member.insert(ignore_permissions=True)
        self.member_name = member.name  # Use actual auto-generated name

        # The Customer.member field carries a UNIQUE constraint and member
        # creation may auto-create a linked Customer. Reuse an existing linked
        # Customer when present; otherwise create one.
        existing_customer = frappe.db.get_value("Customer", {"member": self.member_name}, "name")
        if existing_customer:
            self.customer_name = existing_customer
        else:
            self.customer_name = f"{self.test_prefix}_Customer"
            customer = frappe.get_doc(
                {
                    "doctype": "Customer",
                    "customer_name": self.customer_name,
                    "customer_group": resolve_non_group_customer_group(),
                    "territory": "All Territories",
                    "member": self.member_name,
                }
            )
            customer.insert(ignore_permissions=True)

        frappe.db.commit()

    def tearDown(self):
        """Clean up test data."""
        frappe.set_user("Administrator")
        # Clean up in reverse order of creation
        if frappe.db.exists("Customer", self.customer_name):
            frappe.delete_doc("Customer", self.customer_name, force=True)
        if frappe.db.exists("Member", self.member_name):
            frappe.delete_doc("Member", self.member_name, force=True)
        frappe.db.commit()

    def test_valid_link_not_cleared(self):
        """Valid link to existing member should not be cleared."""
        customer = frappe.get_doc("Customer", self.customer_name)

        # Verify link is valid
        self.assertEqual(customer.member, self.member_name)
        self.assertTrue(frappe.db.exists("Member", self.member_name))

        # Sanitize should not clear valid link
        cleared = sanitize_member_links_on_customer(customer)
        self.assertEqual(cleared, [])
        self.assertEqual(customer.member, self.member_name)

    def test_orphaned_link_after_delete(self):
        """Link becomes orphaned after target document is deleted."""
        # First verify link is valid - load customer into memory before the
        # member is deleted (deleting the member may cascade to the linked
        # Customer, so we must not re-fetch it afterwards).
        customer = frappe.get_doc("Customer", self.customer_name)
        self.assertEqual(customer.member, self.member_name)

        # Detach the customer from the member so deleting the member does not
        # cascade-delete it, then delete the member (creating orphaned ref).
        frappe.db.set_value("Customer", customer.name, "member", None, update_modified=False)
        frappe.delete_doc("Member", self.member_name, force=True)
        frappe.db.commit()

        # Re-point the in-memory doc at the now-orphaned member name
        customer.member = self.member_name
        self.assertEqual(customer.member, self.member_name)
        self.assertFalse(frappe.db.exists("Member", self.member_name))

        # Sanitize should detect and clear the orphaned link
        cleared = sanitize_member_links_on_customer(customer)
        self.assertIn("member", cleared)
        self.assertIsNone(customer.member)

    def test_error_log_created_on_auto_clear(self):
        """Error Log entry should be created when link is auto-cleared."""
        # Load the customer before deleting the member (member deletion may
        # cascade to the linked Customer). Detach first to avoid the cascade.
        customer = frappe.get_doc("Customer", self.customer_name)
        frappe.db.set_value("Customer", customer.name, "member", None, update_modified=False)
        frappe.delete_doc("Member", self.member_name, force=True)
        frappe.db.commit()

        # Re-point the in-memory doc at the now-orphaned member name
        customer.member = self.member_name

        # Clear any existing error logs
        initial_count = frappe.db.count("Error Log", {"method": "Link Sanitization - Auto-Cleared"})

        # Sanitize
        sanitize_member_links_on_customer(customer)
        frappe.db.commit()

        # Check new error log was created
        new_count = frappe.db.count("Error Log", {"method": "Link Sanitization - Auto-Cleared"})
        self.assertGreater(new_count, initial_count)

    def test_get_broken_links_summary(self):
        """get_broken_links_summary should return recent sanitization logs."""
        # This tests the admin utility function
        summary = get_broken_links_summary(limit=10)
        # Should return a list (may be empty if no recent sanitizations)
        self.assertIsInstance(summary, list)

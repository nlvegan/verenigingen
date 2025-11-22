# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Integration tests for MemberCleanupService - Focus on cascade deletion logic

Tests verify that all related records are properly cleaned up when a Member
is deleted, including smart Customer handling and Address unlinking.

Refactored to use real data instead of mocks for more reliable testing.
"""

import unittest

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

from verenigingen.services.member.lifecycle.member_cleanup_service import (
    MemberCleanupService,
)


class TestMemberCleanupService(EnhancedTestCase):
    """Test suite for MemberCleanupService"""

    def add_dynamic_link_to_customer(self, customer_name, member_name):
        """
        Helper method to add dynamic link to customer.
        Permission bypasses allowed in helper methods.
        """
        customer = frappe.get_doc("Customer", customer_name)
        if not any(link.link_name == member_name for link in customer.links):
            customer.append("links", {
                "link_doctype": "Member",
                "link_name": member_name
            })
            customer.save(ignore_permissions=True)

    def add_dynamic_link_to_address(self, address_name, member_name):
        """
        Helper method to add dynamic link to address.
        Permission bypasses allowed in helper methods.
        """
        address = frappe.get_doc("Address", address_name)
        address.append("links", {
            "link_doctype": "Member",
            "link_name": member_name
        })
        address.save(ignore_permissions=True)

    def test_membership_deletion_cancels_submitted(self):
        """Test that submitted Memberships are cancelled before deletion"""
        # Create real member with real membership
        member = self.create_test_member(
            first_name="Cleanup",
            last_name="Test001",
            email="cleanup.test001@example.com"
        )

        # Create and submit a membership
        membership = self.create_test_membership(member_name=member.name)
        membership.submit()
        membership_name = membership.name

        # Reload member to ensure fresh state
        member.reload()

        # Verify membership exists and is submitted
        self.assertTrue(frappe.db.exists("Membership", membership_name))
        self.assertEqual(frappe.get_doc("Membership", membership_name).docstatus, 1)

        # Call cleanup service
        MemberCleanupService.handle_member_deletion(member)

        # Verify membership no longer exists (was cancelled and deleted)
        self.assertFalse(frappe.db.exists("Membership", membership_name))

    def test_dues_schedule_deletion(self):
        """Test that Membership Dues Schedules are force deleted"""
        # Create real member with dues schedules
        member = self.create_test_member(
            first_name="Cleanup",
            last_name="Test002",
            email="cleanup.test002@example.com"
        )

        # Create multiple dues schedules
        schedule1 = self.create_test_dues_schedule(member=member.name)
        schedule2 = self.create_test_dues_schedule(member=member.name)

        schedule1_name = schedule1.name
        schedule2_name = schedule2.name

        # Verify schedules exist
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", schedule1_name))
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", schedule2_name))

        # Reload member
        member.reload()

        # Call cleanup service
        MemberCleanupService.handle_member_deletion(member)

        # Verify both schedules were deleted
        self.assertFalse(frappe.db.exists("Membership Dues Schedule", schedule1_name))
        self.assertFalse(frappe.db.exists("Membership Dues Schedule", schedule2_name))

    def test_sales_invoice_reference_clearing(self):
        """Test that Sales Invoice member references are cleared (not deleted)"""
        # Create real member with sales invoice
        member = self.create_test_member(
            first_name="Cleanup",
            last_name="Test003",
            email="cleanup.test003@example.com"
        )

        # Create a sales invoice linked to this member
        invoice = self.create_test_sales_invoice(customer_name=member.customer)

        # Manually set member field on invoice (simulating member-specific invoice)
        frappe.db.set_value("Sales Invoice", invoice.name, "member", member.name)
        invoice.reload()

        invoice_name = invoice.name

        # Verify invoice exists and has member reference
        self.assertTrue(frappe.db.exists("Sales Invoice", invoice_name))
        self.assertEqual(frappe.db.get_value("Sales Invoice", invoice_name, "member"), member.name)

        # Reload member
        member.reload()

        # Call cleanup service
        MemberCleanupService.handle_member_deletion(member)

        # Verify invoice still exists but member reference is cleared
        self.assertTrue(frappe.db.exists("Sales Invoice", invoice_name))
        self.assertIsNone(frappe.db.get_value("Sales Invoice", invoice_name, "member"))

    def test_customer_preserved_if_has_transactions(self):
        """Test that Customer is preserved when it has transactions"""
        # Create member with customer
        member = self.create_test_member(
            first_name="Cleanup",
            last_name="Test004",
            email="cleanup.test004@example.com"
        )

        customer_name = member.customer

        # Create a payment entry for the customer (transaction)
        payment = self.create_test_payment_entry(party_name=customer_name)
        payment_name = payment.name

        # Verify customer exists and has a transaction
        self.assertTrue(frappe.db.exists("Customer", customer_name))
        self.assertTrue(frappe.db.exists("Payment Entry", payment_name))

        # Reload member
        member.reload()

        # Call cleanup service
        MemberCleanupService.handle_member_deletion(member)

        # Verify customer still exists (preserved because of transaction)
        self.assertTrue(frappe.db.exists("Customer", customer_name))

    def test_customer_deleted_if_no_transactions(self):
        """Test that Customer is deleted when it has no transactions"""
        # Create member with customer but no transactions
        member = self.create_test_member(
            first_name="Cleanup",
            last_name="Test005",
            email="cleanup.test005@example.com"
        )

        customer_name = member.customer

        # Verify customer exists
        self.assertTrue(frappe.db.exists("Customer", customer_name))

        # Verify customer has no transactions (just created, no invoices/payments)
        transaction_count = frappe.db.count("Payment Entry", {"party": customer_name})
        self.assertEqual(transaction_count, 0)

        # Reload member
        member.reload()

        # Call cleanup service
        MemberCleanupService.handle_member_deletion(member)

        # Verify customer was deleted (no transactions to preserve)
        self.assertFalse(frappe.db.exists("Customer", customer_name))

    def test_address_unlinking(self):
        """Test that Address is unlinked but not deleted"""
        # Create member with address
        member = self.create_test_member(
            first_name="Cleanup",
            last_name="Test006",
            email="cleanup.test006@example.com"
        )

        # Create address and link to member
        address = self.create_test_address()
        address_name = address.name

        # Link address to member
        member.primary_address = address_name
        member.save()

        # Verify address exists
        self.assertTrue(frappe.db.exists("Address", address_name))

        # Reload member
        member.reload()

        # Call cleanup service
        MemberCleanupService.handle_member_deletion(member)

        # Verify address still exists (unlinked, not deleted)
        self.assertTrue(frappe.db.exists("Address", address_name))

    def test_child_table_cleanup(self):
        """Test that child tables are cleaned up"""
        # Create member with chapter memberships (child table)
        member = self.create_test_member(
            first_name="Cleanup",
            last_name="Test007",
            email="cleanup.test007@example.com"
        )

        # Create chapter and add member to it
        chapter = self.create_test_chapter()
        chapter.append("members", {
            "member": member.name,
            "chapter_join_date": frappe.utils.today(),
            "status": "Active"
        })
        chapter.save()

        # Verify chapter membership exists
        chapter_memberships = frappe.db.count("Chapter Member", {"member": member.name})
        self.assertGreater(chapter_memberships, 0)

        # Reload member
        member.reload()

        # Call cleanup service
        MemberCleanupService.handle_member_deletion(member)

        # Verify chapter memberships were cleaned up
        remaining_memberships = frappe.db.count("Chapter Member", {"member": member.name})
        self.assertEqual(remaining_memberships, 0)

    def test_unlink_from_customer_removes_links(self):
        """Test that _unlink_member_from_customer removes Dynamic Links"""
        # Create member with customer
        member = self.create_test_member(
            first_name="Cleanup",
            last_name="Test008",
            email="cleanup.test008@example.com"
        )

        customer_name = member.customer

        # Add dynamic link using helper method
        self.add_dynamic_link_to_customer(customer_name, member.name)

        # Verify link exists
        customer = frappe.get_doc("Customer", customer_name)
        initial_link_count = len([link for link in customer.links if link.link_name == member.name])
        self.assertGreater(initial_link_count, 0)

        # Call unlink method directly
        MemberCleanupService._unlink_member_from_customer(member)

        # Verify link was removed
        customer.reload()
        final_link_count = len([link for link in customer.links if link.link_name == member.name])
        self.assertEqual(final_link_count, 0)

    def test_unlink_from_address_removes_links(self):
        """Test that _unlink_member_from_address removes links"""
        # Create member with address
        member = self.create_test_member(
            first_name="Cleanup",
            last_name="Test009",
            email="cleanup.test009@example.com"
        )

        # Create address and link to member
        address = self.create_test_address()
        address_name = address.name

        # Add dynamic link using helper method
        self.add_dynamic_link_to_address(address_name, member.name)

        # Verify link exists
        address_doc = frappe.get_doc("Address", address_name)
        initial_link_count = len([link for link in address_doc.links if link.link_name == member.name])
        self.assertGreater(initial_link_count, 0)

        # Call unlink method directly
        MemberCleanupService._unlink_member_from_address(member, address_name)

        # Verify link was removed
        address_doc.reload()
        final_link_count = len([link for link in address_doc.links if link.link_name == member.name])
        self.assertEqual(final_link_count, 0)

    def test_error_handling_in_deletion_loops(self):
        """Test that errors during deletion are logged but don't stop cleanup"""
        # Create member with membership
        member = self.create_test_member(
            first_name="Cleanup",
            last_name="Test010",
            email="cleanup.test010@example.com"
        )

        # Create membership
        membership = self.create_test_membership(member_name=member.name)

        # Manually corrupt the membership to cause an error
        # (e.g., set invalid docstatus that will fail validation)
        frappe.db.set_value("Membership", membership.name, "docstatus", 99)

        # Reload member
        member.reload()

        # Call cleanup service - should handle error gracefully
        try:
            MemberCleanupService.handle_member_deletion(member)
            # If it completes without raising, the error handling worked
        except Exception as e:
            # The service should catch errors, so this shouldn't happen
            self.fail(f"Cleanup service should handle errors gracefully, but raised: {e}")


def run_tests():
    """Run test suite"""
    unittest.main()


if __name__ == "__main__":
    run_tests()

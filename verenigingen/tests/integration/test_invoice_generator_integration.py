# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Integration test for InvoiceGenerator service integration with MembershipDuesSchedule.

Tests that the service properly integrates with the DocType's generate_invoice() method.
"""

import unittest
from datetime import date

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestInvoiceGeneratorIntegration(EnhancedTestCase):
    """Test InvoiceGenerator service integration with MembershipDuesSchedule"""

    def setUp(self):
        """Set up test fixtures with real data"""
        super().setUp()

        # Create real test member
        self.member = self.create_test_member(
            first_name="Integration", last_name="Test", birth_date="1985-05-15"
        )

        # Create customer and link to member
        self.customer_doc = frappe.new_doc("Customer")
        self.customer_doc.customer_name = f"{self.member.first_name} {self.member.last_name}"
        self.customer_doc.customer_type = "Individual"
        self.customer_doc.insert()

        self.member.customer = self.customer_doc.name
        self.member.save()
        self.member.reload()

        # Create membership (which also creates dues schedule automatically)
        self.membership = self.create_test_membership(
            member_name=self.member.name, membership_type_name="Regular Member"
        )

        # Get the automatically created dues schedule
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": self.member.name, "status": "Active"},
            limit=1,
        )
        if schedules:
            self.schedule = frappe.get_doc("Membership Dues Schedule", schedules[0].name)
        else:
            frappe.throw("No schedule was created with membership")

        # Reload member to ensure we have latest data
        self.member.reload()

    def test_generate_invoice_via_schedule_doctype(self):
        """
        Test that MembershipDuesSchedule.generate_invoice() properly uses InvoiceGenerator service.

        This tests the full integration: DocType orchestration -> Service invoice creation
        """
        # Arrange - schedule already created in setUp

        # Act - call the DocType method (which should use our service internally)
        invoice = self.schedule.generate_invoice()

        # Assert - invoice created successfully
        self.assertIsNotNone(invoice, "generate_invoice() should return an invoice")
        self.assertEqual(invoice.customer, self.customer_doc.name)
        self.assertEqual(invoice.member, self.member.name)
        self.assertEqual(invoice.is_membership_invoice, 1)
        self.assertEqual(invoice.membership_dues_schedule_display, self.schedule.name)

        # Verify coverage dates were set
        self.assertIsNotNone(invoice.custom_coverage_start_date)
        self.assertIsNotNone(invoice.custom_coverage_end_date)

        # Verify schedule tracking was updated
        self.schedule.reload()
        self.assertEqual(self.schedule.last_generated_invoice, invoice.name)
        self.assertIsNotNone(self.schedule.last_invoice_coverage_start)
        self.assertIsNotNone(self.schedule.last_invoice_coverage_end)

        # Verify invoice has items
        self.assertEqual(len(invoice.items), 1)
        self.assertEqual(invoice.items[0].qty, 1)
        self.assertEqual(invoice.items[0].rate, self.schedule.dues_rate)
